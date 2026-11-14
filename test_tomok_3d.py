"""공사 카드 3D(/tomok_3d, static/tomok_card.js, 법규 검토 설계 수치 칸) 시험. `python test_tomok_3d.py`. 네트워크 불필요."""
import os
import re
import unittest

import app as appmod

HERE = os.path.dirname(os.path.abspath(__file__))


class Tomok3DTests(unittest.TestCase):
    def setUp(self):
        self.http = appmod.app.test_client()

    def test_page_served_and_offline(self):
        r = self.http.get('/tomok_3d')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        # 행정망(인터넷 차단)에서도 열리도록 외부 스크립트·CDN을 쓰지 않는다
        self.assertNotRegex(html, r'(src|href)="(https?:)?//')
        self.assertNotIn('cdn.jsdelivr', html)
        for path in re.findall(r'"(/static/vendor/three/[^"]+)"', html):
            target = path if path.endswith('.js') else path + 'controls/OrbitControls.js'
            self.assertEqual(self.http.get(target).status_code, 200, target)
        self.assertIn('window.loadCard', html)
        self.assertIn("'tomok-card'", html)

    def test_vendor_files(self):
        base = os.path.join(HERE, 'static', 'vendor', 'three')
        self.assertTrue(os.path.getsize(os.path.join(base, 'three.module.min.js')) > 500_000)
        oc = open(os.path.join(base, 'addons', 'controls', 'OrbitControls.js'), encoding='utf-8').read()
        self.assertIn("from 'three'", oc)  # importmap으로 위 파일에 연결된다
        self.assertTrue(os.path.exists(os.path.join(base, 'LICENSE')))

    def test_law_review_has_design_inputs(self):
        html = self.http.get('/law_review').get_data(as_text=True)
        for el in ('d3-L', 'd3-B', 'd3-T', 'd3-joint', 'd3-flume', 'd3-unit', 'd3-pit', 'd3-toggle', 'd3-open', 'd3-desc'):
            self.assertIn(f'id="{el}"', html)
        self.assertIn('/static/tomok_card.js', html)

    def test_form_hooks_keep_design(self):
        js = open(os.path.join(HERE, 'static', 'script.js'), encoding='utf-8').read()
        self.assertIn('design: window.TomokCard', js)  # 저장된 분석의 입력에 설계 수치가 남는다
        inp = open(os.path.join(HERE, 'static', 'law_review_input.js'), encoding='utf-8').read()
        self.assertIn('TomokCard.apply', inp)

    def test_home_card(self):
        self.assertIn('href="/tomok_3d"', self.http.get('/').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
