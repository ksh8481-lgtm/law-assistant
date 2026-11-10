"""입력에서 확정되는 룰 엔진 변수(lr_flags.py)와 새로 넣은 지식 기반 규칙 시험. `python test_lr_flags.py`. 네트워크 불필요."""
import json
import os
import unittest

import lr_flags
import rule_engine

NAMHAE = [{'address': '경상남도 남해군 남해읍 입현리 1'}, {'address': '경상남도 남해군 남해읍 서변리 100'}]


def ids(params):
    return {r['id'] for r in rule_engine.evaluate_knowledge_base(params)}


class FlagTests(unittest.TestCase):
    def test_budget_and_area_aliases(self):
        f = lr_flags.derive_flags('x', '토목공사', 50, 2000, '', NAMHAE)
        self.assertEqual((f['total_budget'], f['total_project_cost']), (50.0, 5_000_000_000.0))     # 억 원과 원 두 가지 이름
        self.assertEqual((f['total_area_sqm'], f['land_area'], f['development_area']), (2000.0, 2000.0, 2000.0))
        self.assertNotIn('total_budget', lr_flags.derive_flags('x', '토목공사', 0, 0, '', []))      # 모르는 값은 만들지 않는다
        self.assertNotIn('total_budget', lr_flags.derive_flags('x', '토목공사', 'abc', None, '', []))

    def test_location_type_county_only_when_all_parcels_are_in_a_county(self):
        self.assertEqual(lr_flags.derive_flags('x', '토목공사', 1, 1, '', NAMHAE)['location_type'], 'county')
        mixed = NAMHAE + [{'address': '경상남도 창원시 의창구 1'}]
        self.assertNotIn('location_type', lr_flags.derive_flags('x', '토목공사', 1, 1, '', mixed))
        self.assertNotIn('location_type', lr_flags.derive_flags('x', '토목공사', 1, 1, '', [{'address': '부산광역시 해운대구 1'}]))
        self.assertNotIn('location_type', lr_flags.derive_flags('x', '토목공사', 1, 1, '', []))

    def test_facility_and_road_excavation_from_text(self):
        f = lr_flags.derive_flags('도시계획도로 개설', '토목공사', 1, 1, '도로 굴착 후 상수도관 매설', [])
        self.assertEqual((f['facility_type'], f['has_road_excavation']), ('road', True))
        f = lr_flags.derive_flags('소하천 정비', '토목공사', 1, 1, '제방 축조', [])
        self.assertEqual(f['facility_type'], 'river')
        self.assertNotIn('has_road_excavation', f)
        f = lr_flags.derive_flags('도로 포장', '토목공사', 1, 1, '아스팔트 포장', [])
        self.assertNotIn('has_road_excavation', f)                                      # 굴착·매설 말이 없으면 만들지 않는다
        self.assertNotIn('facility_type', lr_flags.derive_flags('x', '토목공사', 1, 1, '도로와 하천 정비', []))   # 도로와 하천이 함께면 정하지 않는다
        f = lr_flags.derive_flags('x', '건축공사', 1, 1, '도서관', [])
        self.assertNotIn('facility_type', f)


class RuleActivationTests(unittest.TestCase):
    def test_namhae_rules_fire_from_known_inputs_only(self):
        f = lr_flags.derive_flags('남해읍 도로', '토목공사', 50, 2000, '도로 개설', NAMHAE)
        got = ids(dict(f, is_public=True))
        self.assertIn('MID_TERM_LOCAL_FINANCIAL_PLAN', got)        # total_project_cost >= 20억
        self.assertIn('INVESTMENT_REVIEW', got)                    # 군 지역 + 20억 이상
        small = ids(dict(lr_flags.derive_flags('남해읍 도로', '토목공사', 5, 100, '도로 개설', NAMHAE), is_public=True))
        self.assertNotIn('MID_TERM_LOCAL_FINANCIAL_PLAN', small)   # 5억은 기준 미만

    def test_new_rules_and_their_triggers(self):
        base = {'is_public': True}
        self.assertIn('LAND_OBSTRUCTION_COMPENSATION', ids(dict(base, has_parcels=True)))
        self.assertNotIn('LAND_OBSTRUCTION_COMPENSATION', ids(base))
        self.assertIn('ROAD_EXCAVATION_PLAN', ids(dict(base, has_road_excavation=True)))
        self.assertNotIn('ROAD_EXCAVATION_PLAN', ids(base))
        got = ids(base)
        self.assertTrue({'CONTRACT_SUPERVISION', 'DEFECT_WARRANTY_INSPECTION'} <= got)
        self.assertNotIn('CONTRACT_SUPERVISION', ids({}))          # 공공사업이라는 것도 모르면 붙이지 않는다

    def test_new_rules_are_well_formed(self):
        kb = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'law_knowledge_base.json'), encoding='utf-8'))
        by = {r['id']: r for r in kb}
        for rid in ('LAND_OBSTRUCTION_COMPENSATION', 'ROAD_EXCAVATION_PLAN', 'CONTRACT_SUPERVISION', 'DEFECT_WARRANTY_INSPECTION'):
            r = by[rid]
            self.assertTrue(r['name'] and r['law_link'] and r['desc'], rid)
            self.assertIn(r['phase'], ('planning', 'design', 'construction', 'completion', 'maintenance'))
        self.assertEqual(len(by), len(kb))                         # id 중복 없음
        self.assertEqual(by['DEFECT_WARRANTY_INSPECTION']['phase'], 'maintenance')


if __name__ == '__main__':
    unittest.main(verbosity=2)
