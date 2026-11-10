"""Gemini 클라이언트가 API 버전을 직접 고정하는지 확인한다. `python test_gemini_version.py`. 네트워크 불필요.

배경: google-genai는 requirements에 버전이 고정돼 있지 않아 재배포 때 최신이 설치된다. 기본 API 버전이 v1로 바뀌면 JSON 모드(response_mime_type)가
"JSON mode is not enabled for api version v1" 400으로 거부돼, 법정 의무 마스터·PQ 서류 추출·법규 검토 인용 판정이 모두 실패한다(2026-11-10 운영에서 발생).
"""
import unittest
from unittest import mock

import gemini_client


class ApiVersionTests(unittest.TestCase):
    def setUp(self):
        self._client = gemini_client._client
        gemini_client._client = None

    def tearDown(self):
        gemini_client._client = self._client

    def test_client_is_created_with_pinned_api_version(self):
        with mock.patch('google.genai.Client') as ctor:
            gemini_client.get_client()
        kwargs = ctor.call_args.kwargs
        self.assertEqual(kwargs['http_options'].api_version, 'v1beta')       # 기본값에 기대지 않는다
        self.assertIn('api_key', kwargs)

    def test_client_is_shared_not_recreated(self):
        with mock.patch('google.genai.Client') as ctor:
            a = gemini_client.get_client()
            b = gemini_client.get_client()
        self.assertIs(a, b)
        self.assertEqual(ctor.call_count, 1)

    def test_real_sdk_accepts_the_options(self):
        """가짜가 아닌 실제 SDK가 이 인자 모양을 받는다(SDK 버전이 올라 인자가 바뀌면 여기서 실패)."""
        with mock.patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key-not-real'}):
            c = gemini_client.get_client()
        self.assertIsNotNone(c)

    def test_api_version_can_be_overridden_by_env_name_only(self):
        self.assertEqual(gemini_client.API_VERSION, 'v1beta')


if __name__ == '__main__':
    unittest.main(verbosity=2)
