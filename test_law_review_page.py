"""개발사업 스마트 법규 검토 화면(입력·보고서)과 분석 진행 단계 API 시험. `python test_law_review_page.py`. 네트워크·AI 불필요.

화면 동작 자체(붙여넣기 해석, 저장·복구, 체크리스트, CSV)는 브라우저에서 확인했고, 여기서는 화면이 기대하는 요소·스크립트·API 모양이 빠지지 않았는지 고정한다.
"""
import unittest
import uuid

import app as appmod


class PageTests(unittest.TestCase):
    def setUp(self):
        self.http = appmod.app.test_client()

    def test_input_page_has_helpers_and_scripts_in_order(self):
        html = self.http.get('/law_review').get_data(as_text=True)
        for needle in ('id="saved-panel"', 'id="draft-banner"', 'id="paste-parcel-btn"', 'id="paste-panel"', 'id="paste-text"', 'id="parcel-summary"',
                       'id="desc-hints"', 'id="form-message"', 'id="analysis-status"'):
            self.assertIn(needle, html, needle)
        self.assertNotIn('7단계', html)                               # 예전 안내 문구(지번을 7단계로)는 없다
        i_store, i_main, i_input = (html.index(x) for x in ('law_review_store.js', '/static/script.js', 'law_review_input.js'))
        self.assertLess(i_store, i_main)                              # 저장 모듈 -> 폼 스크립트 -> 입력 도우미 순서
        self.assertLess(i_main, i_input)

    def test_static_scripts_are_served(self):
        for path in ('/static/law_review_store.js', '/static/law_review_input.js', '/static/script.js'):
            r = self.http.get(path)
            self.assertEqual(r.status_code, 200, path)
            r.close()
        js = self.http.get('/static/script.js').get_data(as_text=True)
        self.assertIn('window.LRForm', js)                            # 도우미가 쓰는 공개 함수
        self.assertIn('function runAnalysis', js)
        inp = self.http.get('/static/law_review_input.js').get_data(as_text=True)
        for fn in ('function parsePasted', 'function refreshParcelSummary', 'function explain', 'window.LRInput'):
            self.assertIn(fn, inp, fn)

    def test_report_page_has_toolbar_and_export(self):
        html = self.http.get('/report').get_data(as_text=True)
        for needle in ('id="report-toolbar"', 'id="btn-csv"', 'id="btn-print-top"', 'law_review_store.js', 'function exportCsv', 'function initChecklist',
                       "get('rec')", 'setSnapshot'):
            self.assertIn(needle, html, needle)


class StageApiTests(unittest.TestCase):
    def setUp(self):
        self.http = appmod.app.test_client()
        self.jid = 'test-' + uuid.uuid4().hex

    def tearDown(self):
        if self.jid in appmod.JOBS:
            del appmod.JOBS[self.jid]

    def test_status_returns_the_current_stage(self):
        appmod._lr_stage(self.jid, '법제처에서 관련 법령 원문 조회 중')
        d = self.http.get(f'/api/analyze/status/{self.jid}').get_json()
        self.assertEqual((d['status'], d['stage']), ('processing', '법제처에서 관련 법령 원문 조회 중'))
        appmod._lr_stage(self.jid, '법령 원문과 항목별 대조 중(마무리)')
        self.assertEqual(self.http.get(f'/api/analyze/status/{self.jid}').get_json()['stage'], '법령 원문과 항목별 대조 중(마무리)')

    def test_plain_processing_job_has_empty_stage_and_completion_removes_it(self):
        appmod.JOBS[self.jid] = {"status": "processing"}
        self.assertEqual(self.http.get(f'/api/analyze/status/{self.jid}').get_json(), {'status': 'processing', 'stage': ''})
        appmod.JOBS[self.jid] = {"status": "completed", "result": {"permits": [], "phases": {}}}
        d = self.http.get(f'/api/analyze/status/{self.jid}').get_json()
        self.assertEqual(d['status'], 'completed')
        self.assertEqual(self.http.get(f'/api/analyze/status/{self.jid}').status_code, 404)

    def test_stage_write_failure_does_not_raise(self):
        class Broken:
            def __setitem__(self, k, v):
                raise RuntimeError('db locked')
        orig = appmod.JOBS
        appmod.JOBS = Broken()
        try:
            appmod._lr_stage('x', '단계')                           # 예외 없이 지나간다
        finally:
            appmod.JOBS = orig

    def test_run_analysis_reports_stages_in_order(self):
        """AI·네트워크를 가짜로 바꿔 run_analysis가 단계를 순서대로 알리는지 본다."""
        stages = []
        orig_stage, orig_gen, orig_ground = appmod._lr_stage, appmod.gemini_client.generate, appmod.generate_with_search_grounding
        import mcp_agent_sync

        class R:
            def __init__(self, text):
                self.text = text
        appmod._lr_stage = lambda jid, text: stages.append(text)
        appmod.gemini_client.generate = lambda *a, **k: R('{}')
        appmod.generate_with_search_grounding = lambda *a, **k: R('{"permits": [], "phases": {}}')
        orig_ctx = mcp_agent_sync.get_mcp_context_sync
        mcp_agent_sync.get_mcp_context_sync = lambda q: ''
        try:
            appmod.run_analysis(self.jid, {'projectName': 'x', 'projectType': '토목공사', 'budget': 1, 'totalArea': 100, 'publicWaterArea': 0,
                                           'description': 'd', 'parcels': [{'address': 'a', 'area': '100', 'zoning': '일반상업지역', 'jimok': '대'}]})
        finally:
            appmod._lr_stage, appmod.gemini_client.generate, appmod.generate_with_search_grounding = orig_stage, orig_gen, orig_ground
            mcp_agent_sync.get_mcp_context_sync = orig_ctx
        self.assertEqual(appmod.JOBS[self.jid]['status'], 'completed', appmod.JOBS[self.jid])
        order = ['입력한 사업·필지 정리 중', '사업 조건 추출 중(AI)', '법제처에서 관련 법령 원문 조회 중', '인허가·의무 항목 분석 중(AI, 가장 오래 걸리는 단계)',
                 '법령 링크 연결 중', '법령 원문과 항목별 대조 중(마무리)']
        self.assertEqual(stages, order)


if __name__ == '__main__':
    unittest.main(verbosity=2)
