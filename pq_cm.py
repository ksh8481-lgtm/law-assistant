"""
경상남도 건설사업관리사업자 사업수행능력 평가 엔진 (pq_engine의 'cm' 엔진).

기준: 경상남도 건설엔지니어링사업자 사업수행능력 세부평가기준 [별표 2] 건설사업관리사업자(경상남도 공고 제2026-1486호).
점수는 입력값을 [별표 2]의 구간표에 적용한 결정적 계산이며(AI 관여 없음), 항목마다 근거 문장(basis)을 남긴다.

구조
- 팀 단위(group A 참여기술인, 면접, 공사비 절감 가점, 부패행위 감점, 실격): 공동수급체여도 한 번만 평가한다.
- 사업체 단위(group B~E, 신규고용 가점): 단독이면 1회, 공동도급이면 구성원별로 평가한 뒤 지분율을 곱해 합산한다.
  단, 유사과업 수행실적은 고시 예시대로 구성원 실적금액에 지분율을 곱해 합산한 금액으로 구간을 찾는다.
"""
import math

import pq_engine as E
from pq_engine import Warn, _fmt, num, rnd, relative_grades, tier_ge

MEMBER_GROUPS = ('B', 'C', 'D', 'E')
MAIN_WORK = {'토목·폐기물처리시설': 'civil', '건축': 'building'}
PHASE = {'설계 및 시공단계': 'both', '설계단계': 'design', '시공단계': 'const'}
DQ_LABELS = [
    ('dq_lead_qual', '책임건설사업관리기술인 경력·배치기준 부적합'),
    ('dq_safety', '시공단계 안전관리담당자 교육훈련 미이수자 참여'),
    ('dq_overlap', '업무중첩도 기준 위반(별표 Ⅰ.9)'),
    ('dq_replaced', '요양 사유 교체 후 3개월 내 참여(별표 Ⅰ.10)'),
    ('dq_other', '그 밖의 실격 사유(발주청 확인)'),
]


# ---------------------------------------------------------------- 표 조회 도우미
def _band_idx(value, mins):
    for i, m in enumerate(mins):
        if value >= m:
            return i
    return len(mins) - 1


def _band_text(i, mins, unit='억원'):
    if i == 0:
        return f'{_fmt(mins[0])}{unit} 이상'
    if i == len(mins) - 1 and mins[i] <= 0:
        return f'{_fmt(mins[i - 1])}{unit} 미만'
    return f'{_fmt(mins[i])}{unit} 이상 {_fmt(mins[i - 1])}{unit} 미만'


def _grid(value, thresholds, pcts):
    """value >= thresholds[j] 인 첫 j의 (pct, j). 모두 미달이면 마지막 pct."""
    for j, t in enumerate(thresholds):
        if value >= t:
            return pcts[j], j
    return pcts[-1], len(thresholds)


def _grid_text(value, unit, thresholds, j):
    if j == 0:
        rng = f'{_fmt(thresholds[0])}{unit} 이상'
    elif j >= len(thresholds):
        rng = f'{_fmt(thresholds[-1])}{unit} 미만'
    else:
        rng = f'{_fmt(thresholds[j])}{unit} 이상 {_fmt(thresholds[j - 1])}{unit} 미만'
    return f'{_fmt(value)}{unit} → {rng}'


def _weights(rows, warn, label):
    """분야 구성 -> [(분야명, 배분비율(0~1))]. 배분율을 모두 비우면 균등, 합이 100이 아니면 비율대로 환산."""
    names = []
    for r in rows or []:
        n = (r.get('name') or '').strip()
        if n:
            names.append((n, num(r.get('pct'))))
    if not names:
        return []
    if all(p is None for _n, p in names):
        return [(n, 1.0 / len(names)) for n, _p in names]
    if any(p is None for _n, p in names):
        warn.add(f'{label}: 점수배분율이 빈 분야가 있어 0%로 계산했습니다.')
    vals = [(n, p or 0.0) for n, p in names]
    total = sum(p for _n, p in vals)
    if total <= 0:
        return [(n, 1.0 / len(vals)) for n, _p in vals]
    if abs(total - 100) > 0.01:
        warn.add(f'{label}: 점수배분율 합계가 {_fmt(total)}%입니다(100%여야 합니다). 비율대로 환산해 계산했습니다.')
    return [(n, p / total) for n, p in vals]


# ---------------------------------------------------------------- 사업 정보 -> 계산 조건
def _context(spec, project, warn):
    sc = spec['scoring']
    pj = project or {}
    cost = num(pj.get('total_cost'))
    if cost is None or cost <= 0:
        raise ValueError('사업 정보에 해당공사규모(총공사비, 억원)를 입력해 주세요.')
    mw = MAIN_WORK.get(pj.get('main_work'))
    if mw is None:
        raise ValueError('사업 정보에서 주된 공종(토목·폐기물처리시설 / 건축)을 선택해 주세요.')
    phase = PHASE.get(pj.get('phase'))
    if phase is None:
        raise ValueError('사업 정보에서 건설사업관리 발주 단계를 선택해 주세요.')
    include_const = pj.get('include_construction', True) is not False
    interview = bool(pj.get('interview'))
    rel = 'relative' if str(pj.get('rel_mode', '')).startswith('평가위원') else 'direct'

    base = {it['id']: float(it['max']) for it in spec['items']}
    dyn_lead = dyn_fm = 0.0
    if interview:
        fee = num(pj.get('fee'))
        if fee is None:
            warn.add('면접 배점 구간을 정하려면 건설사업관리 사업비가 필요합니다. 입력이 없어 20억 원 미만 구간(책임 2점·분야별 1점)으로 계산했습니다.')
            fee = 0.0
        dyn_lead = next(p for b, p in sc['interview_points']['lead'] if fee >= b)
        dyn_fm = next(p for b, p in sc['interview_points']['fm'] if fee >= b)
    base['itv.lead'], base['itv.fm'] = dyn_lead, dyn_fm
    base['lead.career'] = sc['career_total'] - dyn_lead
    base['fm.career'] = sc['career_total'] - dyn_fm

    excluded = set()
    if not include_const:
        for it in spec['items']:
            if it['id'].startswith('sup.') or it['id'].startswith('swap.'):
                excluded.add(it['id'])
        lost = sum(base[i] for i in excluded)
        warn.add(f'시공단계 건설사업관리를 포함하지 않아 기술지원기술인·교체빈도 배점 {_fmt(lost)}점을 제외했습니다. '
                 '고시에 따라 다른 평가항목에 항목별 배점의 ±20% 범위에서 배분하려면 [배점 조정]에서 직접 입력하세요(합계 100점).')
        for i in excluded:
            base[i] = 0.0

    maxes = dict(base)
    pct_adj = spec.get('adjust_pct', 20)
    for iid, v in (pj.get('adjust') or {}).items():
        v = num(v)
        if iid not in base or v is None or iid in excluded or iid in ('itv.lead', 'itv.fm'):
            continue
        lo, hi = base[iid] * (1 - pct_adj / 100.0), base[iid] * (1 + pct_adj / 100.0)
        if v < lo - 1e-9 or v > hi + 1e-9:
            warn.add(f"'{_item_name(spec, iid)}' 배점 {_fmt(v)}점이 고시 허용 범위({_fmt(lo)}~{_fmt(hi)}점, ±{pct_adj}%)를 벗어났습니다.")
        maxes[iid] = v
    total_max = sum(maxes.values())
    if abs(total_max - 100) > 0.01:
        warn.add(f'배점 합계가 {_fmt(total_max)}점입니다(고시의 합계는 100점).')

    return {
        'cost': cost, 'main_work': mw, 'phase': phase, 'interview': interview, 'rel': rel,
        'include_const': include_const, 'maxes': maxes, 'total_max': total_max,
        'fields': _weights(pj.get('fields'), warn, '분야별 건설사업관리기술인 구성'),
        'support': _weights(pj.get('support_fields'), warn, '기술지원기술인 구성') if include_const else [],
        'no_result': num(pj.get('no_result_score')),
        'itv_pts': (dyn_lead, dyn_fm),
    }


def _mlabel(mname):
    return mname if mname.startswith('구성원') else f'구성원 {mname}'


def _item_name(spec, iid):
    for it in spec['items']:
        if it['id'] == iid:
            return it['name']
    return iid


def _group_of(spec, iid):
    return next(i['group'] for i in spec['items'] if i['id'] == iid)


def _row(spec, ctx, iid, pct, basis, note='', score=None, digits=2):
    mx = ctx['maxes'][iid]
    s = mx * pct / 100.0 if score is None else score
    if score is not None and mx > 0 and pct is None:
        pct = s / mx * 100.0
    return {'id': iid, 'name': _item_name(spec, iid), 'group': _group_of(spec, iid), 'max': rnd(mx, digits),
            'pct': None if pct is None else round(pct, 4), 'score': rnd(s, digits), 'basis': basis, 'note': note}


# ---------------------------------------------------------------- 팀 단위: 참여기술인·면접·가점·감점·실격
def _edu_pts(cfg, p):
    tr = cfg['training'].get(p.get('edu_training'), 0.0)
    q = cfg['qual'].get(p.get('qualification'), 0.0)
    return tr, q


def _team(spec, ctx, persons, itv_auto, warn):
    sc = spec['scoring']
    maxes = ctx['maxes']
    items = []
    lead = persons.get('lead') or {}
    fm_map = persons.get('field') or {}
    sup_map = persons.get('support') or {}
    team = persons.get('team') or {}
    cost = ctx['cost']

    def add(iid, pct, basis, note='', score=None):
        if maxes.get(iid, 0) <= 0:
            return
        items.append(_row(spec, ctx, iid, pct, basis, note, score))

    def zero(iid, basis):
        add(iid, 0.0, basis, score=0.0)

    # --- 책임건설사업관리기술인
    label = '책임건설사업관리기술인'
    if not lead:
        warn.add(f'{label}: 입력 없음 → 0점 처리')
        for iid in ('lead.career', 'lead.perf', 'lead.edu'):
            zero(iid, f'{label}: 입력 없음')
    else:
        v = num(lead.get('career'))
        if v is None:
            warn.add(f'{label} 해당분야 경력 미입력 → 0점 처리')
            zero('lead.career', f'{label} 경력 미입력')
        else:
            cfg = sc['lead_career']
            bi = _band_idx(cost, cfg['cost_min'])
            pct, j = _grid(v, cfg['rows'][bi], sc['grid_pct'])
            add('lead.career', pct, f"{label} 해당분야 경력 / 공사규모 {_band_text(bi, cfg['cost_min'])}: {_grid_text(v, cfg['unit'], cfg['rows'][bi], j)} → {pct}%")
        g, v = lead.get('grade'), num(lead.get('perf'))
        cfg = sc['lead_perf']
        if g not in cfg['by_grade']:
            warn.add(f'{label} 등급이 없거나 직무분야 실적 구간표(특급·고급)에 없는 등급이라 실적 0점 처리')
            zero('lead.perf', f'{label} 직무분야 실적: 등급 {g or "미입력"} → 0점(구간표는 특급·고급만)')
        elif v is None:
            warn.add(f'{label} 직무분야 실적 미입력 → 0점 처리')
            zero('lead.perf', f'{label} 직무분야 실적 미입력')
        else:
            th = cfg['by_grade'][g]
            pct, j = _grid(v, th, sc['grid_pct'])
            add('lead.perf', pct, f"{label} 직무분야 실적 / {g}기술인: {_grid_text(v, cfg['unit'], th, j)} → {pct}%")
        tr, q = _edu_pts(sc['edu']['lead'], lead)
        pts = min(tr + q, 1.0)
        add('lead.edu', pts / 1.0 * 100, f'{label} 교육훈련 {lead.get("edu_training") or "-"}({tr}점) + 기술자격 {lead.get("qualification") or "-"}({q}점) = {_fmt(pts)}점(최대 1점)')

    # --- 분야별 / 기술지원: 분야별 점수배분율 가중
    def weighted(iid, rows, p_map, label, fn):
        if maxes.get(iid, 0) <= 0:
            return
        if not rows:
            warn.add(f'{label}: 구성(분야·점수배분율)이 없어 0점 처리')
            zero(iid, f'{label}: 구성 없음')
            return
        total, parts = 0.0, []
        for name, w in rows:
            p = p_map.get(name) or {}
            ratio, text = fn(p, name)
            if ratio is None:
                warn.add(f'{label}({name}): {text} → 해당 분야 0점 처리')
                ratio, text = 0.0, f'{name} {text} → 0'
            total += w * ratio
            parts.append(f'[{text} × 배분율 {rnd(w * 100, 1)}%]')
        add(iid, total * 100, f'{label}: ' + ' + '.join(parts))

    def fm_career(p, name):
        v = num(p.get('career'))
        if not p or v is None:
            return None, '경력 미입력'
        cfg = sc['fm_career']
        bi = _band_idx(cost, cfg['cost_min'])
        pct, j = _grid(v, cfg['rows'][bi], sc['grid_pct'])
        return pct / 100.0, f"{name} {_grid_text(v, cfg['unit'], cfg['rows'][bi], j)}(공사규모 {_band_text(bi, cfg['cost_min'])}) → {pct}%"

    def fm_perf(p, name):
        g, v = p.get('grade'), num(p.get('perf'))
        cfg = sc['fm_perf']
        if not p or g not in cfg['by_grade']:
            return None, f'등급 {g or "미입력"}(구간표는 특급·고급·중급)'
        if v is None:
            return None, '직무분야 실적 미입력'
        th = cfg['by_grade'][g]
        pct, j = _grid(v, th, sc['grid_pct'])
        return pct / 100.0, f"{name} {g} {_grid_text(v, cfg['unit'], th, j)} → {pct}%"

    def fm_edu(p, name):
        tr, q = _edu_pts(sc['edu']['fm'], p)
        return min(tr + q, 1.0) / 1.0, f'{name} 교육훈련 {p.get("edu_training") or "-"} {_fmt(tr)}점'

    def sup_grade(p, name):
        g = p.get('grade')
        if not p or not g:
            return None, '등급 미입력'
        cfg = sc['sup_grade']
        ok = cfg['big_ok'] if cost >= cfg['big_cost'] else cfg['small_ok']
        size = f"총공사비 {_fmt(cfg['big_cost'])}억 {'이상' if cost >= cfg['big_cost'] else '미만'}"
        return (1.0 if g in ok else 0.0), f"{name} {g}기술인({size}, 만점 인정 등급: {'·'.join(ok)}) → {'100' if g in ok else '0'}%"

    def sup_career(p, name):
        v = num(p.get('career'))
        if not p or v is None:
            return None, '경력 미입력'
        cfg = sc['sup_career']
        bi = _band_idx(cost, cfg['cost_min'])
        pct, j = _grid(v, cfg['rows'][bi], sc['grid_pct'])
        return pct / 100.0, f"{name} {_grid_text(v, cfg['unit'], cfg['rows'][bi], j)}(공사규모 {_band_text(bi, cfg['cost_min'])}) → {pct}%"

    def sup_edu(p, name):
        tr, q = _edu_pts(sc['edu']['sup'], p)
        return min(tr + q, 1.0) / 1.0, f'{name} 교육훈련 {p.get("edu_training") or "-"}({tr}점) + 기술자격 {p.get("qualification") or "-"}({q}점)'

    weighted('fm.career', ctx['fields'], fm_map, '분야별 건설사업관리기술인 해당분야 경력', fm_career)
    weighted('fm.perf', ctx['fields'], fm_map, '분야별 건설사업관리기술인 직무분야 실적', fm_perf)
    weighted('fm.edu', ctx['fields'], fm_map, '분야별 건설사업관리기술인 교육훈련', fm_edu)
    weighted('sup.grade', ctx['support'], sup_map, '기술지원기술인 등급', sup_grade)
    weighted('sup.career', ctx['support'], sup_map, '기술지원기술인 해당분야 경력', sup_career)
    weighted('sup.edu', ctx['support'], sup_map, '기술지원기술인 교육훈련', sup_edu)

    # --- 면접(발표)
    for iid, gkey, label, who, which in (('itv.lead', 'itv_lead_grade', '책임건설사업관리기술인 면접', 'lead', 0),
                                         ('itv.fm', 'itv_fm_grade', '분야별 건설사업관리기술인 면접', 'fm', 1)):
        if maxes.get(iid, 0) <= 0:
            continue
        g = itv_auto.get(who) if ctx['rel'] == 'relative' else team.get(gkey)
        if g in (None, '', '미제출'):
            warn.add(f'{label} 평가 미입력·미제출 → 0점 처리')
            zero(iid, f'{label}: 평가 미제출 → 0점')
        else:
            pct = sc['relative_grade_pct'][g]
            how = '상대평가 자동 배분' if ctx['rel'] == 'relative' else '등급 직접 입력'
            add(iid, pct, f'{label} {g} 등급({how}) → 배점한도 {_fmt(ctx["itv_pts"][which])}점 × {pct}%')

    # --- 가점(공사비 절감) / 감점(부패행위)
    bsv = sc['bonus_save']
    save_pts, save_parts = 0.0, []
    for who, ak, rk in (('상주기술인', 'save_res_amt', 'save_res_rate'), ('기술지원기술인', 'save_sup_amt', 'save_sup_rate')):
        amt, rate = num(team.get(ak)), num(team.get(rk))
        if amt is None and rate is None:
            continue
        wa = next((w for b, w in bsv['amount_weight'] if (amt or 0) >= b), 0.0)
        wr = next((w for b, w in bsv['rate_weight'] if (rate or 0) >= b), 0.0)
        w = max(wa, wr)
        pts = bsv['per_person'] * w
        save_pts += pts
        save_parts.append(f"{who} 절감 {_fmt(amt or 0)}억/{_fmt(rate or 0)}% → 가중치 {w} → {rnd(pts, 3)}점")
    corrupt_pts, corrupt_text = 0.0, ''
    if team.get('corrupt'):
        cr = sc['corrupt']
        amt, rate = num(team.get('corrupt_amt')), num(team.get('corrupt_rate'))
        if amt is None and rate is None:
            warn.add('부패행위 감점 대상으로 체크했지만 피해금액·비율이 비어 있어 가장 낮은 구간(1점)으로 계산했습니다.')
        if (rate or 0) > cr['rate_hi'] or (amt or 0) > cr['amt_hi']:
            corrupt_pts = cr['points'][0]
        elif (rate or 0) > cr['rate_mid'] or (amt or 0) > cr['amt_mid']:
            corrupt_pts = cr['points'][1]
        else:
            corrupt_pts = cr['points'][2]
        corrupt_text = f'부패행위 피해 {_fmt(amt or 0)}억원/{_fmt(rate or 0)}% → {_fmt(corrupt_pts)}점 감점'

    dq = [text for key, text in DQ_LABELS if team.get(key)]
    return items, {'save': save_pts, 'save_parts': save_parts, 'corrupt': corrupt_pts, 'corrupt_text': corrupt_text}, dq


# ---------------------------------------------------------------- 사업체 단위: 유사과업·신용도·기술개발·교체빈도
def _sim_eff(ctx, firm):
    a, b, c, d, e = (num(firm.get(k)) for k in ('cm_both', 'cm_design', 'cm_design_eng', 'cm_const', 'cm_super'))
    if all(x is None for x in (a, b, c, d, e)):
        return None, '유사 건설엔지니어링 수행실적 미입력'
    a, b, c, d, e = (x or 0.0 for x in (a, b, c, d, e))
    if ctx['phase'] == 'both':
        v = a + (b + c * 0.7) * 0.7 + (d + e * 0.7) * 0.7
        t = (f'설계·시공 포함 {_fmt(a)} + (설계단계 {_fmt(b)} + 설계건설엔지니어링 {_fmt(c)}×0.7)×0.7 '
             f'+ (시공단계 {_fmt(d)} + 감리·시행령 제45조제1항제3호 {_fmt(e)}×0.7)×0.7')
    elif ctx['phase'] == 'design':
        v = a + (b + c * 0.7) * 1.0
        t = f'설계·시공 포함 {_fmt(a)} + (설계단계 {_fmt(b)} + 설계건설엔지니어링 {_fmt(c)}×0.7)×1.0'
    else:
        v = a + (d + e * 0.7) * 1.0
        t = f'설계·시공 포함 {_fmt(a)} + (시공단계 {_fmt(d)} + 감리·시행령 제45조제1항제3호 {_fmt(e)}×0.7)×1.0'
    return v, f'{t} = {_fmt(rnd(v, 3))}억원'


def _sim_score(spec, ctx, eff, eff_note):
    sc = spec['scoring']
    cfg = sc['sim_civil'] if ctx['main_work'] == 'civil' else sc['sim_building']
    bi = _band_idx(ctx['cost'], cfg['cost_min'])
    pct, j = _grid(eff, cfg['rows'][bi], sc['grid_pct'])
    kind = '토목·폐기물처리시설' if ctx['main_work'] == 'civil' else '건축'
    return pct, f"{eff_note} / {kind} 공사규모 {_band_text(bi, cfg['cost_min'])}: {_grid_text(rnd(eff, 3), cfg['unit'], cfg['rows'][bi], j)} → {pct}%"


def _member(spec, ctx, firm, warn):
    """사업체 1곳의 B~E 항목 계산. 반환: ({iid: {pct,score,basis,note}}, eff, eff_note, hire(pts, basis))."""
    sc = spec['scoring']
    maxes = ctx['maxes']
    out = {}

    def put(iid, pct=None, basis='', note='', score=None):
        if maxes.get(iid, 0) <= 0:
            return
        mx = maxes[iid]
        s = mx * pct / 100.0 if score is None else score
        out[iid] = {'pct': (s / mx * 100.0 if mx else 0.0) if pct is None else pct, 'score': s, 'basis': basis, 'note': note}

    # 나. 수행성과
    avg = num(firm.get('perf_avg'))
    if avg is not None:
        pct, bound = tier_ge(avg, sc['sim_result']['tiers'])
        put('sim.result', pct, f'건설사업관리 수행성과 평균 {_fmt(avg)}점 → {_fmt(bound) if bound > -1e8 else "86점 미만"}{"점 이상" if bound > -1e8 else ""} → {pct}%')
    elif ctx['no_result'] is not None:
        pct = ctx['no_result'] / 2.0 * 100.0
        put('sim.result', pct, f'해당 발주청 수행성과 없음 → 발주청이 정한 기본 {_fmt(ctx["no_result"])}점 부여', '고시: 수행성과가 없는 사업체는 1.8 또는 1.6점을 부여할 수 있음(입찰공고 시 제시).')
    else:
        warn.add('건설사업관리 수행성과가 비어 있고 기본 점수도 정해지지 않아 0점 처리')
        put('sim.result', 0.0, '수행성과 미입력 → 0점', score=0.0)

    eff, eff_note = _sim_eff(ctx, firm)

    # 다. 신용도
    mf = math.ceil(num(firm.get('suspend_months')) or 0)
    mt = math.ceil(num(firm.get('tech_suspend_months')) or 0)
    s = max(0.0, maxes['credit.stop'] - sc['stop']['per_month'] * (mf + mt))
    put('credit.stop', None, f"{_fmt(maxes['credit.stop'])}점 - 사업자 영업정지 {mf}개월×0.2 - 참여기술인 자격·업무정지 {mt}개월×0.2 = {_fmt(rnd(s, 3))}점(1개월 미만은 1개월, 0점 미만은 0점)", score=s)
    bf, bt = num(firm.get('bad_deduct_firm')) or 0.0, num(firm.get('bad_deduct_tech')) or 0.0
    s = max(0.0, maxes['credit.penalty'] - bf - bt)
    put('credit.penalty', None, f"{_fmt(maxes['credit.penalty'])}점 - 사업자 벌점 감점 {_fmt(bf)}점 - 참여기술인 벌점 감점 {_fmt(bt)}점 = {_fmt(rnd(s, 3))}점(0점 미만은 0점)", score=s)

    cr = sc['credit']
    ctype, crate = firm.get('credit_type'), firm.get('credit_rating')
    if ctype in (None, '', '미제출') or crate in (None, ''):
        put('credit.finance', None, '신용평가등급 미제출 → 0점', score=cr['points']['none'] * maxes['credit.finance'] / 3.0)
    else:
        bond = crate if ctype != '기업어음' else cr['paper_to_bond'].get(crate)
        if bond is None or bond not in cr['bond_order']:
            warn.add(f'신용평가등급 {crate}({ctype})을 인식하지 못해 0점 처리')
            put('credit.finance', None, f'신용평가등급 {crate}({ctype}) 인식 불가 → 0점', score=0.0)
        else:
            ri = cr['bond_order'].index(bond)
            if ri <= cr['bond_order'].index('BBB-'):
                pts, band = cr['points']['ge_BBB-'], 'BBB- 이상(회사채 기준)'
            elif bond == 'CCC+ 이하':
                pts, band = cr['points']['le_CCC+'], 'CCC+ 이하(회사채 기준)'
            else:
                pts, band = cr['points']['lt_BBB-_ge_B-'], 'BBB- 미만 B- 이상(회사채 기준)'
            put('credit.finance', None, f"{ctype} {crate}" + (f' (회사채 {bond}에 준함)' if ctype == '기업어음' else '') + f' → {band} → {pts}점(원 배점 3.0 기준)',
                score=pts * maxes['credit.finance'] / 3.0)

    # 라. 개발·활용 실적
    dev_sum, dev_parts = 0.0, []
    for r in firm.get('dev_items') or []:
        n = max(1.0, num(r.get('applicants')) or 1.0)
        pts = sc['dev']['new_tech_point'] / n
        dev_sum += pts
        dev_parts.append(f"신기술 개발 {sc['dev']['new_tech_point']}점" + (f'÷{_fmt(n)}명' if n > 1 else '') + f'={rnd(pts, 3)}')
    use = sc['use']
    best = {}
    for i, r in enumerate(firm.get('use_items') or []):
        t = r.get('type')
        if t not in use['base_points']:
            continue
        share = num(r.get('share_pct'))
        sf = 1.0 if share is None else share / 100.0
        cnt = (num(r.get('use_count')) if num(r.get('use_count')) is not None else 1.0) * sf
        amt = (num(r.get('use_amount')) or 0.0) * sf
        wc = next((w for b, w in use['count_weight'] if cnt >= b), 0.0)
        wa = next((w for b, w in use['amount_weight'] if amt >= b), 0.0)
        w = max(wc, wa)
        age_f, age_txt = 1.0, ''
        if t == '특허':
            age = num(r.get('age_years'))
            if age is None:
                warn.add('특허 활용실적의 출원 후 경과기간이 비어 있어 100%(5년 미만)로 계산했습니다.')
                age = 0.0
            age_f = next((p for b, p in use['patent_age'] if age < b), 0.0) / 100.0
            age_txt = f' × 경과 {_fmt(age)}년 인정 {rnd(age_f * 100)}%'
        pts = use['base_points'][t] * w * cnt * age_f
        grp = (r.get('dup_group') or '').strip() or f'__{i}'
        text = f"{t} {use['base_points'][t]}점 × 가중치 {w}(건수 {_fmt(cnt)}건·금액 {_fmt(amt)}억 중 유리한 구간) × {_fmt(cnt)}건{age_txt} = {rnd(pts, 3)}"
        if grp not in best or pts > best[grp][0]:
            best[grp] = (pts, t, text)
    new_tech_use = sum(p for p, t, _x in best.values() if t == '건설신기술')
    patent_use = sum(p for p, t, _x in best.values() if t == '특허')
    patent_use_cap = min(patent_use, use['patent_cap'])
    total = dev_sum + new_tech_use + patent_use_cap
    s = min(total, maxes['tech.devuse'])
    parts = dev_parts + [x for _p, _t, x in best.values()]
    put('tech.devuse', None, ('개발·활용 실적 없음 → 0점' if not parts else ' + '.join(parts) +
                              (f' (특허 활용 합계 {rnd(patent_use, 3)}점은 최대 {use["patent_cap"]}점까지만 인정)' if patent_use > use['patent_cap'] else '') +
                              f' = {rnd(total, 3)}점 (배점 {_fmt(maxes["tech.devuse"])}점 상한)'), score=s)

    inv, sales = num(firm.get('invest_amount')), num(firm.get('sales_amount'))
    if inv is None or sales in (None, 0):
        warn.add('투자실적(투자액·건설부문 총매출액) 미입력 → 0점 처리')
        put('tech.invest', None, '투자실적 미입력 → 0점', score=0.0)
    else:
        ratio = inv / sales * 100.0
        cfg = sc['invest']
        pts, bound = tier_ge(ratio, cfg['points'])
        put('tech.invest', None, f"투자액 {_fmt(inv)}억 / 건설부문 총매출 {_fmt(sales)}억 = {rnd(ratio, 3)}% → {'%g%% 이상' % bound if bound > -1e8 else '0.5% 미만'} → {pts}점(원 배점 {cfg['base']}점 기준)",
            score=pts * maxes['tech.invest'] / cfg['base'])

    # 마. 교체빈도
    sw = sc['swap_firm']
    sc_n, ss_n, dep = num(firm.get('swap_cnt')), num(firm.get('swap_support_cnt')), num(firm.get('deployed_cnt'))
    if sc_n is None and ss_n is None and dep is None:
        warn.add('교체빈도(사업자) 입력(교체건수·배치 인원)이 없어 0점 처리')
        put('swap.firm', None, '교체빈도 미입력 → 0점', score=0.0)
    else:
        cnt = (sc_n or 0.0) + math.floor((ss_n or 0.0) / sw['support_per'])
        if not dep:
            if cnt > 0:
                warn.add('교체건수는 있는데 시공단계 배치 인원이 0 또는 비어 있어 교체빈도(사업자)를 0점 처리')
                put('swap.firm', None, '배치 인원 없음 → 계산 불가, 0점', score=0.0)
                rate = None
            else:
                rate = 0.0
        else:
            rate = cnt / dep * 100.0
        if rate is not None:
            pts = next(p for b, p in sw['points'] if rate < b)
            put('swap.firm', None, f"교체건수 {_fmt(sc_n or 0)}건 + 기술지원 {_fmt(ss_n or 0)}건÷5(내림) = {_fmt(cnt)}건 / 배치 {_fmt(dep or 0)}명 = {rnd(rate, 2)}% → {pts}점(원 배점 {sw['base']}점 기준)",
                score=pts * maxes['swap.firm'] / sw['base'])
    st = sc['swap_tech']
    res, sup = num(firm.get('swap_resident')) or 0.0, num(firm.get('swap_support')) or 0.0
    s = max(0.0, maxes['swap.tech'] - st['per_resident'] * res - st['per_support'] * sup)
    put('swap.tech', None, f"{_fmt(maxes['swap.tech'])}점 - 상주 교체 {_fmt(res)}회×{st['per_resident']} - 기술지원 교체 {_fmt(sup)}회×{st['per_support']} = {_fmt(rnd(s, 3))}점(0점 미만은 0점)", score=s)

    # 가점: 신규 고용
    hire = num(firm.get('new_hire_rate'))
    if firm.get('reg_over_6m') is False:
        hire_pts, hire_basis = 0.0, '등록 후 6개월이 지나지 않아 가점 대상 아님'
    elif hire is None:
        hire_pts, hire_basis = 0.0, '신규 고용률 미입력 → 가점 없음'
    else:
        hire_pts = next((p for b, p in sc['bonus_hire']['tiers'] if hire >= b), 0.0)
        hire_basis = f'신규 고용률 {_fmt(hire)}% → 가점 {hire_pts}점'
    return out, eff, eff_note, (hire_pts, hire_basis)


# ---------------------------------------------------------------- 입찰사 1곳 평가
def _evaluate_bidder(spec, ctx, b, idx, itv_auto):
    digits = spec.get('rounding_digits', 2)
    sc = spec['scoring']
    name = (b.get('name') or '').strip() or f'입찰사 {idx + 1}'
    warn = Warn()
    persons = b.get('persons') or {}
    team_items, tb, dq = _team(spec, ctx, persons, itv_auto, warn)
    items = list(team_items)
    members = [m for m in (b.get('members') or []) if isinstance(m, dict)]
    result_members = None

    if not members:
        calc, eff, eff_note, hire = _member(spec, ctx, b.get('firm') or {}, warn)
        if eff is None:
            warn.add('유사 건설엔지니어링 수행실적이 비어 있어 0점 처리')
            items.append(_row(spec, ctx, 'sim.perf', 0.0, '유사 건설엔지니어링 수행실적 미입력 → 0점', score=0.0))
        else:
            pct, text = _sim_score(spec, ctx, eff, eff_note)
            items.append(_row(spec, ctx, 'sim.perf', pct, text))
        for iid, c in calc.items():
            items.append(_row(spec, ctx, iid, c['pct'], c['basis'], c['note'], score=c['score']))
        hire_total, hire_basis = hire[0], hire[1]
    else:
        shares = [num(m.get('share')) for m in members]
        if any(s is None or s <= 0 for s in shares):
            warn.add('공동수급체 구성원의 참여지분율이 비었거나 0 이하입니다. 지분율을 입력해 주세요(없는 구성원은 제외하고 계산했습니다).')
        keep = [(m, s) for m, s in zip(members, shares) if s is not None and s > 0]
        if not keep:
            raise ValueError(f"'{name}': 공동수급체 구성원의 참여지분율을 입력해 주세요.")
        total_share = sum(s for _m, s in keep)
        if abs(total_share - 100) > 0.01:
            warn.add(f'공동수급체 지분율 합계가 {_fmt(total_share)}%입니다(100%여야 합니다). 비율대로 환산해 계산했습니다.')
        mres = []
        for mi, (m, s) in enumerate(keep):
            mname = (m.get('name') or '').strip() or f'구성원 {mi + 1}'
            mw = Warn()
            calc, eff, eff_note, hire = _member(spec, ctx, m.get('firm') or {}, mw)
            for t in mw.items:
                warn.add(f'[{_mlabel(mname)}] {t}')
            mres.append((mname, s / total_share, calc, eff, eff_note, hire))
        # 유사과업 수행실적: 구성원 실적금액 × 지분율 합산 후 구간 적용(고시 예시)
        effs = [(n, sh, e, en) for n, sh, _c, e, en, _h in mres]
        if all(e is None for _n, _s, e, _en in effs):
            warn.add('유사 건설엔지니어링 수행실적이 모든 구성원에서 비어 있어 0점 처리')
            items.append(_row(spec, ctx, 'sim.perf', 0.0, '구성원 실적 미입력 → 0점', score=0.0))
        else:
            total_eff = sum(sh * (e or 0.0) for _n, sh, e, _en in effs)
            note = ' + '.join(f"[{n} 지분 {rnd(sh * 100, 1)}%: {_fmt(rnd(e or 0.0, 3))}억]" for n, sh, e, _en in effs) + f' = {rnd(total_eff, 3)}억원(구성원 실적×지분율 합산)'
            pct, text = _sim_score(spec, ctx, total_eff, note)
            items.append(_row(spec, ctx, 'sim.perf', pct, text, '공동도급 예시: (A사 200억×0.6)+(B사 100억×0.4)=160억원에 구간을 적용(고시 Ⅱ.4 예시).'))
        # 그 밖의 사업체 단위 항목: 구성원별 점수 × 지분율
        iids = [it['id'] for it in spec['items'] if it['group'] in MEMBER_GROUPS and it['id'] != 'sim.perf' and ctx['maxes'].get(it['id'], 0) > 0]
        for iid in iids:
            score, parts = 0.0, []
            for n, sh, calc, _e, _en, _h in mres:
                c = calc.get(iid)
                if c is None:
                    continue
                sc_n = rnd(c['score'], digits)
                score += sc_n * sh
                parts.append(f"[{n} 지분 {rnd(sh * 100, 1)}%: {c['basis']} = {_fmt(sc_n)}점 × {rnd(sh, 4)}]")
            items.append(_row(spec, ctx, iid, None, ' + '.join(parts), '공동도급: 구성원별 평가점수(소수 둘째자리) × 참여지분율 합산.', score=score))
        hire_total = sum(sh * h[0] for _n, sh, _c, _e, _en, h in mres)
        hire_basis = ' + '.join(f"[{n} 지분 {rnd(sh * 100, 1)}%: {h[1]} × {rnd(sh, 4)}]" for n, sh, _c, _e, _en, h in mres)
        result_members = [{'name': n, 'share': rnd(sh * 100, 2)} for n, sh, *_r in mres]

    order = {it['id']: i for i, it in enumerate(spec['items'])}
    items.sort(key=lambda it: order[it['id']])
    group_scores = {}
    for it in items:
        group_scores[it['group']] = rnd(group_scores.get(it['group'], 0.0) + it['score'], digits)
    base_total = rnd(sum(it['score'] for it in items), digits)

    # 가점·감점: 상계 후 5점 한도, 총점 100점 한도(고시 Ⅰ.6, Ⅲ.2)
    plus = hire_total + tb['save']
    net_raw = plus - tb['corrupt']
    cap = sc['net_cap']
    net = max(-cap, min(cap, net_raw))
    bparts = [f"신규 고용: {hire_basis}"]
    bparts += tb['save_parts'] or ['공사비 절감 가점 없음']
    if tb['corrupt_text']:
        bparts.append(tb['corrupt_text'])
    bparts.append(f"가점 {rnd(plus, 3)} - 감점 {_fmt(tb['corrupt'])} = {rnd(net_raw, 3)}점(상계 후 ±{cap}점 한도)")
    total_score = max(0.0, min(100.0, base_total + net))
    if base_total + net > 100:
        warn.add('가점 반영 후 100점을 초과해 100점으로 처리했습니다(고시 Ⅰ.6).')
    res = {
        'name': name, 'items': items, 'group_scores': group_scores, 'base_total': base_total,
        'bonus': {'score': rnd(net, digits), 'basis': ' / '.join(bparts), 'name': '가점·감점 합계'},
        'total': rnd(total_score, digits), 'disqualified': bool(dq), 'dq_reasons': dq, '_warn': warn.items,
    }
    if result_members:
        res['members'] = result_members
    if dq:
        warn.add(f'실격 사유가 체크되어 순위에서 제외했습니다: ' + ', '.join(dq))
        res['_warn'] = warn.items
    return res


def evaluate(spec, project, bidders):
    warn = Warn()
    ctx = _context(spec, project, warn)
    itv_auto = [{} for _ in bidders]
    if ctx['interview'] and ctx['rel'] == 'relative':
        keys = [str(i) for i in range(len(bidders))]
        for who, rk in (('lead', 'itv_lead_raw'), ('fm', 'itv_fm_raw')):
            raw = {k: num(((b.get('persons') or {}).get('team') or {}).get(rk)) for k, b in zip(keys, bidders)}
            g = relative_grades(raw, spec)
            for i, k in enumerate(keys):
                itv_auto[i][who] = g[k]
        if len(bidders) < 2:
            warn.add('상대평가는 입찰사가 2개 이상일 때 의미가 있습니다(1개사는 수 등급으로 처리).')
    results = [_evaluate_bidder(spec, ctx, b, i, itv_auto[i]) for i, b in enumerate(bidders)]

    ranked = sorted([i for i, r in enumerate(results) if not r['disqualified']], key=lambda i: -results[i]['total'])
    last_total, last_rank = None, 0
    for pos, i in enumerate(ranked, start=1):
        t = results[i]['total']
        if last_total is not None and abs(t - last_total) < 1e-9:
            results[i]['rank'] = last_rank
        else:
            results[i]['rank'] = pos
            last_total, last_rank = t, pos
    for r in results:
        r.setdefault('rank', None)
        for w in r.pop('_warn'):
            warn.add(f"[{r['name']}] {w}")
    return {'spec_id': spec['id'], 'maxes': {k: rnd(v, 2) for k, v in ctx['maxes'].items()},
            'total_max': rnd(ctx['total_max'], 2), 'results': results, 'warnings': warn.items}
