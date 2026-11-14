"""tools/pdf_digest.py 시험. `python test_pdf_digest.py`. 네트워크·AI 불필요. OCR 시험은 Windows 에서만 돈다(아니면 건너뜀).

시험용 PDF 는 pymupdf 로 직접 만든다: 1쪽 = 글자 + 선 있는 표 + 벡터 막대그래프(캡션) + 래스터 그림, 2쪽 = 글자만, 3쪽 = 스캔본(글자를 이미지로만 넣음),
4쪽 = 글자가 깨진 쪽(기호만 나오는 글자).
"""
import os
import shutil
import sys
import tempfile
import unittest

import pymupdf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
import pdf_digest as P  # noqa: E402

PARAGRAPH = ('The committee reviewed the proposal and concluded that the project area may be extended. '
             'Further consultation with the competent authority is required before approval. ') * 2


def make_pdf(path):
    doc = pymupdf.open()
    # --- 1쪽: 글자 + 표 + 벡터 차트 + 래스터 그림
    p = doc.new_page()
    p.insert_text((50, 60), 'Section 1. Overview', fontsize=16)
    p.insert_textbox(pymupdf.Rect(50, 75, 545, 150), PARAGRAPH, fontsize=10)
    x0, y0, cw, rh = 50, 170, 120, 24
    rows = [['Item', 'Qty', 'Amount'], ['Pipe A', '12', '1,200'], ['Pipe B', '7', '3,500'], ['Total', '19', '4,700']]
    for r in range(len(rows) + 1):
        p.draw_line((x0, y0 + r * rh), (x0 + 3 * cw, y0 + r * rh))
    for c in range(4):
        p.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + len(rows) * rh))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            p.insert_text((x0 + c * cw + 6, y0 + r * rh + 16), val, fontsize=10)
    # 벡터 막대그래프
    cx, cy = 60, 460
    p.draw_line((cx, cy), (cx, cy - 150))
    p.draw_line((cx, cy), (cx + 260, cy))
    for i, hgt in enumerate((60, 110, 85, 130)):
        p.draw_rect(pymupdf.Rect(cx + 20 + i * 58, cy - hgt, cx + 60 + i * 58, cy), fill=(0.2, 0.4, 0.8))
        p.insert_text((cx + 25 + i * 58, cy + 14), f'Q{i + 1}', fontsize=9)
    p.insert_text((cx, cy + 40), 'Figure 1. Sales by quarter', fontsize=9)
    # 래스터 그림
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 160, 120), False)
    pix.set_rect(pix.irect, (200, 120, 60))
    p.insert_image(pymupdf.Rect(350, 330, 510, 450), pixmap=pix)
    # --- 2쪽: 글자만
    p2 = doc.new_page()
    p2.insert_textbox(pymupdf.Rect(50, 60, 545, 700), PARAGRAPH * 3, fontsize=11)
    # --- 3쪽: 스캔본(글자를 이미지로만)
    tmp = pymupdf.open()
    tp = tmp.new_page()
    tp.insert_textbox(pymupdf.Rect(50, 60, 545, 700), PARAGRAPH * 3, fontsize=14)
    img = tp.get_pixmap(dpi=150)
    p3 = doc.new_page()
    p3.insert_image(p3.rect, pixmap=img)
    # --- 4쪽: 글자가 깨진 쪽(기호만 나오는 글자)
    p4 = doc.new_page()
    p4.insert_textbox(pymupdf.Rect(50, 60, 545, 300), '!"#$%$!  &\'()*+,-./  :;<=>?@  [\\]^_`  {|}~ ' * 12, fontsize=11)
    doc.save(path)
    doc.close()


class HelperTests(unittest.TestCase):
    def test_wordish_ratio_detects_symbol_garbage(self):
        self.assertGreater(P.wordish_ratio('안녕하세요 Hello 123'), 0.9)
        self.assertLess(P.wordish_ratio('!"#$%$! &\'()*+,-./ :;<=>?@'), 0.2)
        self.assertEqual(P.wordish_ratio(''), 1.0)

    def test_token_estimates(self):
        self.assertEqual(P.est_text_tokens(1300), 1000)
        self.assertEqual(P.est_image_tokens(750, 100), 100)

    def test_table_markdown_and_escape(self):
        md = P._table_markdown([['A', 'B'], ['x|y', None], ['1', '2\n3']])
        self.assertEqual(md.splitlines()[0], '| A | B |')
        self.assertIn('x\\|y', md)
        self.assertIn('| 1 | 2 3 |', md)
        self.assertEqual(P._table_markdown([['only one row', 'x']]), '')

    def test_table_like_uses_short_lines(self):
        self.assertTrue(P.table_like('\n'.join(['1 식', '강정옥', '관정', '1,800,000'] * 8)))
        self.assertFalse(P.table_like('\n'.join(['This is a long ordinary sentence of prose text number %d.' % i for i in range(30)])))
        self.assertFalse(P.table_like('a\nb\nc'))                                         # 줄이 적으면 판단 안 함

    def test_merge_rects_joins_touching_pieces(self):
        r = P._merge_rects([pymupdf.Rect(0, 0, 50, 50), pymupdf.Rect(52, 0, 100, 50), pymupdf.Rect(300, 300, 350, 350)])
        self.assertEqual(len(r), 2)

    def test_parse_pages(self):
        self.assertEqual(P.parse_pages('1-3,5', 10), [1, 2, 3, 5])
        self.assertEqual(P.parse_pages('8-', 10), [8, 9, 10])
        self.assertEqual(P.parse_pages('', 3), [1, 2, 3])
        self.assertEqual(P.parse_pages('2,2,99', 5), [2])


class DigestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.pdf = os.path.join(cls.dir, 'mixed.pdf')
        make_pdf(cls.pdf)
        cls.out = os.path.join(cls.dir, 'out')
        cls.summary = P.build_digest(cls.pdf, cls.out, ocr=False)
        with open(os.path.join(cls.out, 'digest.md'), encoding='utf-8') as f:
            cls.md = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def kinds(self):
        return [r['kind'] for r in self.summary['pages']]

    def test_page_kinds(self):
        self.assertEqual(self.kinds(), ['digital', 'digital', 'scan', 'garbled'])

    def test_table_becomes_markdown_and_is_not_duplicated_as_text(self):
        self.assertEqual(self.summary['pages'][0]['tables'], 1)
        self.assertIn('| Item | Qty | Amount |', self.md)
        self.assertIn('| Pipe B | 7 | 3,500 |', self.md)
        self.assertEqual(self.md.count('Pipe B'), 1)                                       # 표 안의 글자가 본문에 또 나오지 않는다

    def test_text_is_kept_in_reading_order(self):
        self.assertLess(self.md.index('Section 1. Overview'), self.md.index('| Item |'))
        self.assertIn('the project area may be extended', self.md)

    def test_figures_are_cropped_and_referenced_not_inlined(self):
        figs = os.listdir(os.path.join(self.out, 'figs'))
        self.assertIn('p1_f1.png', figs)                                                   # 차트 또는 그림이 파일로 저장됨
        self.assertGreaterEqual(self.summary['pages'][0]['figs'], 2)                        # 벡터 차트 + 래스터 그림
        self.assertIn('figs/p1_f1.png', self.md)
        body = [l for l in self.md.splitlines() if 'Q3' in l]
        self.assertEqual(len(body), 1)                                                     # 차트 눈금 글자는 본문 줄이 아니라 〔그림 속 글자〕 한 줄에만 있다
        self.assertTrue(body[0].startswith('〔그림 속 글자:'))
        self.assertIn('Figure 1. Sales by quarter', self.md)                               # 캡션은 본문 또는 그림 옆에 남는다

    def test_figure_images_are_downscaled(self):
        for name in os.listdir(os.path.join(self.out, 'figs')):
            pix = pymupdf.Pixmap(os.path.join(self.out, 'figs', name))
            self.assertLessEqual(max(pix.width, pix.height), P.FIG_MAX_EDGE_PX + 2, name)

    def test_scan_and_garbled_pages_point_to_page_image_when_no_ocr(self):
        self.assertIn('## 쪽 3 [scan]', self.md)
        self.assertIn('## 쪽 4 [garbled]', self.md)
        self.assertIn('figs/p3_page.png', self.md)
        self.assertIn('OCR 없음', self.md)
        self.assertEqual(self.summary['pages'][2]['flag'], 'image-only')

    def test_saving_estimate_is_reported_against_all_pages_as_images(self):
        s = self.summary
        self.assertGreater(s['baseline_all_pages_as_images'], s['text_tokens'])
        self.assertGreater(s['saving_text_only_pct'], 0)

    def test_pages_option_limits_work(self):
        out = os.path.join(self.dir, 'out2')
        s = P.build_digest(self.pdf, out, pages='2', ocr=False)
        self.assertEqual([r['page'] for r in s['pages']], [2])

    def test_cli_prints_a_summary_table(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(P.main([self.pdf, '-o', os.path.join(self.dir, 'out3'), '--no-ocr']), 0)
        text = buf.getvalue()
        self.assertIn('요약본:', text)
        self.assertIn('토큰 어림', text)
        self.assertIn('digital', text)


@unittest.skipUnless(sys.platform.startswith('win'), 'Windows 내장 OCR 시험')
class OcrTests(unittest.TestCase):
    def test_scan_page_gets_ocr_text(self):
        d = tempfile.mkdtemp()
        try:
            pdf = os.path.join(d, 'mixed.pdf')
            make_pdf(pdf)
            s = P.build_digest(pdf, os.path.join(d, 'out'), pages='3', ocr=True)
            if not s['ocr_used']:
                self.skipTest('이 PC에 OCR 엔진이 없다')
            with open(os.path.join(d, 'out', 'digest.md'), encoding='utf-8') as f:
                md = f.read()
            self.assertIn('OCR 글자입니다', md)
            self.assertIn('committee', md)
            self.assertGreater(s['pages'][0]['chars'], 100)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
