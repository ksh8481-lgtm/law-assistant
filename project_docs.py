"""
사업 서류(내역서·설명서)에서 글자를 뽑아 "주요 사업 내용 및 목적"을 쓰는 데 쓰는 읽기 도구.

[왜 따로 만들었나]
- 기존 doc_extract.py는 엑셀을 openpyxl로 읽는데 requirements.txt에 openpyxl이 없다(운영 서버에 없으면 조용히 빈 글이 된다). 의존 라이브러리를 늘리면 재배포 때 설치 실패·버전 변동 위험이 있어,
  xlsx·docx·hwpx는 표준 라이브러리(zipfile + xml)만으로 읽는다. PDF는 이미 requirements에 있는 pymupdf를 쓴다.
- 지원: .xlsx(내역서), .pdf, .docx, .hwpx, .txt/.csv/.md, 도면 .dxf(글자·치수·레이어·단위를 글로), 이미지 png/jpg/webp(AI가 직접 봄). 글자가 거의 없는 PDF(스캔본)는 scanned로 표시해 AI가 파일을 직접 읽게 한다.
- 도면 .dwg는 CAD 전용 이진 형식이라 읽지 않는다(DXF 또는 PDF로 저장 안내).
- 지원하지 않음: .xls(옛 엑셀), .hwp(옛 한글), .doc -> UnsupportedDoc(사용자에게 보여 줄 말 포함).
읽기만 하고 서버에 저장하지 않는다(호출한 쪽이 임시 파일을 지운다).
"""
import os
import re
import zipfile
import xml.etree.ElementTree as ET

MAX_FILE_BYTES = 25 * 1024 * 1024          # 파일 하나 25MB
MAX_SHEET_ROWS = 260                        # 시트 하나에서 읽는 줄 수(내역서는 수천 줄이 될 수 있어 앞부분 + 집계 시트 위주)
MAX_CELL_CHARS = 120
# 시트 이름에 이 말이 있으면 먼저 읽는다(길어서 잘릴 때 총괄·집계가 남도록)
PRIORITY_SHEET_WORDS = (('총괄', '집계', '원가', '요약'), ('공종', '내역'))     # 앞 묶음일수록 먼저(세부내역보다 총괄·집계가 앞)

NS_MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
NS_REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
NS_PKG_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
NS_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class UnsupportedDoc(Exception):
    """사용자에게 그대로 보여 줄 수 있는 말을 담는다."""


def _local(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _clean(s, limit=MAX_CELL_CHARS):
    s = re.sub(r'\s+', ' ', str(s)).strip()
    return s[:limit]


def _num(v):
    """엑셀에 저장된 숫자 문자열을 읽기 좋게(3.0 -> 3, 1234.5000001 -> 1234.5)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return ('%.6f' % f).rstrip('0').rstrip('.')


# ---------------------------------------------------------------- xlsx
def _shared_strings(z):
    try:
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    except KeyError:
        return []
    out = []
    for si in root.findall(NS_MAIN + 'si'):
        out.append(''.join(t.text or '' for t in si.iter(NS_MAIN + 't')))      # 서식이 섞인 글(<r><t>)도 이어 붙인다
    return out


def _sheet_list(z):
    """[(시트 이름, 시트 xml 경로)] - 통합 문서의 시트 순서대로."""
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = {}
    try:
        for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels')).findall(NS_PKG_REL + 'Relationship'):
            target = r.get('Target', '')
            rels[r.get('Id')] = target.lstrip('/') if target.startswith('/') else 'xl/' + target
    except KeyError:
        pass
    out = []
    for sh in wb.iter(NS_MAIN + 'sheet'):
        rid = sh.get(NS_REL + 'id')
        path = rels.get(rid)
        if path and path in z.namelist():
            out.append((sh.get('name', ''), path))
    return out


def _col_index(ref):
    letters = re.match(r'[A-Z]+', ref or '')
    n = 0
    for ch in (letters.group(0) if letters else ''):
        n = n * 26 + (ord(ch) - 64)
    return n


def xlsx_text(path, max_rows=MAX_SHEET_ROWS):
    """(글, 잘렸는지, 시트 수). 수식 셀은 저장된 계산값을 쓴다."""
    truncated = False
    with zipfile.ZipFile(path) as z:
        strings = _shared_strings(z)
        sheets = _sheet_list(z)
        def rank(s):
            for i, words in enumerate(PRIORITY_SHEET_WORDS):
                if any(w in s[0] for w in words):
                    return i
            return len(PRIORITY_SHEET_WORDS)
        sheets.sort(key=rank)                                                                  # 안정 정렬: 같은 등급은 원래 순서
        parts = []
        for name, spath in sheets:
            root = ET.fromstring(z.read(spath))
            rows = []
            for row in root.iter(NS_MAIN + 'row'):
                cells = []
                for c in row.findall(NS_MAIN + 'c'):
                    t = c.get('t')
                    if t == 's':
                        v = c.find(NS_MAIN + 'v')
                        idx = int(v.text) if v is not None and (v.text or '').isdigit() else -1
                        val = strings[idx] if 0 <= idx < len(strings) else ''
                    elif t == 'inlineStr':
                        val = ''.join(x.text or '' for x in c.iter(NS_MAIN + 't'))
                    else:
                        v = c.find(NS_MAIN + 'v')
                        val = _num(v.text) if v is not None and v.text is not None else ''
                    val = _clean(val)
                    if val:
                        cells.append(val)
                if cells:
                    rows.append(' | '.join(cells))
            if not rows:
                continue
            if len(rows) > max_rows:
                truncated = True
                rows = rows[:max_rows] + [f'... (이 시트는 {len(rows)}줄이라 앞의 {max_rows}줄만 읽었습니다)']
            parts.append(f'[엑셀 시트: {name}]\n' + '\n'.join(rows))
    return '\n\n'.join(parts), truncated, len(sheets)


# ---------------------------------------------------------------- docx
def docx_text(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read('word/document.xml'))
    lines = []

    def para_text(p):
        return ''.join(t.text or '' for t in p.iter(NS_W + 't'))
    body = root.find(NS_W + 'body')
    for el in (body if body is not None else []):
        tag = _local(el.tag)
        if tag == 'p':
            s = para_text(el).strip()
            if s:
                lines.append(s)
        elif tag == 'tbl':
            for tr in el.iter(NS_W + 'tr'):
                cells = [_clean(' '.join(para_text(p) for p in tc.iter(NS_W + 'p'))) for tc in tr.findall(NS_W + 'tc')]
                cells = [c for c in cells if c]
                if cells:
                    lines.append(' | '.join(cells))
    return '\n'.join(lines)


# ---------------------------------------------------------------- hwpx
def hwpx_text(path):
    out = []
    with zipfile.ZipFile(path) as z:
        sections = sorted(n for n in z.namelist() if re.match(r'Contents/section\d+\.xml$', n))
        for n in sections:
            root = ET.fromstring(z.read(n))
            for p in root.iter():
                if _local(p.tag) == 'p':
                    s = ''.join((t.text or '') for t in p.iter() if _local(t.tag) == 't').strip()
                    if s:
                        out.append(s)
    return '\n'.join(out)


# ---------------------------------------------------------------- pdf
def pdf_text(path):
    """(글, 쪽 수, 스캔본 의심). 쪽당 글자가 매우 적으면 스캔본(이미지)으로 본다."""
    try:
        import pymupdf
    except ImportError:                      # 옛 pymupdf는 fitz라는 이름으로만 import된다
        import fitz as pymupdf
    doc = pymupdf.open(path)
    try:
        pages = len(doc)
        text = '\n'.join(page.get_text() for page in doc)
    finally:
        doc.close()
    chars = len(re.sub(r'\s+', '', text))
    return text, pages, (pages > 0 and chars / pages < 40)


# ---------------------------------------------------------------- 도면: DXF
DXF_MAX_TEXTS = 400
DXF_UNITS = {0: '미지정', 1: '인치', 2: '피트', 3: '마일', 4: '밀리미터(mm)', 5: '센티미터(cm)', 6: '미터(m)', 7: '킬로미터(km)', 14: '데시미터', 15: '데카미터'}
DRAW_MAX_PAGES = 30                         # 도면 PDF를 AI에 직접 보여 줄 최대 쪽 수(앞쪽 표지·일반도·평면도 위주)
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp')


def _dxf_decode(raw):
    # 2007(AC1021) 이후 DXF는 UTF-8인데 $DWGCODEPAGE(예: ANSI_949)는 그대로 적혀 있다 -> 코드페이지를 먼저 믿으면 한글이 깨진다.
    # 그래서 UTF-8로 읽어 보고, 안 되면(옛 버전) 선언된 코드페이지(한국 CAD는 거의 ANSI_949)로 읽는다.
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    m = re.search(rb'\$DWGCODEPAGE\s*\r?\n\s*3\s*\r?\n\s*([A-Za-z0-9_\-]+)', raw)
    cp = (m.group(1).decode('ascii', 'ignore').upper() if m else '')
    enc = {'ANSI_1252': 'cp1252', 'ANSI_932': 'cp932', 'ANSI_936': 'gbk', 'ANSI_950': 'cp950'}.get(cp, 'cp949')
    return raw.decode(enc, errors='replace')


def _dxf_clean_text(s):
    """DXF 글자의 서식 코드를 걷어 낸다(\\P 줄바꿈, \\fArial;, {…}, \\U+XXXX, %%c 등)."""
    s = re.sub(r'\\U\+([0-9A-Fa-f]{4})', lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace('\\P', ' ').replace('\\~', ' ').replace('%%c', 'Ø').replace('%%C', 'Ø').replace('%%d', '°').replace('%%D', '°').replace('%%p', '±').replace('%%P', '±')
    s = re.sub(r'\\[A-Za-z][^;\\]*;', '', s)
    s = re.sub(r'\\[LlOoKk]', '', s)
    s = s.replace('{', '').replace('}', '').replace('\\\\', '\\')
    return re.sub(r'\s+', ' ', s).strip()


def dxf_text(path, max_texts=DXF_MAX_TEXTS):
    """DXF(ASCII) 도면에서 글자·치수·레이어·단위를 뽑는다. 도형의 모양은 읽지 않는다(글로 적힌 것만)."""
    with open(path, 'rb') as f:
        raw = f.read()
    if raw[:18] == b'AutoCAD Binary DXF':
        raise UnsupportedDoc('이 DXF는 바이너리 형식이라 읽지 못합니다. CAD에서 [다른 이름으로 저장]으로 ASCII DXF로 저장하거나 PDF로 출력해 올려 주세요.')
    text = _dxf_decode(raw)
    lines = text.splitlines()
    if len(lines) < 4 or not re.match(r'^\s*0\s*$', lines[0]):
        raise UnsupportedDoc('DXF 형식이 아니거나 손상된 파일입니다. CAD에서 DXF 또는 PDF로 다시 저장해 올려 주세요.')
    units, version = None, ''
    texts, dims, layers, kinds = [], [], {}, {}
    section, ent, last_var = '', None, None

    def flush():
        nonlocal ent
        if not ent:
            return
        t = ent['type']
        if section in ('ENTITIES', 'BLOCKS'):
            kinds[t] = kinds.get(t, 0) + 1
            if ent.get('layer'):
                layers[ent['layer']] = layers.get(ent['layer'], 0) + 1
            if t in ('TEXT', 'MTEXT', 'ATTRIB'):
                body = ''.join(ent['chunks']) + ent.get('last', '') if t == 'MTEXT' else ent.get('last', '')
                body = _dxf_clean_text(body)
                if body:
                    texts.append(body)
            elif t == 'DIMENSION':
                override = _dxf_clean_text(ent.get('last', ''))
                meas = ent.get('meas')
                if meas is not None:
                    try:
                        val = _num(round(float(meas), 3))
                    except ValueError:
                        val = meas
                    dims.append(val if override in ('', '<>') else f'{val} (표기: {override})')
                elif override and override != '<>':
                    dims.append(override)
        ent = None

    i, n = 0, len(lines) - 1
    while i < n:
        code, val = lines[i].strip(), lines[i + 1].rstrip('\r\n')
        i += 2
        if code == '0':
            flush()
            v = val.strip()
            if v == 'SECTION':
                section = ''
            elif v == 'ENDSEC':
                section = ''
            elif v == 'EOF':
                break
            else:
                ent = {'type': v, 'chunks': []}
            continue
        if code == '2' and section == '' and ent is None:
            section = val.strip()
            continue
        if section == 'HEADER':
            if code == '9':
                last_var = val.strip()
            elif last_var == '$INSUNITS' and code == '70':
                try:
                    units = int(val.strip())
                except ValueError:
                    pass
                last_var = None
            elif last_var == '$ACADVER' and code == '1':
                version = val.strip()
                last_var = None
            continue
        if ent is None:
            continue
        if code == '8':
            ent['layer'] = val.strip()
        elif code == '1':
            ent['last'] = val
        elif code == '3' and ent['type'] == 'MTEXT':
            ent['chunks'].append(val)
        elif code == '42' and ent['type'] == 'DIMENSION':
            ent['meas'] = val.strip()
    flush()

    def uniq(seq):
        seen, out = {}, []
        for s in seq:
            if s not in seen:
                seen[s] = 1
                out.append(s)
            else:
                seen[s] += 1
        return [(s if seen[s] == 1 else f'{s} (x{seen[s]})') for s in out]

    texts_u, dims_u = uniq(texts), uniq(dims)
    cut = len(texts_u) > max_texts
    out = [f'[DXF 도면] 도면 단위: {DXF_UNITS.get(units, "알 수 없음(" + str(units) + ")") if units is not None else "표시 없음(치수 값의 단위는 도면에 따름)"}'
           + (f' / 버전 {version}' if version else '')]
    if layers:
        top = sorted(layers.items(), key=lambda kv: -kv[1])[:60]
        out.append('레이어(객체 수): ' + ', '.join(f'{k}({v})' for k, v in top))
    if kinds:
        out.append('객체 종류: ' + ', '.join(f'{k} {v}' for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:15]))
    if texts_u:
        out.append('도면에 적힌 글자:\n' + '\n'.join('- ' + t for t in texts_u[:max_texts]) + (f'\n... (글자 {len(texts_u)}개 중 앞의 {max_texts}개만)' if cut else ''))
    if dims_u:
        out.append('치수(도면 단위): ' + ', '.join(dims_u[:300]))
    if not texts_u and not dims_u:
        out.append('(글자·치수 객체가 없습니다. 선·도형만 있는 도면이면 글로는 읽을 수 없으니 PDF로 출력해 함께 올려 주세요.)')
    return '\n'.join(out), cut


def trim_pdf(path, out_path, max_pages=None):
    """쪽이 많은 PDF의 앞쪽 max_pages쪽(기본 DRAW_MAX_PAGES)만 새 파일로 저장한다. (원래 쪽 수, 저장한 쪽 수)를 돌려준다."""
    max_pages = max_pages or DRAW_MAX_PAGES
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    src = pymupdf.open(path)
    try:
        total = len(src)
        if total <= max_pages:
            return total, total
        dst = pymupdf.open()
        dst.insert_pdf(src, from_page=0, to_page=max_pages - 1)
        dst.save(out_path, garbage=3, deflate=True)
        dst.close()
        return total, max_pages
    finally:
        src.close()


# ---------------------------------------------------------------- 진입점
def read_document(path, name=None, max_chars=70000):
    """파일 한 개를 읽어 {'name', 'text', 'kind', 'truncated', 'scanned', 'pages'}로 돌려준다. 지원하지 않는 형식이거나 읽을 수 없으면 UnsupportedDoc."""
    name = name or os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise UnsupportedDoc(f'"{name}"은 파일이 너무 큽니다(최대 {MAX_FILE_BYTES // 1024 // 1024}MB). 필요한 쪽만 나눠 올려 주세요.')
    info = {'name': name, 'kind': ext.lstrip('.'), 'truncated': False, 'scanned': False, 'pages': None, 'text': ''}
    try:
        if ext == '.xlsx':
            info['text'], info['truncated'], _n = xlsx_text(path)
        elif ext == '.pdf':
            info['text'], info['pages'], info['scanned'] = pdf_text(path)
        elif ext == '.dxf':
            info['text'], info['truncated'] = dxf_text(path)
        elif ext == '.dwg':
            raise UnsupportedDoc(f'"{name}"은 CAD 전용 형식(.dwg)이라 서버에서 읽지 못합니다. CAD에서 [다른 이름으로 저장] -> DXF(ASCII)로 저장하거나, PDF로 출력해 올려 주세요(PDF는 AI가 그림까지 직접 봅니다).')
        elif ext in IMAGE_EXTS:
            info['scanned'] = True                  # 이미지는 글자를 못 뽑으니 AI가 파일을 직접 본다
        elif ext == '.docx':
            info['text'] = docx_text(path)
        elif ext == '.hwpx':
            info['text'] = hwpx_text(path)
        elif ext in ('.txt', '.csv', '.md'):
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                info['text'] = f.read()
        elif ext == '.xls':
            raise UnsupportedDoc(f'"{name}"은 옛 엑셀(.xls)이라 읽지 못합니다. 엑셀에서 [다른 이름으로 저장] -> .xlsx로 저장해 올려 주세요.')
        elif ext == '.hwp':
            raise UnsupportedDoc(f'"{name}"은 옛 한글(.hwp)이라 읽지 못합니다. 한글에서 PDF 또는 .hwpx로 저장해 올려 주세요.')
        elif ext in ('.doc',):
            raise UnsupportedDoc(f'"{name}"은 옛 워드(.doc)라 읽지 못합니다. .docx 또는 PDF로 저장해 올려 주세요.')
        else:
            raise UnsupportedDoc(f'"{name}"은 지원하지 않는 형식({ext or "확장자 없음"})입니다. xlsx, pdf, docx, hwpx, dxf, 이미지(png·jpg), txt를 올려 주세요.')
    except UnsupportedDoc:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, IndexError) as e:
        raise UnsupportedDoc(f'"{name}"을 읽지 못했습니다(파일이 손상됐거나 암호가 걸려 있을 수 있습니다). 다른 형식으로 저장해 다시 올려 주세요.') from e
    if len(info['text']) > max_chars:
        info['text'] = info['text'][:max_chars]
        info['truncated'] = True
    if not info['text'].strip() and not info['scanned']:
        raise UnsupportedDoc(f'"{name}"에서 글자를 찾지 못했습니다. 내용이 비어 있거나 이미지로만 된 파일일 수 있습니다.')
    return info


# ---------------------------------------------------------------- AI에 보낼 지시문
def build_prompt(project_type, bill_text, spec_text, scanned_names, project_name='', draw_text='', draw_names=()):
    """내역서·설명서·도면 글을 "주요 사업 내용 및 목적" 글로 정리하게 하는 지시문. 문서에 없는 내용을 지어내지 않게 한다.
    scanned_names = 글을 못 뽑아 파일째 첨부한 스캔본/이미지, draw_names = 그림까지 직접 보게 첨부한 도면 파일."""
    attached = ''
    if scanned_names:
        attached += '[스캔본(이미지) 파일 - 함께 첨부되어 직접 읽어야 하는 파일: ' + ', '.join(scanned_names) + ']\n'
    if draw_names:
        attached += '[도면 파일 - 함께 첨부되어 있으니 그림·표제란·평면도·단면도·치수·주석을 직접 보고 읽으십시오: ' + ', '.join(draw_names) + ']\n'
    bill_section = ('[3. 내역서 주요 공종·수량]\n- (내역서의 큰 공종과 대표 수량·금액 5~12줄)\n\n' if bill_text.strip()
                    else '(내역서가 없으므로 [3] 절은 쓰지 말고 바로 [4]로 넘어가십시오)\n\n')
    drawing_rules = ''
    if draw_text or draw_names:
        drawing_rules = """6. 도면에서 읽은 내용은 출처를 "(도면)"으로 쓰십시오. 도면에 적힌 글자·치수·표제란·범례·주석만 옮기고, 선의 길이를 재거나 축척으로 환산해 계산하지 마십시오. 축척·단위가 불분명하면 "도면 단위 확인 필요"라고 적으십시오. 도면에서 보이는 구조물(옹벽, 교량, 암거, 배수시설 등)·횡단 구성(차로·보도·측구 폭)·굴착/성토 단면·기존 시설·지장물·매설물 표시는 [2]에 포함하십시오. 흐릿하거나 확실하지 않은 글자는 "(판독 불확실)"로 표시하십시오.
"""
    return f"""당신은 대한민국 지방자치단체 시설직 공무원을 돕는 건설사업 서류 검토 보조자입니다.
아래 [설명서]·[내역서]·[도면]은 사용자가 올린 실제 사업 서류에서 뽑은 글(또는 첨부 파일)입니다. 이 서류만 근거로 "개발사업 법규 검토"에 입력할 **주요 사업 내용 및 목적**을 정리하세요.

[입력 정보] 공종: {project_type or '미지정'} / 사업명(입력): {project_name or '미입력'}

[절대 규칙]
1. 서류에 적힌 내용만 쓰십시오. 없는 사실·숫자를 지어내거나 일반 지식으로 채우지 마십시오. 서류에서 찾지 못한 항목은 본문에 쓰지 말고 맨 끝 "서류에서 찾지 못한 정보"에만 나열하십시오.
2. 숫자(연장, 폭, 면적, 깊이, 높이, 수량, 금액)는 서류의 값을 단위와 함께 그대로 옮기고, 핵심 수치에는 출처를 괄호로 붙이십시오(예: "(내역서)", "(설명서)"). 엑셀은 본문에 "[엑셀 시트: 이름]" 표시가 있을 때만 그 시트 이름을 쓰고, 없는 시트 이름·쪽수는 쓰지 마십시오. 서류에 없는 항목(점용, 지장물 등)을 [2]에 "해당 없음"이나 추정으로 채우지 말고 [4]에 적으십시오.
3. 법규 검토에 영향을 주는 사실을 빠뜨리지 마십시오: 규모, 공종, 주요 구조물(옹벽·교량·암거·배수시설 등), 굴착·절토·성토(깊이·물량), 철거·해체(석면 포함 여부), 하천·공유수면·도로 점용 여부, 지장물·지하매설물(상하수도·전기·통신·가스), 산지·농지·문화재 관련 언급, 가설·흙막이, 공사기간·사업비.
4. 서류에 서로 다른 값이 있으면 하나로 단정하지 말고 "서류 간 값이 다름: A(설명서) / B(내역서)"로 적으십시오.
5. 판단이나 법령 적용 의견은 쓰지 마십시오(그건 다음 단계에서 합니다). 사실만 정리하십시오.
{drawing_rules}
[출력 형식 - 순수 텍스트, 마크다운 기호(#, **) 없이 아래 틀 그대로]
[1. 사업 개요]
- 사업명: (서류에 있으면)
- 사업 목적: (서류에 있는 목적·필요성을 1~3문장으로)
- 위치·사업 기간·사업비: (서류에 있는 것만)

[2. 주요 공사 내용 및 제원]
- (한 줄에 하나씩. 공종, 규모, 구조물, 굴착·성토, 철거, 점용, 지장물 등. 수치와 출처 포함)

{bill_section}[4. 서류에서 찾지 못한 정보]
- (위 3번 규칙의 항목 중 서류에 없는 것을 쉼표로 나열. 모두 있으면 "없음")

전체 분량은 한글 1,800자 안팎으로 간결하게 쓰십시오.
{attached}
===== [설명서] =====
{spec_text or '(설명서 없음)'}

===== [내역서] =====
{bill_text or '(내역서 없음)'}

===== [도면에서 뽑은 글자] =====
{draw_text or ('(도면 글자 없음 - 첨부된 도면 파일을 직접 보십시오)' if draw_names else '(도면 없음)')}
"""
