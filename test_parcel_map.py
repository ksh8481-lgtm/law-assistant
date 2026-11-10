"""편입 필지 지도(/api/parcel_geometry, static/parcel_map.js, 화면 요소) 시험. `python test_parcel_map.py`. 네트워크 불필요(VWorld는 가짜)."""
import unittest

import app as appmod

PNU_A = '4884025022101000000'
PNU_B = '4884025022100990000'
PNU_C = '4884025022199999999'


def vworld_ok(pnu, jibun='100 대'):
    return {"response": {"status": "OK", "result": {"featureCollection": {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[[[127.0, 34.0], [127.1, 34.0], [127.1, 34.1], [127.0, 34.0]]]]},
        "properties": {"pnu": pnu, "jibun": jibun, "addr": "경상남도 남해군 남해읍 서변리 100", "jiga": "626900", "gosi_year": "2025"}}]}}}}


class FakeResp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class GeometryEndpointTests(unittest.TestCase):
    def setUp(self):
        self.http = appmod.app.test_client()
        self.calls = []
        self._orig = appmod.requests.get
        appmod._PARCEL_GEOM_CACHE.clear()

        def fake_get(url, params=None, timeout=None):
            self.calls.append(params)
            pnu = params['attrFilter'].split(':=:')[1]
            if pnu == PNU_C:
                return FakeResp({"response": {"status": "NOT_FOUND"}})
            if pnu == PNU_B:
                return FakeResp({"response": {"status": "ERROR", "error": {"code": "INCORRECT_KEY", "text": "인증키 정보가 올바르지 않습니다."}}})
            return FakeResp(vworld_ok(pnu))
        appmod.requests.get = fake_get

    def tearDown(self):
        appmod.requests.get = self._orig
        appmod._PARCEL_GEOM_CACHE.clear()

    def test_returns_features_missing_and_errors_separately(self):
        d = self.http.get(f'/api/parcel_geometry?pnu={PNU_A},{PNU_B},{PNU_C}').get_json()
        self.assertTrue(d['success'])
        self.assertEqual([f['properties']['pnu'] for f in d['features']], [PNU_A])
        self.assertEqual(d['features'][0]['properties']['jibun'], '100 대')
        self.assertEqual(d['features'][0]['geometry']['type'], 'MultiPolygon')
        self.assertEqual(d['missing'], [PNU_C])                                   # 지적도에 없음(오류 아님)
        self.assertEqual([e['pnu'] for e in d['errors']], [PNU_B])                # 조회 오류는 따로 알린다
        self.assertIn('인증키', d['errors'][0]['message'])

    def test_request_uses_cadastral_layer_wgs84_and_a_registered_domain(self):
        self.http.get(f'/api/parcel_geometry?pnu={PNU_A}')                      # 시험 클라이언트의 host는 localhost
        p = self.calls[0]
        self.assertEqual((p['data'], p['crs'], p['geometry']), ('LP_PA_CBND_BUBUN', 'EPSG:4326', 'true'))
        self.assertEqual(p['attrFilter'], f'pnu:=:{PNU_A}')
        self.assertEqual(p['domain'], appmod._VWORLD_DOMAIN_FALLBACK)           # localhost는 INCORRECT_KEY라 배포 주소로 바꿔 부른다

    def test_found_features_are_cached_but_errors_are_not(self):
        self.http.get(f'/api/parcel_geometry?pnu={PNU_A},{PNU_B}')
        self.http.get(f'/api/parcel_geometry?pnu={PNU_A},{PNU_B}')
        asked = [c['attrFilter'] for c in self.calls]
        self.assertEqual(asked.count(f'pnu:=:{PNU_A}'), 1)                      # 찾은 것은 한 번만
        self.assertEqual(asked.count(f'pnu:=:{PNU_B}'), 2)                      # 오류는 다시 물어본다(일시 오류 복구)

    def test_duplicates_collapsed_and_bad_input_rejected(self):
        d = self.http.get(f'/api/parcel_geometry?pnu={PNU_A},{PNU_A}').get_json()
        self.assertEqual(len(d['features']), 1)
        self.assertEqual(self.http.get('/api/parcel_geometry').status_code, 400)
        r = self.http.get('/api/parcel_geometry?pnu=123,abc')
        self.assertEqual(r.status_code, 400)
        self.assertIn('19자리', r.get_json()['message'])
        too_many = ','.join(str(4884025022100000000 + i) for i in range(appmod.PARCEL_GEOM_MAX_PNUS + 1))
        self.assertEqual(self.http.get(f'/api/parcel_geometry?pnu={too_many}').status_code, 400)

    def test_network_failure_is_reported_per_parcel_not_as_a_crash(self):
        def boom(*a, **k):
            raise ConnectionError('network down')
        appmod.requests.get = boom
        d = self.http.get(f'/api/parcel_geometry?pnu={PNU_A}').get_json()
        self.assertTrue(d['success'])
        self.assertEqual(d['features'], [])
        self.assertIn('network down', d['errors'][0]['message'])

    def test_domain_helper_keeps_real_hosts(self):
        with appmod.app.test_request_context('/', base_url='https://example.cloudtype.app'):
            self.assertEqual(appmod._vworld_data_domain(), 'example.cloudtype.app')
        with appmod.app.test_request_context('/', base_url='http://127.0.0.1:5000'):
            self.assertEqual(appmod._vworld_data_domain(), appmod._VWORLD_DOMAIN_FALLBACK)


class PageTests(unittest.TestCase):
    def test_page_has_map_panel_and_scripts_in_order(self):
        html = appmod.app.test_client().get('/law_review').get_data(as_text=True)
        for needle in ('id="parcel-map-panel"', 'id="parcel-map"', 'id="pm-base-map"', 'id="pm-base-sat"', 'id="pm-cadastral"', 'id="pm-fit"', 'id="pm-legend"', 'id="pm-note"',
                       'leaflet.min.js', 'leaflet.min.css', '/static/parcel_map.js'):
            self.assertIn(needle, html, needle)
        self.assertLess(html.index('leaflet.min.js'), html.index('/static/parcel_map.js'))      # 지도 라이브러리가 먼저
        self.assertLess(html.index('/static/script.js'), html.index('/static/parcel_map.js'))
        self.assertNotIn('id="pm-', html.split('<form id="project-form">')[0])                 # 폼 밖(헤더)에는 없다

    def test_map_script_wiring(self):
        js = appmod.app.test_client().get('/static/parcel_map.js').get_data(as_text=True)
        for needle in ('/api/parcel_geometry', 'MutationObserver', 'focusin', 'lp_pa_cbnd_bubun', 'pm-selected', 'ParcelMap', "zoningError !== '1'"):
            self.assertIn(needle, js, needle)
        # 지목 묶음에 흔한 지목이 모두 들어 있다
        for j in ('전', '답', '과수원', '임야', '대', '도로', '하천', '구거', '잡종지'):
            self.assertIn("'" + j + "'", js, j)


if __name__ == '__main__':
    unittest.main(verbosity=2)
