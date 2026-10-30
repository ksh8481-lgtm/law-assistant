"""
Gemini 호출을 `gemini_client`(신버전 google-genai)로 옮긴 엔드포인트들의 계약 테스트. `python test_gemini_endpoints.py`로 실행한다.

[방식]
공용 클라이언트를 가짜로 바꿔 끼우고, 각 엔드포인트가 새 SDK에 실제로 넘기는 값(모델, contents 형식, 설정)을 기록해 검사한다.
Gemini에는 한 번도 접속하지 않는다(키·비용·네트워크 불필요). 검사하는 것:
  - 구 SDK 형식(채팅의 {"role","parts":[문자열]}, 파일 객체)이 신 SDK 형식으로 바뀌어 전달되는가
  - 어느 모델을 먼저 쓰고, 실패하면 다음 모델로 넘어가는가
  - 온도·JSON 모드 같은 설정이 예전과 같은가
  - 응답이 예전과 같은 모양으로 돌아가는가

[왜 필요한가]
SDK를 바꾸면서 가장 흔한 사고는 "맨 문자열을 parts에 넣으면 신 SDK가 거부한다"처럼 형식이 어긋나 한 기능만 조용히 죽는 것이다.
이미지·채팅·JSON처럼 손으로 확인하기 어려운 경로를 여기서 한꺼번에 잡는다.
"""
import json
import types
import unittest

import app as appmod
import gemini_client as gc


class _Resp:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


class _Models:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.fail_models = set()

    def generate_content(self, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if model in self.fail_models:
            raise RuntimeError(f"429 quota ({model})")
        text = self.reply(self.calls[-1]) if callable(self.reply) else self.reply
        return _Resp(text)


class _Files:
    def get(self, name):
        return types.SimpleNamespace(name=name, uri="https://files.test/" + name, mime_type="application/pdf")


class FakeClient:
    def __init__(self, reply="OK"):
        self.models = _Models(reply)
        self.files = _Files()


def _cfg(call, key):
    """config가 GenerateContentConfig 객체여도 dict여도 값을 꺼낸다."""
    cfg = call["config"]
    if cfg is None:
        return None
    return cfg.get(key) if isinstance(cfg, dict) else getattr(cfg, key, None)


class EndpointContractTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeClient()
        self._saved = (gc._client, appmod.GEMINI_KEY)
        gc._client = self.fake
        appmod.GEMINI_KEY = "test-key"
        self.http = appmod.app.test_client()

    def tearDown(self):
        gc._client, appmod.GEMINI_KEY = self._saved

    # --- 후속 질의(채팅) -------------------------------------------------------
    def test_chat_other_review_converts_old_style_history(self):
        self.fake.models.reply = "답변입니다"
        r = self.http.post("/api/chat/other_review", json={
            "chat_history": [{"role": "model", "text": "이전 답변"}, {"role": "user", "text": "이전 질문"}],
            "new_message": "새 질문", "initial_context": "원래 질문", "file_name": "files/abc"})
        body = r.get_json()
        self.assertTrue(body["success"], body)
        self.assertEqual(body["result"], "답변입니다")
        call = self.fake.models.calls[0]
        self.assertEqual(call["model"], "gemini-2.5-pro")                       # 본 모델 우선
        self.assertEqual(call["contents"][0], {"role": "user", "parts": [
            {"text": "원래 질문"},
            {"file_data": {"file_uri": "https://files.test/files/abc", "mime_type": "application/pdf"}}]})
        self.assertEqual(call["contents"][1], {"role": "model", "parts": [{"text": "이전 답변"}]})
        self.assertEqual(call["contents"][-1], {"role": "user", "parts": [{"text": "새 질문"}]})
        self.assertEqual(_cfg(call, "temperature"), 0.2)                        # LEGAL_GEN_CONFIG 그대로

    def test_chat_other_review_falls_back_to_flash(self):
        self.fake.models.fail_models = {"gemini-2.5-pro"}
        self.fake.models.reply = "flash 답변"
        r = self.http.post("/api/chat/other_review", json={"new_message": "Q", "initial_context": "C"})
        self.assertEqual(r.get_json()["result"], "flash 답변")
        self.assertEqual([c["model"] for c in self.fake.models.calls], ["gemini-2.5-pro", "gemini-2.5-flash"])

    def test_chat_other_review_reports_failure_when_all_models_fail(self):
        self.fake.models.fail_models = {"gemini-2.5-pro", "gemini-2.5-flash"}
        r = self.http.post("/api/chat/other_review", json={"new_message": "Q", "initial_context": "C"})
        body = r.get_json()
        self.assertFalse(body["success"])
        self.assertIn("채팅 응답 생성 실패", body["message"])

    def test_chat_duty_list_uses_flash_first_with_history(self):
        self.fake.models.reply = "의무 답변"
        r = self.http.post("/api/chat/duty_list", json={
            "law_name": "건설기술 진흥법", "new_message": "점검 주기는?",
            "chat_history": [{"role": "user", "text": "안녕"}, {"role": "model", "text": "네"}]})
        self.assertEqual(r.get_json()["result"], "의무 답변")
        call = self.fake.models.calls[0]
        self.assertEqual(call["model"], "gemini-2.5-flash")                     # 예전 순서: flash 우선
        self.assertEqual(call["contents"][-1], {"role": "user", "parts": [{"text": "점검 주기는?"}]})
        self.assertEqual(call["contents"][1], {"role": "user", "parts": [{"text": "안녕"}]})
        self.assertIsNone(_cfg(call, "temperature"))                            # 예전에도 설정 없음

    def test_chat_report_uses_flash_and_returns_raw_text(self):
        self.fake.models.reply = "보고서 설명"
        r = self.http.post("/api/chat/report", json={
            "report_data": {"a": 1}, "new_message": "요약해줘", "chat_history": []})
        self.assertEqual(r.get_json(), {"success": True, "result": "보고서 설명"})
        call = self.fake.models.calls[0]
        self.assertEqual(call["model"], "gemini-2.5-flash")
        self.assertIn('"a": 1', call["contents"][0]["parts"][0]["text"])

    # --- 단발 호출 ------------------------------------------------------------
    def test_supervisor_checklist_filters_by_ai_exclusions(self):
        db = appmod.app.test_client().get("/api/supervisor/checklist").get_json()
        first = db["data"]["project_stages"][0]["checklists"][0]["task_id"] if "data" in db else None
        self.fake.models.reply = json.dumps([first] if first else [])
        r = self.http.post("/api/supervisor/checklist", json={"description": "도로 포장", "budget": 10, "projectName": "T"})
        self.assertEqual(r.status_code, 200)
        call = self.fake.models.calls[0]
        self.assertEqual(call["model"], "gemini-2.5-flash")
        self.assertIsInstance(call["contents"], str)                           # 맨 문자열 프롬프트는 그대로 전달

    def test_extract_parcel_sends_prompt_and_file_part(self):
        self.fake.models.reply = '```json\n[{"address": "서울시 강남구 역삼동 123-4", "area": "500"}]\n```'
        real = appmod.upload_file_for_gemini
        appmod.upload_file_for_gemini = lambda path, **kw: types.SimpleNamespace(
            name="files/p1", uri="https://files.test/files/p1", mime_type="application/pdf")
        try:
            import io
            r = self.http.post("/api/extract_parcel_from_drawing",
                               data={"file": (io.BytesIO(b"%PDF-1.4 test"), "도면.pdf")},
                               content_type="multipart/form-data")
        finally:
            appmod.upload_file_for_gemini = real
        body = r.get_json()
        self.assertTrue(body.get("success"), body)
        call = self.fake.models.calls[0]
        self.assertEqual(call["model"], "gemini-2.5-flash")
        self.assertIsInstance(call["contents"][0], str)
        self.assertEqual(call["contents"][1], {"file_data": {"file_uri": "https://files.test/files/p1",
                                                              "mime_type": "application/pdf"}})

    # --- 백그라운드 작업 ------------------------------------------------------
    def test_pq_extract_requests_json_at_zero_temperature_pro_first(self):
        self.fake.models.reply = "{}"
        appmod.run_pq_extract("pq-test", "gyeongnam_cm", {}, "입찰사", [])
        call = self.fake.models.calls[0]
        self.assertEqual(call["model"], "gemini-2.5-pro")
        self.assertEqual(_cfg(call, "response_mime_type"), "application/json")
        self.assertEqual(_cfg(call, "temperature"), 0)
        self.assertIn(appmod.JOBS["pq-test"]["status"], ("completed", "error"))
        self.assertNotIn("genai", appmod.JOBS["pq-test"].get("message", "").lower())

    def test_design_review_runs_through_wrapper_and_keeps_its_verify_pass(self):
        self.fake.models.reply = "## 검토 결과\n문제 없음"
        appmod.run_design_review("dr-test", "시험 공사", "civil", ["kcsc"], "", {})
        job = appmod.JOBS["dr-test"]
        self.assertEqual(job["status"], "completed", job)
        models = [c["model"] for c in self.fake.models.calls]
        self.assertEqual(models[0], "gemini-2.5-pro")                           # 본 검토
        self.assertEqual(_cfg(self.fake.models.calls[0], "temperature"), 0.2)
        # 설계도서 검토는 구글검색 검증 패스를 그대로 유지한다(질의응답 경로만 기본 off)
        self.assertGreaterEqual(len(models), 2)
        self.assertTrue(_cfg(self.fake.models.calls[1], "tools"))

    def test_design_review_reports_error_text_when_every_model_fails(self):
        self.fake.models.fail_models = {"gemini-2.5-pro", "gemini-2.5-flash"}
        appmod.run_design_review("dr-fail", "시험 공사", "civil", ["kcsc"], "", {})
        job = appmod.JOBS["dr-fail"]
        self.assertEqual(job["status"], "completed")
        self.assertIn("오류가 발생했습니다", job["result"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
