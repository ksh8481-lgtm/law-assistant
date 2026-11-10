"""내역서·설명서 읽기(project_docs.py)와 /api/project_docs/start 시험. `python test_project_docs.py`. 네트워크·AI 불필요(AI는 가짜).

핵심: openpyxl 없이도 xlsx를 읽는가 / docx·hwpx·pdf / 지원하지 않는 형식은 사용자에게 보여 줄 말로 거절 / 스캔본 PDF는 AI에 넘김 /
임시 파일은 항상 지워지는가 / AI가 서류에 없는 말을 지어내지 않도록 지시문에 규칙이 들어 있는가.
"""
import os
import tempfile
import time
import unittest
import zipfile

import project_docs as pdocs

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def make_xlsx(path, sheets):
    """표준 라이브러리만으로 만든 최소 xlsx. sheets = [(이름, [[셀, ...], ...])]. 문자열은 공유 문자열, 숫자는 값, ('f', 계산값)은 수식 셀."""
    shared, sheet_xml = [], []
    for _name, rows in sheets:
        xs = []
        for ri, row in enumerate(rows, 1):
            cs = []
            for ci, v in enumerate(row, 1):
                ref = f"{chr(64 + ci)}{ri}"
                if v is None:
                    continue
                if isinstance(v, tuple):
                    cs.append(f'<c r="{ref}"><f>SUM(A1:A2)</f><v>{v[1]}</v></c>')
                elif isinstance(v, (int, float)):
                    cs.append(f'<c r="{ref}"><v>{v}</v></c>')
                else:
                    shared.append(v)
                    cs.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            xs.append(f'<row r="{ri}">{"".join(cs)}</row>')
        sheet_xml.append(f'<worksheet xmlns="{MAIN}"><sheetData>{"".join(xs)}</sheetData></worksheet>')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        sheets_el = ''.join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, (n, _r) in enumerate(sheets, 1))
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{MAIN}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{sheets_el}</sheets></workbook>')
        rels = ''.join(f'<Relationship Id="rId{i}" Type="x" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
        z.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        z.writestr('xl/sharedStrings.xml', f'<sst xmlns="{MAIN}">' + ''.join(f'<si><t>{s}</t></si>' for s in shared) + '</sst>')
        for i, x in enumerate(sheet_xml, 1):
            z.writestr(f'xl/worksheets/sheet{i}.xml', x)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.dir, name)


class XlsxTests(Tmp):
    def test_reads_strings_numbers_and_formula_values_without_openpyxl(self):
        p = self.path('내역서.xlsx')
        make_xlsx(p, [('공종별내역서', [['공종', '규격', '수량'], ['토공', '굴착 L=300m', 1234.5], ['포장', '아스콘', 3.0], ['합계', None, ('f', 1237.5)]])])
        text, truncated, n = pdocs.xlsx_text(p)
        self.assertEqual((truncated, n), (False, 1))
        self.assertIn('[엑셀 시트: 공종별내역서]', text)
        self.assertIn('토공 | 굴착 L=300m | 1234.5', text)
        self.assertIn('포장 | 아스콘 | 3', text)                  # 3.0 -> 3
        self.assertIn('합계 | 1237.5', text)                       # 수식 셀은 저장된 값
        self.assertNotIn('None', text)

    def test_summary_sheets_come_first_and_long_sheets_are_truncated(self):
        p = self.path('big.xlsx')
        rows = [[f'항목{i}', i] for i in range(1, 401)]
        make_xlsx(p, [('세부내역', rows), ('총괄표', [['총사업비', 5000000000]])])
        text, truncated, _n = pdocs.xlsx_text(p, max_rows=50)
        self.assertTrue(truncated)
        self.assertLess(text.index('[엑셀 시트: 총괄표]'), text.index('[엑셀 시트: 세부내역]'))   # 총괄이 먼저
        self.assertIn('앞의 50줄만 읽었습니다', text)
        self.assertNotIn('항목399', text)

    def test_matches_openpyxl_when_available(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest('openpyxl 없음')
        p = self.path('real.xlsx')
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '내역'
        ws.append(['공종', '수량'])
        ws.append(['콘크리트', 12.5])
        ws.append(['철근', 7])
        wb.save(p)
        text, _t, _n = pdocs.xlsx_text(p)
        self.assertIn('콘크리트 | 12.5', text)
        self.assertIn('철근 | 7', text)


class OtherFormatTests(Tmp):
    def test_docx_paragraphs_and_tables(self):
        W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        body = (f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>사업 목적: 도로 개설</w:t></w:r></w:p>'
                '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>연장</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>300m</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        p = self.path('설명서.docx')
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('word/document.xml', body)
        self.assertEqual(pdocs.docx_text(p), '사업 목적: 도로 개설\n연장 | 300m')

    def test_hwpx(self):
        sec = ('<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
               '<hp:p><hp:run><hp:t>사업명: 남해읍 도로</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>폭 8m</hp:t></hp:run></hp:p></hs:sec>')
        p = self.path('설명서.hwpx')
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('Contents/section0.xml', sec)
        self.assertEqual(pdocs.hwpx_text(p), '사업명: 남해읍 도로\n폭 8m')

    def test_pdf_text_and_scanned_detection(self):
        import pymupdf
        p = self.path('a.pdf')
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), 'Project purpose: road construction. Length 300 m, width 8 m. ' * 4)
        doc.save(p)
        doc.close()
        text, pages, scanned = pdocs.pdf_text(p)
        self.assertEqual((pages, scanned), (1, False))
        self.assertIn('road construction', text)
        blank = self.path('scan.pdf')
        d2 = pymupdf.open()
        d2.new_page()
        d2.save(blank)
        d2.close()
        info = pdocs.read_document(blank, 'scan.pdf')                  # 글자가 없어도 스캔본이면 거절하지 않고 표시
        self.assertTrue(info['scanned'])

    def test_plain_text(self):
        p = self.path('a.txt')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('연장 300m')
        self.assertEqual(pdocs.read_document(p)['text'], '연장 300m')


def dxf_bytes(pairs, codepage=None, encoding='utf-8'):
    """(코드, 값) 쌍 목록으로 최소 ASCII DXF를 만든다."""
    out = []
    for c, v in pairs:
        out.append(f'{c:>3}\r\n{v}\r\n')
    return ''.join(out).encode(encoding)


def sample_dxf(encoding='utf-8', codepage='ANSI_949'):
    header = [(0, 'SECTION'), (2, 'HEADER'), (9, '$ACADVER'), (1, 'AC1027'), (9, '$DWGCODEPAGE'), (3, codepage), (9, '$INSUNITS'), (70, 4), (0, 'ENDSEC')]
    ents = [(0, 'SECTION'), (2, 'ENTITIES'),
            (0, 'TEXT'), (8, '주기'), (1, '도로 확장 B=6.0m (기존 4.0m)'),
            (0, 'MTEXT'), (8, '주기'), (3, '아스콘 포장 '), (1, '{\\fMalgun Gothic|b0;t=5cm\\P}표층'),
            (0, 'TEXT'), (8, '주기'), (1, '도로 확장 B=6.0m (기존 4.0m)'),
            (0, 'DIMENSION'), (8, '치수'), (1, '<>'), (42, '6000.0'),
            (0, 'DIMENSION'), (8, '치수'), (1, 'L=%%c600'), (42, '310000.0'),
            (0, 'LINE'), (8, '도로중심선'),
            (0, 'ATTDEF'), (8, '표제'), (1, 'DWG NO'),
            (0, 'ATTRIB'), (8, '표제'), (1, '도면명: 남해읍 마을안길 평면도'),
            (0, 'ENDSEC'), (0, 'EOF')]
    return dxf_bytes(header + ents, encoding=encoding)


class DrawingTests(Tmp):
    def check_dxf(self, enc):
        p = self.path('평면도.dxf')
        with open(p, 'wb') as f:
            f.write(sample_dxf(encoding=enc))
        text, cut = pdocs.dxf_text(p)
        self.assertFalse(cut)
        self.assertIn('밀리미터(mm)', text)
        self.assertIn('도로 확장 B=6.0m (기존 4.0m) (x2)', text)          # 같은 글자는 한 번만, 횟수 표시
        self.assertIn('아스콘 포장 t=5cm 표층', text)                     # MTEXT 이어 붙임 + 서식 코드 제거
        self.assertIn('도면명: 남해읍 마을안길 평면도', text)
        self.assertNotIn('DWG NO', text)                                  # ATTDEF(양식 글자)는 제외
        self.assertIn('6000', text)
        self.assertIn('310000 (표기: L=Ø600)', text)                      # 치수 값 + 사용자가 바꿔 쓴 표기, %%c -> Ø
        self.assertIn('도로중심선(1)', text)                              # 레이어 목록
        self.assertNotIn('Malgun', text)
        return text

    def test_dxf_utf8(self):
        self.check_dxf('utf-8')

    def test_dxf_korean_ansi_codepage(self):
        self.check_dxf('cp949')                                           # 옛 한국 CAD가 저장하는 cp949

    def test_dxf_without_text_says_so(self):
        p = self.path('lines.dxf')
        with open(p, 'wb') as f:
            f.write(dxf_bytes([(0, 'SECTION'), (2, 'ENTITIES'), (0, 'LINE'), (8, '0'), (0, 'ENDSEC'), (0, 'EOF')]))
        text, _c = pdocs.dxf_text(p)
        self.assertIn('PDF로 출력해', text)

    def test_dxf_errors_and_dwg(self):
        p = self.path('b.dxf')
        with open(p, 'wb') as f:
            f.write(b'AutoCAD Binary DXF\r\n\x1a\x00')
        with self.assertRaises(pdocs.UnsupportedDoc) as cm:
            pdocs.read_document(p, 'b.dxf')
        self.assertIn('바이너리', str(cm.exception))
        q = self.path('c.dxf')
        with open(q, 'wb') as f:
            f.write(b'this is not dxf at all\nreally')
        with self.assertRaises(pdocs.UnsupportedDoc):
            pdocs.read_document(q, 'c.dxf')
        d = self.path('d.dwg')
        with open(d, 'wb') as f:
            f.write(b'AC1032\x00\x00')
        with self.assertRaises(pdocs.UnsupportedDoc) as cm:
            pdocs.read_document(d, 'd.dwg')
        self.assertIn('DXF', str(cm.exception))
        self.assertIn('PDF', str(cm.exception))

    def test_image_is_visual_only_and_not_rejected(self):
        p = self.path('도면.png')
        with open(p, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'0' * 100)
        info = pdocs.read_document(p, '도면.png')
        self.assertTrue(info['scanned'])
        self.assertEqual(info['text'], '')

    def test_trim_pdf(self):
        import pymupdf
        p = self.path('many.pdf')
        doc = pymupdf.open()
        for i in range(5):
            doc.new_page().insert_text((72, 72), f'page {i}')
        doc.save(p)
        doc.close()
        out = self.path('trim.pdf')
        self.assertEqual(pdocs.trim_pdf(p, out, max_pages=3), (5, 3))
        self.assertEqual(len(pymupdf.open(out)), 3)
        self.assertEqual(pdocs.trim_pdf(p, self.path('x.pdf'), max_pages=9), (5, 5))
        self.assertFalse(os.path.exists(self.path('x.pdf')))               # 줄일 필요 없으면 만들지 않는다


class UnsupportedTests(Tmp):
    def raises(self, name, content=b'x', contains=''):
        p = self.path(name)
        with open(p, 'wb') as f:
            f.write(content)
        with self.assertRaises(pdocs.UnsupportedDoc) as cm:
            pdocs.read_document(p, name)
        self.assertIn(contains, str(cm.exception))
        return str(cm.exception)

    def test_old_formats_get_a_clear_instruction(self):
        self.assertIn('.xlsx', self.raises('a.xls', contains='옛 엑셀'))
        self.assertIn('hwpx', self.raises('a.hwp', contains='옛 한글'))
        self.raises('a.doc', contains='.docx')
        self.raises('a.zip', contains='지원하지 않는 형식')

    def test_broken_or_empty_files(self):
        self.raises('b.xlsx', b'not a zip', contains='읽지 못했습니다')
        self.raises('empty.txt', b'   ', contains='글자를 찾지 못했습니다')

    def test_too_big(self):
        p = self.path('big.txt')
        with open(p, 'wb') as f:
            f.write(b'a' * 2048)
        orig = pdocs.MAX_FILE_BYTES
        pdocs.MAX_FILE_BYTES = 1024
        try:
            with self.assertRaises(pdocs.UnsupportedDoc):
                pdocs.read_document(p)
        finally:
            pdocs.MAX_FILE_BYTES = orig

    def test_long_text_is_cut_and_flagged(self):
        p = self.path('long.txt')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('가' * 500)
        info = pdocs.read_document(p, max_chars=100)
        self.assertEqual((len(info['text']), info['truncated']), (100, True))


class PromptTests(unittest.TestCase):
    def test_prompt_forbids_inventing_and_carries_inputs(self):
        pr = pdocs.build_prompt('토목공사', '내역 본문', '설명 본문', ['scan.pdf'], '남해읍 도로')
        for needle in ('서류에 적힌 내용만 쓰십시오', '지어내거나', '서류에서 찾지 못한 정보', '법령 적용 의견은 쓰지 마십시오', '내역 본문', '설명 본문', 'scan.pdf', '토목공사', '남해읍 도로'):
            self.assertIn(needle, pr, needle)
        self.assertIn('(설명서 없음)', pdocs.build_prompt('', '내역', '', [], ''))
        self.assertIn('[3. 내역서 주요 공종·수량]', pdocs.build_prompt('', '내역', '', [], ''))
        self.assertNotIn('[3. 내역서 주요 공종·수량]', pdocs.build_prompt('', '', '설명', [], ''))   # 내역서가 없으면 [3] 틀을 주지 않는다
        no_draw = pdocs.build_prompt('', '내역', '설명', [], '')
        self.assertIn('(도면 없음)', no_draw)
        self.assertNotIn('(도면)', no_draw)                                    # 도면이 없으면 도면 규칙을 넣지 않는다
        with_draw = pdocs.build_prompt('', '', '', [], '', draw_text='[DXF 도면] x', draw_names=['평면도.pdf'])
        for needle in ('"(도면)"', '축척으로 환산해 계산하지 마십시오', '판독 불확실', '평면도.pdf', '[DXF 도면] x'):
            self.assertIn(needle, with_draw, needle)


class EndpointTests(Tmp):
    def setUp(self):
        super().setUp()
        import app as appmod
        self.appmod = appmod
        self.http = appmod.app.test_client()
        self._orig = (appmod.GEMINI_KEY, appmod.gemini_client.generate_with_fallback, appmod.upload_file_for_gemini, appmod.gemini_file_part)
        appmod.GEMINI_KEY = 'test'
        self.calls = []

        class R:
            text = '```text\n[1. 사업 개요]\n- 사업명: 시험\n```'
        appmod.gemini_client.generate_with_fallback = lambda payload, **k: (self.calls.append(payload) or (R(), 'm'))
        self.uploaded = []
        appmod.upload_file_for_gemini = lambda path, display_name=None, **k: (self.uploaded.append(display_name) or type('G', (), {'mime_type': 'application/pdf', 'uri': 'u'})())
        self.temps = []
        import tempfile as tf
        self._mk = tf.mkstemp

        def tracked(*a, **k):
            fd, path = self._mk(*a, **k)
            self.temps.append(path)
            return fd, path
        tf.mkstemp = tracked

    def tearDown(self):
        import tempfile as tf
        tf.mkstemp = self._mk
        a = self.appmod
        a.GEMINI_KEY, a.gemini_client.generate_with_fallback, a.upload_file_for_gemini, a.gemini_file_part = self._orig
        super().tearDown()

    def post(self, files):
        data = {}
        for field, name, content in files:
            data.setdefault(field, []).append((__import__('io').BytesIO(content), name))
        data['projectType'] = '토목공사'
        return self.http.post('/api/project_docs/start', data=data, content_type='multipart/form-data')

    def wait(self, job_id):
        for _ in range(200):
            d = self.http.get(f'/api/analyze/status/{job_id}').get_json()
            if d['status'] != 'processing':
                return d
            time.sleep(0.05)
        self.fail('작업이 끝나지 않음')

    def xlsx_bytes(self):
        p = self.path('b.xlsx')
        make_xlsx(p, [('총괄', [['공종', '금액'], ['토공', 1000]])])
        return open(p, 'rb').read()

    def test_no_files_is_rejected(self):
        r = self.http.post('/api/project_docs/start', data={}, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 400)

    def test_reads_files_and_returns_clean_text_and_removes_temp_files(self):
        r = self.post([('bill', '내역서.xlsx', self.xlsx_bytes()), ('spec', '설명서.txt', '사업 목적: 도로 개설\n연장 300m'.encode('utf-8'))])
        self.assertEqual(r.status_code, 200)
        d = self.wait(r.get_json()['job_id'])
        self.assertEqual(d['status'], 'completed', d)
        res = d['result']
        self.assertEqual(res['text'], '[1. 사업 개요]\n- 사업명: 시험')                       # 코드 블록 표시는 걷어 낸다
        self.assertEqual([(f['name'], f['role']) for f in res['files']], [('내역서.xlsx', 'bill'), ('설명서.txt', 'spec')])
        prompt = self.calls[0][-1]
        self.assertIn('토공 | 1000', prompt)                                                 # 내역서 글이 AI에 전달됨
        self.assertIn('연장 300m', prompt)
        self.assertTrue(self.temps and all(not os.path.exists(t) for t in self.temps), '임시 파일이 남았다')

    def test_unsupported_files_become_notes_but_others_still_work(self):
        r = self.post([('bill', '옛.xls', b'x'), ('spec', '설명서.txt', 'abc 설명'.encode('utf-8'))])
        d = self.wait(r.get_json()['job_id'])
        self.assertEqual(d['status'], 'completed', d)
        self.assertTrue(any('옛 엑셀' in n for n in d['result']['notes']))
        self.assertEqual(len(d['result']['files']), 1)

    def test_only_unsupported_files_is_an_error_with_instructions(self):
        r = self.post([('spec', '옛.hwp', b'x')])
        d = self.wait(r.get_json()['job_id'])
        self.assertEqual(d['status'], 'error')
        self.assertIn('hwpx', d['message'])
        self.assertTrue(all(not os.path.exists(t) for t in self.temps))

    def test_scanned_pdf_is_uploaded_to_the_ai(self):
        import pymupdf
        p = self.path('scan.pdf')
        doc = pymupdf.open()
        doc.new_page()
        doc.save(p)
        doc.close()
        r = self.post([('spec', '스캔.pdf', open(p, 'rb').read())])
        d = self.wait(r.get_json()['job_id'])
        self.assertEqual(d['status'], 'completed', d)
        self.assertEqual(self.uploaded, ['스캔.pdf'])
        self.assertTrue(any('스캔본' in n for n in d['result']['notes']))
        self.assertEqual(len(self.calls[0]), 2)                                            # [파일 조각, 지시문]

    def test_ai_failure_is_reported_and_files_removed(self):
        def boom(*a, **k):
            raise RuntimeError('429 quota')
        self.appmod.gemini_client.generate_with_fallback = boom
        r = self.post([('spec', '설명서.txt', 'abc 설명'.encode('utf-8'))])
        d = self.wait(r.get_json()['job_id'])
        self.assertEqual(d['status'], 'error')
        self.assertIn('429', d['message'])
        self.assertTrue(all(not os.path.exists(t) for t in self.temps))

    def pdf_bytes(self, pages, text='Plan view road width 6m length 310m. ' * 3):
        import pymupdf
        p = self.path('d%d.pdf' % pages)
        doc = pymupdf.open()
        for i in range(pages):
            doc.new_page().insert_text((72, 72), text)
        doc.save(p)
        doc.close()
        return open(p, 'rb').read()

    def test_drawing_pdf_is_attached_for_the_ai_to_see_and_text_goes_in_prompt(self):
        r = self.post([('draw', '평면도.pdf', self.pdf_bytes(2))])
        d = self.wait(r.get_json()['job_id'])
        self.assertEqual(d['status'], 'completed', d)
        self.assertEqual(self.uploaded, ['평면도.pdf'])
        self.assertEqual(len(self.calls[0]), 2)
        prompt = self.calls[0][-1]
        self.assertIn('Plan view road width 6m', prompt)                    # 도면 PDF의 글자도 함께
        self.assertIn('도면 파일 - 함께 첨부', prompt)
        self.assertEqual([(f['name'], f['role']) for f in d['result']['files']], [('평면도.pdf', 'draw')])
        self.assertTrue(all(not os.path.exists(t) for t in self.temps))

    def test_long_drawing_pdf_is_trimmed_for_the_ai_and_temp_files_removed(self):
        orig = pdocs.DRAW_MAX_PAGES
        pdocs.DRAW_MAX_PAGES = 2
        try:
            r = self.post([('draw', '긴도면.pdf', self.pdf_bytes(5))])
            d = self.wait(r.get_json()['job_id'])
        finally:
            pdocs.DRAW_MAX_PAGES = orig
        self.assertEqual(d['status'], 'completed', d)
        self.assertTrue(any('5쪽' in n and '앞의 2쪽' in n for n in d['result']['notes']), d['result']['notes'])
        self.assertTrue(all(not os.path.exists(t) for t in self.temps), '줄인 임시 PDF가 남았다')

    def test_dxf_drawing_goes_as_text_only(self):
        r = self.post([('draw', '평면도.dxf', sample_dxf())])
        d = self.wait(r.get_json()['job_id'])
        self.assertEqual(d['status'], 'completed', d)
        self.assertEqual(self.uploaded, [])                                  # DXF는 글로만 보낸다
        self.assertEqual(len(self.calls[0]), 1)
        self.assertIn('도면명: 남해읍 마을안길 평면도', self.calls[0][-1])

    def test_image_drawing_is_attached(self):
        r = self.post([('draw', '단면도.png', b'\x89PNG\r\n\x1a\n' + b'0' * 50)])
        d = self.wait(r.get_json()['job_id'])
        self.assertEqual(d['status'], 'completed', d)
        self.assertEqual(self.uploaded, ['단면도.png'])
        self.assertTrue(any('이미지' in n for n in d['result']['notes']))

    def test_dwg_only_is_an_error_that_explains_dxf_or_pdf(self):
        r = self.post([('draw', '원본.dwg', b'AC1032')])
        d = self.wait(r.get_json()['job_id'])
        self.assertEqual(d['status'], 'error')
        self.assertIn('DXF', d['message'])

    def test_too_many_files(self):
        r = self.post([('spec', f'{i}.txt', b'abc') for i in range(7)])
        self.assertEqual(r.status_code, 400)
        self.assertIn('6개', r.get_json()['message'])
        self.assertTrue(all(not os.path.exists(t) for t in self.temps))


class PageTests(unittest.TestCase):
    def test_page_has_docs_panel_and_no_profiler(self):
        import app as appmod
        html = appmod.app.test_client().get('/law_review').get_data(as_text=True)
        for needle in ('id="docs-panel"', 'id="docs-bill"', 'id="docs-spec"', 'id="docs-draw"', 'id="docs-read-btn"', 'id="docs-result"', 'law_review_docs.js'):
            self.assertIn(needle, html, needle)
        for gone in ('스마트 공사 프로파일러', 'generate-template-btn', 'smart-tags-container', 'domain-tab-btn'):
            self.assertNotIn(gone, html, gone)
        js = appmod.app.test_client().get('/static/script.js').get_data(as_text=True)
        self.assertNotIn('domainTagsData', js)
        self.assertIn('window.LRForm', js)                                    # 입력 도우미가 쓰는 함수는 그대로


if __name__ == '__main__':
    unittest.main(verbosity=2)
