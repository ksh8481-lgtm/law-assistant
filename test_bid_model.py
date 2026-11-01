"""
낙찰가 예측(bid_rules·bid_model·bid_sampling·bid_service)과 API 시험. `python test_bid_model.py`로 실행한다. 네트워크가 필요 없다(조달청 API는 가짜로 대체).

핵심으로 확인하는 것:
- 낙찰하한이 예규(별표 1~7)의 식과 통과점수에서 정확히 나오는가: 89.745 / 88.745 / 87.495 / 81.995 %, 가격 외 점수가 모자라면 올라가는가
- 사례 계산: 낙찰자 비율 (낙찰금액-A)/(예정가격-A), 사정률(예정가격÷기초금액)
- 낙찰 조건에 낙찰하한이 들어가는가(하한 아래로 쓰면 이기지 못함 - 예전 백테스트는 낮게 쓸수록 이겼다), 결과 세 갈래 합이 1인가
- 목표 확률별로 "그 확률 이상인 가장 높은 가격"을 고르는가, 도달할 수 없는 목표는 도달 불가로 나오는가
- 기초금액·A값 표본 조회: 캐시, 기초금액 없음/일시 오류 구분, 최근순
"""
import unittest

import bid_model as bm
import bid_rules
import bid_sampling as bs

BASE = 100_000_000


def make_item(i, base=BASE, a_frac=0.05, sajung=100.0, r_w=0.9, n=50, date=None):
    """낙찰 목록 한 건. 낙찰금액 = A + r_w × (예정가격 - A), 낙찰률 = 낙찰금액 ÷ 예정가격."""
    plan = base * sajung / 100.0
    a = base * a_frac
    amt = a + r_w * (plan - a)
    return {'bidNtceNo': f'N{i:03d}', 'bidNtceOrd': '000', 'sucsfbidRate': str(round(amt / plan * 100.0, 6)), 'sucsfbidAmt': str(round(amt)),
            'prtcptCnum': str(n), 'rlOpengDt': date or f'2026-10-{(i % 28) + 1:02d} 10:00:00', 'bidNtceNm': f'공사{i}', 'dminsttNm': '시험군'}


def case(sajung, r_w, base=BASE, a_frac=0.05, n=50):
    """분석 사례 한 건(build_cases가 만드는 모양)."""
    plan = base * sajung / 100.0
    a = base * a_frac
    amt = a + r_w * (plan - a)
    est = bid_rules.estimated_from_base(base)
    return {'no': 'x', 'amt': amt, 'rate': amt / plan * 100.0, 'base': base, 'a': a, 'plan': plan, 'sajung': sajung, 'r_w': r_w,
            'w': amt / base * 100.0, 'n': n, 'date': '', 'band': bid_rules.band_for(est)['id'], 'est': est}


class RulesTests(unittest.TestCase):
    def test_legal_floor_by_band(self):
        got = {b['id']: float(bid_rules.min_ratio(b)) * 100 for b in bid_rules.spec()['bands']}
        self.assertAlmostEqual(got['b7'], 89.745, places=3)                       # 2억 미만
        self.assertAlmostEqual(got['b6'], 89.745, places=3)                       # 2~4억
        self.assertAlmostEqual(got['b5'], 89.745, places=3)                       # 4~10억
        self.assertAlmostEqual(got['b4'], 88.745, places=3)                       # 10~30억
        self.assertAlmostEqual(got['b3'], 88.745, places=3)                       # 30~50억
        self.assertAlmostEqual(got['b2'], 87.495, places=3)                       # 50~100억
        self.assertAlmostEqual(got['b1'], 81.995, places=3)                       # 100~300억

    def test_missing_others_score_raises_floor(self):
        b = bid_rules.band_for(100_000_000)
        self.assertAlmostEqual(float(bid_rules.min_ratio(b, 9.5)) * 100, 89.775, places=3)
        self.assertAlmostEqual(float(bid_rules.min_ratio(b, 9.0)) * 100, 89.795, places=3)
        self.assertIsNone(bid_rules.min_ratio(b, 1.0))                            # 가격 외 점수가 너무 낮으면 어떤 가격으로도 통과 못 함

    def test_band_boundaries(self):
        ids = {est: bid_rules.band_for(est)['id'] for est in (1, 199_999_999, 200_000_000, 399_999_999, 400_000_000, 999_999_999,
                                                               1_000_000_000, 4_999_999_999, 5_000_000_000, 9_999_999_999, 10_000_000_000, 29_999_999_999)}
        self.assertEqual([ids[k] for k in sorted(ids)], ['b7', 'b7', 'b6', 'b6', 'b5', 'b5', 'b4', 'b3', 'b2', 'b2', 'b1', 'b1'])
        self.assertIsNone(bid_rules.band_for(30_000_000_000))                      # 300억 이상은 이 규정 밖

    def test_price_score_formula_and_cap(self):
        b = next(x for x in bid_rules.spec()['bands'] if x['id'] == 'b5')
        self.assertEqual(float(bid_rules.price_score(b, '0.9')), 80.0)             # 90%이면 만점
        self.assertAlmostEqual(float(bid_rules.price_score(b, '0.8975')), 80 - 20 * 0.0025 * 100, places=6)
        self.assertEqual(float(bid_rules.price_score(b, '0.5')), 2.0)              # 계산값이 음수여도 최저 2점
        self.assertEqual(float(bid_rules.price_score(b, '0.9025')), 75.0)          # 90.25% 이상(예정가격 이하)은 고정점수 75

    def test_floor_rate_vs_plan_uses_a(self):
        # A가 예정가격의 6%이면 89.745%(A 기준)는 예정가격 대비 90.2%
        self.assertAlmostEqual(bid_rules.floor_rate_vs_plan('0.89745', 0.06), (0.06 + 0.89745 * 0.94) * 100, places=6)

    def test_a_amount_sums_known_fields(self):
        rec = {k: '1000' for k in bid_rules.spec()['a_fields']}
        rec['npnInsrprm'] = ''
        rec['qltyMngcst'] = None
        self.assertEqual(bid_rules.a_amount(rec), 1000.0 * (len(bid_rules.spec()['a_fields']) - 2))


class BuildCasesTests(unittest.TestCase):
    def test_r_w_and_sajung(self):
        it = make_item(1, sajung=99.0, r_w=0.9)
        c = bm.build_cases([it], {('N001', '000'): {'base': float(BASE), 'a': BASE * 0.05}})[0]
        self.assertAlmostEqual(c['sajung'], 99.0, places=3)                     # 예정가격 ÷ 기초금액
        self.assertAlmostEqual(c['r_w'], 0.9, places=4)                          # (낙찰금액-A) ÷ (예정가격-A)
        self.assertEqual((c['n'], c['band']), (50, 'b7'))

    def test_bad_cases_are_dropped(self):
        ok = {'base': float(BASE), 'a': BASE * 0.05}
        items = [make_item(1), make_item(2), make_item(3, r_w=0.5), make_item(4, sajung=120), make_item(5)]
        info = {('N001', '000'): ok, ('N002', '000'): None, ('N003', '000'): ok, ('N004', '000'): ok}      # 5번은 조회 결과 없음
        self.assertEqual([c['no'] for c in bm.build_cases(items, info)], ['N001'])   # 자료 없음·비율 이상·사정률 범위 밖은 제외


class ProbabilityTests(unittest.TestCase):
    R_MIN = 0.9

    def test_win_requires_floor_and_beating_the_winner(self):
        # a_frac=0, 사정률 100 → 하한 f = 90.0 (기초금액 대비 %). 낙찰 w = 90.1, 90.2, 90.5, 91.0
        cases = [case(100, rw / 100, a_frac=0.0) for rw in (90.1, 90.2, 90.5, 91.0)]
        wp = lambda r: bm.win_probability(cases, r, 100.0, self.R_MIN)
        self.assertEqual(wp(0.8999), 0.0)                                       # 하한 아래: 탈락 (낮게 쓸수록 이긴다는 예전 계산과 반대)
        self.assertEqual(wp(0.9), 1.0)                                          # 하한 이상이고 모두의 낙찰가보다 낮음
        self.assertEqual(wp(0.901), 0.75)                                       # 같은 가격은 이기지 못한다(< 만 승리)
        self.assertEqual(wp(0.905), 0.25)
        self.assertEqual(wp(0.91), 0.0)

    def test_outcomes_sum_to_one_and_split_correctly(self):
        cases = [case(100, rw / 100, a_frac=0.0) for rw in (90.1, 90.2, 90.5, 91.0)]
        w, below, lost = bm.outcomes(cases, 0.8999, 100.0, self.R_MIN)
        self.assertEqual((w, below, lost), (0.0, 1.0, 0.0))                     # 전부 하한 아래로 탈락
        w, below, lost = bm.outcomes(cases, 0.9015, 100.0, self.R_MIN)
        self.assertEqual((w, below, lost), (0.75, 0.0, 0.25))                   # 3건 낙찰, 1건(90.1)은 더 낮은 가격에 패배
        for r in (0.85, 0.9, 0.9012, 0.95):
            self.assertAlmostEqual(sum(bm.outcomes(cases, r, 100.0, self.R_MIN)), 1.0)

    def test_a_value_moves_the_floor_price(self):
        # 같은 비율이라도 A가 크면 낙찰하한가(원)가 올라가고, 예정가격 대비로는 하한율이 높아진다
        lo = bm.floor_price(1e8, 0.0, 0.9, 100.0)
        hi = bm.floor_price(1e8, 1e7, 0.9, 100.0)
        self.assertAlmostEqual(lo, 90_000_000)
        self.assertAlmostEqual(hi, 91_000_000)

    def test_sajung_spread_makes_a_single_price_win_only_part_of_the_time(self):
        # 사정률 99와 101 → 하한은 89.1과 90.9. 한 가격으로는 둘 다 잡을 수 없다.
        cases = [case(99, 0.9 + 0.0003, a_frac=0.0), case(101, 0.9 + 0.0003, a_frac=0.0)]
        peak = max(p for _, p in bm.curve(cases, 100.0, self.R_MIN))
        self.assertEqual(peak, 0.5)

    def test_recommend_picks_highest_price_meeting_each_target(self):
        cases = [case(100, rw / 100, a_frac=0.0) for rw in (90.1, 90.2, 90.5, 91.0)]
        rec, cv = bm.recommend(cases, 100.0, self.R_MIN, targets=(0.5, 1.0, 1.5))
        self.assertEqual(rec['peak']['p'], 1.0)
        self.assertAlmostEqual(rec['peak']['r'], 0.9009, places=4)              # 확률 100%인 구간의 가장 높은 가격
        t50, t100, t150 = rec['targets']
        self.assertAlmostEqual(t50['r'], 0.9049, places=4)                      # 4건 중 2건 이상 이기려면 90.5 미만 중 가장 높은 가격
        self.assertTrue(t100['reachable'] and not t150['reachable'])
        self.assertIsNone(t150['r'])

    def test_risk_targets_pick_lowest_price_under_the_risk(self):
        cases = [case(100, rw / 100, a_frac=0.0) for rw in (90.1, 90.2, 90.5, 91.0)]
        rec, cv = bm.recommend(cases, 100.0, self.R_MIN)
        by = {t['risk']: t for t in rec['risk_targets']}
        self.assertTrue(by[0.10]['reachable'])
        self.assertLessEqual(by[0.10]['below_floor'], 0.10)
        self.assertAlmostEqual(by[0.10]['r'], 0.9, places=3)                    # 하한 바로 위가 탈락 위험이 없는 가장 낮은 가격


class FilterAndSegmentTests(unittest.TestCase):
    def setUp(self):
        self.cases = ([case(100, 0.9005, base=1e8, n=10) for _ in range(20)] + [case(100, 0.9010, base=1e9, n=100) for _ in range(20)])

    def test_filters_narrow_when_enough_cases(self):
        out, notes = bm.filter_cases(self.cases, band_id='b7')
        self.assertEqual((len(out), notes), (20, []))
        out, notes = bm.filter_cases(self.cases, participants='60_119')
        self.assertEqual(len(out), 20)
        self.assertTrue(all(c['n'] >= 60 for c in out))

    def test_filters_fall_back_with_a_note_when_too_few(self):
        out, notes = bm.filter_cases(self.cases, band_id='b1')
        self.assertEqual(len(out), 40)
        self.assertTrue(any('추정가격 구간' in n for n in notes))
        out, notes = bm.filter_cases(self.cases, participants='ge120')
        self.assertEqual(len(out), 40)
        self.assertTrue(any('경쟁 규모' in n for n in notes))

    def test_segments_skip_small_groups(self):
        seg = bm.segment_table(self.cases + [case(100, 0.9, base=5e8, n=30)] * 3, 0.89745)
        self.assertEqual({s['label'] for s in seg['participants']}, {'1~19곳', '60~119곳'})     # 3건뿐인 20~59곳은 뺀다
        self.assertTrue(all(s['n'] >= 8 for s in seg['participants']))


class BacktestTests(unittest.TestCase):
    def test_low_prices_do_not_look_good(self):
        # 학습·검증 모두 하한 바로 위에서 낙찰. 낮게 쓰기(하위 10%)는 일부 사례에서 하한 아래라 탈락한다.
        train, test = [], []
        for i in range(40):
            for target in (train, test):
                target.append(case(99 + (i % 5) * 0.5, 0.89745 + 0.0003 + (i % 3) * 0.0003))
        res = bm.backtest(train, test, lambda c: 0.89745)
        rows = {r['key']: r for r in res['rows']}
        self.assertGreaterEqual(rows['peak']['realized'], rows['low10']['realized'])
        self.assertLessEqual(rows['low10']['r'], rows['peak']['r'])
        for r in res['rows']:
            self.assertTrue(0.0 <= r['realized'] <= 1.0 and 0.0 <= r['predicted'] <= 1.0)
        self.assertEqual((res['train_n'], res['test_n']), (40, 40))

    def test_too_few_cases_returns_none(self):
        self.assertIsNone(bm.backtest([case(100, 0.9)] * 5, [case(100, 0.9)] * 10, lambda c: 0.89745))
        self.assertIsNone(bm.backtest([case(100, 0.9)] * 20, [case(100, 0.9)] * 3, lambda c: 0.89745))


class SamplingTests(unittest.TestCase):
    def setUp(self):
        import pps_bid
        self.pps = pps_bid
        self._orig = pps_bid.fetch_bid_base_amount
        bs.clear_cache()
        self.calls = []

        def fake(no, ord_='000'):
            self.calls.append(no)
            if no == 'N002':
                return None, bs.NOT_FOUND_MSG                               # 기초금액 없음(확정)
            if no == 'N003':
                return None, '조회 실패: timeout'                            # 일시 오류
            return {'bssamt': '100000000', 'bidNtceNo': no, 'sftyMngcst': '3000000', 'qltyMngcst': '1000000'}, None
        pps_bid.fetch_bid_base_amount = fake

    def tearDown(self):
        self.pps.fetch_bid_base_amount = self._orig
        bs.clear_cache()

    def items(self):
        return [make_item(i, date=f'2026-10-{i:02d} 10:00:00') for i in range(1, 8)]

    def test_recent_first_limit_and_cache(self):
        got, st = bs.fetch_base_info(self.items(), limit=4)
        self.assertEqual(sorted(self.calls), ['N004', 'N005', 'N006', 'N007'])   # 개찰일이 가장 최근인 4건만
        self.assertEqual((st['requested'], st['fetched'], st['cached']), (4, 4, 0))
        self.assertEqual(got[('N004', '000')], {'base': 100_000_000.0, 'a': 4_000_000.0})   # A값은 구성 항목 합
        self.calls.clear()
        got2, st2 = bs.fetch_base_info(self.items(), limit=4)
        self.assertEqual(self.calls, [])                                         # 두 번째는 조회 없이 보관한 값
        self.assertEqual((st2['cached'], st2['fetched']), (4, 0))
        self.assertEqual(got, got2)

    def test_missing_is_cached_but_transient_failure_is_not(self):
        got, st = bs.fetch_base_info(self.items(), limit=7)
        self.assertEqual((st['missing'], st['failed'], st['fetched']), (1, 1, 5))
        self.assertIsNone(got[('N002', '000')])                                  # 없음은 None으로 기억
        self.assertNotIn(('N003', '000'), got)                                   # 일시 오류는 결과에 없다
        self.calls.clear()
        bs.fetch_base_info(self.items(), limit=7)
        self.assertEqual(self.calls, ['N003'])                                   # 일시 오류만 다시 시도


class PageTests(unittest.TestCase):
    def test_predictor_page_uses_rule_based_floor(self):
        import app as appmod
        html = appmod.app.test_client().get('/bid_predictor').get_data(as_text=True)
        for needle in ('id="aAmount"', 'id="othersScore"', 'id="participants"', 'id="model-section"', 'function renderModel',
                       'function renderModelChart', '하한 미달로 탈락', '더 낮은 가격에 패배', '예규에 정해진 값'):
            self.assertIn(needle, html, needle)
        self.assertNotIn('id="floorRate"', html)                                 # 낙찰하한은 규정에서 계산하므로 입력받지 않는다
        self.assertNotIn('하위10% 전략', html)


class ServiceAndApiTests(unittest.TestCase):
    def setUp(self):
        import app as appmod
        import pps_bid
        self.appmod, self.pps = appmod, pps_bid
        self.http = appmod.app.test_client()
        self._orig = (pps_bid.fetch_bid_history, pps_bid.fetch_bid_base_amount, pps_bid._fetch_rate_group)
        bs.clear_cache()
        # 기초금액 1억~1.59억(구간 b7), 사정률 99.8~100.2, 낙찰자 비율 89.8~90.4%, A는 기초금액의 5%
        self.items, self.bases = [], {}
        for i in range(60):
            base = 100_000_000 + i * 1_000_000
            self.items.append(make_item(i, base=base, sajung=99.8 + (i % 5) * 0.1, r_w=0.898 + (i % 4) * 0.002, n=20 + (i % 3) * 50,
                                        date=f'2026-09-{(i % 28) + 1:02d} 09:00:00'))
            self.bases[f'N{i:03d}'] = base
        pps_bid.fetch_bid_history = lambda **kw: (self.items, [])
        pps_bid.fetch_bid_base_amount = lambda no, ord_='000': ({'bssamt': str(self.bases[no]), 'sftyMngcst': str(int(self.bases[no] * 0.05))}, None)
        pps_bid._fetch_rate_group = lambda ranges, *a, **k: ((self.items[:20], []) if len(ranges) == 2 else (self.items[20:], []))

    def tearDown(self):
        self.pps.fetch_bid_history, self.pps.fetch_bid_base_amount, self.pps._fetch_rate_group = self._orig
        bs.clear_cache()

    def test_predict_uses_legal_floor_and_returns_three_way_outcomes(self):
        d = self.http.post('/api/analyze/bid_predict', json={'keyword': '공사', 'months': 6, 'baseAmount': '120000000', 'aAmount': '6000000'}).get_json()
        self.assertTrue(d['success'], d)
        m = d['model']
        self.assertIsNone(d['model_error'])
        self.assertEqual(m['band']['byeolpyo'], 7)                                              # 기초금액 1.2억 → 추정가격 약 1.09억 → [별표 7]
        self.assertAlmostEqual(m['band']['r_min_pct'], 89.745, places=3)                        # 하한은 추정이 아니라 규정값
        self.assertEqual(m['band']['pass_score'], 95)
        self.assertEqual((m['target']['a'], m['target']['a_estimated']), (6_000_000, False))
        self.assertEqual(m['cases_total'], 60)
        peak = m['recommend']['peak']
        self.assertAlmostEqual(peak['p'] + peak['below_floor'] + peak['lost_to_lower'], 1.0, places=3)
        self.assertGreater(peak['p'], 0)
        # 금액 = A + 비율 × (기초금액 × 사정률 가정 - A)
        sg = m['target']['sajung_guess']
        self.assertAlmostEqual(peak['amount'], 6_000_000 + peak['r_pct'] / 100 * (120_000_000 * sg / 100 - 6_000_000), delta=2)
        reach = [t for t in m['recommend']['targets'] if t['reachable']]
        for t in reach:
            self.assertGreaterEqual(t['p'], t['target'] - 1e-9)
        xs = [t['x_pct'] for t in reach]
        self.assertEqual(xs, sorted(xs, reverse=True))                                          # 목표 확률이 높을수록 가격은 낮아진다
        self.assertTrue(m['recommend']['risk_targets'])
        lo, hi = m['target']['floor_price_range']
        self.assertLessEqual(lo, m['target']['floor_price_guess'])
        self.assertLessEqual(m['target']['floor_price_guess'], hi)
        self.assertTrue(any('보장하지 않' in n for n in m['notes']))
        self.assertTrue(m['curve'] and all('below_floor' in p for p in m['curve']))

    def test_a_amount_and_others_score_are_optional_with_notes(self):
        d = self.http.post('/api/analyze/bid_predict', json={'keyword': '공사', 'baseAmount': '120000000'}).get_json()
        m = d['model']
        self.assertTrue(m['target']['a_estimated'])
        self.assertTrue(any('A값을 입력하지 않아' in n for n in m['notes']))
        self.assertTrue(any('만점' in n for n in m['notes']))
        d2 = self.http.post('/api/analyze/bid_predict', json={'keyword': '공사', 'baseAmount': '120000000', 'othersScore': '9.5'}).get_json()
        self.assertAlmostEqual(d2['model']['band']['r_min_pct'], 89.775, places=3)              # 가격 외 점수가 모자라면 하한이 올라간다
        d3 = self.http.post('/api/analyze/bid_predict', json={'keyword': '공사', 'baseAmount': '120000000', 'othersScore': '1'}).get_json()
        self.assertIsNone(d3['model'])
        self.assertIn('통과할 수 없', d3['model_error'])

    def test_300eok_or_more_is_out_of_scope(self):
        d = self.http.post('/api/analyze/bid_predict', json={'keyword': '공사', 'baseAmount': '40000000000'}).get_json()
        self.assertTrue(d['success'])
        self.assertIsNone(d['model'])
        self.assertIn('300억원', d['model_error'])

    def test_no_base_amount_means_no_model_and_old_fields_remain(self):
        d = self.http.post('/api/analyze/bid_predict', json={'keyword': '공사'}).get_json()
        self.assertTrue(d['success'])
        self.assertIsNone(d['model'])
        self.assertIn('stats', d)

    def test_too_few_cases_gives_clear_reason(self):
        self.pps.fetch_bid_history = lambda **kw: (self.items[:6], [])
        d = self.http.post('/api/analyze/bid_predict', json={'keyword': '공사', 'baseAmount': '120000000'}).get_json()
        self.assertTrue(d['success'])                       # 기존 통계는 그대로 나오고
        self.assertIsNone(d['model'])
        self.assertIn('최소', d['model_error'])               # 이유가 설명된다

    def test_base_amount_endpoint_returns_a_value(self):
        self.pps.fetch_bid_base_amount = lambda no, ord_='000': ({'bssamt': '157981000', 'sftyMngcst': '9000000', 'qltyMngcst': '113864'}, None)
        d = self.http.get('/api/open_bids/base_amount?bidNtceNo=R26BK01764059&bidNtceOrd=000').get_json()
        self.assertTrue(d['success'], d)
        self.assertEqual(d['aAmount'], 9_113_864)

    def test_backtest_endpoint_uses_floor_aware_model(self):
        d = self.http.post('/api/analyze/bid_backtest', json={'keyword': '공사', 'months': 6, 'testMonths': 2}).get_json()
        self.assertTrue(d['success'], d)
        keys = {r['key'] for r in d['rows']}
        self.assertTrue({'peak', 'median', 'low10'} <= keys)
        self.assertNotIn('per_percentile', d)               # 낮게 쓸수록 승률이 높게 나오던 예전 표는 더 이상 내려가지 않는다
        self.assertAlmostEqual(d['r_min'], 0.89745, places=4)
        self.pps._fetch_rate_group = lambda ranges, *a, **k: (self.items[:3], [])               # 사례가 너무 적으면 이유를 알려 준다
        r = self.http.post('/api/analyze/bid_backtest', json={'keyword': '공사', 'months': 6, 'testMonths': 2}).get_json()
        self.assertFalse(r['success'])
        self.assertIn('사후 검증이 어렵습니다', r['message'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
