"""Gemini 호출 실패를 사용자가 알아볼 수 있는 말로 바꾸는 부분(gemini_client.classify_error 등) 시험. `python test_gemini_errors.py`. 네트워크·키 불필요.

배경(2026-11-16 실사용): 선불 크레딧이 바닥나 `402 RESOURCE_EXHAUSTED ... Your prepayment credits are depleted`가 났는데 화면에는 "모든 AI 모델이
요청 한도 초과 또는 오류로 실패했습니다"라고만 나와 원인을 알 수 없었고, 모델을 바꿔 가며 다시 시도하느라 시간도 낭비됐다.
"""
import unittest

import gemini_client as gc

# 실사용에서 화면에 나온 오류 문장 그대로
CREDITS_MSG = ("402 RESOURCE_EXHAUSTED. {'error': {'code': 402, 'message': 'Your prepayment credits are depleted. Please go to AI Studio at "
               "https://ai.studio/projects to manage your project and billing. Learn more at https://ai.google.dev/gemini-api/docs/billing#prepay. ', "
               "'status': 'RESOURCE_EXHAUSTED'}}")


class FakeAPIError(Exception):
    def __init__(self, code, status, msg):
        super().__init__(f"{code} {status}. {msg}")
        self.code, self.status = code, status


class ClassifyTests(unittest.TestCase):
    def test_prepayment_credits_depleted_is_its_own_kind_with_instructions(self):
        kind, msg = gc.classify_error(FakeAPIError(402, 'RESOURCE_EXHAUSTED', CREDITS_MSG))
        self.assertEqual(kind, 'credits')
        self.assertIn('크레딧', msg)
        self.assertIn('충전', msg)
        self.assertIn('ai.studio', msg)
        self.assertIn('402', msg)                                  # 오류 코드도 남긴다
        for wrong in ('한도', '429', 'quota'):
            self.assertNotIn(wrong, msg)                           # 화면의 "호출 한도" 분기(explain)가 오인하지 않게

    def test_plain_text_credits_message_without_a_code_attribute(self):
        self.assertEqual(gc.classify_error(RuntimeError(CREDITS_MSG))[0], 'credits')

    def test_rate_limit_is_distinguished_from_credits(self):
        kind, msg = gc.classify_error(FakeAPIError(429, 'RESOURCE_EXHAUSTED', 'Quota exceeded for metric generate_content_requests_per_minute'))
        self.assertEqual(kind, 'rate')
        self.assertIn('다시 시도', msg)
        self.assertEqual(gc.classify_error(RuntimeError('RESOURCE_EXHAUSTED: quota'))[0], 'rate')

    def test_key_and_permission_errors(self):
        self.assertEqual(gc.classify_error(FakeAPIError(403, 'PERMISSION_DENIED', 'The caller does not have permission'))[0], 'key')
        self.assertEqual(gc.classify_error(FakeAPIError(400, 'INVALID_ARGUMENT', 'API key not valid. Please pass a valid API key.'))[0], 'key')

    def test_server_trouble_and_bad_request_and_other(self):
        self.assertEqual(gc.classify_error(FakeAPIError(503, 'UNAVAILABLE', 'The model is overloaded'))[0], 'overloaded')
        self.assertEqual(gc.classify_error(TimeoutError('Deadline exceeded'))[0], 'overloaded')
        self.assertEqual(gc.classify_error(FakeAPIError(400, 'INVALID_ARGUMENT', 'JSON mode is not enabled for api version v1'))[0], 'bad_request')
        kind, msg = gc.classify_error(ValueError('something unexpected https://internal.example/x?key=SECRET123'))
        self.assertEqual(kind, 'other')
        self.assertIn('ValueError', msg)
        self.assertNotIn('SECRET123', msg)                                   # 원문(주소·키가 섞일 수 있음)은 화면에 보이지 않는다
        self.assertNotIn('internal.example', msg)
        self.assertIn('SECRET123', gc.as_gemini_error(ValueError('x key=SECRET123')).cause)   # 서버 로그용 cause 에는 남는다

    def test_missing_or_retired_model_gets_its_own_message(self):
        kind, msg = gc.classify_error(FakeAPIError(404, 'NOT_FOUND', 'models/gemini-2.5-pro is not found for API version v1beta'))
        self.assertEqual(kind, 'model')
        self.assertIn('GEMINI_MAIN_MODEL', msg)
        self.assertNotIn('gemini-2.5-pro', msg)
        self.assertNotIn(kind, gc.FAIL_FAST_KINDS)                              # 다른 모델은 될 수 있으니 폴백을 계속한다

    def test_http_402_is_credits_even_with_different_wording(self):
        for text in ('billing account has no available funds', 'RESOURCE_EXHAUSTED: please top up'):
            kind, _msg = gc.classify_error(FakeAPIError(402, 'RESOURCE_EXHAUSTED', text))
            self.assertEqual(kind, 'credits', text)                          # 문구가 바뀌어도 402 면 크레딧 소진(다른 모델을 계속 부르지 않는다)
        self.assertEqual(gc.classify_error(FakeAPIError(429, 'RESOURCE_EXHAUSTED', 'billing depleted rate'))[0], 'rate')

    def test_as_gemini_error_is_idempotent_and_keeps_cause(self):
        raw = FakeAPIError(402, 'RESOURCE_EXHAUSTED', CREDITS_MSG)
        ge = gc.as_gemini_error(raw)
        self.assertIsInstance(ge, gc.GeminiError)
        self.assertIs(gc.as_gemini_error(ge), ge)
        self.assertEqual(str(ge), ge.user_message)
        self.assertIn('prepayment', ge.cause)


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self._gen = gc.generate
        self.tried = []

    def tearDown(self):
        gc.generate = self._gen

    def install(self, errors_by_model):
        def fake(contents, model=None, **k):
            self.tried.append(model)
            err = errors_by_model.get(model)
            if err:
                raise gc.as_gemini_error(err)
            return 'RESP'
        gc.generate = fake

    def test_credits_error_stops_at_the_first_model(self):
        self.install({'pro': FakeAPIError(402, 'RESOURCE_EXHAUSTED', CREDITS_MSG), 'flash': FakeAPIError(402, 'RESOURCE_EXHAUSTED', CREDITS_MSG)})
        with self.assertRaises(gc.GeminiError) as cm:
            gc.generate_with_fallback('x', models=['pro', 'flash'], label='t')
        self.assertEqual(self.tried, ['pro'])                               # 같은 키라 flash도 똑같이 실패한다
        self.assertEqual(cm.exception.kind, 'credits')

    def test_key_error_also_stops(self):
        self.install({'pro': FakeAPIError(403, 'PERMISSION_DENIED', 'denied')})
        with self.assertRaises(gc.GeminiError):
            gc.generate_with_fallback('x', models=['pro', 'flash'])
        self.assertEqual(self.tried, ['pro'])

    def test_rate_and_overload_still_fall_back_to_the_next_model(self):
        self.install({'pro': FakeAPIError(503, 'UNAVAILABLE', 'overloaded')})
        resp, used = gc.generate_with_fallback('x', models=['pro', 'flash'])
        self.assertEqual((resp, used), ('RESP', 'flash'))
        self.assertEqual(self.tried, ['pro', 'flash'])

    def test_all_models_failing_raises_the_last_friendly_error(self):
        self.install({'pro': FakeAPIError(429, 'RESOURCE_EXHAUSTED', 'quota'), 'flash': FakeAPIError(503, 'UNAVAILABLE', 'busy')})
        with self.assertRaises(gc.GeminiError) as cm:
            gc.generate_with_fallback('x', models=['pro', 'flash'])
        self.assertEqual(cm.exception.kind, 'overloaded')
        self.assertEqual(self.tried, ['pro', 'flash'])


class GenerateWrapsRawErrorsTests(unittest.TestCase):
    def test_raw_sdk_error_becomes_gemini_error(self):
        class FakeModels:
            def generate_content(self, **k):
                raise FakeAPIError(402, 'RESOURCE_EXHAUSTED', CREDITS_MSG)

        class FakeClient:
            models = FakeModels()
        orig = gc.get_client
        gc.get_client = lambda: FakeClient()
        try:
            with self.assertRaises(gc.GeminiError) as cm:
                gc.generate('hello', model='gemini-2.5-flash', label='t')
        finally:
            gc.get_client = orig
        self.assertEqual(cm.exception.kind, 'credits')


class AuxiliaryStepsTests(unittest.TestCase):
    """키워드·법령명 추출 같은 보조 단계가 크레딧 소진을 삼키지 않고 바로 올려야 한다."""

    def test_fatal_errors_propagate_but_others_are_swallowed(self):
        import mcp_agent_sync as m
        orig = gc.generate
        try:
            gc.generate = lambda *a, **k: (_ for _ in ()).throw(gc.as_gemini_error(FakeAPIError(402, 'RESOURCE_EXHAUSTED', CREDITS_MSG)))
            with self.assertRaises(gc.GeminiError) as cm:
                m._extract_keyword_and_jurisdiction('아무 질문')
            self.assertEqual(cm.exception.kind, 'credits')
            with self.assertRaises(gc.GeminiError):
                m._extract_subject_laws('아무 질문')
            gc.generate = lambda *a, **k: (_ for _ in ()).throw(gc.as_gemini_error(FakeAPIError(503, 'UNAVAILABLE', 'busy')))
            self.assertEqual(m._extract_keyword_and_jurisdiction('아무 질문'), ('', '', '', [], []))   # 일시 장애는 기존처럼 건너뛴다
            self.assertEqual(m._extract_subject_laws('아무 질문'), [])
        finally:
            gc.generate = orig


class EndToEndTests(unittest.TestCase):
    """크레딧이 소진된 날: 기타 행정 검토를 시작하면 첫 AI 호출에서 바로 원인이 적힌 오류로 끝난다(여러 단계를 기다리지 않는다)."""

    def test_other_review_fails_fast_with_the_friendly_message(self):
        import time
        import app as appmod
        orig_key, orig_gen = appmod.GEMINI_KEY, gc.generate
        calls = []

        def boom(*a, **k):
            calls.append(k.get('label'))
            raise gc.as_gemini_error(FakeAPIError(402, 'RESOURCE_EXHAUSTED', CREDITS_MSG))
        appmod.GEMINI_KEY = 'test'
        gc.generate = boom
        try:
            http = appmod.app.test_client()
            r = http.post('/api/analyze/other_review', json={'text': '관광단지 면적 변경 시 재해영향평가를 받아야 하나요?'})
            jid = r.get_json()['job_id']
            d = {}
            for _ in range(100):
                d = http.get(f'/api/analyze/other_review_status/{jid}').get_json()
                if d.get('status') != 'processing':
                    break
                time.sleep(0.1)
        finally:
            appmod.GEMINI_KEY, gc.generate = orig_key, orig_gen
        self.assertEqual(d.get('status'), 'error', d)
        self.assertIn('크레딧', d['message'])
        self.assertIn('충전', d['message'])
        self.assertNotIn('요청 한도 초과 또는 오류', d['message'])                    # 예전의 모호한 문장이 아니다
        self.assertLessEqual(len(calls), 3)                                          # 보조 단계 AI 호출이 이어지지 않는다


if __name__ == '__main__':
    unittest.main(verbosity=2)
