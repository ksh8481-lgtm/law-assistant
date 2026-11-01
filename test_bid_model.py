"""
낙찰가 예측 모델(bid_model·bid_sampling·bid_service)과 API 시험. `python test_bid_model.py`로 실행한다. 네트워크가 필요 없다(조달청 API는 가짜로 대체).

핵심으로 확인하는 것:
- 사례 계산: 낙찰금액÷기초금액(w), 사정률(예정가격÷기초금액)
- 낙찰 조건에 낙찰하한이 들어가는가(하한 아래로 쓰면 이기지 못함 - 예전 백테스트는 낮게 쓸수록 이겼다)
- 목표 확률별로 "그 확률 이상인 가장 높은 가격"을 고르는가
- 기초금액 표본 조회: 캐시, 기초금액 없음/일시 오류 구분, 최근순
"""
import unittest

import bid_model as bm
import bid_sampling as bs


def item(i, base, sajung=100.0, rate=90.0, n=50, date=None):
    plan = base * sajung / 100.0
    return {'bidNtceNo': f'N{i:03d}', 'bidNtceOrd': '000', 'sucsfbidRate': str(rate), 'sucsfbidAmt': str(round(plan * rate / 100.0)),
            'prtcptCnum': str(n), 'rlOpengDt': date or f'2026-10-{(i % 28) + 1:02d} 10:00:00', 'bidNtceNm': f'공사{i}', 'dminsttNm': '시험군'}


def case(sajung, w, base=1e8, n=50):
    return {'no': 'x', 'amt': base * w / 100, 'rate': 90.0, 'base': base, 'plan': base * sajung / 100, 'sajung': sajung, 'w': w, 'n': n, 'date': ''}


class BuildCasesTests(unittest.TestCase):
    def test_w_and_sajung(self):
        it = item(1, 100_000_000, sajung=99.0, rate=90.5)
        c = bm.build_cases([it], {('N001', '000'): 100_000_000.0})[0]
        self.assertAlmostEqual(c['sajung'], 99.0, places=3)                  # 예정가격 ÷ 기초금액
        self.assertAlmostEqual(c['w'], 99.0 * 0.905, places=3)               # 낙찰금액 ÷ 기초금액 = 사정률 × 낙찰률
        self.assertEqual(c['n'], 50)

    def test_bad_cases_are_dropped(self):
        items = [item(1, 1e8), item(2, 1e8), item(3, 1e8, rate=40), item(4, 1e8, sajung=120), item(5, 1e8)]
        base_map = {('N001', '000'): 1e8, ('N002', '000'): None, ('N003', '000'): 1e8, ('N004', '000'): 1e8}      # 5번은 기초금액 조회 결과 없음
        got = bm.build_cases(items, base_map)
        self.assertEqual([c['no'] for c in got], ['N001'])                    # 기초금액 없음·낙찰률 이상·사정률 범위 밖은 제외


class FloorAndProbabilityTests(unittest.TestCase):
    def test_floor_estimate_ignores_far_below_outliers(self):
        rates = [90.0 + (i % 10) * 0.05 for i in range(60)] + [80.0, 82.0]
        f = bm.estimate_floor_rate(rates)
        self.assertGreaterEqual(f, 89.9)                                      # 80%대 다른 방식 낙찰은 하한 추정에서 빠진다
        self.assertLessEqual(f, 90.1)
        self.assertIsNone(bm.estimate_floor_rate([90, 91]))

    def test_win_requires_floor_and_beating_the_winner(self):
        # 하한 f=90.0(사정률 100, 하한율 90). 낙찰 w = 90.1, 90.2, 90.5, 91.0
        cases = [case(100, w) for w in (90.1, 90.2, 90.5, 91.0)]
        b = bm.bounds(cases, 90.0)
        self.assertEqual(bm.win_probability(b, 89.99), 0.0)                   # 하한 아래: 탈락 (낮게 쓸수록 이긴다는 예전 계산과 반대)
        self.assertEqual(bm.win_probability(b, 90.0), 1.0)                    # 하한 이상이고 모두의 낙찰가보다 낮음
        self.assertEqual(bm.win_probability(b, 90.1), 0.75)                   # 같은 가격은 지지 않지만 이기지도 못한다(< 만 승리)
        self.assertEqual(bm.win_probability(b, 90.5), 0.25)
        self.assertEqual(bm.win_probability(b, 91.0), 0.0)

    def test_sajung_spread_makes_a_single_price_win_only_part_of_the_time(self):
        # 사정률이 99와 101이면 하한은 89.1과 90.9. 한 가격으로는 둘 다 잡을 수 없다.
        cases = [case(99, 89.2), case(101, 91.0)]
        b = bm.bounds(cases, 90.0)
        self.assertAlmostEqual(b[0][0], 89.1)
        self.assertAlmostEqual(b[1][0], 90.9)
        self.assertEqual(bm.win_probability(b, 89.15), 0.5)                   # 첫 사례만 이김
        self.assertEqual(bm.win_probability(b, 90.95), 0.5)                   # 둘째 사례만 이김(첫 사례는 89.2보다 높아 짐)
        self.assertEqual(max(p for _, p in bm.curve(cases, 90.0)), 0.5)

    def test_recommend_picks_highest_price_meeting_each_target(self):
        cases = [case(100, w) for w in (90.1, 90.2, 90.5, 91.0)]
        rec, cv = bm.recommend(cases, 90.0, targets=(0.5, 1.0, 1.5))
        self.assertEqual(rec['peak']['p'], 1.0)
        self.assertAlmostEqual(rec['peak']['x'], 90.09, places=2)             # 확률 100%인 구간의 가장 높은 가격
        t50, t100, t150 = rec['targets']
        self.assertAlmostEqual(t50['x'], 90.49, places=2)                     # 4건 중 2건 이상 이기려면 90.5 미만 중 가장 높은 가격
        self.assertTrue(t100['reachable'] and not t150['reachable'])
        self.assertIsNone(t150['x'])
        self.assertAlmostEqual(rec['floor_x_median'], 90.0)


class FilterAndSegmentTests(unittest.TestCase):
    def setUp(self):
        self.cases = ([case(100, 90.2, base=1e8, n=10) for _ in range(20)] + [case(100, 90.4, base=1e9, n=100) for _ in range(20)])

    def test_filters_narrow_when_enough_cases(self):
        out, notes = bm.filter_cases(self.cases, base=1.2e8)
        self.assertEqual((len(out), notes), (20, []))
        out, notes = bm.filter_cases(self.cases, participants='60_119')
        self.assertEqual(len(out), 20)
        self.assertTrue(all(c['n'] >= 60 for c in out))

    def test_filters_fall_back_with_a_note_when_too_few(self):
        out, notes = bm.filter_cases(self.cases, base=5e10)
        self.assertEqual(len(out), 40)
        self.assertTrue(any('규모' in n for n in notes))
        out, notes = bm.filter_cases(self.cases, participants='ge120')
        self.assertEqual(len(out), 40)
        self.assertTrue(any('경쟁 규모' in n for n in notes))

    def test_segments_skip_small_groups(self):
        seg = bm.segment_table(self.cases + [case(100, 90.0, base=5e8, n=30)] * 3, 90.0)
        self.assertEqual({s['label'] for s in seg['participants']}, {'1~19곳', '60~119곳'})     # 3건뿐인 20~59곳은 뺀다
        self.assertEqual({s['label'] for s in seg['size']}, {'2억원 미만', '5억~20억원'})
        self.assertTrue(all(s['n'] >= 8 for s in seg['participants'] + seg['size']))


class BacktestTests(unittest.TestCase):
    def test_low_prices_do_not_look_good_any_more(self):
        # 학습·검증 모두 하한 90.0(사정률 100)에 바짝 붙어 낙찰. 낮게 쓰기(하위 10%)는 일부 사례에서 하한 아래라 탈락한다.
        train, test = [], []
        for i in range(40):
            sj = 99 + (i % 5) * 0.5                                           # 99.0 ~ 101.0
            for target in (train, test):
                c = case(sj, sj * 0.90 + 0.05 + (i % 3) * 0.05)               # 각 사례의 하한 바로 위에서 낙찰
                c['rate'] = 90.1
                target.append(c)
        res = bm.backtest(train, test, floor_rate=90.0)
        rows = {r['key']: r for r in res['rows']}
        self.assertGreater(rows['peak']['realized'], rows['low10']['realized'])
        self.assertLess(rows['low10']['x'], rows['peak']['x'])
        for r in res['rows']:
            self.assertTrue(0.0 <= r['realized'] <= 1.0 and 0.0 <= r['predicted'] <= 1.0)
        self.assertEqual((res['train_n'], res['test_n'], res['floor_rate']), (40, 40, 90.0))

    def test_too_few_cases_returns_none(self):
        self.assertIsNone(bm.backtest([case(100, 90.2)] * 5, [case(100, 90.2)] * 10))
        self.assertIsNone(bm.backtest([case(100, 90.2)] * 20, [case(100, 90.2)] * 3))


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
            return {'bssamt': '100000000', 'bidNtceNo': no}, None
        pps_bid.fetch_bid_base_amount = fake

    def tearDown(self):
        self.pps.fetch_bid_base_amount = self._orig
        bs.clear_cache()

    def items(self):
        return [item(i, 1e8, date=f'2026-10-{i:02d} 10:00:00') for i in range(1, 8)]

    def test_recent_first_limit_and_cache(self):
        got, st = bs.fetch_base_amounts(self.items(), limit=4)
        self.assertEqual(sorted(self.calls), ['N004', 'N005', 'N006', 'N007'])   # 개찰일이 가장 최근인 4건만
        self.assertEqual((st['requested'], st['fetched'], st['cached']), (4, 4, 0))
        self.calls.clear()
        got2, st2 = bs.fetch_base_amounts(self.items(), limit=4)
        self.assertEqual(self.calls, [])                                         # 두 번째는 조회 없이 보관한 값
        self.assertEqual((st2['cached'], st2['fetched']), (4, 0))
        self.assertEqual(got, got2)

    def test_missing_is_cached_but_transient_failure_is_not(self):
        got, st = bs.fetch_base_amounts(self.items(), limit=7)
        self.assertEqual((st['missing'], st['failed'], st['fetched']), (1, 1, 5))
        self.assertIsNone(got[('N002', '000')])                                  # 없음은 None으로 기억
        self.assertNotIn(('N003', '000'), got)                                   # 일시 오류는 결과에 없다
        self.calls.clear()
        bs.fetch_base_amounts(self.items(), limit=7)
        self.assertEqual(self.calls, ['N003'])                                   # 일시 오류만 다시 시도


class PageTests(unittest.TestCase):
    def test_predictor_page_has_new_inputs_and_model_section(self):
        import app as appmod
        html = appmod.app.test_client().get('/bid_predictor').get_data(as_text=True)
        for needle in ('id="floorRate"', 'id="participants"', 'id="model-section"', 'function renderModel', 'function renderModelChart',
                       '기초금액 대비 낙찰금액', '낙찰하한 아래면 탈락'):
            self.assertIn(needle, html, needle)
        self.assertNotIn('하위10% 전략', html)                                   # 낮게 쓰기를 부추기던 예전 백테스트 설명은 없다


class ServiceAndApiTests(unittest.TestCase):
    def setUp(self):
        import app as appmod
        import pps_bid
        self.appmod, self.pps = appmod, pps_bid
        self.http = appmod.app.test_client()
        self._orig = (pps_bid.fetch_bid_history, pps_bid.fetch_bid_base_amount, pps_bid._fetch_rate_group)
        bs.clear_cache()
        # 사정률 99.8~100.2, 낙찰률 90.1~91.3%인 사례 60건(기초금액 1억~1.59억)
        self.items = []
        self.bases = {}
        for i in range(60):
            base = 100_000_000 + i * 1_000_000
            sj = 99.8 + (i % 5) * 0.1
            self.items.append(item(i, base, sajung=sj, rate=round(90.1 + (i % 4) * 0.4, 3), n=20 + (i % 3) * 50, date=f'2026-09-{(i % 28) + 1:02d} 09:00:00'))
            self.bases[f'N{i:03d}'] = base
        pps_bid.fetch_bid_history = lambda **kw: (self.items, [])
        pps_bid.fetch_bid_base_amount = lambda no, ord_='000': ({'bssamt': str(self.bases[no])}, None)
        pps_bid._fetch_rate_group = lambda ranges, *a, **k: ((self.items[:20], []) if len(ranges) == 2 else (self.items[20:], []))

    def tearDown(self):
        self.pps.fetch_bid_history, self.pps.fetch_bid_base_amount, self.pps._fetch_rate_group = self._orig
        bs.clear_cache()

    def test_predict_returns_model_with_won_amounts(self):
        d = self.http.post('/api/analyze/bid_predict', json={'keyword': '공사', 'months': 6, 'baseAmount': '120000000'}).get_json()
        self.assertTrue(d['success'], d)
        m = d['model']
        self.assertIsNone(d['model_error'])
        self.assertTrue(m['floor_estimated'])
        self.assertEqual(m['cases_total'], 60)
        peak = m['recommend']['peak']
        self.assertAlmostEqual(peak['amount'], round(120_000_000 * peak['x'] / 100))        # 금액 = 기초금액 × 투찰률
        self.assertGreater(peak['p'], 0)
        reach = [t for t in m['recommend']['targets'] if t['reachable']]
        self.assertTrue(reach)
        for t in reach:                                                                       # 확률이 높을수록(목표가 클수록) 가격은 낮아지거나 같다
            self.assertGreaterEqual(t['p'], t['target'] - 1e-9)
        xs = [t['x'] for t in reach]
        self.assertEqual(xs, sorted(xs, reverse=True))
        self.assertTrue(any('낙찰하한율은' in n for n in m['notes']))
        self.assertTrue(any('보장하지 않' in n for n in m['notes']))
        self.assertTrue(m['curve'] and m['segments']['participants'])

    def test_user_floor_rate_overrides_estimate(self):
        d = self.http.post('/api/analyze/bid_predict', json={'keyword': '공사', 'baseAmount': '120000000', 'floorRate': '89.9'}).get_json()
        self.assertEqual((d['model']['floor_rate'], d['model']['floor_estimated']), (89.9, False))

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

    def test_backtest_endpoint_uses_floor_aware_model(self):
        d = self.http.post('/api/analyze/bid_backtest', json={'keyword': '공사', 'months': 6, 'testMonths': 2}).get_json()
        self.assertTrue(d['success'], d)
        keys = {r['key'] for r in d['rows']}
        self.assertTrue({'peak', 'median', 'low10'} <= keys)
        self.assertNotIn('per_percentile', d)               # 낮게 쓸수록 승률이 높게 나오던 예전 표는 더 이상 내려가지 않는다
        self.pps._fetch_rate_group = lambda ranges, *a, **k: (self.items[:3], [])               # 사례가 너무 적으면 이유를 알려 준다
        r = self.http.post('/api/analyze/bid_backtest', json={'keyword': '공사', 'months': 6, 'testMonths': 2}).get_json()
        self.assertFalse(r['success'])
        self.assertIn('사후 검증이 어렵습니다', r['message'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
