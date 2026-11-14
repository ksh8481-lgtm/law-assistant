"""
pdf_digest.py - 글자·표·그림이 섞인 PDF를 AI에 넘기기 좋은 "요약본"으로 바꿔 토큰을 줄이는 도구.

왜 만들었나
  PDF를 통째로(쪽 전체를 이미지로) 넘기면 토큰이 많이 든다. 그런데 한 문서 안에서도 쪽마다, 한 쪽 안에서도 부분마다 성격이 다르다.
  글자는 글로, 표는 표 구조로, 그림은 그 부분만 잘라 낮은 해상도 이미지로, 스캔본은 OCR 글자로 따로 처리하면 AI가 읽어야 할 양이 크게 줄어든다.

사용법 (backend 폴더에서)
  python tools/pdf_digest.py 문서.pdf                  # 문서_digest/ 폴더에 digest.md 와 figs/ 를 만든다
  python tools/pdf_digest.py 문서.pdf -o out --pages 3-9 --dpi 80
  AI에게는 digest.md 를 읽게 하고, 그림은 digest.md 에 적힌 figs/ 파일 중 필요한 것만 보여 준다.

처리 규칙(쪽마다)
  digital   글자가 선택되는 쪽 -> 글자 + 표(마크다운) + 그림(잘라서 PNG, 자리표시자만 본문에 둔다)
  scan      글자가 거의 없고 쪽 전체가 이미지(스캔본) -> OCR 글자(가능하면) + 쪽 이미지(필요할 때 확인용)
  garbled   글자는 있으나 깨진 쪽(글꼴 매핑이 없는 PDF) -> scan 과 같은 방식
  표는 pymupdf 의 find_tables(선이 그려진 표)로 찾는다. 선 없는 표는 못 찾을 수 있고, 그때는 글자로 나온다.

한계(정직하게)
  - 단이 여러 개인 쪽은 읽는 순서가 틀릴 수 있다(위->아래, 왼쪽->오른쪽으로 정렬).
  - OCR 은 Windows 내장 한글 OCR 만 지원한다(그 밖의 환경에서는 OCR 없이 이미지만 만든다). 숫자·이름은 오인식이 있을 수 있다.
  - 토큰 수는 "글자 수 / 1.3", "이미지 가로x세로 / 750" 으로 어림한 값이다(실측 아님).
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile

import pymupdf

SCAN_MIN_CHARS = 40            # 쪽당 글자가 이보다 적고 이미지가 있으면 스캔본으로 본다
FIG_MIN_AREA = 0.03            # 쪽 넓이의 3% 미만 그림은 장식(로고·점)으로 보고 버린다
FIG_MIN_SIDE = 50              # 변이 50pt 미만(선·띠)이면 그림이 아니다
FIG_MAX_EDGE_PX = 900          # 잘라 낸 그림의 긴 변 상한(픽셀)
OCR_DPI = 200
CHARS_PER_TOKEN = 1.3
IMG_TOKEN_DIV = 750


# ---------------------------------------------------------------- 글자 상태 판별
_WORDISH = re.compile(r'[0-9A-Za-z㄰-㆏가-힣一-鿿]')


def wordish_ratio(text: str) -> float:
    """공백을 뺀 글자 중 글자·숫자(한글·영문·숫자·한자) 비율. 낮으면 글꼴 매핑이 깨져 기호만 나온 것이다."""
    s = re.sub(r'\s+', '', text or '')
    if not s:
        return 1.0
    return len(_WORDISH.findall(s)) / len(s)


def count_chars(text: str) -> int:
    return len(re.sub(r'\s+', '', text or ''))


def est_text_tokens(chars: int) -> int:
    return int(math.ceil(chars / CHARS_PER_TOKEN))


def est_image_tokens(w_px: float, h_px: float) -> int:
    return int(math.ceil(w_px * h_px / IMG_TOKEN_DIV))


# ---------------------------------------------------------------- 기하
def _rect_area(r) -> float:
    return max(0.0, r.x1 - r.x0) * max(0.0, r.y1 - r.y0)


def _overlap_ratio(a, b) -> float:
    """a 넓이 중 b 와 겹치는 비율."""
    inter = pymupdf.Rect(a) & pymupdf.Rect(b)
    if inter.is_empty:
        return 0.0
    return _rect_area(inter) / max(_rect_area(a), 1e-6)


def _center_in(block_rect, region) -> bool:
    cx, cy = (block_rect.x0 + block_rect.x1) / 2, (block_rect.y0 + block_rect.y1) / 2
    return region.x0 <= cx <= region.x1 and region.y0 <= cy <= region.y1


def _merge_rects(rects, pad=6):
    """서로 겹치거나 가까운 사각형을 하나로 합친다(그림 조각이 여러 개로 쪼개지는 것을 막는다)."""
    rects = [pymupdf.Rect(r) for r in rects]
    merged = True
    while merged:
        merged = False
        out = []
        while rects:
            r = rects.pop()
            grown = pymupdf.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
            for i, o in enumerate(out):
                if not (grown & o).is_empty:
                    out[i] = o | r
                    merged = True
                    break
            else:
                out.append(r)
        rects = out
    return rects


# ---------------------------------------------------------------- 표
def _table_markdown(rows) -> str:
    def clean(c):
        c = '' if c is None else str(c)
        return re.sub(r'\s+', ' ', c).replace('|', '\\|').strip()
    rows = [[clean(c) for c in r] for r in rows if r]
    width = max((len(r) for r in rows), default=0)
    rows = [r + [''] * (width - len(r)) for r in rows]
    if len(rows) < 2 or width < 2:
        return ''
    lines = ['| ' + ' | '.join(rows[0]) + ' |', '|' + '|'.join(['---'] * width) + '|']
    lines += ['| ' + ' | '.join(r) + ' |' for r in rows[1:]]
    return '\n'.join(lines)


def find_page_tables(page):
    """[(bbox, markdown)] - 선이 있는 표 중 내용이 충분히 찬 것만. 거의 빈 표는 레이아웃 선이므로 버린다."""
    out = []
    try:
        tabs = page.find_tables()
    except Exception:
        return out
    for t in tabs.tables:
        try:
            rows = t.extract()
        except Exception:
            continue
        cells = [c for r in rows for c in r]
        if len(rows) < 2 or not cells:
            continue
        filled = sum(1 for c in cells if c and str(c).strip()) / len(cells)
        if filled < 0.3:
            continue
        md = _table_markdown(rows)
        if md:
            out.append((pymupdf.Rect(t.bbox), md))
    return out


# ---------------------------------------------------------------- 그림
def find_page_figures(page, table_rects, scan_like):
    """쪽 안의 그림 영역들. 그림 이미지 + 벡터로 그린 도형 묶음(차트·도면)을 합친다. 표 영역과 쪽 전체 스캔 이미지는 제외."""
    page_rect = page.rect
    page_area = _rect_area(page_rect)
    cand = []
    try:
        for info in page.get_image_info():
            r = pymupdf.Rect(info['bbox']) & page_rect
            if r.is_empty:
                continue
            if _rect_area(r) / page_area >= 0.7 and scan_like:      # 쪽 전체를 덮는 스캔 이미지는 그림이 아니라 쪽 자체다
                continue
            cand.append(r)
    except Exception:
        pass
    try:
        for r in page.cluster_drawings():
            r = pymupdf.Rect(r) & page_rect
            if not r.is_empty:
                cand.append(r)
    except Exception:
        pass
    keep = []
    for r in _merge_rects(cand):
        if _rect_area(r) / page_area < FIG_MIN_AREA or min(r.width, r.height) < FIG_MIN_SIDE:
            continue
        if any(_overlap_ratio(r, t) >= 0.6 for t in table_rects):      # 표의 테두리선 묶음
            continue
        keep.append(r)
    return sorted(keep, key=lambda r: (r.y0, r.x0))


CAPTION_RE = re.compile(r'^\s*(그림|도|표|Fig\.?|Figure|Table)\s*[\d.\-]+', re.I)


def absorb_labels(figs, text_blocks, reach=22, max_chars=30):
    """그림 바로 옆(축 눈금·범례·라벨)에 있는 짧은 글자를 그림 영역에 포함시킨다. 벡터 도형 묶음에는 축 바깥의 눈금 글자가 안 들어가기 때문이다.
    캡션("그림 1." 등)과 긴 글은 본문으로 남긴다. text_blocks = [(Rect, 글자)]"""
    out = []
    for r in figs:
        r = pymupdf.Rect(r)
        changed = True
        while changed:
            changed = False
            zone = pymupdf.Rect(r.x0 - reach, r.y0 - reach, r.x1 + reach, r.y1 + reach)
            for br, t in text_blocks:
                if (br & zone).is_empty or br in r:
                    continue
                flat = re.sub(r'\s+', ' ', t).strip()
                if len(flat) > max_chars or CAPTION_RE.match(flat):
                    continue
                grown = r | br
                if _rect_area(grown) > _rect_area(r) * 1.8:           # 한 글자 때문에 그림이 크게 부풀면 다른 것이다
                    continue
                r, changed = grown, True
        out.append(r)
    return _merge_rects(out, pad=0)


def save_clip(page, rect, path, max_edge=FIG_MAX_EDGE_PX, dpi=90, pad=4):
    """rect 영역만 잘라 PNG 로 저장한다. 긴 변이 max_edge 를 넘지 않도록 해상도를 낮춘다. (가로px, 세로px)를 돌려준다."""
    clip = pymupdf.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad) & page.rect
    scale = dpi / 72.0
    long_edge = max(clip.width, clip.height) * scale
    if long_edge > max_edge:
        scale = max_edge / max(clip.width, clip.height)
    pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(scale, scale))
    pix.save(path)
    return pix.width, pix.height


def content_bbox(page, margin=14, skip_bottom=0.0):
    """쪽에서 내용이 있는 부분만의 사각형(여백 제거). 못 찾으면 쪽 전체."""
    pix = page.get_pixmap(dpi=40, colorspace=pymupdf.csGRAY)
    w, h = pix.width, pix.height
    data = pix.samples
    xs0, ys0, xs1, ys1 = w, h, -1, -1
    limit = int(h * (1 - skip_bottom))
    for y in range(limit):
        row = data[y * w:(y + 1) * w]
        for x in range(w):
            if row[x] < 200:
                if x < xs0: xs0 = x
                if x > xs1: xs1 = x
                if y < ys0: ys0 = y
                if y > ys1: ys1 = y
    if xs1 < 0:
        return page.rect
    sx, sy = page.rect.width / w, page.rect.height / h
    r = pymupdf.Rect(xs0 * sx - margin, ys0 * sy - margin, (xs1 + 1) * sx + margin, (ys1 + 1) * sy + margin)
    return r & page.rect


# ---------------------------------------------------------------- OCR (Windows 내장 한글 OCR)
_OCR_PS1 = r'''
param([string]$Manifest)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.RandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$engine = $null
try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('ko')) } catch {}
if ($engine -eq $null) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if ($engine -eq $null) { Write-Output 'NO_ENGINE'; exit 3 }
foreach ($path in (Get-Content -LiteralPath $Manifest -Encoding UTF8)) {
  if (-not $path) { continue }
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
  $lines = $res.Lines | ForEach-Object { $_.Text }
  [System.IO.File]::WriteAllText($path + '.ocr.txt', ($lines -join "`n"), (New-Object System.Text.UTF8Encoding($false)))
}
'''


def ocr_available() -> bool:
    return sys.platform.startswith('win')


def run_ocr(png_paths):
    """{png 경로: OCR 글자}. 지원하지 않는 환경이거나 실패하면 빈 사전(호출자는 이미지로 대신한다)."""
    if not png_paths or not ocr_available():
        return {}
    tmp = tempfile.mkdtemp(prefix='pdf_digest_ocr_')
    script = os.path.join(tmp, 'ocr.ps1')
    manifest = os.path.join(tmp, 'manifest.txt')
    with open(script, 'w', encoding='utf-8-sig') as f:
        f.write(_OCR_PS1)
    with open(manifest, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(os.path.abspath(p) for p in png_paths))
    try:
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, '-Manifest', manifest],
                       capture_output=True, timeout=300)
    except Exception:
        return {}
    out = {}
    for p in png_paths:
        t = os.path.abspath(p) + '.ocr.txt'
        if os.path.exists(t):
            with open(t, encoding='utf-8') as f:
                out[p] = f.read()
            os.remove(t)
    return out


def ruled_table(page) -> bool:
    """스캔 쪽에 표의 선(가로선 3개 이상, 세로선 2개 이상)이 있는지. numpy 가 없으면 판단하지 않는다(False).
    OCR 글자 모양만으로는 표를 가려내기 어려워(편지글도 줄이 짧다) 이미지의 선을 본다."""
    try:
        import numpy as np
    except ImportError:
        return False
    pix = page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width) < 140
    h_rows = np.where(a.mean(axis=1) >= 0.35)[0]
    v_cols = np.where(a.mean(axis=0) >= 0.12)[0]

    def groups(idx):
        return 0 if len(idx) == 0 else 1 + int((np.diff(idx) > 2).sum())
    return groups(h_rows) >= 3 and groups(v_cols) >= 2


def table_like(text: str) -> bool:
    """OCR 글자가 표처럼 보이는지. 표를 OCR 하면 칸 하나가 한 줄이 되어 줄이 아주 짧아진다(실측 8쪽 감정평가서: 표 쪽 평균 줄 길이 3.6자·7.6자,
    줄글 쪽 12.4~32.3자). 그래서 줄이 20개 이상이면서 평균 길이가 9자 이하일 때 표로 본다. 한 문서로 맞춘 기준이라 다른 문서에서는 빗나갈 수 있다 - 표시일 뿐이고
    그 쪽 이미지를 보게 안내하는 용도다."""
    lines = [l.strip() for l in (text or '').splitlines() if l.strip()]
    if len(lines) < 20:
        return False
    avg = sum(len(l) for l in lines) / len(lines)
    return avg <= 9


# ---------------------------------------------------------------- 쪽 분석
def classify_page(page):
    """('digital'|'scan'|'garbled'|'empty', 글자 수, 글자 상태 비율)"""
    text = page.get_text()
    chars = count_chars(text)
    if chars >= SCAN_MIN_CHARS or chars >= 10:
        ratio = wordish_ratio(text)
        if chars >= 20 and ratio < 0.5:
            return 'garbled', chars, ratio
        if chars >= SCAN_MIN_CHARS:
            return 'digital', chars, ratio
    has_image = False
    try:
        has_image = any(_rect_area(pymupdf.Rect(i['bbox']) & page.rect) / _rect_area(page.rect) >= 0.5 for i in page.get_image_info())
    except Exception:
        pass
    if has_image:
        return 'scan', chars, 1.0
    return ('digital' if chars else 'empty'), chars, 1.0


def digest_page(page, pno, figdir, dpi):
    """한 쪽을 처리해 결과 사전을 돌려준다.
    items: 본문에 들어갈 조각 [(y, x, 종류, 내용)], figs: 저장한 그림 [(파일, 가로px, 세로px)]"""
    kind, chars, ratio = classify_page(page)
    info = {'page': pno, 'kind': kind, 'chars': chars, 'wordish': round(ratio, 2), 'tables': 0, 'figs': [], 'items': [], 'note': ''}
    if kind in ('scan', 'garbled'):
        r = content_bbox(page, skip_bottom=0.0)
        name = f'p{pno}_page.png'
        w, h = save_clip(page, r, os.path.join(figdir, name), dpi=dpi)
        info['figs'].append((name, w, h, '쪽 전체(내용 부분)'))
        info['ocr_png'] = None
        info['ruled'] = ruled_table(page)
        big = os.path.join(figdir, f'.ocr_p{pno}.png')
        page.get_pixmap(dpi=OCR_DPI, clip=r).save(big)
        info['ocr_png'] = big
        return info

    tables = find_page_tables(page)
    table_rects = [t[0] for t in tables]
    figs = find_page_figures(page, table_rects, scan_like=False)
    blocks = page.get_text('blocks', sort=True)
    figs = sorted(absorb_labels(figs, [(pymupdf.Rect(b[:4]), b[4] or '') for b in blocks if b[6] == 0 and (b[4] or '').strip()]),
                  key=lambda r: (r.y0, r.x0))
    info['tables'] = len(tables)
    items = []
    for bbox, md in tables:
        items.append((bbox.y0, bbox.x0, 'table', md))
    for i, r in enumerate(figs, 1):
        name = f'p{pno}_f{i}.png'
        w, h = save_clip(page, r, os.path.join(figdir, name), dpi=dpi)
        info['figs'].append((name, w, h, ''))
        items.append((r.y0, r.x0, 'fig', (name, w, h, r)))
    inside_fig = 0
    fig_texts = {}
    captions = {}
    for b in blocks:
        if b[6] != 0:
            continue
        br = pymupdf.Rect(b[:4])
        text = (b[4] or '').strip()
        if not text:
            continue
        if any(_center_in(br, t) for t in table_rects):
            continue                                                    # 표 안의 글자는 표에 이미 들어 있다
        in_fig = next((idx for idx, r in enumerate(figs) if _center_in(br, r)), None)
        if in_fig is not None:
            inside_fig += count_chars(text)                             # 그림 속 글자(눈금·범례·치수)는 그림 아래에 짧게 붙이고 본문에서는 뺀다
            fig_texts.setdefault(in_fig, []).append(re.sub(r'\s+', ' ', text))
            continue
        if CAPTION_RE.match(text):
            captions.setdefault('list', []).append((br, text))
        items.append((br.y0, br.x0, 'text', re.sub(r'[ \t]+\n', '\n', text)))
    if inside_fig:
        info['note'] = f'그림 속 글자 {inside_fig}자는 그림 아래 〔그림 속 글자〕에 모았다(300자까지)'
    # 그림 바로 위·아래(40pt 이내)에 있는 "그림 N"/"표 N" 형태의 글을 캡션으로 붙인다
    for k, it in enumerate(items):
        if it[2] != 'fig':
            continue
        name, w, h, r = it[3]
        cap = ''
        for br, t in captions.get('list', []):
            near_vertically = 0 <= br.y0 - r.y1 <= 40 or 0 <= r.y0 - br.y1 <= 40
            overlaps_horizontally = br.x0 < r.x1 and br.x1 > r.x0
            if near_vertically and overlaps_horizontally:
                cap = t.replace('\n', ' ')[:80]
                break
        idx = int(name.split('_f')[1].split('.')[0]) - 1
        inner = ' / '.join(fig_texts.get(idx, []))
        items[k] = (it[0], it[1], 'fig', (name, w, h, cap, inner[:300] + ('…' if len(inner) > 300 else '')))
    items.sort(key=lambda t: (round(t[0] / 4), t[1]))
    info['items'] = items
    return info


# ---------------------------------------------------------------- 전체
def parse_pages(spec, n):
    if not spec:
        return list(range(1, n + 1))
    pages = []
    for part in spec.split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-', 1)
            pages += range(int(a or 1), int(b or n) + 1)
        elif part:
            pages.append(int(part))
    return [p for p in dict.fromkeys(pages) if 1 <= p <= n]


def build_digest(pdf_path, outdir, pages=None, dpi=90, ocr=True):
    """PDF -> outdir/digest.md, outdir/figs/*.png. 요약 사전(쪽별 종류·토큰 어림)을 돌려준다."""
    doc = pymupdf.open(pdf_path)
    figdir = os.path.join(outdir, 'figs')
    os.makedirs(figdir, exist_ok=True)
    plist = parse_pages(pages, len(doc))
    results = [digest_page(doc[p - 1], p, figdir, dpi) for p in plist]

    ocr_targets = [r['ocr_png'] for r in results if r.get('ocr_png')]
    ocr_text = run_ocr(ocr_targets) if (ocr and ocr_targets) else {}
    for p in ocr_targets:
        try:
            os.remove(p)
        except OSError:
            pass

    name = os.path.basename(pdf_path)
    md = [f'# PDF 요약본: {name} ({len(doc)}쪽 중 {len(plist)}쪽 처리)',
          '> 글자·표는 본문에 있고, 그림은 `figs/` 이미지로 따로 있다. 이미지는 필요한 것만 열어 보면 된다. ⚠ 표시는 확인이 필요한 쪽이다.', '']
    total_text_chars = 0
    total_fig_tokens = 0
    total_page_img_tokens = 0
    must_view_tokens = 0
    page_rows = []
    for r in results:
        p = r['page']
        head = f"## 쪽 {p} [{r['kind']}]"
        md.append(head)
        text_chars = 0
        if r['kind'] in ('scan', 'garbled'):
            fname, w, h, _d = r['figs'][0]
            ocr_png = r.get('ocr_png')
            txt = (ocr_text.get(ocr_png) or '').strip() if ocr_png else ''
            reason = '스캔본(글자 정보 없음)' if r['kind'] == 'scan' else '글자가 깨져 있음(글꼴 매핑 없음)'
            if txt:
                like_table = bool(r.get('ruled')) or table_like(txt)
                md.append(f"> ⚠ {reason} -> OCR 글자입니다. 오인식 가능(이름·숫자는 이미지로 확인): `figs/{fname}`"
                          + (' · **표로 보임: OCR 로는 칸 순서가 깨지므로 이 이미지를 보세요**' if like_table else ''))
                md.append(txt)
                text_chars = count_chars(txt)
                if like_table:
                    r['flag'] = 'table-like'
            else:
                md.append(f"> ⚠ {reason} -> 글자로 바꾸지 못했습니다(OCR 없음). 이미지로 확인: ![쪽 {p}](figs/{fname})")
                r['flag'] = 'image-only'
            total_page_img_tokens += est_image_tokens(w, h)
            if r.get('flag') in ('table-like', 'image-only'):
                must_view_tokens += est_image_tokens(w, h)
        else:
            for _y, _x, kind, content in r['items']:
                if kind == 'text':
                    md.append(content)
                    text_chars += count_chars(content)
                elif kind == 'table':
                    md.append(content)
                    text_chars += count_chars(content)
                elif kind == 'fig':
                    fname, w, h, cap, inner = content
                    md.append(f"![그림 p{p}]({'figs/' + fname}) 〔{w}x{h}px{(' · ' + cap) if cap else ''}〕")
                    if inner:
                        md.append(f"〔그림 속 글자: {inner}〕")
                        text_chars += count_chars(inner)
                    total_fig_tokens += est_image_tokens(w, h)
            if r['note']:
                md.append(f"> {r['note']}")
        md.append('')
        total_text_chars += text_chars
        r['text_chars'] = text_chars
        page_rows.append({'page': p, 'kind': r['kind'], 'chars': text_chars, 'tables': r['tables'], 'figs': len(r['figs']), 'flag': r.get('flag', '')})

    digest_path = os.path.join(outdir, 'digest.md')
    with open(digest_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    first = doc[plist[0] - 1].rect if plist else pymupdf.Rect(0, 0, 595, 842)
    page_px = (first.width / 72 * 100, first.height / 72 * 100)          # 100dpi 로 쪽 전체를 이미지로 보낼 때
    baseline = len(plist) * est_image_tokens(*page_px)
    text_tokens = est_text_tokens(total_text_chars)
    summary = {
        'pages': page_rows,
        'digest_path': digest_path,
        'text_tokens': text_tokens,
        'figure_tokens_if_all_viewed': total_fig_tokens,
        'scan_page_image_tokens_if_all_viewed': total_page_img_tokens,
        'recommended_view_tokens': total_fig_tokens + must_view_tokens,
        'baseline_all_pages_as_images': baseline,
        'ocr_used': bool(ocr_text),
        'saving_text_only_pct': round(100 * (1 - text_tokens / baseline)) if baseline else 0,
        'saving_with_all_figs_pct': round(100 * (1 - (text_tokens + total_fig_tokens + total_page_img_tokens) / baseline)) if baseline else 0,
        'saving_recommended_pct': round(100 * (1 - (text_tokens + total_fig_tokens + must_view_tokens) / baseline)) if baseline else 0,
    }
    with open(os.path.join(outdir, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description='글자·표·그림이 섞인 PDF를 토큰이 적게 드는 요약본으로 바꾼다.')
    ap.add_argument('pdf')
    ap.add_argument('-o', '--out', help='출력 폴더(기본: <pdf 이름>_digest)')
    ap.add_argument('--pages', help='처리할 쪽, 예: 1-5,8')
    ap.add_argument('--dpi', type=int, default=90, help='그림·쪽 이미지 해상도(기본 90)')
    ap.add_argument('--no-ocr', action='store_true', help='OCR 을 쓰지 않는다')
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    out = a.out or (os.path.splitext(a.pdf)[0] + '_digest')
    s = build_digest(a.pdf, out, pages=a.pages, dpi=a.dpi, ocr=not a.no_ocr)
    print(f"요약본: {s['digest_path']}")
    print('쪽 | 종류 | 글자 | 표 | 그림 | 표시')
    for r in s['pages']:
        print(f"{r['page']:>3} | {r['kind']:<7} | {r['chars']:>5} | {r['tables']:>2} | {r['figs']:>2} | {r['flag']}")
    print(f"토큰 어림: 요약본 글자 {s['text_tokens']:,} + 그림 {s['figure_tokens_if_all_viewed']:,} + 표로 보이는 스캔 쪽 이미지 {s['recommended_view_tokens'] - s['figure_tokens_if_all_viewed']:,}"
          f" = 권장 {s['text_tokens'] + s['recommended_view_tokens']:,}  (쪽 전체를 이미지로 보낼 때 {s['baseline_all_pages_as_images']:,})")
    print(f"절감 어림: 글자만 {s['saving_text_only_pct']}% / 권장 범위만 보면 {s['saving_recommended_pct']}% / 스캔 쪽 이미지까지 전부 보면 {s['saving_with_all_figs_pct']}%  (OCR {'사용' if s['ocr_used'] else '미사용'})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
