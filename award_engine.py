"""
지방자치단체 입찰시 낙찰자 결정기준 - 사업수행능력평가(PQ) 대상 기술용역 적격심사 계산 엔진.

pq_engine이 "PQ 점수"를 계산하면, 이 모듈은 그 점수를 받아 적격심사 종합평점을 계산하고 낙찰자를 정한다.

  종합평점 = PQ 환산점수 + 책임기술자 경력 + 지역업체 참여도 + 경영상태 + 입찰가격 평점 - 감점
  낙찰자   = 예정가격 이하 최저가 입찰자부터 순서대로 심사해 종합평점이 적격통과점수 이상인 첫 입찰자
             (동일가격이면 PQ 점수가 높은 자, 그것도 같으면 추첨)

규정 값(배점·산식 계수·적격통과점수)은 award_specs/*.json에 조항 번호와 함께 두고 이 모듈은 그 값대로 계산만 한다.
AI는 점수를 만들지 않는다 - 항상 입력값에서 결정적으로 계산하며, 입찰사마다 계산 근거(basis)를 풀어 쓴다.
점수 계산은 Decimal로 해서 부동소수 오차 때문에 통과점수 경계(예: 91.9999..)가 뒤집히지 않게 한다.
"""
import json
import os
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

_SPEC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'award_specs')
_SPEC_CACHE = {}

MAX_BIDDERS = 40


class AwardInputError(ValueError):
    """사용자가 고칠 수 있는 입력 오류(화면에 그대로 보여 준다)."""


# ---------------------------------------------------------------- 명세 로딩
def list_specs():
    out = []
    for fn in sorted(os.listdir(_SPEC_DIR)):
        if fn.endswith('.json'):
            spec = load_spec(fn[:-5])
            out.append({'id': spec['id'], 'name': spec['name'], 'short': spec.get('short', spec['name']),
                        'status': 'ready', 'source': spec.get('source', {})})
    return out


def load_spec(spec_id: str) -> dict:
    if spec_id not in _SPEC_CACHE:
        path = os.path.join(_SPEC_DIR, f'{spec_id}.json')
        if not os.path.isfile(path) or os.path.basename(path) != f'{spec_id}.json':
            raise KeyError(spec_id)
        with open(path, encoding='utf-8') as f:
            _SPEC_CACHE[spec_id] = json.load(f)
    return _SPEC_CACHE[spec_id]


# ---------------------------------------------------------------- 숫자 도우미
def _d(v, field, *, required=True, minimum=None, maximum=None):
    """입력값을 Decimal로. 비어 있으면 required=False일 때만 None. 범위를 벗어나면 AwardInputError."""
    if v is None or (isinstance(v, str) and v.strip() == ''):
        if required:
            raise AwardInputError(f'{field}을(를) 입력해 주세요.')
        return None
    if isinstance(v, bool):
        raise AwardInputError(f'{field}에 숫자를 입력해 주세요.')
    try:
        x = Decimal(str(v).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        raise AwardInputError(f'{field}에 숫자를 입력해 주세요. (입력값: {v})')
    if not x.is_finite():
        raise AwardInputError(f'{field}에 올바른 숫자를 입력해 주세요.')
    if minimum is not None and x < Decimal(str(minimum)):
        raise AwardInputError(f'{field}은(는) {minimum} 이상이어야 합니다.')
    if maximum is not None and x > Decimal(str(maximum)):
        raise AwardInputError(f'{field}은(는) {maximum} 이하여야 합니다.')
    return x


def _q(x: Decimal, digits: int) -> Decimal:
    return x.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def fmt(x, digits=4) -> str:
    """점수 표시: 불필요한 0을 뺀다(92.0000 -> 92, 58.3680 -> 58.368). 통과점수 경계가 반올림으로 가려지지 않도록 반올림은 4자리에서만 한다."""
    if x is None:
        return ''
    s = format(_q(Decimal(x), digits), 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s or '0'


def _tier(value: Decimal, tiers):
    """tiers=[[기준, 점수], ...] (기준 큰 것부터). value가 기준 이상인 첫 구간의 점수, 없으면 0. 구간 판정에는 반올림하지 않은 값을 쓴다."""
    for lo, score in tiers:
        if value >= Decimal(str(lo)):
            return Decimal(str(score)), Decimal(str(lo))
    return Decimal(0), None


# ---------------------------------------------------------------- 구간 선택
def pick_band(spec: dict, estimated_price: Decimal) -> dict:
    for band in sorted(spec['bands'], key=lambda b: -b['min_estimated_price']):
        if estimated_price >= Decimal(str(band['min_estimated_price'])):
            return band
    return spec['bands'][-1]


# ---------------------------------------------------------------- 입찰가격 평점
def price_score(band: dict, ratio_raw: Decimal, ratio_digits: int):
    """(평점, 설명). ratio_raw = 입찰가격 / 예정가격(반올림 전).
    예정가격 이하이면서 cap_from_ratio 이상이면 cap_score. 그 밖에는 top - slope × |center - 비율| × 100 (최저 min_score)."""
    p = band['price']
    cap_from = Decimal(str(p['cap_from_ratio']))
    if cap_from <= ratio_raw <= 1:
        return Decimal(str(p['cap_score'])), (
            f"입찰가격/예정가격 = {fmt(ratio_raw * 100)}% → 예정가격의 {fmt(cap_from * 100)}% 이상({fmt(Decimal(str(p['cap_score'])))}점 고정)")
    r = _q(ratio_raw, ratio_digits)
    center = Decimal(str(p['center']))
    raw = Decimal(str(p['top'])) - Decimal(str(p['slope'])) * abs(center - r) * 100
    score = max(raw, Decimal(str(p['min_score'])))
    floor_note = f' → 최저평점 {fmt(Decimal(str(p["min_score"])))}점 적용' if raw < Decimal(str(p['min_score'])) else ''
    slope = fmt(Decimal(str(p['slope'])))
    slope_txt = '' if slope == '1' else f'{slope} × '
    return score, (f"입찰가격/예정가격 = {fmt(r, ratio_digits)}(소수점 다섯째 자리 반올림) → "
                   f"{fmt(Decimal(str(p['top'])))} - {slope_txt}|{center} - {fmt(r, ratio_digits)}| × 100 = {fmt(raw)}점{floor_note}")


# ---------------------------------------------------------------- 평가
def evaluate(spec_id: str, project: dict, bidders: list) -> dict:
    spec = load_spec(spec_id)
    if not isinstance(bidders, list) or not bidders:
        raise AwardInputError('입찰사를 1개 이상 입력해 주세요.')
    if len(bidders) > MAX_BIDDERS:
        raise AwardInputError(f'입찰사는 최대 {MAX_BIDDERS}개까지 한 번에 평가할 수 있습니다.')
    project = project or {}

    est = _d(project.get('estimated_price'), '추정가격', minimum=1)
    sched = _d(project.get('planned_price'), '예정가격', minimum=1)
    band = pick_band(spec, est)
    w = {k: Decimal(str(v)) for k, v in band['weights'].items()}
    local_applied = bool(project.get('local_applied', True))
    local_kind = project.get('local_kind', 'main')
    if local_kind not in spec['local']['tiers']:
        raise AwardInputError('지역업체 참여도 구분이 올바르지 않습니다.')
    career_excluded = bool(project.get('career_excluded', False))
    digits = spec['rounding']['ratio_digits']
    notes = []

    # 지역업체 참여도를 적용하지 않으면 그 배점은 PQ 환산 배점에 합산한다([별표 1] 제1호 주2) 나))
    pq_weight = w['pq']
    local_weight = w['local']
    if not local_applied:
        pq_weight = pq_weight + local_weight
        local_weight = Decimal(0)
        notes.append(f"지역업체 참여도를 적용하지 않아 그 배점 {fmt(w['local'])}점을 PQ 환산 배점에 합산했습니다"
                     f"(PQ × {fmt(pq_weight)}/100). 이 내용은 입찰공고에 명시되어 있어야 합니다.")
    career_weight = w['career']
    if career_excluded:
        notes.append(f"책임기술자 경력 평가를 입찰공고에서 제외한 경우로 보고 모든 입찰사에게 배점한도 {fmt(career_weight)}점을 줍니다.")

    rows = []
    for i, b in enumerate(bidders):
        if not isinstance(b, dict):
            raise AwardInputError(f'{i + 1}번째 입찰사 입력이 올바르지 않습니다.')
        name = (str(b.get('name') or '').strip() or f'입찰사 {i + 1}')[:60]
        label = f'{name}'
        pq = _d(b.get('pq_score'), f'{label}의 PQ 점수', minimum=0, maximum=120)
        ded = _d(b.get('penalty_deduction'), f'{label}의 벌점 감점', required=False, minimum=0, maximum=20) or Decimal(0)
        price = _d(b.get('bid_price'), f'{label}의 입찰가격', minimum=1)
        basis = []

        # 1) PQ 환산: (벌점 감점 적용 전 점수, 100점 한도) × 환산배점/100 - 벌점 감점(환산하지 않고 그대로)
        pq_cap = Decimal(str(spec['pq_conversion']['cap']))
        pre = min(pq + ded, pq_cap)
        pq_conv = _q(pre * pq_weight / 100, 4) - ded
        if ded > 0:
            basis.append(f"PQ 환산: ({fmt(pq)} + 벌점 감점 {fmt(ded)}, 100점 한도 = {fmt(pre)}) × {fmt(pq_weight)}/100 - 벌점 감점 {fmt(ded)} = {fmt(pq_conv)}점")
        else:
            capped = ' (100점 한도 적용)' if pq > pq_cap else ''
            basis.append(f"PQ 환산: {fmt(min(pq, pq_cap))}{capped} × {fmt(pq_weight)}/100 = {fmt(pq_conv)}점")

        # 2) 책임기술자 경력
        if career_excluded:
            career = career_weight
            basis.append(f"책임기술자 경력: 평가 제외 공고 → 배점한도 {fmt(career)}점")
        else:
            cr = _d(b.get('career_ratio'), f'{label}의 책임기술자 경력 비율', minimum=0, maximum=100)
            career, lo = _tier(cr, spec['career']['tiers'])
            basis.append(f"책임기술자 경력: 합산 비율 {fmt(cr)}% → " + (f"{fmt(lo)}% 이상 구간 {fmt(career)}점" if lo is not None else '20% 미만 0점'))

        # 3) 지역업체 참여도
        if not local_applied:
            local = Decimal(0)
            basis.append('지역업체 참여도: 적용하지 않음(PQ 환산 배점에 합산)')
        elif b.get('local_solo'):
            local = Decimal(0)
            basis.append('지역업체 참여도: 지역업체 단독 참여 → 0점(제4절 1.라)')
        else:
            lr = _d(b.get('local_ratio'), f'{label}의 지역업체 참여비율', minimum=0, maximum=100)
            local, lo = _tier(lr, spec['local']['tiers'][local_kind])
            basis.append(f"지역업체 참여도: 합산 참여비율 {fmt(lr)}% → " + (f"{fmt(lo)}% 이상 구간 {fmt(local)}점" if lo is not None else '기준 미달 0점'))

        # 4) 경영상태
        mode = b.get('mgmt_mode') or 'full'
        mgmt_max = Decimal(str(spec['mgmt']['max']))
        if mode == 'full':
            mgmt = mgmt_max
            basis.append(f"경영상태: PQ 점수에 경영상태가 반영된 경우 → 만점 {fmt(mgmt)}점")
        elif mode == 'credit':
            tier = next((t for t in spec['mgmt']['credit_tiers'] if t['id'] == b.get('mgmt_tier')), None)
            if tier is None:
                raise AwardInputError(f'{label}의 신용평가 등급 구간을 선택해 주세요.')
            mgmt = Decimal(str(tier['score']))
            basis.append(f"경영상태: 신용평가 {tier['label']} → {fmt(mgmt)}점")
        elif mode == 'score':
            mgmt = _d(b.get('mgmt_score'), f'{label}의 경영상태 점수', minimum=0, maximum=float(mgmt_max))
            basis.append(f"경영상태: 직접 입력 {fmt(mgmt)}점(배점 {fmt(mgmt_max)}점 이내)")
        else:
            raise AwardInputError(f'{label}의 경영상태 입력 방식이 올바르지 않습니다.')

        # 5) 입찰가격
        ratio_raw = price / sched
        over = price > sched
        if over:
            pscore = Decimal(0)
            basis.append(f"입찰가격: 예정가격({fmt(sched)}원)을 초과해 심사 대상에서 제외")
        else:
            pscore, ptxt = price_score(band, ratio_raw, digits)
            basis.append(f"입찰가격: {ptxt}")

        # 6) 감점
        penalty = Decimal(0)
        if b.get('tech_shortage'):
            d = Decimal(str(spec['deductions']['tech_shortage']['points']))
            penalty += d
            basis.append(f"기술인력 보유 미달: {fmt(d)}점")
        wa = _d(b.get('wage_arrears_count'), f'{label}의 임금체불 공개 횟수', required=False, minimum=0, maximum=100) or Decimal(0)
        if wa > 0:
            per = Decimal(str(spec['deductions']['wage_arrears']['per_count']))
            cap = Decimal(str(spec['deductions']['wage_arrears']['cap']))
            d = max(per * wa, cap)
            penalty += d
            basis.append(f"임금체불 공개 {fmt(wa)}회: {fmt(per)} × {fmt(wa)} = {fmt(per * wa)}점" + (f" → 한도 {fmt(cap)}점 적용" if per * wa < cap else ''))

        total = pq_conv + career + local + mgmt + pscore + penalty
        rows.append({
            'index': i, 'name': name, 'pq_score': float(pq), 'bid_price': float(price), 'price_ratio': float(_q(ratio_raw, 6)),
            'over_planned': over,
            'scores': {'pq': float(pq_conv), 'career': float(career), 'local': float(local), 'mgmt': float(mgmt),
                       'price': float(pscore), 'deduction': float(penalty)},
            'total': float(_q(total, 4)), 'total_exact': format(total, 'f'),
            'basis': basis, '_total': total, '_pq': pq, '_price': price,
        })

    pass_score = Decimal(str(band['pass_score']))
    _decide(rows, pass_score)
    maxima = {'pq': pq_weight, 'career': career_weight, 'local': local_weight, 'mgmt': w['mgmt'], 'price': w['price']}
    for r in rows:
        r['pass'] = r['_total'] >= pass_score
        r['shortfall'] = float(_q(max(pass_score - r['_total'], Decimal(0)), 4))
        for k in ('_total', '_pq', '_price'):
            r.pop(k)
    winner = next((r for r in rows if r['status'] == 'winner'), None)
    lottery = [r['index'] for r in rows if r['status'] == 'lottery']
    if winner is None and not lottery:
        notes.append(f"적격통과점수({fmt(pass_score)}점) 이상인 입찰사가 없습니다. 재공고입찰 등 후속 절차는 규정과 계약부서 판단에 따릅니다.")
    if lottery:
        notes.append('동일가격 최저가 입찰자의 종합평점·PQ 점수까지 같아 추첨으로 낙찰자를 정해야 합니다.')
    return {
        'spec_id': spec_id,
        'band': {'id': band['id'], 'label': band['label'], 'ref': band['ref'], 'pass_score': float(pass_score),
                 'pass_ref': band['pass_ref'], 'price_ref': band['price']['ref']},
        'weights': {k: float(v) for k, v in maxima.items()},
        'estimated_price': float(est), 'planned_price': float(sched),
        'results': rows,
        'winner_index': winner['index'] if winner else None,
        'lottery_indexes': lottery,
        'notes': notes,
        'source': spec['source'],
    }


def _decide(rows: list, pass_score: Decimal):
    """상태를 정한다. 예정가격 이하 입찰자를 입찰가격 낮은 순으로 묶어(동일가격 = 같은 묶음) 순서대로 심사한다.
    status: winner(낙찰자) / lottery(추첨 대상) / pass(통과했으나 같은 가격 묶음에서 PQ 점수가 낮음) /
            fail(적격통과점수 미달) / after(낙찰자 결정 이후라 심사하지 않음) / over(예정가격 초과로 제외)"""
    for r in rows:
        r['status'] = 'over' if r['over_planned'] else None
        r['review_order'] = None
    eligible = [r for r in rows if not r['over_planned']]
    groups = {}
    for r in eligible:
        groups.setdefault(r['_price'], []).append(r)
    done = False
    order = 0
    for price in sorted(groups):
        grp = groups[price]
        order += 1
        for r in grp:
            r['review_order'] = order
        if done:
            for r in grp:
                r['status'] = 'after'
            continue
        passing = [r for r in grp if r['_total'] >= pass_score]
        for r in grp:
            r['status'] = 'pass' if r in passing else 'fail'
        if passing:
            best_pq = max(r['_pq'] for r in passing)
            top = [r for r in passing if r['_pq'] == best_pq]
            if len(top) == 1:
                top[0]['status'] = 'winner'
            else:
                for r in top:
                    r['status'] = 'lottery'
            done = True
