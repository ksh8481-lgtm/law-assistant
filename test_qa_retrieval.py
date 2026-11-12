"""기타 행정 검토(Q&A)의 자료 수집 보강 시험: 법령해석례 검색, 주제어로 소관 법률 고정, 조문 고르는 키워드 정리. `python test_qa_retrieval.py`.
네트워크·AI 없이 돈다(법제처·Gemini는 가짜). 마지막 시험 하나만 법제처에 접속하며, 접속이 안 되면 건너뛴다(SKIP_ONLINE_TESTS=1로도 건너뜀).

배경: 같은 질문(관광단지 면적 변경 + 재해영향평가)에서 (1) AI가 법령명을 뽑을 때 자연재해대책법이 5번 중 1번 빠졌고, (2) 조문 고르는 키워드가
"면적변경", "그이후" 같은 말이라 시행령 제6조의2(재협의 기준 수치)가 컨텍스트에 안 들어갔고, (3) 법제처 법령해석례(25-0166)를 아예 조회하지 않았다.
"""
import os
import unittest
import xml.etree.ElementTree as ET

import mcp_agent_sync as m
import moleg_mcp as mm

QUESTION = """재해영향성 검토 관련법이생기기전 관광진흥법에 따라 1998년 관광단지 지정을 했어
그이후에 재해영향평가관련법이 생겼어
그리고 나서 관광단지 면적변경이 생겼어
이러한 겨우 재해영향성검토를 안받아도 돼??"""


class KeywordTests(unittest.TestCase):
    def test_query_terms_drop_colloquial_junk_but_keep_real_terms(self):
        terms = m._query_terms(QUESTION)
        for junk in ('그이후', '관련법이생기기전', '지정을', '생겼어', '그리고'):
            self.assertNotIn(junk, terms)
        for good in ('재해영향성', '관광단지', '관광진흥법'):
            self.assertIn(good, terms)

    def test_query_terms_do_not_mangle_nouns_ending_in_a_particle_letter(self):
        self.assertIn('하수도', m._query_terms('하수도 설치 가능 여부'))                # '도'는 조사처럼 보여도 명사의 일부
        self.assertIn('관광단지', m._query_terms('관광단지를 지정'))                      # 조사 '를'은 떼낸다

    def test_split_compound(self):
        self.assertEqual(m._split_compound('면적변경'), ['면적', '변경'])
        self.assertEqual(m._split_compound('지정해제'), ['지정', '해제'])
        self.assertEqual(m._split_compound('하도급'), [])
        self.assertEqual(m._split_compound('면적 변경'), [])                           # 이미 띄어 쓴 것은 그대로
        self.assertEqual(m._split_compound('변경'), [])


class HintTests(unittest.TestCase):
    def test_topic_words_pin_the_governing_law(self):
        hits = m._hinted_laws(QUESTION)
        self.assertEqual([h[0] for h in hits], ['자연재해대책법', '관광진흥법'])
        self.assertIn('재협의', hits[0][1])                                          # 조문 고르는 추가 키워드
        self.assertEqual(hits[0][2], '재해영향평가')                                  # 해석례 검색 주제어

    def test_spacing_variants_still_match_and_unrelated_questions_get_nothing(self):
        self.assertEqual(m._hinted_laws('재해 영향 평가')[:0], [])                      # 띄어 쓴 형태는 '재해영향' 낱말이 없어 안 붙는다(과잉 방지)
        self.assertEqual(m._hinted_laws('사전 재해영향성 검토')[0][0], '자연재해대책법')
        self.assertEqual(m._hinted_laws('영업손실보상 대상인가요'), [])
        self.assertEqual(m._hinted_laws(''), [])

    def test_at_most_two_hinted_laws(self):
        self.assertLessEqual(len(m._hinted_laws('재해영향평가 환경영향평가 교통영향평가 관광단지 산지전용')), 2)

    def test_hinted_law_names_look_like_official_names(self):
        for _t, law, _x, _topic in m._LAW_HINTS:
            self.assertTrue(m._clean_law_name(law), law)                           # '법/법률'로 끝나 _merge_unique에서 버려지지 않는다


class InterpretationQueryTests(unittest.TestCase):
    def test_short_queries_primary_alone_and_with_one_more_word(self):
        qs, terms = m._interpretation_queries('재해영향평가', ['재해영향평가', '관광단지', '면적변경', '협의'], m._hinted_laws(QUESTION), QUESTION)
        self.assertIn('재해영향평가', qs)
        self.assertIn('재해영향평가 면적', qs)                                        # '면적변경'은 쪼개서 쓴다(제목에 모두 있어야 걸리므로)
        self.assertNotIn('재해영향평가 면적변경', qs)
        self.assertTrue(all(len(q.split()) <= 2 for q in qs))                      # 단어 3개 이상이면 거의 0건
        self.assertIn('재해영향평가', terms)


def search_xml(items):
    body = ''.join(f'<expc id="{i}"><법령해석례일련번호>{seq}</법령해석례일련번호><안건명><![CDATA[{title}]]></안건명><안건번호>{no}</안건번호>'
                   f'<회신기관명>법제처</회신기관명><회신일자>{date}</회신일자></expc>' for i, (seq, title, no, date) in enumerate(items, 1))
    return ET.fromstring(f'<Expc><totalCnt>{len(items)}</totalCnt>{body}</Expc>')


T_REC = '행안부 - 일반산업단지 지정해제로 부지면적이 30퍼센트 이상 감소한 경우 재해영향평가등의 재협의 대상인지'
T_ROAD = '민원인 - 도로를 설치하는 도시ㆍ군계획시설사업이 재해영향평가 협의 대상인지'
T_OTHER = '민원인 - 건축물 용도변경 신고'


class InterpretationSearchTests(unittest.TestCase):
    def setUp(self):
        self._f = mm._fetch_law_xml_with_retry
        self.calls = []

        def fake(url, *a, **k):
            self.calls.append(url)
            if 'lawService.do' in url:
                seq = url.split('ID=')[1].split('&')[0]
                return ET.fromstring(f'<ExpcService><질의요지><![CDATA[ 질의 {seq}\n  내용 ]]></질의요지><회답><![CDATA[ 회답 {seq} ]]></회답></ExpcService>')
            if 'query=' in url and 'expc' in url:
                import urllib.parse
                q = urllib.parse.unquote(url.split('query=')[1].split('&')[0])
                if q == '재해영향평가':
                    return search_xml([('1', T_REC, '24-0880', '2025.03.28'), ('2', T_REC, '25-0166', '2025.03.28'), ('3', T_REC, '25-0165', '2025.03.28'), ('4', T_ROAD, '24-0864', '2025.02.28')])
                if q == '재해영향평가 면적':
                    return search_xml([('4', T_ROAD, '24-0864', '2025.02.28'), ('5', T_OTHER, '23-0001', '2023.01.01')])
                return search_xml([])
            raise AssertionError(url)
        mm._fetch_law_xml_with_retry = fake

    def tearDown(self):
        mm._fetch_law_xml_with_retry = self._f

    def test_merges_dedupes_same_title_and_ranks_by_relevance(self):
        out = mm.search_interpretations(['재해영향평가', '재해영향평가 면적', '재해영향평가 없음'], ['재해영향평가', '재협의', '부지면적'])
        self.assertIn('[법제처 해석례 25-0166]', out)                              # 같은 사안 세 건 중 대표 하나(안건번호가 큰 것)
        self.assertIn('같은 사안의 다른 회신 안건번호: 24-0880, 25-0165', out)
        self.assertEqual(out.count('행안부 - 일반산업단지'), 1)
        self.assertIn('[법제처 해석례 24-0864]', out)
        self.assertNotIn('용도변경', out)                                          # 질의 용어가 제목에 하나도 없으면 뺀다
        self.assertLess(out.index('25-0166'), out.index('24-0864'))                # 제목에 질의 용어가 더 많은 것이 먼저
        self.assertIn('expcSeq=', out)
        self.assertNotIn('OC=', out)                                               # 링크에 API 인증키가 새지 않는다

    def test_top_items_carry_question_and_answer_and_no_invention_warning(self):
        out = mm.search_interpretations(['재해영향평가'], ['재해영향평가', '재협의'], max_items=2, detail_items=1)
        self.assertIn('질의요지: 질의 2', out)                                       # 대표(25-0166, 일련번호 2)의 본문
        self.assertIn('회답: 회답 2', out)
        self.assertIn('지어내지 마십시오', out)
        self.assertEqual(out.count('질의요지:'), 1)                                  # detail_items=1

    def test_empty_and_failures_are_swallowed(self):
        self.assertEqual(mm.search_interpretations([], ['x']), '')
        self.assertEqual(mm.search_interpretations(['결과없는검색어'], ['x']), '')

        def boom(url, *a, **k):
            raise ConnectionError('down')
        mm._fetch_law_xml_with_retry = boom
        self.assertEqual(mm.search_interpretations(['재해영향평가'], ['재해영향평가']), '')   # 보조 자료라 답변을 막지 않는다

    def test_all_title_match_fallback_keeps_one_result(self):
        out = mm.search_interpretations(['재해영향평가'], ['전혀관련없는말'])
        self.assertIn('해석례', out)                                                # 관련어가 하나도 안 겹쳐도 가장 가까운 1건은 남긴다


class ContextAssemblyTests(unittest.TestCase):
    """get_mcp_context_sync가 AI 추출이 법령을 빠뜨려도 소관 법률을 넣고, 해석례 절을 붙이는지."""

    def setUp(self):
        self._orig = {k: getattr(m, k) for k in ('_extract_keyword_and_jurisdiction', '_extract_admrul_names', 'search_laws_with_text', 'search_interpretations',
                                                  'search_law', 'search_precedents_by_keyword', 'search_ordinance')}
        self.law_calls = []
        self.interp_calls = []
        m._extract_keyword_and_jurisdiction = lambda q: ('재해영향평가', '', '재해영향평가', ['재난 및 안전관리 기본법'], ['면적변경', '협의'])   # 자연재해대책법·관광진흥법을 빠뜨린 추출
        m._extract_admrul_names = lambda q: []
        m.search_law = lambda k: 'law'
        m.search_precedents_by_keyword = lambda k: 'prec'
        m.search_ordinance = lambda k: 'No ordinances found'

        def fake_laws(names, kws, **k):
            self.law_calls.append((list(names), list(kws), k))
            return '[법령 원문 발췌: ' + names[0] + ']\n본문'
        m.search_laws_with_text = fake_laws

        def fake_interp(queries, terms, **k):
            self.interp_calls.append((list(queries), list(terms)))
            return '[법령해석례(법제처 공식 회신) 검색 결과] 안건 25-0166'
        m.search_interpretations = fake_interp

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(m, k, v)

    def test_hinted_laws_are_added_first_even_when_extraction_missed_them(self):
        ctx = m.get_mcp_context_sync(QUESTION)
        names, kws, kw_args = self.law_calls[0]
        self.assertEqual(names[:2], ['자연재해대책법', '관광진흥법'])
        self.assertIn('재난 및 안전관리 기본법', names)                              # AI가 뽑은 법령도 남는다
        self.assertLessEqual(len(names), 5)
        for k in ('재협의', '경미한 변경', '면적', '변경'):                           # 힌트 키워드 + 합성어 분해
            self.assertIn(k, kws)
        self.assertNotIn('그이후', kws)
        self.assertEqual(kw_args.get('max_total_len'), 34000)
        self.assertIn('안건 25-0166', ctx)                                          # 해석례 절이 컨텍스트에 들어간다

    def test_unrelated_question_gets_no_pinned_law_and_interpretation_failure_is_harmless(self):
        m._extract_keyword_and_jurisdiction = lambda q: ('영업손실보상', '', '영업손실', ['공익사업을 위한 토지 등의 취득 및 보상에 관한 법률'], ['영업손실'])

        def boom(*a, **k):
            raise RuntimeError('expc down')
        m.search_interpretations = boom
        ctx = m.get_mcp_context_sync('영업손실보상 대상인가요')
        self.assertEqual(self.law_calls[0][0], ['공익사업을 위한 토지 등의 취득 및 보상에 관한 법률'])
        self.assertIn('[법령 원문 발췌:', ctx)                                       # 해석례가 죽어도 나머지는 그대로


@unittest.skipIf(os.environ.get('SKIP_ONLINE_TESTS') == '1', '온라인 시험 건너뜀')
class OnlineTests(unittest.TestCase):
    def test_hinted_law_names_exist_at_moleg_and_expc_finds_25_0166(self):
        try:
            for _t, law, _x, _topic in m._LAW_HINTS:
                root = mm._fetch_law_xml_with_retry(
                    f"https://www.law.go.kr/DRF/lawSearch.do?OC={mm.MOLEG_API_KEY}&target=law&type=XML&query={__import__('urllib.parse').parse.quote(law)}")
                names = [l.findtext('법령명한글', '') for l in root.findall('.//law')]
                self.assertIn(law, names, f'{law}: 법제처 정식 명칭과 다르다')
            out = mm.search_interpretations(['재해영향평가', '재해영향평가 면적'], ['재해영향평가', '재협의', '부지면적'])
        except (OSError, RuntimeError) as e:
            self.skipTest(f'법제처 접속 불가: {e}')
        self.assertIn('25-0166', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
