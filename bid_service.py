"""
낙찰가 예측 - 화면(API)용 조립 계층. 계산은 bid_model.py, 낙찰하한 규정은 bid_rules.py, 기초금액·A값 표본 조회는 bid_sampling.py가 한다.
"""
import statistics

import bid_model as bm
import bid_rules
import bid_sampling as bs

DISCLAIMER = ('과거 낙찰 사례에서 같은 방식으로 투찰했다면 이겼을 비율을 계산한 통계입니다. 이번 입찰의 낙찰을 보장하지 않으며, '
              '예정가격은 개찰 때 복수예비가격 추첨으로 정해지므로 같은 가격으로도 결과가 달라집니다.')


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x > 0 else None


def analyze(items, base_amount, a_amount=None, presumed_price=None, others=None, participants=None, sample_size=120):
    """낙찰 이력(items)으로 이번 공고(기초금액·A값)의 투찰 추천을 만든다. 계산할 수 없으면 (None, 이유)."""
    base = _num(base_amount)
    if base is None:
        return None, '기초금액을 입력해 주세요.'
    est_in = _num(presumed_price)
    est = est_in or bid_rules.estimated_from_base(base)
    band = bid_rules.band_for(est)
    if band is None:
        return None, '추정가격이 300억원 이상이라 이 규정(지방자치단체 시설공사 적격심사, 300억원 미만)의 범위 밖입니다.'
    others_in = _num(others)
    others_used = band['others_max'] if others_in is None else min(others_in, band['others_max'])
    r_min = bid_rules.min_ratio(band, others_used)
    if r_min is None:
        return None, (f"가격 외 점수가 {others_used:g}점(만점 {band['others_max']}점)이면 입찰가격 평점이 만점이어도 적격통과점수 "
                      f"{band['pass_score']}점에 못 미쳐 어떤 가격으로도 통과할 수 없습니다.")
    r_min = float(r_min)

    sample_size = max(30, min(int(sample_size or 120), 200))
    info_map, sstats = bs.fetch_base_info(items, limit=sample_size)
    cases_all = bm.build_cases(items, info_map)
    if len(cases_all) < bm.MIN_CASES:
        return None, (f'기초금액을 확인할 수 있는 낙찰 사례가 {len(cases_all)}건뿐입니다(최소 {bm.MIN_CASES}건 필요). '
                      '조회 기간을 늘리거나 검색 조건을 넓혀 주세요.')
    cases, notes = bm.filter_cases(cases_all, band_id=band['id'], participants=participants)
    desc = bm.describe(cases)
    sg = bm.sajung_guess(cases)

    a_in = _num(a_amount)
    a_t = a_in if a_in is not None else statistics.median(c['a'] / c['base'] for c in cases) * base
    rec, cv = bm.recommend(cases, sg, r_min)

    plan_guess = base * sg / 100.0
    floor_guess = bm.floor_price(base, a_t, r_min, sg)
    sj = sorted(c['sajung'] for c in cases)
    f_lo, f_hi = bm.floor_price(base, a_t, r_min, bm._q(sj, 10)), bm.floor_price(base, a_t, r_min, bm._q(sj, 90))

    def price_row(r):
        price, x_pct = bm.target_price(base, a_t, r, sg)
        return {'r_pct': round(r * 100, 4), 'amount': int(round(price)), 'x_pct': round(x_pct, 4), 'margin_won': int(round(price - floor_guess))}

    def target_row(t):
        if not t['reachable']:
            return dict(t, amount=None, x_pct=None, margin_won=None, r_pct=None)
        return dict(t, **price_row(t['r']))

    def risk_row(t):
        if not t['reachable']:
            return dict(t, amount=None, x_pct=None, margin_won=None, r_pct=None)
        return dict(t, **price_row(t['r']))

    peak = dict(rec['peak'], **price_row(rec['peak']['r']))
    step = 5                                                  # 곡선은 0.0005(비율 0.05%p)마다만 내려 보낸다
    grid = []
    for i, (r, p) in enumerate(cv):
        if i % step == 0:
            price, x_pct = bm.target_price(base, a_t, r, sg)
            w_, b_, l_ = bm.outcomes(cases, r, sg, r_min)
            grid.append({'r_pct': round(r * 100, 4), 'x_pct': round(x_pct, 4), 'amount': int(round(price)), 'p': round(p, 4),
                         'below_floor': round(b_, 4), 'lost_to_lower': round(l_, 4)})
    floor_x = floor_guess / base * 100.0

    notes = list(notes)
    if a_in is None:
        notes.append('A값을 입력하지 않아 비슷한 과거 공고의 A값 비율(기초금액 대비 중앙값)로 추정했습니다. 공고문(기초금액 자료)에 A값이 있으면 입력해 주세요. A값에 따라 낙찰하한 가격이 크게 달라집니다.')
    if others_in is None:
        notes.append(f"내 가격 외 점수(수행능력 등)를 입력하지 않아 만점({band['others_max']}점)으로 계산한 법정 낙찰하한입니다. 점수가 모자라면 하한이 올라갑니다.")
    if est_in is None:
        notes.append('추정가격을 입력하지 않아 기초금액÷1.1로 구간을 정했습니다.')
    if sstats['failed']:
        notes.append(f"기초금액 조회가 {sstats['failed']}건 실패(오류·시간 초과)해 그 사례는 뺐습니다.")
    n_med = statistics.median(c['n'] for c in cases if c['n']) if any(c['n'] for c in cases) else None
    if peak['p'] < 0.2:
        notes.append(f"가격만으로는 낙찰 확률이 낮은 공사입니다(최고 {peak['p'] * 100:.1f}%). 낙찰자는 낙찰하한가 바로 위(하한 대비 +{(desc['r_w']['median'] - r_min * 100):.2f}%p 안팎)에 몰려 있는데, "
                     f"예정가격(사정률)이 개찰 때까지 ±{(bm._q(sj, 90) - bm._q(sj, 10)) / 2:.2f}% 정도 흔들려 하한가가 {int(round(f_lo)):,}원~{int(round(f_hi)):,}원 사이에서 움직입니다."
                     + (f" 참가업체도 보통 {int(n_med)}곳 안팎입니다." if n_med else ''))
    notes.append(DISCLAIMER)

    return {
        'band': {'id': band['id'], 'label': band['label'], 'byeolpyo': band['byeolpyo'], 'pass_score': band['pass_score'], 'ref': band['ref'],
                 'others_used': others_used, 'others_max': band['others_max'], 'r_min_pct': round(r_min * 100, 4),
                 'floor_pct_of_plan': round(bid_rules.floor_rate_vs_plan(r_min, a_t / plan_guess) if plan_guess else 0, 3)},
        'target': {'base': base, 'a': round(a_t), 'a_estimated': a_in is None, 'estimated_price': round(est), 'sajung_guess': round(sg, 3),
                   'plan_guess': int(round(plan_guess)), 'floor_price_guess': int(round(floor_guess)), 'floor_x_pct': round(floor_x, 4),
                   'floor_price_range': [int(round(f_lo)), int(round(f_hi))]},
        'sample': sstats, 'cases_total': len(cases_all), 'cases_used': len(cases), 'describe': desc,
        'recommend': {'peak': peak, 'targets': [target_row(t) for t in rec['targets']], 'risk_targets': [risk_row(t) for t in rec['risk_targets']]},
        'curve': grid, 'segments': bm.segment_table(cases, r_min), 'notes': notes,
    }, None


def backtest(train_items, test_items, presumed_price=None, participants=None, train_limit=100, test_limit=70):
    """학습(예전)·검증(최근) 낙찰 이력으로 사후 검증. 사례마다 그 사례 추정가격 구간의 규정 하한(가격 외 점수 만점)을 쓴다. 계산할 수 없으면 (None, 이유)."""
    tr_map, s1 = bs.fetch_base_info(train_items, limit=train_limit)
    te_map, s2 = bs.fetch_base_info(test_items, limit=test_limit)
    tr, te = bm.build_cases(train_items, tr_map), bm.build_cases(test_items, te_map)
    est_in = _num(presumed_price)
    if est_in:
        band = bid_rules.band_for(est_in)
        if band is not None:
            tr2, te2 = [c for c in tr if c['band'] == band['id']], [c for c in te if c['band'] == band['id']]
            if len(tr2) >= bm.MIN_CASES and len(te2) >= 5:
                tr, te = tr2, te2
    if participants in bm.PARTICIPANT_BANDS:
        _label, lo, hi = bm.PARTICIPANT_BANDS[participants]
        tr, te = [c for c in tr if lo <= c['n'] < hi], [c for c in te if lo <= c['n'] < hi]
    cache = {}

    def r_min_fn(c):
        bid = c['band']
        if bid not in cache:
            band = next((b for b in bid_rules.spec()['bands'] if b['id'] == bid), None)
            cache[bid] = float(bid_rules.min_ratio(band)) if band else 0.8975
        return cache[bid]

    res = bm.backtest(tr, te, r_min_fn)
    if res is None:
        return None, (f'기초금액을 확인한 사례가 학습 {len(tr)}건·검증 {len(te)}건뿐이라 사후 검증이 어렵습니다'
                      f'(학습 {bm.MIN_CASES}건, 검증 5건 이상 필요). 조회 기간을 늘리거나 검색 조건을 넓혀 주세요.')
    res['train_sample'], res['test_sample'] = s1, s2
    return res, None
