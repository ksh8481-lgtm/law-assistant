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

    def test_single_quoted_term_must_appear_in_cited_articles(self):
        c = {"no": 13, "br": 0, "claim": "착수 시 '상주, 기술지원 기술인 지정신고서'를 제출한다"}
        c2 = {**c, "no": 23}
        wrong = cc._check_single_quoted_terms([(c, "제13조(과업착수준비) 업무수행계획서를 작성한다"),
                                               (c2, "제23조(발주방식 결정 지원) 발주방식을 정한다")])
        self.assertIn("지정신고서", wrong)
        self.assertIn("제13조, 제23조", wrong)
        right = cc._check_single_quoted_terms([(c, "제13조 ..."), ({**c, "no": 50}, "3. 상주, 기술지원 기술인 지정신고서")])
        self.assertIsNone(right)                                    # 하나라도 포함하면 통과
        self.assertIsNone(cc._check_single_quoted_terms([({"no": 1, "br": 0, "claim": "따옴표 없는 문장"}, "x")]))
        self.assertIsNone(cc._check_single_quoted_terms([]))
        # 짧은 인용('원칙') 사이의 문장 조각을 용어로 오인하지 않는다(운영 답변 재처리에서 발견한 오탐)
        short = {"no": 9, "br": 0, "claim": "산정을 '원칙'으로 규정하고, 시공단계 기술인수에 '포함한다'고 명시한다"}
        self.assertIsNone(cc._check_single_quoted_terms([(short, "산정하는 것을 원칙으로 한다. 기술인수는 포함한다")]))

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


GUIDE_NAME = "건설공사 사업관리방식 검토기준 및 업무수행지침"
SAMPLE_CONTEXT = (
    f"[행정규칙 원문 발췌: {CM_NAME}] (국토교통부 고시, 시행 2023-10-17, 현행, 법제처 조회 2026-10-21) "
    f"(https://www.law.go.kr/행정규칙/%EA%B1%B4)\n제9조 ...\n\n"
    f"[행정규칙 원문 발췌: {GUIDE_NAME}] (국토교통부 고시, 시행 2026-07-08, 현행, 법제처 조회 2026-10-21) "
    f"(https://www.law.go.kr/행정규칙/%EA%B1%B5)\n※ 2027-01-01 시행 예정인 개정본이 있습니다. 아래는 ...\n제8조 ...")


class PostProcessTests(unittest.TestCase):
    """운영 확인에서 드러난 문제: 시행일 미표기, 고시를 /법령/ 주소로 링크, 링크 없는 고시 인용."""

    def setUp(self):
        import law_linkify as ll
        self.ll = ll
        self.infos = ll.extract_admrul_info_from_context(SAMPLE_CONTEXT)

    def test_extract_info_parses_headers_and_pending(self):
        self.assertEqual([i["name"] for i in self.infos], [CM_NAME, GUIDE_NAME])
        self.assertEqual((self.infos[0]["ymd"], self.infos[0]["status"], self.infos[0]["pending"]),
                         ("2023-10-17", "현행", ""))
        self.assertEqual(self.infos[1]["pending"], "2027-01-01")
        self.assertEqual(self.ll.extract_admrul_info_from_context("고시 없음"), [])

    def test_footer_lists_only_mentioned_admruls_with_effective_date(self):
        footer = self.ll.admrul_footer(f"{CM_NAME} 제9조에 따라 산정한다.", self.infos)
        self.assertIn("시행 2023-10-17, 현행", footer)
        self.assertNotIn(GUIDE_NAME, footer)
        self.assertEqual(self.ll.admrul_footer("고시 언급 없음", self.infos), "")
        both = self.ll.admrul_footer(f"{CM_NAME}, {GUIDE_NAME}", self.infos)
        self.assertIn("2027-01-01 시행 예정", both)

    def test_wrong_law_url_for_admrul_is_rewritten_to_admrul_url(self):
        text = f"[{GUIDE_NAME}](https://www.law.go.kr/법령/건설공사사업관리방식검토기준및업무수행지침/제13조)"
        out = self.ll.linkify_law_citations(text, None, self.infos)
        self.assertIn("law.go.kr/행정규칙/", out)
        self.assertNotIn("law.go.kr/법령/", out)
        self.assertTrue(out.endswith("%EC%A0%9C13%EC%A1%B0)"))     # 제13조 경로 유지

    def test_bare_admrul_mentions_get_admrul_links(self):
        out = self.ll.linkify_law_citations(
            f"「{CM_NAME}」 제9조 ①과 {CM_NAME} 별표 2를 따른다.", None, self.infos)
        self.assertEqual(out.count("](https://www.law.go.kr/행정규칙/"), 2)
        self.assertIn("/%EC%A0%9C9%EC%A1%B0)", out)            # 제9조까지 연결
        self.assertIn(f"[{CM_NAME} 별표 2](", out)              # 별표는 라벨에 포함(주소는 고시 본문)
        self.assertNotIn("law.go.kr/법령/", out)

    def test_existing_admrul_links_and_law_links_are_untouched(self):
        text = (f"[{CM_NAME} 제9조](https://www.law.go.kr/행정규칙/{CM_NAME}/제9조) "
                "[건설기술 진흥법 제39조](https://www.law.go.kr/법령/건설기술진흥법/제39조)")
        out = self.ll.linkify_law_citations(text, None, self.infos)
        self.assertIn("/행정규칙/", out)
        self.assertIn("law.go.kr/법령/%EA%B1%B4%EC%84%A4%EA%B8%B0%EC%88%A0%EC%A7%84%ED%9D%A5%EB%B2%95/", out)
        self.assertEqual(out.count("]("), 2)                    # 링크 안에 링크가 생기지 않음

    def test_without_admrul_infos_behaves_as_before(self):
        text = "건설기술 진흥법 제39조에 따른다."
        self.assertEqual(self.ll.linkify_law_citations(text), self.ll.linkify_law_citations(text, None, None))
        self.assertIn("law.go.kr/법령/", self.ll.linkify_law_citations(text))


@needs_net
class OnlineTests(unittest.TestCase):
    def test_real_header_matches_the_parser(self):
        """moleg_mcp가 만드는 헤더 형식과 law_linkify의 파서가 어긋나면(한쪽만 바꾸면) 여기서 걸린다."""
        import law_linkify as ll
        out = m.search_admrul_with_text([CM_NAME], TOPIC)
        infos = ll.extract_admrul_info_from_context(out)
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0]["name"], CM_NAME)
        self.assertEqual(infos[0]["status"], "현행")
        self.assertRegex(infos[0]["ymd"], r"^\d{4}-\d{2}-\d{2}$")

    def test_articles_listed_after_admrul_link_are_verified(self):
        """운영 확인: '[…지침](링크)(국토교통부고시) 제13조 및 제23조'처럼 링크 뒤에 조가 떨어져 있으면 검증이 안 됐다."""
        url = "https://www.law.go.kr/행정규칙/" + GUIDE_NAME
        text = f"[{GUIDE_NAME}]({url})(국토교통부고시) 제8조 및 제999조: 배치기준을 정한다."
        cites = cc._find_citations(text)
        self.assertEqual([(c["no"], c["adm"]) for c in cites], [(8, True), (999, True)])
        out = cc.annotate_unverified_citations(text)
        self.assertNotIn("제8조는 존재하지 않는", out)
        self.assertIn("제999조는 존재하지 않는 조문", out)
        self.assertLess(out.index("제8조"), out.index("⚠️"))        # 경고는 해당 조 바로 뒤에 붙는다

    def test_wrong_but_existing_article_is_flagged_by_quoted_term(self):
        """운영 답변의 실제 사례: 지정신고서는 제50조·제80조에 있는데 제13조·제23조로 인용했다(둘 다 존재하는 조문)."""
        url = "https://www.law.go.kr/행정규칙/" + GUIDE_NAME
        wrong = (f"[{GUIDE_NAME}]({url})(국토교통부고시) 제13조 및 제23조: 착수 시 "
                 f"'상주, 기술지원 기술인 지정신고서'를 포함한다.")
        right = wrong.replace("제13조 및 제23조", "제50조")
        self.assertIn("지정신고서'이(가) 인용한 제13조, 제23조", cc.annotate_unverified_citations(wrong))
        self.assertNotIn("💡", cc.annotate_unverified_citations(right))

    def test_bare_citation_is_linked_then_verified(self):
        """링크 없이 쓴 고시 인용도 링크가 달리고, 없는 조문이면 경고가 붙는다(운영에서 못 잡던 경로)."""
        import law_linkify as ll
        infos = ll.extract_admrul_info_from_context(m.search_admrul_with_text([CM_NAME], TOPIC))
        text = f"{CM_NAME} 제9조에 따라 포함한다.\n{CM_NAME} 제99조에 따른다.\n"
        lines = cc.annotate_unverified_citations(ll.linkify_law_citations(text, None, infos)).splitlines()
        self.assertNotIn("⚠️", lines[0])
        self.assertIn("제99조는 존재하지 않는 조문", lines[1])

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
