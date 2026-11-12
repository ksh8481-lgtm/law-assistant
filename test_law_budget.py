"""법령 원문 가져오기의 분량 배분(moleg_mcp.search_laws_with_text) 시험. `python test_law_budget.py`. 네트워크 불필요.

배경: 질의가 가리키는 법령이 여러 개일 때 분량 상한을 목록 앞쪽 법령이 다 써 버려 뒤쪽의 핵심 법령(자연재해대책법)이 통째로 빠졌고,
AI가 "제공된 법령 데이터베이스에 원문이 없다"며 직접 찾아보라고 답했다. 본 법률은 상한과 무관하게 모두 싣고, 시행령·시행규칙은 관련 높은 법령부터 채우며,
싣지 못한 법령은 AI에게 따로 알려야 한다.
"""
import re
import unittest
import xml.etree.ElementTree as ET

import moleg_mcp as mm

# 법령 이름 -> [(법령명, 일련번호)] (법, 시행령, 시행규칙 순)
LAWS = {
    '재난 및 안전관리 기본법': [('재난 및 안전관리 기본법', '1'), ('재난 및 안전관리 기본법 시행령', '2'), ('재난 및 안전관리 기본법 시행규칙', '3')],
    '관광진흥법': [('관광진흥법', '11'), ('관광진흥법 시행령', '12'), ('관광진흥법 시행규칙', '13')],
    '자연재해대책법': [('자연재해대책법', '21'), ('자연재해대책법 시행령', '22'), ('자연재해대책법 시행규칙', '23')],
}
# 일련번호 -> 본문(키워드 '재해영향평가' 가 많을수록 질의와 관련 높은 법령). 각 본문은 3,000자.
TEXT = {mst: ('x' * 2990) for names in LAWS.values() for _n, mst in names}
TEXT['21'] = '재해영향평가 ' * 40 + 'x' * 2500          # 핵심 법령의 본 법률(핵심어가 많음)
TEXT['11'] = '재해영향평가 ' * 3 + 'x' * 2900
TEXT['1'] = 'x' * 2990


def search_xml(name):
    fam = LAWS.get(name)
    if not fam:
        return ET.fromstring('<LawSearch></LawSearch>')
    items = ''.join(f'<law><법령명한글>{nm}</법령명한글><법령일련번호>{mst}</법령일련번호></law>' for nm, mst in fam)
    return ET.fromstring(f'<LawSearch>{items}</LawSearch>')


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self._f, self._d = mm._fetch_law_xml_with_retry, mm._law_detail_text
        self.fetched = []

        def fake_search(url, *a, **k):
            import urllib.parse
            q = urllib.parse.unquote(re.search(r'query=([^&]+)', url).group(1))
            return search_xml(q)
        mm._fetch_law_xml_with_retry = fake_search

        def fake_detail(mst, keywords, max_len=6000, include_byeolpyo=False):
            self.fetched.append(mst)
            return TEXT[mst]
        mm._law_detail_text = fake_detail

    def tearDown(self):
        mm._fetch_law_xml_with_retry, mm._law_detail_text = self._f, self._d

    def headers(self, out):
        return re.findall(r'\[법령 원문 발췌: ([^\]]+)\]', out)

    def run_search(self, names, budget, per_name_max=3):
        return mm.search_laws_with_text(names, ['재해영향평가'], per_name_max=per_name_max, max_total_len=budget)

    def test_every_named_law_gets_its_base_text_even_when_budget_is_tiny(self):
        out = self.run_search(['재난 및 안전관리 기본법', '관광진흥법', '자연재해대책법'], budget=1000)
        self.assertEqual(self.headers(out), ['재난 및 안전관리 기본법', '관광진흥법', '자연재해대책법'])   # 앞 법령이 상한을 다 써도 뒤 법령이 빠지지 않는다

    def test_extras_go_to_the_most_relevant_law_first_and_tier_by_tier(self):
        # 본 법률 3개 = 약 9,000자. 상한 13,000자면 시행령 약 2개만 더 들어간다.
        out = self.run_search(['재난 및 안전관리 기본법', '관광진흥법', '자연재해대책법'], budget=13000)
        got = self.headers(out)
        self.assertIn('자연재해대책법 시행령', got)                      # 질의와 가장 관련 높은 법령의 시행령이 먼저
        self.assertIn('관광진흥법 시행령', got)                          # 시행규칙보다 다른 법령의 시행령이 먼저
        self.assertNotIn('자연재해대책법 시행규칙', got)
        self.assertNotIn('재난 및 안전관리 기본법 시행령', got)           # 관련 낮은 법령의 시행령은 상한이 모자라면 빠진다

    def test_sections_are_grouped_by_law_in_the_requested_order(self):
        out = self.run_search(['재난 및 안전관리 기본법', '관광진흥법', '자연재해대책법'], budget=40000)
        self.assertEqual(self.headers(out), [nm for n in ('재난 및 안전관리 기본법', '관광진흥법', '자연재해대책법') for nm, _m in LAWS[n]])

    def test_dropped_laws_are_announced_to_the_ai(self):
        out = self.run_search(['재난 및 안전관리 기본법', '관광진흥법', '자연재해대책법'], budget=13000)
        self.assertIn('분량 제한으로 이번 답변에 원문 발췌를 싣지 못한 법령', out)
        for dropped in ('자연재해대책법 시행규칙', '재난 및 안전관리 기본법 시행령'):
            self.assertIn(dropped, out.split('분량 제한으로')[1])
        full = self.run_search(['관광진흥법'], budget=40000)
        self.assertNotIn('분량 제한으로', full)                          # 다 실었으면 안내하지 않는다

    def test_unfindable_law_is_reported_not_silently_dropped(self):
        out = self.run_search(['관광진흥법', '존재하지않는법'], budget=40000)
        self.assertIn("법령 '존재하지않는법'", out)
        self.assertIn('원문을 싣지 못했습니다', out)
        self.assertIn('[법령 원문 발췌: 관광진흥법]', out)

    def test_per_name_max_still_limits_the_family(self):
        out = self.run_search(['자연재해대책법'], budget=40000, per_name_max=1)
        self.assertEqual(self.headers(out), ['자연재해대책법'])
        out2 = self.run_search(['자연재해대책법'], budget=40000, per_name_max=2)
        self.assertEqual(self.headers(out2), ['자연재해대책법', '자연재해대책법 시행령'])

    def test_skip_msts_not_fetched_again(self):
        out = mm.search_laws_with_text(['관광진흥법'], ['x'], skip_msts={'11'})
        self.assertNotIn('[법령 원문 발췌: 관광진흥법]', out)
        self.assertNotIn('11', self.fetched)


if __name__ == '__main__':
    unittest.main(verbosity=2)
