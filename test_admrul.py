"""
고시(행정규칙) 원문·별표 조회와 고시 인용 검증의 회귀 테스트. `python test_admrul.py`로 실행한다.

[왜 만들었나]
"건설사업관리 인원 산정 시 기술지원기술인을 빼도 되나?"에 프로그램이 조문 번호도 수치도 못 대고 일반론만 답했다.
원인은 고시 조회 부재와 별표 미독해였고, 정답은 「건설엔지니어링 대가 등에 관한 기준」 제9조 ①
("시공단계의 기술인수는 기술지원기술인수를 포함한다")과 별표 2 바목(단순 10%·보통 15%·복잡 20%)이다.

- 오프라인 테스트: 별표 자르기, 이름 정리, 인용 파싱, 비율 대조 로직 (네트워크 불필요)
- 온라인 테스트: 법제처 API를 실제로 호출해 위 두 조항이 선택되는지, 가짜 인용이 걸러지는지 확인
  (법제처에 연결되지 않으면 온라인 테스트는 건너뛴다. 고시가 개정돼 문구가 바뀌면 온라인 테스트가 실패할 수
   있으니, 그때는 고시 원문을 확인하고 기대 문구를 갱신할 것)
Gemini 키가 없으면 LLM 부분은 실패하고 결정적 검사만 돌아간다(설계상 원문 유지).
"""
import unittest

import moleg_mcp as m
import mcp_agent_sync as s
import citation_check as cc

CM_NAME = "건설엔지니어링 대가 등에 관한 기준"
TOPIC = ["기술지원기술인", "건설사업관리", "인원수", "배치"]
ART9_PHRASE = "시공단계의 기술인수는 기술지원기술인수를 포함한다"
BP2_PHRASE = "단순한 공종 10%, 보통의 공종 15%, 복잡한 공종 20%"
URL_ADM = "https://www.law.go.kr/행정규칙/" + CM_NAME


def _online() -> bool:
    try:
        return bool(m._admrul_search(CM_NAME))
    except Exception:
        return False


ONLINE = _online()
needs_net = unittest.skipUnless(ONLINE, "법제처 API에 연결할 수 없어 건너뜀")


class OfflineTests(unittest.TestCase):
    def test_chunk_byeolpyo_splits_by_mok_and_drops_table_borders(self):
        content = "1. 총칙\n  가. 첫째 목\n┌──┬──┐\n│구분│내용  │\n└──┴──┘\n  나. 둘째 목\n"
        chunks = m._chunk_byeolpyo(content)
        self.assertEqual([c[1] for c in chunks], ["1. 총칙", "가. 첫째 목\n구분 | 내용", "나. 둘째 목"])
        self.assertTrue(all(top == "1. 총칙" for top, _ in chunks))

    def test_chunk_byeolpyo_caps_long_runs(self):
        content = "1. 표\n" + "\n".join("행 " + "가" * 100 for _ in range(60))
        self.assertTrue(all(len(body) <= 2000 for _top, body in m._chunk_byeolpyo(content, max_chunk=1800)))

    def test_rank_by_keywords_prefers_title_hit_and_drops_noise(self):
        texts = ["바. 기술지원기술인수는 일정 비율로 산정한다", "가. 직접경비는 따로 정한다", "나. 기술지원기술인 출장여비"]
        ranked = m._rank_by_keywords(texts, ["기술지원기술인"])
        self.assertEqual(ranked[0][1], 0)
        self.assertNotIn(1, [i for _s, i in ranked])
        self.assertEqual(m._rank_by_keywords([], ["x"]), [])

    def test_clean_admrul_name(self):
        self.assertEqual(s._clean_admrul_name("「건설공사 사업관리방식 검토기준 및 업무수행지침」"),
                         "건설공사 사업관리방식 검토기준 및 업무수행지침")
        self.assertEqual(s._clean_admrul_name("건설산업기본법"), "")        # 법률은 고시 경로로 보내지 않는다
        self.assertEqual(s._clean_admrul_name("기준"), "")                # 너무 짧음

    def test_hinted_admruls_triggers_on_cm_terms(self):
        names = s._hinted_admruls("건설사업관리 인원수 산정할때 기술지원인수를 빼도 되나?")
        self.assertIn(CM_NAME, names)
        self.assertEqual(s._hinted_admruls("하수도 점용허가 절차"), [])

    def test_find_citations_parses_admrul_links_with_spaces(self):
        text = (f"[{CM_NAME} 제9조]({URL_ADM}/제9조)\n"
                f"기술지원기술인 15% [{CM_NAME} 별표 2]({URL_ADM})")
        cites = cc._find_citations(text)
        art = [c for c in cites if c["kind"] == "art"][0]
        bp = [c for c in cites if c["kind"] == "bp"][0]
        self.assertTrue(art["adm"] and bp["adm"])
        self.assertEqual((art["law"], art["no"]), ("건설엔지니어링대가등에관한기준", 9))
        self.assertEqual((bp["law"], bp["no"]), ("건설엔지니어링대가등에관한기준", 2))
        self.assertEqual(bp["line_cites"], 1)

    def test_find_citations_keeps_law_links_as_non_admrul(self):
        cites = cc._find_citations("[건설기술 진흥법 제39조](https://www.law.go.kr/법령/건설기술진흥법/제39조)")
        self.assertEqual(len(cites), 1)
        self.assertFalse(cites[0]["adm"])

    def test_check_percent(self):
        base = {"kind": "bp", "no": 2, "br": 0, "line_cites": 1}
        body = "단순한 공종 10%, 보통의 공종 15%, 복잡한 공종 20%"
        self.assertIsNone(cc._check_percent({**base, "claim": "보통은 15%를 곱한다"}, body))
        self.assertIn("5%", cc._check_percent({**base, "claim": "일반은 5%를 곱한다"}, body))
        self.assertIsNone(cc._check_percent({**base, "claim": "5%를 곱한다", "line_cites": 2}, body))   # 인용 여럿이면 건너뜀
        self.assertIsNone(cc._check_percent({**base, "claim": "비율을 곱한다"}, body))


@needs_net
class OnlineTests(unittest.TestCase):
    def test_lookup_returns_current_exact_match_only(self):
        meta = m._lookup_admrul(CM_NAME)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["name"], CM_NAME)
        self.assertTrue(meta["current"])
        self.assertIsNone(m._lookup_admrul("존재하지 않는 가짜 지침"))
        self.assertIsNone(m._lookup_admrul("기준"))

    def test_search_picks_art9_and_byeolpyo2_mok_with_header(self):
        out = m.search_admrul_with_text([CM_NAME], TOPIC)
        self.assertTrue(out.startswith(f"[행정규칙 원문 발췌: {CM_NAME}]"))
        self.assertIn("현행", out.splitlines()[0])
        self.assertRegex(out.splitlines()[0], r"시행 \d{4}-\d{2}-\d{2}")
        self.assertIn(ART9_PHRASE, out)
        self.assertIn(BP2_PHRASE, out)
        self.assertIn("[별표 2:", out)
        self.assertNotIn("[법령 원문 발췌", out)      # law_linkify가 /법령/ 주소로 오인하지 않도록 헤더를 분리

    def test_search_skips_unknown_name_without_inventing(self):
        self.assertEqual(m.search_admrul_with_text(["존재하지 않는 가짜 지침"], TOPIC), "")
        self.assertEqual(m.search_admrul_with_text([], TOPIC), "")

    def test_law_retrieval_still_works(self):
        out = m.search_laws_with_text(["건설기술 진흥법"], ["건설사업관리", "배치", "기술인"],
                                      per_law_len=3000, max_total_len=6000)
        self.assertIn("[법령 원문 발췌: 건설기술 진흥법]", out)
        self.assertIn("제39조(건설사업관리 등의 시행)", out)

    def test_annotate_flags_bad_admrul_citations_and_keeps_good_ones(self):
        text = (
            f"시공단계 기술인수는 기술지원기술인수를 포함합니다. [{CM_NAME} 제9조]({URL_ADM}/제9조)\n"
            f"보통 공종은 시공단계 인원의 15%를 곱합니다. [{CM_NAME} 별표 2]({URL_ADM})\n"
            f"일반 공종은 시공단계 인원의 5%를 곱합니다. [{CM_NAME} 별표 2]({URL_ADM})\n"
            f"별표 9에 따라 산정합니다. [{CM_NAME} 별표 9]({URL_ADM})\n"
            f"제99조에 따릅니다. [{CM_NAME} 제99조]({URL_ADM}/제99조)\n")
        lines = cc.annotate_unverified_citations(text).splitlines()
        self.assertNotIn("⚠️", lines[0] + lines[1])
        self.assertNotIn("💡", lines[0] + lines[1])
        self.assertIn("5%", lines[2])
        self.assertIn("💡", lines[2])
        self.assertIn("별표 9가 존재하지 않습니다", lines[3])
        self.assertIn("제99조는 존재하지 않는 조문", lines[4])

    def test_end_to_end_context_for_original_question(self):
        """원래 질문: LLM이 없어도(힌트만으로) 두 고시와 정답 문구가 컨텍스트에 들어와야 한다."""
        ctx = s.get_mcp_context_sync("건설사업관리 인원수 산정할때 기술지원인수를 산정하지 않아도 문제가없어?")
        self.assertIn(f"[행정규칙 원문 발췌: {CM_NAME}]", ctx)
        self.assertIn("[행정규칙 원문 발췌: 건설공사 사업관리방식 검토기준 및 업무수행지침]", ctx)
        self.assertIn(ART9_PHRASE, ctx)
        self.assertIn(BP2_PHRASE, ctx)


if __name__ == "__main__":
    unittest.main(verbosity=2)
