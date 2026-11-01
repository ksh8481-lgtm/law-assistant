"""
적격심사 거꾸로 계산: "얼마에 입찰해야 통과하나?"

award_engine.evaluate()가 "입찰가격을 알 때 종합평점·낙찰자"를 구한다면, 이 모듈은 그 반대다. 용역비(추정가격·예정가격)와 입찰사의 PQ 점수 등을 알 때
**입찰가격을 예정가격의 몇 %(몇 원)로 써야 종합평점이 적격통과점수 이상인지**를 구한다.

입찰가격 평점은 예정가격의 88%에서 최고점이고 양쪽으로 줄어드는 모양(평점 = 만점 - 계수 × |88% - 비율| × 100, 예정가격 근처는 고정점수)이라
통과하는 입찰가격은 하나의 구간 [하한, 상한]이 된다.
- 하한 = 통과하는 가장 낮은 입찰가격. 이보다 낮게 쓰면 가격 평점이 모자라 탈락한다. 최저가부터 심사하므로 가장 경쟁력 있는 값이다.
- 상한 = 통과하는 가장 높은 입찰가격. 예정가격 고정점수 구간까지 통과하면 예정가격(100%)이다.
- PQ 점수가 너무 낮아 가격을 가장 유리하게(88%) 써도 못 미치면 "통과 불가"와, 통과에 필요한 최소 PQ 점수를 알려 준다.

경계는 evaluate()가 쓰는 것과 같은 price_score()로 정확히 확인한다. 비율을 소수점 다섯째 자리에서 반올림하기 때문에 통과 경계가 반올림 구간의 끝
(예: 86.395%)에 걸리고, 원 단위 금액으로는 그 구간의 첫 원이 하한이 된다.
경력·지역업체 비율을 비워 두면 만점으로 가정(가장 유리한 경우)하고, 가정했다는 사실을 결과에 적는다.
"""
from decimal import Decimal

from award_engine import (AwardInputError, MAX_BIDDERS, _d, _q, _tier, fmt, load_spec, pick_band, price_score)


def required_price(spec_id: str, project: dict, bidders: list) -> dict:
    spec = load_spec(spec_id)
    if not isinstance(bidders, list) or not bidders:
        raise AwardInputError('입찰사를 1개 이상 입력해 주세요.')
    if len(bidders) > MAX_BIDDERS:
        raise AwardInputError(f'입찰사는 최대 {MAX_BIDDERS}개까지 한 번에 평가할 수 있습니다.')
    project = project or {}
    est = _d(project.get('estimated_price'), '추정가격(용역비)', minimum=1)
    sched = _d(project.get('planned_price'), '예정가격', required=False, minimum=1)
    band = pick_band(spec, est)
    w = {k: Decimal(str(v)) for k, v in band['weights'].items()}
    local_applied = bool(project.get('local_applied', True))
    local_kind = project.get('local_kind', 'main')
    if local_kind not in spec['local']['tiers']:
        raise AwardInputError('지역업체 참여도 구분이 올바르지 않습니다.')
    career_excluded = bool(project.get('career_excluded', False))
    digits = spec['rounding']['ratio_digits']
    pass_score = Decimal(str(band['pass_score']))
    pcfg = band['price']
    top, center = Decimal(str(pcfg['top'])), Decimal(str(pcfg['center']))
    pq_weight, local_weight = w['pq'], w['local']
    notes = []
    if not local_applied:
        pq_weight += local_weight
        local_weight = Decimal(0)
        notes.append(f"지역업체 참여도를 적용하지 않아 그 배점 {fmt(w['local'])}점을 PQ 환산 배점에 합산했습니다(PQ × {fmt(pq_weight)}/100).")
    if career_excluded:
        notes.append(f"책임기술자 경력 평가를 입찰공고에서 제외한 경우로 보고 배점한도 {fmt(w['career'])}점을 줍니다.")
    local_top = Decimal(str(spec['local']['tiers'][local_kind][0][1]))

    out_rows = []
    for i, b in enumerate(bidders):
        if not isinstance(b, dict):
            raise AwardInputError(f'{i + 1}번째 입찰사 입력이 올바르지 않습니다.')
        name = (str(b.get('name') or '').strip() or f'입찰사 {i + 1}')[:60]
        pq = _d(b.get('pq_score'), f'{name}의 PQ 점수', minimum=0, maximum=120)
        ded = _d(b.get('penalty_deduction'), f'{name}의 벌점 감점', required=False, minimum=0, maximum=20) or Decimal(0)
        assumptions = []

        # PQ 환산: (벌점 감점 적용 전 점수, 100점 한도) × 환산배점/100 - 벌점 감점(환산하지 않고 그대로)
        pq_cap = Decimal(str(spec['pq_conversion']['cap']))
        pre = min(pq + ded, pq_cap)
        pq_conv = _q(pre * pq_weight / 100, 4) - ded

        if career_excluded:
            career = w['career']
        else:
            cr = _d(b.get('career_ratio'), f'{name}의 책임기술자 경력 비율', required=False, minimum=0, maximum=100)
            if cr is None:
                career = w['career']
                assumptions.append(f"책임기술자 경력 비율을 입력하지 않아 만점({fmt(career)}점, 30% 이상)으로 가정했습니다.")
            else:
                career, _lo = _tier(cr, spec['career']['tiers'])
        if not local_applied or b.get('local_solo'):
            local = Decimal(0)
        else:
            lr = _d(b.get('local_ratio'), f'{name}의 지역업체 참여비율', required=False, minimum=0, maximum=100)
            if lr is None:
                local = local_top
                assumptions.append(f"지역업체 참여비율을 입력하지 않아 만점({fmt(local)}점)으로 가정했습니다.")
            else:
                local, _lo = _tier(lr, spec['local']['tiers'][local_kind])

        mode = b.get('mgmt_mode') or 'full'
        mgmt_max = Decimal(str(spec['mgmt']['max']))
        if mode == 'full':
            mgmt = mgmt_max
        elif mode == 'credit':
            tier = next((t for t in spec['mgmt']['credit_tiers'] if t['id'] == b.get('mgmt_tier')), None)
            if tier is None:
                raise AwardInputError(f'{name}의 신용평가 등급 구간을 선택해 주세요.')
            mgmt = Decimal(str(tier['score']))
        elif mode == 'score':
            mgmt = _d(b.get('mgmt_score'), f'{name}의 경영상태 점수', minimum=0, maximum=float(mgmt_max))
        else:
            raise AwardInputError(f'{name}의 경영상태 입력 방식이 올바르지 않습니다.')

        penalty = Decimal(0)
        if b.get('tech_shortage'):
            penalty += Decimal(str(spec['deductions']['tech_shortage']['points']))
        wa = _d(b.get('wage_arrears_count'), f'{name}의 임금체불 공개 횟수', required=False, minimum=0, maximum=100) or Decimal(0)
        if wa > 0:
            penalty += max(Decimal(str(spec['deductions']['wage_arrears']['per_count'])) * wa,
                           Decimal(str(spec['deductions']['wage_arrears']['cap'])))

        fixed = pq_conv + career + local + mgmt + penalty          # 입찰가격 평점을 뺀 나머지 합계
        need = pass_score - fixed                                  # 입찰가격 평점이 최소 이만큼은 있어야 통과
        row = {
            'index': i, 'name': name, 'pq_score': float(pq), 'assumptions': assumptions,
            'parts': {'pq': float(pq_conv), 'career': float(career), 'local': float(local), 'mgmt': float(mgmt), 'deduction': float(penalty)},
            'subtotal': float(_q(fixed, 4)), 'need_price_score': float(_q(max(need, Decimal(0)), 4)), 'price_score_max': float(top),
        }

        def ok(ratio, fixed=fixed):
            return fixed + price_score(band, ratio, digits)[0] >= pass_score

        if need > top:
            # 가격을 가장 유리하게(88%) 써도 못 미친다. 통과에 필요한 최소 PQ 점수를 구한다.
            need_conv = pass_score - (career + local + mgmt + penalty + top)
            pre_needed = (need_conv + ded) * 100 / pq_weight
            pq_needed = None
            if pre_needed <= pq_cap:
                v = pre_needed - ded
                v = (v * 100).to_integral_value(rounding='ROUND_CEILING') / 100          # 소수 둘째 자리로 올림(모자라지 않게)
                pq_needed = max(v, Decimal(0))
            row.update(possible=False, pq_needed=float(pq_needed) if pq_needed is not None else None)
            out_rows.append(row)
            continue

        # 하한: 비율이 낮을수록 가격 평점이 줄어드는 구간(88% 이하)에서 통과하는 가장 낮은 비율
        eps = Decimal('0.0001')
        if ok(eps):
            lo = None                                              # 아무리 낮게 써도 가격 평점이 모자라지 않는다
        else:
            a, c = eps, center                                     # a: 실패, c: 통과
            for _ in range(60):
                m = (a + c) / 2
                a, c = (a, m) if ok(m) else (m, c)
            lo = c
        # 상한: 예정가격(100%)까지 통과하면 100%, 아니면 88% 위쪽에서 통과하는 가장 높은 비율
        if ok(Decimal(1)):
            hi = Decimal(1)
        else:
            a, c = center, Decimal(1)                              # a: 통과, c: 실패
            for _ in range(60):
                m = (a + c) / 2
                a, c = (m, c) if ok(m) else (a, m)
            hi = a

        min_price = max_price = None
        if sched is not None:
            top_p = int(sched)
            if lo is not None:
                p = max(int(lo * sched) - 3, 1)
                for _ in range(50):
                    if ok(Decimal(p) / sched):
                        break
                    p += 1
                while p > 1 and ok(Decimal(p - 1) / sched):
                    p -= 1
                min_price = p
            if hi >= 1:
                p = top_p
            else:
                p = min(int(hi * sched) + 3, top_p)
                for _ in range(50):
                    if ok(Decimal(p) / sched):
                        break
                    p -= 1
                while p + 1 <= top_p and ok(Decimal(p + 1) / sched):
                    p += 1
            max_price = p

        def ratio_pct(r, up, ok=ok):
            """예정가격을 모를 때의 비율 표시: 하한은 올림, 상한은 내림해서 통과 구간 안쪽 값으로 적는다."""
            r5 = (r * 100000).to_integral_value(rounding='ROUND_CEILING' if up else 'ROUND_FLOOR') / 100000
            step = Decimal('0.00001')
            if up:
                while not ok(r5):
                    r5 += step
                while r5 > step and ok(r5 - step):              # 이분 탐색이 경계를 아주 조금 지나쳤으면 한 칸씩 되돌린다
                    r5 -= step
            else:
                while r5 > 0 and not ok(r5):
                    r5 -= step
            return r5 * 100

        if lo is None:
            min_pct = None
        elif min_price is not None:
            min_pct = Decimal(min_price) / sched * 100
        else:
            min_pct = ratio_pct(lo, True)
        max_pct = Decimal(max_price) / sched * 100 if max_price is not None else ratio_pct(hi, False)
        ladder = []
        for pct in range(70, 101):
            s = price_score(band, Decimal(pct) / 100, digits)[0]
            ladder.append({'ratio_pct': pct, 'price_score': float(s), 'total': float(_q(fixed + s, 4)), 'pass': ok(Decimal(pct) / 100)})
        row.update(possible=True, min_ratio_pct=None if min_pct is None else float(min_pct), max_ratio_pct=float(max_pct),
                   min_price=min_price, max_price=max_price, ladder=ladder)
        out_rows.append(row)

    if sched is None:
        notes.append('예정가격을 입력하지 않아 입찰가격은 예정가격 대비 비율(%)로만 표시합니다. 예정가격을 입력하면 원 단위 금액도 계산합니다.')
    notes.append('적격심사는 예정가격 이하 최저가 입찰자부터 순서대로 심사해 통과한 첫 입찰자를 낙찰자로 정합니다. 통과 구간 안에 있어도 더 낮은 가격으로 통과한 입찰자가 있으면 낙찰되지 않습니다.')
    return {
        'spec_id': spec_id,
        'band': {'id': band['id'], 'label': band['label'], 'ref': band['ref'], 'pass_score': float(pass_score), 'pass_ref': band['pass_ref'],
                 'price_ref': pcfg['ref']},
        'weights': {'pq': float(pq_weight), 'career': float(w['career']), 'local': float(local_weight), 'mgmt': float(w['mgmt']), 'price': float(top)},
        'estimated_price': float(est), 'planned_price': float(sched) if sched is not None else None,
        'results': out_rows, 'notes': notes, 'source': spec['source'],
    }
