"""룰 엔진(rule_engine.py)과 지식 기반(law_knowledge_base.json) 시험. `python test_rule_engine.py`. 네트워크가 필요 없다.

핵심: 모르는 변수를 0으로 읽어 '작다' 조건이 저절로 참이 되던 결함(어떤 사업에도 교육시설 안전성평가 등이 붙음)이 다시 생기지 않는가.
"""
import json
import os
import unittest

import rule_engine as re_


def ids(params):
    return {r['id'] for r in re_.evaluate_knowledge_base(params)}


class MissingVariableTests(unittest.TestCase):
    def test_missing_variable_never_satisfies_a_comparison(self):
        m = re_._MISSING
        self.assertFalse(m < 200)
        self.assertFalse(m <= 4)
        self.assertFalse(m > 0)
        self.assertFalse(m >= 0)
        self.assertFalse(m == False)           # noqa: E712  (예전에는 모르는 값이 False와 같다고 읽혔다)
        self.assertFalse(m != 3)
        self.assertFalse(bool(m))

    def test_unknown_project_gets_only_unconditional_rules(self):
        got = ids({'budget': 50, 'total_area': 2000, 'is_public': True})
        # 사업에 따라 달라지지 않는 규칙(조건 True)만 남고, 모르는 변수에 기대던 규칙은 붙지 않는다
        for bad in ('EDUCATIONAL_FACILITY_SAFETY_ASSESSMENT', 'NATURAL_PARK_PROJECT_IMPLEMENTATION', 'PRELIMINARY_COMPLETION_INSPECTION'):
            self.assertNotIn(bad, got, bad)
        kb = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'law_knowledge_base.json'), encoding='utf-8'))
        always = {r['id'] for r in kb if r['condition'].strip() == 'True'}
        self.assertTrue(always <= got)

    def test_known_variables_still_match(self):
        self.assertIn('LAW_MOUNTAIN', ids({'has_mountain': True}))
        self.assertIn('LAW_ENVIRONMENT', ids({'total_area': 6000}))
        self.assertNotIn('LAW_ENVIRONMENT', ids({'total_area': 4000}))
        self.assertIn('LAW_ENVIRONMENT_LARGE', ids({'total_area': 120000}))
        # 알려진 값으로는 '작다' 조건도 정상 판정
        self.assertIn('EDUCATIONAL_FACILITY_SAFETY_ASSESSMENT', ids({'distance_to_school_m': 3}))
        self.assertNotIn('EDUCATIONAL_FACILITY_SAFETY_ASSESSMENT', ids({'distance_to_school_m': 900}))
        self.assertIn('PRELIMINARY_COMPLETION_INSPECTION', ids({'days_until_completion_date': 30}))

    def test_negation_of_unknown_is_not_a_match_but_negation_of_known_false_is(self):
        self.assertNotIn('NATURAL_PARK_PROJECT_IMPLEMENTATION', ids({'budget': 10}))
        self.assertIn('NATURAL_PARK_PROJECT_IMPLEMENTATION', ids({'is_park_management_authority_project': False}))
        self.assertNotIn('NATURAL_PARK_PROJECT_IMPLEMENTATION', ids({'is_park_management_authority_project': True}))

    def test_none_values_count_as_unknown(self):
        self.assertNotIn('LAW_MOUNTAIN', ids({'has_mountain': None}))

    def test_variables_listing_and_bad_conditions(self):
        v = re_.get_all_variables()
        self.assertIn('total_area', v)
        self.assertIn('distance_to_school_m', v)
        self.assertEqual(ids({}) & {'LAW_MOUNTAIN'}, set())

    def test_every_rule_condition_parses(self):
        kb = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'law_knowledge_base.json'), encoding='utf-8'))
        import ast
        for r in kb:
            ast.parse(r['condition'])          # 문법 오류가 있으면 그 규칙은 조용히 영원히 안 맞게 된다


if __name__ == '__main__':
    unittest.main(verbosity=2)
