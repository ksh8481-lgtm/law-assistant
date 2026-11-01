"""
'법정 의무 마스터'(duty_list)의 법령 본문 처리(`duty_text.py`)와 의무 추출·채팅 엔드포인트 시험. `python test_duty_text.py`로 실행한다.

[검사하는 것]
- 본문이 조문 -> 항 -> 호 -> 목 문서 순서로 이어지는가(예전: 항 전부 뒤에 호 전부, 목은 누락)
- 항·호가 비어 있어도 오류 없이 처리되는가(예전: 조각 하나가 통째로 실패)
- 조각이 조문 경계에서만 잘리고, 긴 조문은 나뉘어도 조 번호가 따라붙는가
- 모델이 적은 조 번호를 서버가 대조해 틀린 번호에 표시를 다는가
- JSON이 깨져 오면 한 번 더 시도하고, 끝내 실패하면 "의무 없음"이 아니라 실패로 알리는가
- 큰 법령의 채팅이 앞 3만 자만 보지 않고 질문과 관련된 조문을 고르는가
법제처에 접속하는 시험은 SKIP_ONLINE_TESTS=1이면 건너뛴다.
"""
import os
import unittest

import app as appmod
import duty_text
import gemini_client as gc
from test_gemini_endpoints import FakeClient, _cfg

XML = """<?xml version="1.0" encoding="UTF-8"?>
<법령>
<기본정보><법령명_한글>시험 법</법령명_한글><시행일자>20260101</시행일자></기본정보>
<조문>
<조문단위><조문번호>1</조문번호><조문여부>전문</조문여부><조문내용>제1장 총칙</조문내용></조문단위>
<조문단위><조문번호>1</조문번호><조문여부>조문</조문여부><조문제목>목적</조문제목><조문내용>제1조(목적) 이 법은 시험을 위한 것이다.</조문내용></조문단위>
<조문단위><조문번호>2</조문번호><조문여부>조문</조문여부><조문제목>정의</조문제목>
  <조문내용>제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.</조문내용>
  <항><항번호>①</항번호><항내용>① 첫째 항 내용</항내용>
    <호><호번호>1.</호번호><호내용>1. 첫째 호</호내용>
      <목><목번호>가.</목번호><목내용>가. 첫째 목
</목내용></목>
    </호>
    <호><호번호>2.</호번호><호내용></호내용></호>
  </항>
  <항><항번호>②</항번호><항내용/></항>
  <항><항번호>③</항번호><항내용>③ 셋째 항 내용</항내용></항>
</조문단위>
<조문단위><조문번호>10</조문번호><조문가지번호>2</조문가지번호><조문여부>조문</조문여부><조문제목>가지</조문제목><조문내용>제10조의2(가지) 가지 조문이다.</조문내용></조문단위>
</조문>
</법령>"""


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.law = duty_text.parse_law(XML)

    def test_chapter_headings_are_not_articles_and_labels_include_branch(self):
        self.assertEqual([a["label"] for a in self.law["articles"]], ["제1조", "제2조", "제10조의2"])

    def test_meta(self):
        self.assertEqual(self.law["name"], "시험 법")
        self.assertEqual(self.law["enforce_date"], "20260101")

    def test_text_keeps_document_order_and_includes_mok(self):
        lines = self.law["articles"][1]["text"].split("\n")
        self.assertEqual(lines, ["제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.", "① 첫째 항 내용", "1. 첫째 호",
                                 "가. 첫째 목", "③ 셋째 항 내용"])        # 호가 ③항 뒤로 밀리지 않고, 목이 빠지지 않는다

    def test_empty_paragraphs_do_not_crash(self):
        # 빈 <항내용/>, <호내용></호내용>가 있어도 위에서 이미 통과했다. 항 텍스트가 None인 경우를 명시적으로 확인
        self.assertTrue(all("None" not in a["text"] for a in self.law["articles"]))


class ChunkTests(unittest.TestCase):
    def _arts(self, sizes):
        return [{"label": f"제{i + 1}조", "title": "", "text": f"제{i + 1}조 " + "가" * n} for i, n in enumerate(sizes)]

    def test_chunks_cut_only_at_article_boundaries(self):
        chunks = duty_text.chunk_articles(self._arts([700, 700, 700, 700]), size=1500)
        self.assertEqual([c["labels"] for c in chunks], [["제1조", "제2조"], ["제3조", "제4조"]])
        for c in chunks:                      # 각 조문이 통째로 한 조각 안에 있다
            for lab in c["labels"]:
                self.assertIn(lab + " ", c["text"])

    def test_long_article_is_split_by_lines_with_label_header(self):
        long_text = "제1조(긴 조문)\n" + "\n".join(f"{i}. " + "나" * 100 for i in range(1, 31))
        chunks = duty_text.chunk_articles([{"label": "제1조", "title": "", "text": long_text}], size=800)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c["labels"] == ["제1조"] for c in chunks))
        self.assertIn("〔제1조 계속〕", chunks[1]["text"])
        rejoined = "".join(c["text"] for c in chunks)
        for i in range(1, 31):                # 줄이 하나도 사라지지 않는다
            self.assertIn(f"{i}. ", rejoined)

    def test_empty_input(self):
        self.assertEqual(duty_text.chunk_articles([]), [])


class VerifyTests(unittest.TestCase):
    def test_article_in_chunk_is_verified_and_wrong_one_is_flagged(self):
        out = duty_text.verify_duties([
            {"article": "제5조제3항", "duty_title": "가"},
            {"article": "제99조", "duty_title": "나"},
            {"article": "제10조의2", "duty_title": "다"}], ["제5조", "제6조", "제10조의2"])
        self.assertEqual([d["article_verified"] for d in out], [True, False, True])

    def test_branch_article_is_not_confused_with_base(self):
        out = duty_text.verify_duties([{"article": "제10조", "duty_title": "가"}], ["제10조의2"])
        self.assertFalse(out[0]["article_verified"])

    def test_placeholder_is_filled_only_when_chunk_has_one_article(self):
        one = duty_text.verify_duties([{"article": "제O조", "duty_title": "가"}], ["제7조"])
        self.assertEqual((one[0]["article"], one[0]["article_verified"]), ("제7조", True))
        many = duty_text.verify_duties([{"article": "조 번호 확인 필요", "duty_title": "가"}], ["제7조", "제8조"])
        self.assertFalse(many[0]["article_verified"])

    def test_duplicates_and_bad_items_are_dropped(self):
        out = duty_text.verify_duties([
            {"article": "제5조", "duty_title": "점검 실시"}, {"article": "제5조", "duty_title": "점검  실시"},
            "문자열", None, {"article": "제5조", "duty_title": "다른 의무"}], ["제5조"])
        self.assertEqual(len(out), 2)
        self.assertEqual(duty_text.verify_duties({"a": 1}, ["제5조"]), [])


class SelectTests(unittest.TestCase):
    def test_small_law_is_returned_whole(self):
        arts = [{"label": "제1조", "title": "a", "text": "짧은 조문"}]
        self.assertEqual(duty_text.select_for_question(arts, "질문", 30000), ("짧은 조문", False))

    def test_large_law_picks_articles_related_to_question_in_law_order(self):
        arts = [{"label": f"제{i}조", "title": "일반", "text": f"제{i}조 " + "일반 내용 " * 200} for i in range(1, 40)]
        arts[30] = {"label": "제31조", "title": "안전점검", "text": "제31조(안전점검) 안전점검을 연 1회 실시한다. " + "내용 " * 100}
        text, excerpted = duty_text.select_for_question(arts, "안전점검은 얼마나 자주 하나?", 3000)
        self.assertTrue(excerpted)
        self.assertIn("제31조(안전점검)", text)           # 앞 3000자만 자르면 절대 들어오지 않는 조문
        self.assertLessEqual(len(text), 3000)


class EndpointTests(unittest.TestCase):
    LAW = {"name": "시험 법", "enforce_date": "20260101",
           "articles": [{"label": "제1조", "title": "목적", "text": "제1조(목적) 사업주는 매년 안전점검을 하여야 한다."},
                        {"label": "제2조", "title": "정의", "text": "제2조(정의) 용어의 뜻은 다음과 같다."}]}

    def setUp(self):
        self.fake = FakeClient()
        self._saved = (gc._client, appmod.GEMINI_KEY)
        gc._client = self.fake
        appmod.GEMINI_KEY = "test-key"
        self.http = appmod.app.test_client()
        law = dict(self.LAW)
        law["chunks"] = duty_text.chunk_articles(law["articles"])
        duty_text._CACHE["TEST-1"] = law

    def tearDown(self):
        gc._client, appmod.GEMINI_KEY = self._saved
        duty_text._CACHE.pop("TEST-1", None)

    def _post(self, idx=0):
        return self.http.post("/api/search_duties_chunk", json={"lsi_seq": "TEST-1", "law_name": "시험 법", "chunk_index": idx}).get_json()

    def test_chunk_returns_verified_duties_with_enforce_date_and_json_mode(self):
        self.fake.models.reply = ('[{"article": "제1조", "duty_title": "안전점검", "description": "매년", "frequency": "연 1회", "target": "사업주"},'
                                  ' {"article": "제77조", "duty_title": "엉뚱", "description": "d", "frequency": "수시", "target": "사업주"}]')
        body = self._post()
        self.assertTrue(body["success"], body)
        d = body["data"]
        self.assertEqual([x["article_verified"] for x in d["duties"]], [True, False])
        self.assertEqual((d["total_chunks"], d["has_more"], d["enforce_date"], d["parse_failed"]), (1, False, "20260101", False))
        call = self.fake.models.calls[0]
        self.assertEqual(call["model"], "gemini-2.5-flash")
        self.assertEqual(_cfg(call, "response_mime_type"), "application/json")
        prompt = call["contents"] if isinstance(call["contents"], str) else str(call["contents"])
        self.assertIn("제1조, 제2조", prompt)                      # 모델에게 이 파트의 조 목록을 알려 준다

    def test_broken_json_is_retried_then_reported_as_failure(self):
        self.fake.models.reply = "이건 JSON이 아닙니다"
        d = self._post()["data"]
        self.assertTrue(d["parse_failed"])
        self.assertEqual(d["duties"], [])
        self.assertEqual(len(self.fake.models.calls), 2)           # 한 번 재시도

    def test_broken_then_good_json_succeeds_on_retry(self):
        replies = iter(["깨진 응답", '[{"article": "제1조", "duty_title": "가", "target": "사업주"}]'])
        self.fake.models.reply = lambda call: next(replies)
        d = self._post()["data"]
        self.assertFalse(d["parse_failed"])
        self.assertEqual(len(d["duties"]), 1)

    def test_chunk_index_out_of_range_is_empty_not_error(self):
        d = self._post(9)["data"]
        self.assertEqual((d["duties"], d["has_more"]), ([], False))

    def test_old_endpoint_is_gone(self):
        self.assertEqual(self.http.post("/api/search_duties", json={}).status_code, 404)

    def test_chat_uses_cached_law_text_in_order(self):
        self.fake.models.reply = "답"
        r = self.http.post("/api/chat/duty_list", json={"law_name": "시험 법", "lsi_seq": "TEST-1", "new_message": "점검 주기는?"})
        self.assertTrue(r.get_json()["success"])
        first = self.fake.models.calls[0]["contents"][0]["parts"][0]["text"]
        self.assertIn("제1조(목적) 사업주는 매년 안전점검을 하여야 한다.", first)
        self.assertNotIn("발췌", first)                             # 작은 법령은 전부 넣으므로 발췌 안내가 없다


class OnlineTests(unittest.TestCase):
    @unittest.skipIf(os.environ.get("SKIP_ONLINE_TESTS"), "SKIP_ONLINE_TESTS")
    def test_real_law_parses_into_numbered_articles(self):
        import urllib.parse
        import requests
        import xml.etree.ElementTree as ET
        try:
            res = requests.get(f"https://www.law.go.kr/DRF/lawSearch.do?OC={appmod.LAW_KEY}&target=law&type=XML&query="
                               + urllib.parse.quote("건설기술 진흥법"), timeout=10)
            mst = ET.fromstring(res.text).find("law").findtext("법령일련번호")
            law = duty_text.fetch_law(mst, appmod.LAW_KEY)
        except Exception as e:
            self.skipTest(f"법제처에 연결할 수 없음: {e}")
        labels = [a["label"] for a in law["articles"]]
        self.assertIn("제2조", labels)
        self.assertTrue(any("의" in l for l in labels))            # 가지 조문(제10조의2 등)
        art2 = next(a for a in law["articles"] if a["label"] == "제2조")["text"]
        self.assertIn("건설사업관리", art2)                          # 제2조 제1호~제2호 아래 '목'의 내용(예전엔 빠졌다)
        self.assertTrue(all(c["labels"] for c in law["chunks"]))
        self.assertRegex(law["enforce_date"], r"^\d{8}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
