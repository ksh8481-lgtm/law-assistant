"""Gemini 모델 세대 차이(2.x -> 3.x)를 흡수하는 부분 시험. `python test_gemini_models.py`. 네트워크·키 불필요.

배경: 구글이 gemini-2.5-pro/flash 를 폐기해 2026-12-01부터 gemini-3.8-flash / gemini-3.5-flash-lite 로 자동 연결하고, 규칙이 바뀐다(thinking_budget -> thinking_level 등).
실측(2026-11-22)한 모델별 동작은 gemini_client.thinking_config_for 의 설명 참고.
"""
import os
import unittest

import gemini_client as gc


def level_of(cfg):
    lv = getattr(cfg, 'thinking_level', None)
    return None if lv is None else (lv.value if hasattr(lv, 'value') else str(lv)).upper()


class ThinkingConfigTests(unittest.TestCase):
    def test_gen3_converts_budget_to_level(self):
        f = gc.thinking_config_for
        self.assertEqual(level_of(f('gemini-3.8-flash', thinking_budget=0)), 'LOW')                  # minimal 은 3.8 Flash 에서 400
        self.assertEqual(level_of(f('gemini-3.8-flash', thinking_budget=512)), 'LOW')
        self.assertEqual(level_of(f('gemini-3.8-flash', thinking_budget=4000)), 'MEDIUM')
        self.assertEqual(level_of(f('gemini-3.8-flash', thinking_budget=20000)), 'HIGH')
        self.assertEqual(level_of(f('gemini-3.5-flash-lite', thinking_budget=0)), 'MINIMAL')         # lite 는 thinking_budget=0 이 400, minimal 은 허용
        self.assertIsNone(f('gemini-3.8-flash'))                                                     # 지정 없으면 모델 기본값
        self.assertIsNone(getattr(f('gemini-3.8-flash', thinking_budget=512), 'thinking_budget', None))

    def test_explicit_level_wins_and_minimal_is_downgraded_off_lite(self):
        f = gc.thinking_config_for
        self.assertEqual(level_of(f('gemini-3.8-flash', thinking_budget=0, thinking_level='high')), 'HIGH')
        self.assertEqual(level_of(f('gemini-3.8-flash', thinking_level='minimal')), 'LOW')
        self.assertEqual(level_of(f('gemini-3.5-flash-lite', thinking_level='minimal')), 'MINIMAL')
        self.assertEqual(level_of(f('models/gemini-3.5-flash-lite', thinking_level='Medium')), 'MEDIUM')

    def test_gen2_keeps_the_old_budget_rules(self):
        f = gc.thinking_config_for
        self.assertEqual(f('gemini-2.5-flash', thinking_budget=0).thinking_budget, 0)
        self.assertEqual(f('gemini-2.5-flash', thinking_budget=512).thinking_budget, 512)
        self.assertIsNone(f('gemini-2.5-pro', thinking_budget=0))                                    # pro 는 사고를 끌 수 없어 0 은 무시
        self.assertEqual(f('gemini-2.5-pro', thinking_budget=512).thinking_budget, 512)
        self.assertIsNone(f('gemini-2.5-flash', thinking_level='high'))                              # 2.x 는 thinking_level 을 모른다

    def test_model_generation(self):
        self.assertEqual([gc.model_generation(m) for m in ('gemini-3.8-flash', 'models/gemini-2.5-pro', 'gemini-4-hydrogen', 'other', '')], [3, 2, 4, 0, 0])


class FakeAPIError(Exception):
    def __init__(self, code, status, msg):
        super().__init__(f"{code} {status}. {msg}")
        self.code, self.status = code, status


class GenerateRetryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._get = gc.get_client
        self.reject_thinking = False
        outer = self

        class Models:
            def generate_content(self, model, contents, config=None):
                cfg = {k: v for k, v in (config.model_dump(exclude_none=True).items() if config is not None else [])}
                outer.calls.append((model, cfg))
                if outer.reject_thinking and ('thinking_config' in cfg or 'temperature' in cfg):
                    raise FakeAPIError(400, 'INVALID_ARGUMENT', 'Request contains an invalid argument.')
                return type('R', (), {'text': 'ok', 'usage_metadata': None})()

        class Client:
            models = Models()
        gc.get_client = lambda: Client()

    def tearDown(self):
        gc.get_client = self._get

    def test_gen3_call_sends_thinking_level_not_budget(self):
        gc.generate('x', model='gemini-3.8-flash', thinking_budget=512, label='t')
        cfg = self.calls[0][1]
        self.assertEqual(str(cfg['thinking_config'].get('thinking_level')).upper().split('.')[-1], 'LOW')
        self.assertNotIn('thinking_budget', cfg['thinking_config'])

    def test_400_on_new_model_retries_without_thinking_and_temperature(self):
        self.reject_thinking = True
        r = gc.generate('x', model='gemini-3.5-flash-lite', temperature=0.2, thinking_budget=0, label='t')
        self.assertEqual(r.text, 'ok')
        self.assertEqual(len(self.calls), 2)
        self.assertIn('temperature', self.calls[0][1])
        self.assertNotIn('thinking_config', self.calls[1][1])
        self.assertNotIn('temperature', self.calls[1][1])

    def test_400_without_those_settings_is_not_retried(self):
        self.reject_thinking = False

        class Boom:
            class models:
                @staticmethod
                def generate_content(**k):
                    raise FakeAPIError(400, 'INVALID_ARGUMENT', 'bad json')
        gc.get_client = lambda: Boom()
        with self.assertRaises(gc.GeminiError):
            gc.generate('x', model='gemini-3.8-flash', label='t')


class DefaultsAndFallbackTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ('GEMINI_MAIN_MODEL', 'GEMINI_FAST_MODEL', 'GEMINI_LIGHT_MODEL', 'GEMINI_MAIN_FALLBACKS')}
        self._gen = gc.generate

    def tearDown(self):
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v
        gc.generate = self._gen

    def test_new_defaults(self):
        self.assertEqual((gc.main_model(), gc.fast_model(), gc.light_model()), ('gemini-3.8-flash', 'gemini-3.8-flash', 'gemini-3.5-flash-lite'))

    def test_same_model_is_not_called_twice_and_a_reserve_is_added(self):
        tried = []

        def fake(contents, model=None, **k):
            tried.append(model)
            raise gc.as_gemini_error(FakeAPIError(503, 'UNAVAILABLE', 'busy'))
        gc.generate = fake
        with self.assertRaises(gc.GeminiError):
            gc.generate_with_fallback('x', models=[gc.fast_model(), gc.main_model()])               # 둘 다 gemini-3.8-flash
        self.assertEqual(tried, ['gemini-3.8-flash', 'gemini-3.6-flash'])

    def test_reserve_is_not_duplicated_when_it_is_the_only_model(self):
        tried = []

        def fake(contents, model=None, **k):
            tried.append(model)
            raise gc.as_gemini_error(FakeAPIError(503, 'UNAVAILABLE', 'busy'))
        gc.generate = fake
        with self.assertRaises(gc.GeminiError):
            gc.generate_with_fallback('x', models=['gemini-3.6-flash'])
        self.assertEqual(tried, ['gemini-3.6-flash'])


class ExtractionUsesLightModelTests(unittest.TestCase):
    def test_keyword_extraction_calls_use_light_model_with_medium_thinking(self):
        import mcp_agent_sync as m
        seen = []
        orig = gc.generate

        def fake(prompt, model=None, **k):
            seen.append((k.get('label'), model, k.get('thinking_level')))
            return type('R', (), {'text': '키워드|||법령|조문'})()
        gc.generate = fake
        try:
            m._extract_keyword_and_jurisdiction('질문')
            m._extract_subject_laws('질문')
            m._extract_admrul_names('질문')
        finally:
            gc.generate = orig
        labels = {l: (mo, th) for l, mo, th in seen}
        for label in ('키워드·법령명 추출', '소관법률 추출', '고시명 추출'):
            self.assertEqual(labels[label], (gc.light_model(), 'medium'), label)


if __name__ == '__main__':
    unittest.main(verbosity=2)
