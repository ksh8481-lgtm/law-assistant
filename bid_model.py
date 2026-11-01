"""
낙찰가 예측 - 과거 낙찰 사례로 "얼마에 투찰하면 낙찰될 확률이 얼마인가"를 계산한다(AI가 아니라 통계 계산).

[예전 방식의 문제]
- 낙찰률(낙찰금액 ÷ 예정가격)로만 분포를 봤는데, 투찰할 때는 예정가격을 모르고 기초금액만 안다. "기초금액 × 낙찰률 ± 3%"로 대충 환산했다.
- 백테스트가 "추천 낙찰률이 실제 낙찰자의 낙찰률보다 낮거나 같으면 이긴다"고만 봐서 낮게 쓸수록 승률이 높게 나왔다(최소값 → 승률 100%).
  실제로는 낙찰하한 아래로 쓰면 무조건 탈락한다.
- 낙찰하한율을 과거 분포에서 추정했다. 하지만 지자체 시설공사 적격심사(300억원 미만)의 낙찰하한은 예규의 입찰가격 평점 식과 적격통과점수에서
  정확히 계산된다(bid_rules.py). 하한은 예정가격이 아니라 (예정가격 - A) 기준이라, A값(보험료·안전관리비 등)이 하한 가격을 크게 좌우한다.

[새 방식]
1. 과거 사례마다 기초금액·A값을 조회해, 낙찰자의 비율 r_w = (낙찰금액-A)/(예정가격-A)와 사정률 s = 예정가격/기초금액을 구한다.
2. 하한은 규정(bid_rules)에서: 비율이 r_min(예: 89.745%) 이상이어야 통과. 사례 i에서 하한 가격 f_i = A_i + r_min × (예정가격_i - A_i).
3. 투찰은 "r_bid로 쓴다"는 정책으로 본다: 내 투찰가 x_i = A_i + r_bid × (기초금액_i × 사정률 가정 - A_i) - 사정률은 개찰 때야 알 수 있으므로 중앙값으로 가정.
   x_i가 하한 이상(f_i ≤ x_i)이고 실제 낙찰가보다 낮으면(x_i < 낙찰금액_i) 그 사례를 이긴 것. 이긴 비율이 낙찰 확률 P(r_bid).
4. 이번 공고의 (기초금액, A)에 같은 r_bid를 적용해 투찰 금액(원)을 낸다. 목표 확률별로 "그 확률 이상인 가장 높은 가격"(이윤이 큰 쪽)을 추천한다.

과거에 이랬다는 통계일 뿐 이번 입찰의 낙찰을 보장하지 않는다(예정가격은 개찰 때 복수예비가격 추첨으로 정해진다).
"""
import statistics

import bid_rules

SAJUNG_MIN, SAJUNG_MAX = 96.5, 103.5     # 복수예비가격 범위(±3%) 안. 벗어나면 기초금액·금액 기준이 달라 값이 맞지 않는 사례로 보고 뺀다
RW_MIN, RW_MAX = 0.80, 1.0001            # 낙찰자의 (낙찰금액-A)/(예정가격-A)가 이 범위 밖이면 다른 낙찰 방식·자료 오류로 보고 뺀다
MIN_CASES = 15                           # 이보다 적으면 확률이 의미 없어 계산하지 않는다
DEFAULT_TARGETS = (0.05, 0.1, 0.2, 0.3, 0.5)  # 목표 낙찰 확률. 소액 공사는 참가업체가 수백 곳이라 한 가격의 낙찰 확률이 낮다. 도달할 수 없는 확률은 '도달 불가'로 표시한다
RISK_TARGETS = (0.5, 0.25, 0.10)               # 하한 미달(탈락) 위험이 이 이하가 되는 가장 낮은 가격

PARTICIPANT_BANDS = {'lt20': ('1~19곳', 1, 20), '20_59': ('20~59곳', 20, 60), '60_119': ('60~119곳', 60, 120), 'ge120': ('120곳 이상', 120, 10 ** 9)}


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def build_cases(items, info_map):
    """낙찰 목록 + {(공고번호, 차수): {'base': 기초금액, 'a': A값}}으로 분석 사례를 만든다. 자료가 없거나 값이 이상한 사례는 뺀다."""
    cases = []
    for it in items:
        rate, amt = _f(it.get('sucsfbidRate')), _f(it.get('sucsfbidAmt'))
        info = info_map.get((it.get('bidNtceNo'), it.get('bidNtceOrd') or '000'))
        if not rate or not amt or not info or not (50.0 < rate <= 100.0) or amt <= 0:
            continue
        base, a = _f(info.get('base')), _f(info.get('a')) or 0.0
        if not base or base <= 0 or a < 0:
            continue
        plan = amt / (rate / 100.0)
        sajung = plan / base * 100.0
        if not (SAJUNG_MIN <= sajung <= SAJUNG_MAX) or plan - a <= 0:
            continue
        r_w = (amt - a) / (plan - a)
        if not (RW_MIN <= r_w <= RW_MAX):
            continue
        try:
            n = int(float(it.get('prtcptCnum') or 0))
        except (TypeError, ValueError):
            n = 0
        est = bid_rules.estimated_from_base(base)
        band = bid_rules.band_for(est)
        cases.append({'no': it.get('bidNtceNo'), 'amt': amt, 'rate': rate, 'base': base, 'a': a, 'plan': plan, 'sajung': sajung, 'r_w': r_w,
                      'w': amt / base * 100.0, 'n': n, 'date': it.get('rlOpengDt') or '', 'band': band['id'] if band else None, 'est': est})
    return cases


def sajung_guess(cases):
    """개찰 전에는 예정가격을 모르므로 사례들의 사정률 중앙값(%)을 내 투찰의 가정으로 쓴다."""
    return statistics.median(c['sajung'] for c in cases)


def policy_bounds(cases, r_bid, s_guess, r_min):
    """r_bid 정책(비율 r_bid로 투찰, 사정률은 s_guess로 가정)에서 사례별 (내 투찰가, 낙찰하한가, 낙찰금액) - 모두 그 사례의 기초금액 대비 %."""
    out = []
    for c in cases:
        b, a = c['base'], c['a']
        x = (a + r_bid * (b * s_guess / 100.0 - a)) / b * 100.0
        f = (a + r_min * (c['plan'] - a)) / b * 100.0
        out.append((x, f, c['w']))
    return out


def win_probability(cases, r_bid, s_guess, r_min):
    """r_bid 정책으로 썼다면 이겼을 사례의 비율: 하한 이상(f <= x)이고 실제 낙찰자보다 낮음(x < w)."""
    if not cases:
        return 0.0
    return sum(1 for x, f, w in policy_bounds(cases, r_bid, s_guess, r_min) if f <= x < w) / len(cases)


def outcomes(cases, r_bid, s_guess, r_min):
    """r_bid 정책으로 썼다면 사례들이 어떻게 갈렸는지 (낙찰, 하한 미달 탈락, 하한은 넘었지만 더 낮은 가격에 패배) 비율. 합은 1."""
    if not cases:
        return 0.0, 0.0, 0.0
    win = below = 0
    for x, f, w in policy_bounds(cases, r_bid, s_guess, r_min):
        if x < f:
            below += 1                      # 낙찰하한 아래로 써서 탈락
        elif x < w:
            win += 1
    n = len(cases)
    return win / n, below / n, (n - win - below) / n


def curve(cases, s_guess, r_min, step=0.0001):
    """[(r_bid, P)]"""
    lo = max(0.5, r_min - 0.03)
    hi = min(1.0, max(c['r_w'] for c in cases) + 0.01)
    out, i = [], 0
    while True:
        r = round(lo + i * step, 6)
        if r > hi:
            break
        out.append((r, win_probability(cases, r, s_guess, r_min)))
        i += 1
    return out


def recommend(cases, s_guess, r_min, targets=DEFAULT_TARGETS, step=0.0001):
    """목표 확률별 추천 비율. 같은 확률이면 더 높은 가격(이윤이 큰 쪽)을 고른다."""
    cv = curve(cases, s_guess, r_min, step)
    peak_p = max(p for _, p in cv)
    peak_r = max(r for r, p in cv if p >= peak_p - 1e-12)
    def out3(r):
        w, b, l = outcomes(cases, r, s_guess, r_min)
        return {'p': w, 'below_floor': b, 'lost_to_lower': l}

    out = {'peak': dict({'r': peak_r}, **out3(peak_r)), 'targets': [], 'risk_targets': []}
    for t in targets:
        ok = [r for r, p in cv if p >= t - 1e-12]
        if ok:
            r = max(ok)
            out['targets'].append(dict({'target': t, 'reachable': True, 'r': r, 'r_low': min(ok), 'r_high': r}, **out3(r)))
        else:
            out['targets'].append({'target': t, 'reachable': False, 'r': None, 'p': None, 'below_floor': None, 'lost_to_lower': None, 'r_low': None, 'r_high': None})
    # 안전 쪽: 하한 미달 위험이 risk 이하가 되는 가장 낮은 가격(그 아래는 더 자주 하한 아래로 떨어진다)
    grid = [r for r, _ in cv]
    for risk in RISK_TARGETS:
        r_ok = next((r for r in grid if outcomes(cases, r, s_guess, r_min)[1] <= risk + 1e-12), None)
        out['risk_targets'].append(dict({'risk': risk, 'reachable': r_ok is not None, 'r': r_ok}, **(out3(r_ok) if r_ok is not None else {'p': None, 'below_floor': None, 'lost_to_lower': None})))
    return out, cv


def target_price(base, a, r_bid, s_guess):
    """이번 공고(기초금액 base, A값 a)에서 비율 r_bid에 해당하는 투찰 금액(원)과 기초금액 대비 %."""
    price = a + r_bid * (base * s_guess / 100.0 - a)
    return price, price / base * 100.0


def floor_price(base, a, r_min, sajung):
    """사정률 sajung(%)일 때 낙찰하한가(원)."""
    return a + r_min * (base * sajung / 100.0 - a)


def _q(sorted_vals, p):
    return sorted_vals[min(len(sorted_vals) - 1, max(0, int(round(p / 100 * (len(sorted_vals) - 1)))))]


def describe(cases):
    rw = sorted(c['r_w'] * 100 for c in cases)
    s = sorted(c['sajung'] for c in cases)
    ap = sorted(c['a'] / c['plan'] * 100 for c in cases)
    return {'n': len(cases),
            'r_w': {'min': round(rw[0], 3), 'p10': round(_q(rw, 10), 3), 'median': round(statistics.median(rw), 3), 'p90': round(_q(rw, 90), 3)},
            'sajung': {'median': round(statistics.median(s), 3), 'p10': round(_q(s, 10), 3), 'p90': round(_q(s, 90), 3), 'min': round(s[0], 3), 'max': round(s[-1], 3)},
            'a_over_plan': {'median': round(statistics.median(ap), 3), 'p10': round(_q(ap, 10), 3), 'p90': round(_q(ap, 90), 3)}}


def filter_cases(cases, band_id=None, participants=None):
    """같은 추정가격 구간(낙찰하한 식이 같은 사례)과 경쟁 규모(참가업체 수 구간)로 좁힌다.
    좁힌 결과가 MIN_CASES보다 적으면 그 조건은 적용하지 않고 notes에 남긴다."""
    notes = []
    out = cases
    if band_id:
        near = [c for c in out if c['band'] == band_id]
        if len(near) >= MIN_CASES:
            out = near
        else:
            notes.append(f'같은 추정가격 구간의 사례가 {len(near)}건뿐이라 구간으로 좁히지 않고 전체 {len(out)}건으로 계산했습니다(구간이 다르면 하한 식이 달라 정확도가 떨어집니다).')
    if participants in PARTICIPANT_BANDS:
        label, lo, hi = PARTICIPANT_BANDS[participants]
        near = [c for c in out if lo <= c['n'] < hi]
        if len(near) >= MIN_CASES:
            out = near
        else:
            notes.append(f'참가업체 {label} 사례가 {len(near)}건뿐이라 경쟁 규모로 좁히지 않았습니다.')
    return out, notes


def segment_table(cases, r_min):
    """참가업체 수별 분포와 확률이 가장 높은 비율. 사례가 8건 미만인 구간은 뺀다."""
    def one(sub):
        sg = sajung_guess(sub)
        cv = curve(sub, sg, r_min, 0.0002)
        pk = max(p for _, p in cv)
        rw = sorted(c['r_w'] * 100 for c in sub)
        return {'n': len(sub), 'r_w_median': round(statistics.median(rw), 3), 'r_w_p10': round(_q(rw, 10), 3), 'r_w_p90': round(_q(rw, 90), 3),
                'peak_r': round(max(r for r, p in cv if p >= pk - 1e-12) * 100, 3), 'peak_p': round(pk, 4)}
    out = {'participants': []}
    for key, (label, lo, hi) in PARTICIPANT_BANDS.items():
        sub = [c for c in cases if lo <= c['n'] < hi]
        if len(sub) >= 8:
            out['participants'].append(dict(one(sub), key=key, label=label))
    return out


def backtest(train_cases, test_cases, r_min_fn, targets=DEFAULT_TARGETS):
    """예전(학습) 사례로 정한 정책(비율 r_bid, 사정률 가정)을 최근(검증) 사례에 그대로 썼다면 실제로 몇 %를 이겼을지.
    r_min_fn(case) -> 그 사례에 적용할 낙찰하한 비율(구간별 규정). 비교용으로 '학습 낙찰자 비율의 하위 10%'(낮게 쓰기)와 중앙값도 같이 본다."""
    if len(train_cases) < MIN_CASES or len(test_cases) < 5:
        return None
    sg = sajung_guess(train_cases)

    def evaluate(cs, r):
        if not cs:
            return 0.0
        wins = 0
        for c in cs:
            b, a = c['base'], c['a']
            x = (a + r * (b * sg / 100.0 - a)) / b * 100.0
            f = (a + r_min_fn(c) * (c['plan'] - a)) / b * 100.0
            wins += 1 if f <= x < c['w'] else 0
        return wins / len(cs)

    r_min_train = statistics.median(r_min_fn(c) for c in train_cases)
    cv = []
    lo, hi = max(0.5, r_min_train - 0.03), min(1.0, max(c['r_w'] for c in train_cases) + 0.01)
    r = lo
    while r <= hi:
        cv.append((round(r, 6), evaluate(train_cases, r)))
        r += 0.0002
    peak_p = max(p for _, p in cv)
    peak_r = max(r for r, p in cv if p >= peak_p - 1e-12)
    rows = []
    for t in targets:
        ok = [r for r, p in cv if p >= t - 1e-12]
        if ok:
            rr = max(ok)
            rows.append({'key': f'target_{int(round(t * 100))}', 'label': f'목표 확률 {int(round(t * 100))}%', 'r': rr,
                         'predicted': evaluate(train_cases, rr), 'realized': evaluate(test_cases, rr)})
    rows.append({'key': 'peak', 'label': '확률이 가장 높은 지점', 'r': peak_r, 'predicted': peak_p, 'realized': evaluate(test_cases, peak_r)})
    rw = sorted(c['r_w'] for c in train_cases)
    for key, label, r in (('median', '학습 낙찰자 비율의 중앙값 그대로', statistics.median(rw)),
                          ('low10', '학습 낙찰자 비율 하위 10% (낮게 쓰기)', _q(rw, 10))):
        rows.append({'key': key, 'label': label, 'r': round(r, 6), 'predicted': evaluate(train_cases, r), 'realized': evaluate(test_cases, r)})
    return {'train_n': len(train_cases), 'test_n': len(test_cases), 'sajung_guess': round(sg, 3), 'r_min': round(r_min_train, 5), 'rows': rows}
