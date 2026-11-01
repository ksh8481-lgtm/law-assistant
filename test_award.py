"""
적격심사 계산 엔진(award_engine.py)과 API 시험. `python test_award.py`로 실행한다. 네트워크가 필요 없다.

기대값은 「지방자치단체 입찰시 낙찰자 결정기준」 제2장의2 [별표 1]의 산식과 같은 문서의 예시(주1) 나)의 (예시1)·(예시2))에서 가져왔다.
규정이 개정되면 award_specs의 값을 고치고 이 시험의 기대값도 문서에 맞춰 함께 고친다.
"""
import unittest

import award_engine as ae

SPEC = 'jibang_jeokgyeok_tech'


def bidder(name='A', pq=90, price=88, **kw):
    """예정가격 100(원)을 기준으로 한 입찰사. price는 예정가격 대비 %."""
    b = {'name': name, 'pq_score': pq, 'bid_price': price, 'career_ratio': 30, 'local_ratio': 30, 'mgmt_mode': 'full'}
    b.update(kw)
    return b


def project(est=2_000_000_000, sched=100, **kw):
    p = {'estimated_price': est, 'planned_price': sched}
    p.update(kw)
    return p


class SpecTests(unittest.TestCase):
    def test_every_band_weights_sum_to_100_and_pass_scores(self):
        spec = ae.load_spec(SPEC)
        for band in spec['bands']:
            self.assertEqual(sum(band['weights'].values()), 100, band['id'])
        ge10, ge5, lt5 = spec['bands']
        self.assertEqual((ge10['pass_score'], ge5['pass_score'], lt5['pass_score']), (92, 95, 95))
        self.assertEqual((ge10['weights']['pq'], ge5['weights']['pq'], lt5['weights']['pq']), (64, 44, 34))

    def test_band_boundaries(self):
        spec = ae.load_spec(SPEC)
        from decimal import Decimal as D
        self.assertEqual(ae.pick_band(spec, D(1_000_000_000))['id'], 'ge_10')      # 10억원 이상
        self.assertEqual(ae.pick_band(spec, D(999_999_999))['id'], 'ge_5')         # 10억원 미만
        self.assertEqual(ae.pick_band(spec, D(500_000_000))['id'], 'ge_5')         # 5억원 이상
        self.assertEqual(ae.pick_band(spec, D(499_999_999))['id'], 'lt_5')


class PriceScoreTests(unittest.TestCase):
    def score(self, est, pct):
        """예정가격 대비 pct(%)로 입찰했을 때의 입찰가격 평점."""
        r = ae.evaluate(SPEC, project(est=est), [bidder(price=pct)])['results'][0]
        return r['scores']['price']

    def test_10eok_or_more(self):
        e = 2_000_000_000
        self.assertEqual(self.score(e, 88), 30)           # 88%가 정점
        self.assertEqual(self.score(e, 90), 28)           # 30 - 2
        self.assertEqual(self.score(e, 87), 29)           # 정점 아래쪽도 절대값
        self.assertEqual(self.score(e, 96), 22)           # 96% 이상 22점 고정
        self.assertEqual(self.score(e, 99.5), 22)
        self.assertEqual(self.score(e, 100), 22)
        self.assertEqual(self.score(e, 50), 2)            # 최저평점 2점

    def test_5_to_10eok(self):
        e = 700_000_000
        self.assertEqual(self.score(e, 88), 50)
        self.assertEqual(self.score(e, 90), 46)           # 50 - 2×2
        self.assertEqual(self.score(e, 90.5), 45)         # 90.5% 이상 45점 고정
        self.assertEqual(self.score(e, 95), 45)
        self.assertEqual(self.score(e, 60), 2)            # 50 - 2×28 < 2 -> 2점

    def test_under_5eok(self):
        e = 300_000_000
        self.assertEqual(self.score(e, 88), 60)
        self.assertEqual(self.score(e, 89), 56)           # 60 - 4×1
        self.assertEqual(self.score(e, 89.25), 55)        # 89.25% 이상 55점 고정
        self.assertEqual(self.score(e, 100), 55)

    def test_ratio_is_rounded_to_4_digits_but_cap_uses_raw_value(self):
        # 비율 0.95996(예정가격 96% 미만): 4자리 반올림하면 0.9600이라 공식으로 30-8=22점이 되고 고정값 22점과 같다.
        r = ae.evaluate(SPEC, project(sched=100000), [bidder(price=95996)])['results'][0]
        self.assertEqual(r['scores']['price'], 22)
        # 비율 0.88004 -> 반올림 0.8800 -> 정점 30점
        r = ae.evaluate(SPEC, project(sched=100000), [bidder(price=88004)])['results'][0]
        self.assertEqual(r['scores']['price'], 30)

    def test_over_planned_price_is_excluded(self):
        res = ae.evaluate(SPEC, project(), [bidder('초과', price=100.5), bidder('정상', price=88)])
        over = res['results'][0]
        self.assertEqual((over['status'], over['over_planned']), ('over', True))
        self.assertIsNone(over['review_order'])
        self.assertEqual(res['winner_index'], 1)


class PqConversionTests(unittest.TestCase):
    def pq_score(self, pq, ded=0, est=2_000_000_000, **pkw):
        b = bidder(pq=pq, price=88)
        if ded:
            b['penalty_deduction'] = ded
        return ae.evaluate(SPEC, project(est=est, **pkw), [b])['results'][0]['scores']['pq']

    def test_plain_conversion(self):
        self.assertEqual(self.pq_score(90), 57.6)                       # 90 × 64/100
        self.assertEqual(self.pq_score(90, est=700_000_000), 39.6)      # 90 × 44/100
        self.assertEqual(self.pq_score(90, est=300_000_000), 30.6)      # 90 × 34/100

    def test_rule_example_1_penalty_is_not_converted(self):
        # 문서 [별표 1] 주1) 나) (예시1): 평가점수 94.5점(벌점 감점 0.5점 반영) -> 95 × 64/100 = 60.8, 60.8 - 0.5 = 60.3
        self.assertEqual(self.pq_score(94.5, ded=0.5), 60.3)

    def test_rule_example_2_pre_deduction_score_is_capped_at_100(self):
        # (예시2): 평가점수 100점 -> 100 × 64/100 = 64, 64 - 0.5 = 63.5
        self.assertEqual(self.pq_score(100, ded=0.5), 63.5)

    def test_over_100_is_capped(self):
        self.assertEqual(self.pq_score(103), 64)

    def test_local_not_applied_adds_its_points_to_pq(self):
        # 지역업체 참여도를 적용하지 않으면 3점을 PQ 환산 배점에 합산: 67/100
        res = ae.evaluate(SPEC, project(local_applied=False), [bidder(pq=90)])
        r = res['results'][0]
        self.assertEqual(r['scores']['pq'], 60.3)                       # 90 × 67/100
        self.assertEqual(r['scores']['local'], 0)
        self.assertEqual(res['weights']['pq'], 67)
        self.assertTrue(any('합산' in n for n in res['notes']))


class OtherScoreTests(unittest.TestCase):
    def one(self, **kw):
        return ae.evaluate(SPEC, project(), [bidder(**kw)])['results'][0]

    def test_career_tiers(self):
        self.assertEqual(self.one(career_ratio=30)['scores']['career'], 1)
        self.assertEqual(self.one(career_ratio=29.99)['scores']['career'], 0.5)
        self.assertEqual(self.one(career_ratio=20)['scores']['career'], 0.5)
        self.assertEqual(self.one(career_ratio=19.99)['scores']['career'], 0)

    def test_career_excluded_gives_full_points(self):
        res = ae.evaluate(SPEC, project(career_excluded=True), [bidder(career_ratio=None)])
        self.assertEqual(res['results'][0]['scores']['career'], 1)

    def test_local_tiers_main_and_other(self):
        self.assertEqual(self.one(local_ratio=30)['scores']['local'], 3)
        self.assertEqual(self.one(local_ratio=25)['scores']['local'], 1)
        self.assertEqual(self.one(local_ratio=19.9)['scores']['local'], 0)
        r = ae.evaluate(SPEC, project(local_kind='other'), [bidder(local_ratio=20)])['results'][0]
        self.assertEqual(r['scores']['local'], 3)                       # 다른 법령 용역은 20% 이상 3점
        r = ae.evaluate(SPEC, project(local_kind='other'), [bidder(local_ratio=10)])['results'][0]
        self.assertEqual(r['scores']['local'], 1)

    def test_local_solo_is_zero(self):
        self.assertEqual(self.one(local_ratio=100, local_solo=True)['scores']['local'], 0)

    def test_mgmt_modes(self):
        self.assertEqual(self.one()['scores']['mgmt'], 2)
        self.assertEqual(self.one(mgmt_mode='credit', mgmt_tier='t18')['scores']['mgmt'], 1.8)
        self.assertEqual(self.one(mgmt_mode='credit', mgmt_tier='t10')['scores']['mgmt'], 1.0)
        self.assertEqual(self.one(mgmt_mode='score', mgmt_score=1.55)['scores']['mgmt'], 1.55)
        with self.assertRaises(ae.AwardInputError):
            self.one(mgmt_mode='score', mgmt_score=2.5)                 # 배점 2점 초과
        with self.assertRaises(ae.AwardInputError):
            self.one(mgmt_mode='credit', mgmt_tier='없는구간')

    def test_deductions(self):
        self.assertEqual(self.one(tech_shortage=True)['scores']['deduction'], -10)
        self.assertEqual(self.one(wage_arrears_count=2)['scores']['deduction'], -0.4)
        self.assertEqual(self.one(wage_arrears_count=9)['scores']['deduction'], -1.0)   # 한도 -1.0
        self.assertEqual(self.one(tech_shortage=True, wage_arrears_count=1)['scores']['deduction'], -10.2)


class DecisionTests(unittest.TestCase):
    """종합평점 = PQ 환산 + 경력 1 + 지역 3 + 경영 2 + 입찰가격. 88% 입찰이면 가격 30점이라 합계 = PQ×0.64 + 36."""

    def test_pass_boundary_is_exact(self):
        # PQ 87.5 -> 56 + 36 = 92.0 : 통과점수와 같으면 통과
        r = ae.evaluate(SPEC, project(), [bidder(pq=87.5)])['results'][0]
        self.assertEqual((r['total'], r['pass'], r['status']), (92.0, True, 'winner'))
        # PQ 87.49 -> 55.9936 + 36 = 91.9936 : 반올림으로 92가 되어 통과하면 안 된다
        r = ae.evaluate(SPEC, project(), [bidder(pq=87.49)])['results'][0]
        self.assertEqual((r['total'], r['pass'], r['status']), (91.9936, False, 'fail'))
        self.assertEqual(r['shortfall'], 0.0064)

    def test_under_10eok_needs_95(self):
        # 5~10억 구간: PQ 환산 44 + 1 + 3 + 2 + 가격 50(88%) = PQ×0.44 + 56. PQ 88.6 -> 38.984 + 56 = 94.984 미달
        r = ae.evaluate(SPEC, project(est=700_000_000), [bidder(pq=88.6)])['results'][0]
        self.assertFalse(r['pass'])
        r = ae.evaluate(SPEC, project(est=700_000_000), [bidder(pq=89)])['results'][0]     # 39.16 + 56 = 95.16
        self.assertTrue(r['pass'])

    def test_lowest_price_first_and_first_passing_wins(self):
        res = ae.evaluate(SPEC, project(), [
            bidder('가', pq=70, price=86),        # 최저가지만 점수 미달
            bidder('나', pq=95, price=88),        # 두 번째로 낮은 가격, 통과 -> 낙찰자
            bidder('다', pq=99, price=90),        # 점수는 더 높아도 낙찰자 결정 이후라 심사하지 않음
        ])
        st = [r['status'] for r in res['results']]
        self.assertEqual(st, ['fail', 'winner', 'after'])
        self.assertEqual(res['winner_index'], 1)
        self.assertEqual([r['review_order'] for r in res['results']], [1, 2, 3])
        self.assertTrue(res['results'][2]['pass'])           # 점수 자체는 통과 수준이어도 순서 때문에 낙찰자가 아니다

    def test_same_lowest_price_higher_pq_wins(self):
        res = ae.evaluate(SPEC, project(), [bidder('가', pq=93, price=88), bidder('나', pq=97, price=88)])
        self.assertEqual([r['status'] for r in res['results']], ['pass', 'winner'])
        self.assertEqual(res['winner_index'], 1)

    def test_same_lowest_price_same_pq_needs_lottery(self):
        res = ae.evaluate(SPEC, project(), [bidder('가', pq=95, price=88), bidder('나', pq=95, price=88)])
        self.assertEqual([r['status'] for r in res['results']], ['lottery', 'lottery'])
        self.assertIsNone(res['winner_index'])
        self.assertEqual(res['lottery_indexes'], [0, 1])
        self.assertTrue(any('추첨' in n for n in res['notes']))

    def test_tied_price_only_passing_bidders_compete(self):
        res = ae.evaluate(SPEC, project(), [bidder('미달', pq=60, price=88), bidder('통과', pq=90, price=88)])
        self.assertEqual([r['status'] for r in res['results']], ['fail', 'winner'])

    def test_nobody_passes(self):
        res = ae.evaluate(SPEC, project(), [bidder('가', pq=60, price=88), bidder('나', pq=70, price=90)])
        self.assertIsNone(res['winner_index'])
        self.assertTrue(any('재공고' in n for n in res['notes']))
        self.assertEqual([r['status'] for r in res['results']], ['fail', 'fail'])

    def test_basis_explains_every_part(self):
        r = ae.evaluate(SPEC, project(), [bidder(pq=94.5, penalty_deduction=0.5, wage_arrears_count=1)])['results'][0]
        text = ' / '.join(r['basis'])
        for needle in ('PQ 환산', '95', '60.3', '책임기술자 경력', '지역업체 참여도', '경영상태', '입찰가격', '임금체불'):
            self.assertIn(needle, text, needle)

    def test_response_carries_band_and_references(self):
        res = ae.evaluate(SPEC, project(est=700_000_000), [bidder(pq=90)])
        self.assertEqual(res['band']['id'], 'ge_5')
        self.assertEqual(res['band']['pass_score'], 95)
        self.assertIn('별표 1', res['band']['ref'])
        self.assertEqual(res['source']['law_id'], '2100000281396')
        self.assertEqual(res['weights'], {'pq': 44, 'career': 1, 'local': 3, 'mgmt': 2, 'price': 50})


class InputValidationTests(unittest.TestCase):
    def bad(self, proj, bidders, needle):
        with self.assertRaises(ae.AwardInputError) as cm:
            ae.evaluate(SPEC, proj, bidders)
        self.assertIn(needle, str(cm.exception))

    def test_messages(self):
        self.bad({}, [bidder()], '추정가격')
        self.bad(project(sched=''), [bidder()], '예정가격')
        self.bad(project(), [], '입찰사를 1개 이상')
        self.bad(project(), [bidder(pq='')], 'PQ 점수')
        self.bad(project(), [bidder(pq='abc')], '숫자')
        self.bad(project(), [bidder(pq=-1)], '이상')
        self.bad(project(), [bidder(price=0)], '입찰가격')
        self.bad(project(), [bidder(career_ratio=120)], '이하')
        self.bad(project(), [bidder()] * 41, '최대 40')
        self.bad(project(local_kind='x'), [bidder()], '구분')

    def test_comma_numbers_are_accepted(self):
        res = ae.evaluate(SPEC, project(est='2,000,000,000', sched='1,000,000,000'), [bidder(price='880,000,000')])
        self.assertEqual(res['results'][0]['scores']['price'], 30)

    def test_empty_name_gets_default(self):
        res = ae.evaluate(SPEC, project(), [bidder(name='  ')])
        self.assertEqual(res['results'][0]['name'], '입찰사 1')


class RequiredPriceTests(unittest.TestCase):
    """award_reverse: 용역비와 PQ 점수로 '얼마에 입찰해야 통과하나'를 거꾸로 구한다. 결과는 evaluate()(정방향)와 어긋나면 안 된다."""

    def setUp(self):
        import award_reverse
        self.rev = award_reverse
        self.sched = 1_000_000_000

    def run_one(self, pq=90, est=2_000_000_000, sched='default', **kw):
        sched = self.sched if sched == 'default' else sched
        proj = {'estimated_price': est}
        if sched is not None:
            proj['planned_price'] = sched
        return self.rev.required_price(SPEC, proj, [dict({'name': 'A', 'pq_score': pq}, **kw)])

    def forward(self, price, pq=90, est=2_000_000_000, **kw):
        b = {'name': 'A', 'pq_score': pq, 'bid_price': price, 'career_ratio': 35, 'local_ratio': 30, 'mgmt_mode': 'full'}
        b.update(kw)
        return ae.evaluate(SPEC, {'estimated_price': est, 'planned_price': self.sched}, [b])['results'][0]

    def test_hand_calculated_range(self):
        # PQ 90: 57.6 + 경력 1 + 지역 3 + 경영 2 = 63.6 -> 92 - 63.6 = 28.4점의 가격 평점이 필요.
        # 30 - |0.88 - r|×100 >= 28.4  ->  86.4% <= r <= 89.6%  (r은 소수점 다섯째 자리 반올림)
        r = self.run_one()['results'][0]
        self.assertTrue(r['possible'])
        self.assertEqual((r['subtotal'], r['need_price_score'], r['price_score_max']), (63.6, 28.4, 30.0))
        # 86.395%부터 반올림하면 86.40%가 되어 통과, 89.605% 미만까지 89.60%로 반올림되어 통과
        self.assertEqual((r['min_price'], r['max_price']), (863_950_000, 896_049_999))
        self.assertAlmostEqual(r['min_ratio_pct'], 86.395, places=6)

    def test_boundaries_agree_with_the_forward_engine_to_the_won(self):
        r = self.run_one()['results'][0]
        self.assertTrue(self.forward(r['min_price'])['pass'])
        self.assertFalse(self.forward(r['min_price'] - 1)['pass'])
        self.assertTrue(self.forward(r['max_price'])['pass'])
        self.assertFalse(self.forward(r['max_price'] + 1)['pass'])

    def test_impossible_even_at_the_best_price_reports_needed_pq(self):
        r = self.run_one(pq=60)['results'][0]
        self.assertFalse(r['possible'])
        self.assertEqual(r['pq_needed'], 87.5)                       # 87.5 × 0.64 + 36 = 92 (가격 88% 만점일 때)
        self.assertFalse(self.forward(int(self.sched * 0.88), pq=60)['pass'])
        self.assertTrue(self.forward(int(self.sched * 0.88), pq=87.5)['pass'])
        self.assertFalse(self.forward(int(self.sched * 0.88), pq=87.49)['pass'])

    def test_high_pq_passes_up_to_the_planned_price(self):
        r = self.run_one(pq=100)['results'][0]                      # 70점 + 가격 22점(예정가격 96%~ 고정) = 92
        self.assertEqual(r['max_price'], self.sched)
        self.assertEqual(r['max_ratio_pct'], 100.0)
        self.assertEqual(r['min_price'], 799_950_000)
        self.assertTrue(self.forward(self.sched, pq=100)['pass'])
        self.assertFalse(self.forward(r['min_price'] - 1, pq=100)['pass'])

    def test_blank_career_and_local_are_assumed_full_and_say_so(self):
        r = self.run_one()['results'][0]
        self.assertEqual(len(r['assumptions']), 2)
        self.assertTrue(any('경력' in a for a in r['assumptions']) and any('지역업체' in a for a in r['assumptions']))
        r2 = self.run_one(career_ratio=25, local_ratio=15)['results'][0]       # 0.5 + 0 -> 60.1점, 필요 31.9점 > 30
        self.assertEqual(r2['assumptions'], [])
        self.assertFalse(r2['possible'])
        self.assertEqual(r2['pq_needed'], 92.97)

    def test_other_bands(self):
        # 5~10억: PQ 환산 44, 가격 50(계수 2), 통과 95점. PQ 90 -> 39.6 + 6 = 45.6 -> 가격 49.4점 이상 필요.
        # 50 - 2×|0.88 - r|×100 >= 49.4 -> 87.7% <= r <= 88.3%
        res = self.run_one(est=700_000_000)
        r = res['results'][0]
        self.assertEqual((r['need_price_score'], r['possible']), (49.4, True))
        self.assertAlmostEqual(r['min_ratio_pct'], 87.695, places=6)        # 반올림 경계
        self.assertEqual(res['band']['pass_score'], 95)

    def test_without_planned_price_only_ratios(self):
        res = self.run_one(sched=None)
        r = res['results'][0]
        self.assertIsNone(r['min_price'])
        self.assertAlmostEqual(r['min_ratio_pct'], 86.395, places=6)
        self.assertAlmostEqual(r['max_ratio_pct'], 89.604, places=6)
        self.assertTrue(any('예정가격을 입력하지 않아' in n for n in res['notes']))

    def test_ladder_matches_pass_flags(self):
        r = self.run_one()['results'][0]
        by = {x['ratio_pct']: x for x in r['ladder']}
        self.assertTrue(by[88]['pass'] and by[88]['total'] == 93.6)
        self.assertTrue(by[87]['pass'] and by[90]['pass'] is False and by[86]['pass'] is False)
        self.assertEqual(len(r['ladder']), 31)

    def test_deduction_and_local_not_applied(self):
        r = self.run_one(tech_shortage=True)['results'][0]                  # -10점이면 가격을 최고로 써도 부족
        self.assertFalse(r['possible'])
        res = self.rev.required_price(
            SPEC, {'estimated_price': 2_000_000_000, 'planned_price': self.sched, 'local_applied': False}, [{'name': 'A', 'pq_score': 90}])
        r = res['results'][0]
        self.assertEqual(r['parts']['pq'], 60.3)                           # 90 × 67/100
        self.assertEqual(r['parts']['local'], 0)

    def test_input_errors(self):
        with self.assertRaises(ae.AwardInputError):
            self.rev.required_price(SPEC, {}, [{'name': 'A', 'pq_score': 90}])                  # 용역비 없음
        with self.assertRaises(ae.AwardInputError):
            self.rev.required_price(SPEC, {'estimated_price': 1e9}, [])
        with self.assertRaises(ae.AwardInputError):
            self.rev.required_price(SPEC, {'estimated_price': 1e9}, [{'name': 'A'}])            # PQ 점수 없음

    def test_api(self):
        import app as appmod
        http = appmod.app.test_client()
        body = {'spec_id': SPEC, 'project': {'estimated_price': '2,000,000,000', 'planned_price': '1,000,000,000'},
                'bidders': [{'name': 'A', 'pq_score': 90}]}
        d = http.post('/api/award/required_price', json=body).get_json()
        self.assertTrue(d['success'])
        self.assertEqual(d['result']['results'][0]['min_price'], 863_950_000)
        r = http.post('/api/award/required_price', json={**body, 'bidders': []})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(http.post('/api/award/required_price', json={**body, 'spec_id': 'nope'}).status_code, 404)


# 실제 예규 PDF 텍스트의 줄 모양(쪽 머리, 줄 바꿈이 숫자·낱말 사이를 가르는 것)을 그대로 흉내 낸 조각. 숫자만 바꿔 끼운다.
def _fixture(**over):
    v = dict(p10=92, p5=95, w1=64, w2=44, w3=34, t1=30, t2=50, t3=60, k2=2, k3=4, c1=96, c2=90.5, c3=89.25, s1=22, s2=45, s3=55,
             cr30=1, cr20=0.5, lm30=3, lm20=1, lo20=3, lo10=1, ts=10, wp=0.2, wc=1.0)
    v.update(over)
    return """
=====PAGE 29=====
■ 지방자치단체 입찰시 낙찰자 결정기준 제2장의1 시설공사 적격심사 세부기준 [별표 1]
 * 평점 =
평가점수
× 99점
100
=====PAGE 152=====
- 150 -
  제5절 낙찰자 결정
1. 계약담당자는 예정가격 이하로서 최저가 입찰자부터 순서대로 심사한 결과 기
술용역은 종합평점이 추정가격 10억원 이상인 용역은 {p10}점(이하 “적격통과점
수”라 한다) 이상, 추정가격이 10억 원 미만인 용역은 {p5}점 이상인 자, 학술연
구용역의 경우 85점 이상인 자를 낙찰자로 결정한다.
=====PAGE 153=====
- 151 -
■ 지방자치단체 입찰시 낙찰자 결정기준 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표 1]
기술 관련법령에 따라 사업수행능력평가(P.Q)를 하는 기술용역 평가기준
  * 평점 =
평가점수
× {w1}점
100
64
 A. 전체 경력기간 합산 대비 사업책임 및 분야별 책임기술자경력 합
산 비율 30% 이상 : {cr30}점
 B. 전체 경력기간 합산 대비 사업책임 및 분야별 책임기술자경력 합
산 비율 30% 미만 20% 이상 : {cr20}점
  A. 지역업체 합산비율 30%이상          : {lm30}점
  B. 지역업체 합산비율 30%미만 20%이상 : {lm20}점
  A. 다른법령에따른 지역업체합산비율 20%이상         : {lo20}점
  B. 다른법령에따른 지역업체합산비율 20%미만10%이상: {lo10}점
○고용노동부 장관이 임금체불로 명단을 공개한 횟수당 △{wp}
△{wc} ※주6)
=====PAGE 154=====
기술자보유현황이 업종등록기준상 미달하는 자 △{ts} ※주5)
  주4) 입찰가격 평가 (30점)
      ① 평점 = {t1} -
( 88
-
입찰가격) × 100
100
예정가격
      ※ 추정가격이 10억 원 이상인 용역은 입찰가격이 예정가격 이하로서 예정가격의 100분의 {c1}이상인 경우의 평점은 {s1}점으로 한다.
=====PAGE 158=====
2. 추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준
  * 평점 =
평가점수
× {w2}점
100
44
 * 평점 = {t2} - {k2} ×
(
88
-
입찰가격) × 100
100
예정가격
  * 입찰가격이 예정가격 이하로서 100분의 {c2} 이상인 경우의 평점은 {s2}점으로 한다.
=====PAGE 159=====
3. 추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준
 *평점 =
평가점수×{w3}점
100
34
 * 평점 = {t3} - {k3} × ( 88
- 입찰가격) × 100
100
예정가격
  * 입찰가격이 예정가격 이하로서 100분의 {c3} 이상인 경우의 평점은 {s3}점으로 한다.
=====PAGE 161=====
■ 지방자치단체 입찰시 낙찰자 결정기준 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표 2]
사업수행능력 평가(P.Q)를 하지 않는 기술용역 평가기준
 * 평점 =
평가점수
× 77점
100
""".format(**v)


class AwardCheckTests(unittest.TestCase):
    """award_check: 명세의 숫자가 예규 원문과 같은지 대조하는 장치. 원문 문장 모양이 바뀌면 조용히 통과하지 않고 '확인 못 함'으로 알려야 한다."""

    def setUp(self):
        import award_check as ac
        self.ac = ac
        self.spec = ae.load_spec(SPEC)

    def test_identical_values_are_all_ok(self):
        rows = self.ac.compare(self.spec, _fixture())
        s = self.ac.summarize(rows)
        self.assertTrue(s['clean'], [r for r in rows if r['status'] != 'ok'])
        self.assertEqual(s['ok'], len(self.ac.LABELS))

    def test_changed_pass_score_and_weight_are_reported_as_diff(self):
        rows = self.ac.compare(self.spec, _fixture(p10=90, w2=46, c2=91))
        diff = {r['key']: (r['expected'], r['found']) for r in rows if r['status'] == 'diff'}
        self.assertEqual(diff, {'pass_ge_10': (92, 90), 'pq_ge_5': (44, 46), 'cap_from_ge_5': (90.5, 91)})
        lines = self.ac.report_lines(self.ac.summarize(rows))
        self.assertTrue(any('명세 92 → 원문 90' in l for l in lines))

    def test_other_chapters_do_not_leak_into_the_slice(self):
        # 시설공사 별표 1의 '99점'이나 [별표 2]의 '77점'을 PQ 환산 배점으로 읽으면 안 된다
        found = self.ac.extract(_fixture())
        self.assertEqual((found['pq_ge_10'], found['pq_ge_5'], found['pq_lt_5']), (64, 44, 34))

    def test_missing_sentence_is_unparsed_not_ok(self):
        text = _fixture().replace('구용역의 경우 85점', '구용역에 한해 85점')          # 적격통과점수 문장 모양이 바뀐 경우
        s = self.ac.summarize(self.ac.compare(self.spec, text))
        self.assertFalse(s['clean'])
        self.assertEqual({r['key'] for r in s['unparsed']}, {'pass_ge_10', 'pass_lt_10'})

    def test_missing_heading_makes_every_table_value_unparsed(self):
        text = _fixture().replace('제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표 1]', '제2장의2 어떤 새 이름 [별표 1]')
        s = self.ac.summarize(self.ac.compare(self.spec, text))
        self.assertGreater(len(s['unparsed']), 20)
        self.assertFalse(s['clean'])

    def test_expected_comes_from_spec(self):
        want = self.ac.expected(self.spec)
        self.assertEqual((want['pass_ge_10'], want['pq_lt_5'], want['cap_from_ge_5'], want['wage_cap']), (92, 34, 90.5, 1))


@unittest.skipIf(__import__('os').environ.get('SKIP_ONLINE_TESTS'), 'SKIP_ONLINE_TESTS')
class AwardCheckOnlineTests(unittest.TestCase):
    def test_current_official_text_matches_spec(self):
        """법제처의 현행 예규 PDF(약 5MB, 486쪽)를 받아 명세와 대조한다. 예규가 개정돼 숫자가 바뀌면 여기서 실패한다(의도된 알림)."""
        import award_check as ac
        try:
            summary = ac.verify_online(SPEC)
        except Exception as e:
            self.skipTest(f'법제처에서 예규 PDF를 받지 못함: {e}')
        self.assertTrue(summary['clean'], ac.report_lines(summary))


class ApiTests(unittest.TestCase):
    def setUp(self):
        import app as appmod
        self.http = appmod.app.test_client()

    def test_spec_endpoint(self):
        d = self.http.get('/api/award/spec/' + SPEC).get_json()
        self.assertTrue(d['success'])
        self.assertEqual(len(d['spec']['bands']), 3)
        self.assertEqual(self.http.get('/api/award/spec/nope').status_code, 404)

    def test_evaluate_endpoint_ok_and_errors(self):
        body = {'spec_id': SPEC, 'project': project(), 'bidders': [bidder(pq=87.5)]}
        d = self.http.post('/api/award/evaluate', json=body).get_json()
        self.assertTrue(d['success'])
        self.assertEqual(d['result']['winner_index'], 0)
        r = self.http.post('/api/award/evaluate', json={**body, 'bidders': []})
        self.assertEqual(r.status_code, 400)
        self.assertIn('입찰사', r.get_json()['message'])
        r = self.http.post('/api/award/evaluate', json={**body, 'spec_id': 'nope'})
        self.assertEqual(r.status_code, 404)

    def test_award_is_a_step_of_the_pq_page_not_a_separate_page(self):
        html = self.http.get('/pq_score').get_data(as_text=True)
        for needle in ('id="awardCard"', 'id="awardBody"', 'award_panel.js', 'pq_score.js'):
            self.assertIn(needle, html, needle)
        self.assertNotIn('id="awardCard" style="display:none', html)                  # 처음부터 보여야 한다(PQ 계산 뒤에야 나타나면 못 찾는다)
        self.assertIn("6단계", html)
        self.assertIn("얼마에 입찰해야", html)                                          # 6단계는 '통과 기준(필요한 입찰가격)'을 알려 주는 화면이다
        self.assertLess(html.index('award_panel.js'), html.index('pq_score.js'))      # pq_score.js가 AwardPanel을 부르므로 먼저 읽혀야 한다
        r = self.http.get('/award')                                                   # 예전 주소는 PQ 화면으로 안내
        self.assertEqual((r.status_code, r.headers['Location'].endswith('/pq_score#award')), (302, True))
        home = self.http.get('/').get_data(as_text=True)
        self.assertNotIn('href="/award"', home)                                       # 홈에 별도 카드는 없다

    def test_pq_script_hands_results_to_the_award_step(self):
        js = open('static/pq_score.js', encoding='utf-8').read()
        self.assertIn('AwardPanel.onPqResult', js)
        self.assertNotIn('sendToAward', js)                                           # 예전 '보내기' 버튼 방식은 없다
        panel = open('static/award_panel.js', encoding='utf-8').read()
        self.assertIn('window.AwardPanel', panel)
        self.assertIn('/api/award/required_price', panel)                             # 거꾸로 계산(필요한 입찰가격)을 먼저 보여 준다


if __name__ == '__main__':
    unittest.main(verbosity=2)
