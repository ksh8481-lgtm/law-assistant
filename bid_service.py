"""
낙찰가 예측 - 화면(API)용 조립 계층. 계산은 bid_model.py, 기초금액 표본 조회는 bid_sampling.py가 한다.
"""
import bid_model as bm
import bid_sampling as bs

DISCLAIMER = ('과거 낙찰 사례에서 같은 가격으로 투찰했다면 이겼을 비율을 계산한 통계입니다. 이번 입찰의 낙찰을 보장하지 않으며, '
              '예정가격은 개찰 때 복수예비가격 추첨으로 정해지므로 같은 가격으로도 결과가 달라집니다.')


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x > 0 else None


def _won(base, x):
    return None if base is None or x is None else int(round(base * x / 100.0))


def analyze(items, base_amount, floor_rate=None, participants=None, sample_size=120):
    """낙찰 이력(items)으로 기초금액 기준 투찰 추천을 만든다. 계산할 수 없으면 (None, 이유)."""
    base = _num(base_amount)
    floor_in = _num(floor_rate)
    sample_size = max(30, min(int(sample_size or 120), 200))
    base_map, sstats = bs.fetch_base_amounts(items, limit=sample_size)
    cases_all = bm.build_cases(items, base_map)
    if len(cases_all) < bm.MIN_CASES:
        return None, (f'기초금액을 확인할 수 있는 낙찰 사례가 {len(cases_all)}건뿐입니다(최소 {bm.MIN_CASES}건 필요). '
                      '조회 기간을 늘리거나 검색 조건을 넓혀 주세요.')
    cases, notes = bm.filter_cases(cases_all, base=base, participants=participants)
    floor = floor_in or bm.estimate_floor_rate([c['rate'] for c in cases])
    if floor is None:
        return None, '낙찰하한율을 추정할 수 없습니다.'
    rec, cv = bm.recommend(cases, floor)
    desc = bm.describe(cases)

    def target_row(t):
        if not t['reachable']:
            return dict(t, amount=None, amount_low=None, amount_high=None, margin_pp=None, margin_won=None)
        margin = round(t['x'] - rec['floor_x_median'], 3)
        return dict(t, amount=_won(base, t['x']), amount_low=_won(base, t['x_low']), amount_high=_won(base, t['x_high']), margin_pp=margin,
                    margin_won=_won(base, margin) if base else None)

    peak = dict(rec['peak'], amount=_won(base, rec['peak']['x']),
                margin_pp=round(rec['peak']['x'] - rec['floor_x_median'], 3))
    step = 0.05
    grid = [{'x': x, 'p': round(p, 4)} for i, (x, p) in enumerate(cv) if i % int(round(step / 0.01)) == 0]
    notes = list(notes)
    if floor_in:
        notes.append(f'낙찰하한율은 입력하신 {floor:g}%를 사용했습니다.')
    else:
        notes.append(f'낙찰하한율은 과거 낙찰률 분포의 아래쪽 끝에서 추정한 {floor:g}%입니다(낙찰자는 모두 하한 이상이므로). '
                     '공고문에 낙찰하한율이 있으면 입력해 주세요.')
    if sstats['failed']:
        notes.append(f"기초금액 조회가 {sstats['failed']}건 실패(오류·시간 초과)해 그 사례는 뺐습니다.")
    notes.append(DISCLAIMER)
    segs = bm.segment_table(cases, floor)
    return {
        'base_amount': base, 'floor_rate': floor, 'floor_estimated': not bool(floor_in),
        'sample': sstats, 'cases_total': len(cases_all), 'cases_used': len(cases), 'describe': desc,
        'recommend': {'peak': peak, 'targets': [target_row(t) for t in rec['targets']], 'floor_x_median': rec['floor_x_median'], 'w_median': rec['w_median']},
        'curve': grid, 'segments': segs, 'notes': notes,
    }, None


def backtest(train_items, test_items, floor_rate=None, participants=None, train_limit=100, test_limit=70):
    """학습(예전)·검증(최근) 낙찰 이력으로 사후 검증. 계산할 수 없으면 (None, 이유)."""
    tr_map, s1 = bs.fetch_base_amounts(train_items, limit=train_limit)
    te_map, s2 = bs.fetch_base_amounts(test_items, limit=test_limit)
    tr, te = bm.build_cases(train_items, tr_map), bm.build_cases(test_items, te_map)
    if participants in bm.PARTICIPANT_BANDS:
        _label, lo, hi = bm.PARTICIPANT_BANDS[participants]
        tr, te = [c for c in tr if lo <= c['n'] < hi], [c for c in te if lo <= c['n'] < hi]
    res = bm.backtest(tr, te, floor_rate=_num(floor_rate))
    if res is None:
        return None, (f'기초금액을 확인한 사례가 학습 {len(tr)}건·검증 {len(te)}건뿐이라 사후 검증이 어렵습니다'
                      f'(학습 {bm.MIN_CASES}건, 검증 5건 이상 필요). 조회 기간을 늘리거나 검색 조건을 넓혀 주세요.')
    res['train_sample'], res['test_sample'] = s1, s2
    return res, None
