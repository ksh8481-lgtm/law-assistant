"""
낙찰가 예측 - 과거 낙찰 사례로 "얼마에 투찰하면 낙찰될 확률이 얼마인가"를 계산한다(AI가 아니라 통계 계산).

[예전 방식의 문제]
- 낙찰률(낙찰금액 ÷ 예정가격)로만 분포를 봤는데, 투찰할 때는 예정가격을 모르고 기초금액만 안다. 그래서 "기초금액 × 낙찰률 ± 3%"로 대충 환산했다.
  실제 공고 25건으로 확인하니 예정가격÷기초금액(사정률)은 98.5%~101.1%로 퍼져 있어, 소액 공사에서는 ±3% 오차가 낙찰 구간(1%p)보다 훨씬 컸다.
- 백테스트가 "추천 낙찰률이 실제 낙찰자의 낙찰률보다 낮거나 같으면 이긴다"고만 봐서, 낮게 쓸수록 승률이 높게 나왔다(최소값 추천 → 승률 100%).
  실제로는 낙찰하한(예정가격 × 낙찰하한율) 아래로 쓰면 무조건 탈락한다.

[새 방식]
1. 과거 사례마다 기초금액을 조회해 "낙찰금액 ÷ 기초금액(w)"과 사정률(예정가격 ÷ 기초금액 = 낙찰금액 ÷ 낙찰률 ÷ 기초금액)을 구한다.
   이렇게 하면 기초금액만 알아도 투찰 금액을 바로 낼 수 있고, ±3% 가정이 사라진다.
2. 사례 i에서 기초금액의 x%로 투찰했다면 이겼을 조건 = 낙찰하한 이상(f_i ≤ x) 이면서 실제 낙찰자보다 낮음(x < w_i).
   f_i = 사정률_i × 낙찰하한율 (기초금액 대비 %). 낙찰확률 P(x) = 이 조건을 만족한 사례의 비율.
   P(x)는 하한 근처에서 올랐다가 낙찰 가격대를 넘으면 내려가는 산 모양이다. 목표 확률별로 "그 확률 이상인 가장 높은 가격"(이윤이 큰 쪽)을 추천한다.
3. 낙찰하한율은 공고문 값을 입력받고, 없으면 낙찰률 분포의 아래쪽 끝에서 추정한다(낙찰자는 모두 하한 이상이므로).
4. 참가업체 수·규모별로 따로 보여 준다(경쟁이 심할수록 낙찰률이 좁게 몰린다).

과거에 이랬다는 통계일 뿐 이번 입찰의 낙찰을 보장하지 않는다.
"""
import statistics

SAJUNG_MIN, SAJUNG_MAX = 96.5, 103.5     # 복수예비가격 범위(±3%) 안. 벗어나면 기초금액·금액 기준(부가세 등)이 달라 값이 맞지 않는 사례로 보고 뺀다
MIN_CASES = 15                           # 이보다 적으면 확률이 의미 없어 계산하지 않는다
DEFAULT_TARGETS = (0.3, 0.4, 0.5, 0.6, 0.7)   # 목표 낙찰 확률. 과거 사례로 도달할 수 없는 확률(예: 최대 53%인데 70%)은 '도달 불가'로 표시한다

PARTICIPANT_BANDS = {'lt20': ('1~19곳', 1, 20), '20_59': ('20~59곳', 20, 60), '60_119': ('60~119곳', 60, 120), 'ge120': ('120곳 이상', 120, 10 ** 9)}
SIZE_BANDS = [('2억원 미만', 0, 2e8), ('2억~5억원', 2e8, 5e8), ('5억~20억원', 5e8, 2e9), ('20억원 이상', 2e9, 1e15)]


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def build_cases(items, base_map):
    """낙찰 목록 + {(공고번호, 차수): 기초금액}으로 분석 사례를 만든다. 기초금액이 없거나 값이 이상한 사례는 뺀다."""
    cases = []
    for it in items:
        rate, amt = _f(it.get('sucsfbidRate')), _f(it.get('sucsfbidAmt'))
        base = base_map.get((it.get('bidNtceNo'), it.get('bidNtceOrd') or '000'))
        if not rate or not amt or not base or not (50.0 < rate <= 100.0) or amt <= 0 or base <= 0:
            continue
        plan = amt / (rate / 100.0)
        sajung = plan / base * 100.0
        if not (SAJUNG_MIN <= sajung <= SAJUNG_MAX):
            continue
        try:
            n = int(float(it.get('prtcptCnum') or 0))
        except (TypeError, ValueError):
            n = 0
        cases.append({'no': it.get('bidNtceNo'), 'amt': amt, 'rate': rate, 'base': base, 'plan': plan, 'sajung': sajung,
                      'w': amt / base * 100.0, 'n': n, 'date': it.get('rlOpengDt') or ''})
    return cases


def estimate_floor_rate(rates):
    """낙찰률 목록에서 낙찰하한율(%)을 추정한다. 낙찰자는 모두 하한 이상이므로 분포의 아래쪽 끝이 하한 근처다.
    중앙값보다 6%p 넘게 낮은 사례(다른 낙찰 방식)는 빼고, 하위 2% 지점을 쓴다. 사례가 5건 미만이면 None."""
    rs = sorted(r for r in (_f(x) for x in rates) if r is not None and 50.0 < r <= 100.0)
    if len(rs) < 5:
        return None
    med = statistics.median(rs)
    core = [r for r in rs if r >= med - 6.0]
    return round(core[int(len(core) * 0.02)], 3)


def bounds(cases, floor_rate):
    """사례별 (낙찰하한 f, 낙찰 w) - 둘 다 기초금액 대비 %."""
    return [(c['sajung'] * floor_rate / 100.0, c['w']) for c in cases]


def win_probability(bnds, x):
    """기초금액의 x%로 투찰했을 때 이겼을 사례의 비율: 하한 이상(f <= x)이고 실제 낙찰자보다 낮음(x < w)."""
    if not bnds:
        return 0.0
    return sum(1 for f, w in bnds if f <= x < w) / len(bnds)


def curve(cases, floor_rate, step=0.01):
    """[(x, P)] - 하한이 가장 낮은 사례부터 낙찰이 가장 높은 사례까지 step(%p) 간격."""
    b = bounds(cases, floor_rate)
    lo, hi = min(f for f, _ in b), max(w for _, w in b)
    out = []
    i = 0
    while True:
        x = round(lo + i * step, 4)
        if x > hi + step:
            break
        out.append((x, win_probability(b, x)))
        i += 1
    return out


def recommend(cases, floor_rate, targets=DEFAULT_TARGETS, step=0.01):
    """목표 확률별 추천 투찰률. 같은 확률이면 더 높은 가격(이윤이 큰 쪽)을 고른다."""
    cv = curve(cases, floor_rate, step)
    peak_p = max(p for _, p in cv)
    peak_x = max(x for x, p in cv if p >= peak_p - 1e-12)
    b = bounds(cases, floor_rate)
    out = {'peak': {'x': peak_x, 'p': peak_p}, 'targets': [],
           'floor_x_median': round(statistics.median(f for f, _ in b), 3), 'w_median': round(statistics.median(w for _, w in b), 3)}
    for t in targets:
        ok = [x for x, p in cv if p >= t - 1e-12]
        if ok:
            out['targets'].append({'target': t, 'reachable': True, 'x': max(ok), 'p': win_probability(b, max(ok)), 'x_low': min(ok), 'x_high': max(ok)})
        else:
            out['targets'].append({'target': t, 'reachable': False, 'x': None, 'p': None, 'x_low': None, 'x_high': None})
    return out, cv


def _q(sorted_vals, p):
    return sorted_vals[min(len(sorted_vals) - 1, max(0, int(round(p / 100 * (len(sorted_vals) - 1)))))]


def describe(cases):
    w = sorted(c['w'] for c in cases)
    s = sorted(c['sajung'] for c in cases)
    return {'n': len(cases),
            'w': {'median': round(statistics.median(w), 3), 'mean': round(statistics.mean(w), 3), 'p10': round(_q(w, 10), 3), 'p90': round(_q(w, 90), 3),
                  'min': round(w[0], 3), 'max': round(w[-1], 3)},
            'sajung': {'median': round(statistics.median(s), 3), 'p10': round(_q(s, 10), 3), 'p90': round(_q(s, 90), 3), 'min': round(s[0], 3), 'max': round(s[-1], 3)}}


def filter_cases(cases, base=None, participants=None):
    """비슷한 규모(기초금액 0.5~2배)와 경쟁 규모(참가업체 수 구간)로 좁힌다. 좁힌 결과가 MIN_CASES보다 적으면 그 조건은 적용하지 않고 notes에 남긴다."""
    notes = []
    out = cases
    if base:
        near = [c for c in out if 0.5 * base <= c['base'] <= 2.0 * base]
        if len(near) >= MIN_CASES:
            out = near
        else:
            notes.append(f'기초금액과 비슷한 규모(0.5~2배)의 사례가 {len(near)}건뿐이라 규모로 좁히지 않고 전체 {len(out)}건으로 계산했습니다.')
    if participants in PARTICIPANT_BANDS:
        label, lo, hi = PARTICIPANT_BANDS[participants]
        near = [c for c in out if lo <= c['n'] < hi]
        if len(near) >= MIN_CASES:
            out = near
        else:
            notes.append(f'참가업체 {label} 사례가 {len(near)}건뿐이라 경쟁 규모로 좁히지 않았습니다.')
    return out, notes


def segment_table(cases, floor_rate):
    """참가업체 수별·규모별 분포와 확률이 가장 높은 투찰률. 사례가 8건 미만인 구간은 뺀다."""
    def one(sub):
        b = bounds(sub, floor_rate)
        w = sorted(c['w'] for c in sub)
        cv = curve(sub, floor_rate, 0.02)
        pk = max(p for _, p in cv)
        return {'n': len(sub), 'w_median': round(statistics.median(w), 3), 'w_p10': round(_q(w, 10), 3), 'w_p90': round(_q(w, 90), 3),
                'spread': round(_q(w, 90) - _q(w, 10), 3), 'peak_x': max(x for x, p in cv if p >= pk - 1e-12), 'peak_p': round(pk, 4)}
    out = {'participants': [], 'size': []}
    for key, (label, lo, hi) in PARTICIPANT_BANDS.items():
        sub = [c for c in cases if lo <= c['n'] < hi]
        if len(sub) >= 8:
            out['participants'].append(dict(one(sub), key=key, label=label))
    for label, lo, hi in SIZE_BANDS:
        sub = [c for c in cases if lo <= c['base'] < hi]
        if len(sub) >= 8:
            out['size'].append(dict(one(sub), label=label))
    return out


def backtest(train_cases, test_cases, floor_rate=None, targets=DEFAULT_TARGETS):
    """예전(학습) 사례로 정한 투찰률을 최근(검증) 사례에 그대로 썼다면 실제로 몇 %를 이겼을지.
    같은 낙찰하한율(학습 구간에서 추정)로 판정한다. 비교용으로 '낙찰금액÷기초금액 하위 10%'(예전 방식처럼 낮게 쓰기)와 중앙값도 같이 본다."""
    if len(train_cases) < MIN_CASES or len(test_cases) < 5:
        return None
    floor = floor_rate or estimate_floor_rate([c['rate'] for c in train_cases])
    if floor is None:
        return None
    rec, _cv = recommend(train_cases, floor, targets)
    tb = bounds(test_cases, floor)
    trb = bounds(train_cases, floor)
    w_train = sorted(c['w'] for c in train_cases)
    rows = []
    for t in rec['targets']:
        if t['reachable']:
            rows.append({'key': f"target_{int(round(t['target'] * 100))}", 'label': f"목표 확률 {int(round(t['target'] * 100))}%", 'x': t['x'],
                         'predicted': t['p'], 'realized': win_probability(tb, t['x'])})
    rows.append({'key': 'peak', 'label': '확률이 가장 높은 지점', 'x': rec['peak']['x'], 'predicted': rec['peak']['p'], 'realized': win_probability(tb, rec['peak']['x'])})
    for key, label, x in (('median', '낙찰금액÷기초금액 중앙값 그대로', statistics.median(w_train)),
                          ('low10', '낙찰금액÷기초금액 하위 10% (낮게 쓰기)', _q(w_train, 10))):
        rows.append({'key': key, 'label': label, 'x': round(x, 3), 'predicted': win_probability(trb, x), 'realized': win_probability(tb, x)})
    return {'floor_rate': floor, 'train_n': len(train_cases), 'test_n': len(test_cases), 'rows': rows}
