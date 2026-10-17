"""
정밀안전점검·정밀안전진단사업자 사업수행능력 평가 엔진 (pq_engine의 'safe' 엔진).

기준: 경상남도 건설엔지니어링사업자 사업수행능력 세부평가기준 [별표 3](경상남도 공고 제2026-1486호).
점수는 입력값을 [별표 3]의 구간표에 적용한 결정적 계산이며(AI 관여 없음), 항목마다 근거 문장(basis)을 남긴다.

구조
- 팀 단위(group A 참여기술인, group E 업무중첩도, 우수기관 가점, 실격): 공동수급체여도 한 번만 평가한다.
- 사업체 단위(group B~D, 신규 고용 가점): 단독이면 1회, 공동이행이면 구성원별로 평가해 지분율을 곱해 합산한다.
"""
import math

from pq_engine import Warn, _fmt, num, rnd

MEMBER_ITEMS = ('sim.cnt', 'sim.amt', 'credit.result', 'credit.stop', 'credit.finance', 'tech.dev', 'tech.use', 'tech.invest')


def _item_name(spec, iid):
    return next(i['name'] for i in spec['items'] if i['id'] == iid)


def _group_of(spec, iid):
    return next(i['group'] for i in spec['items'] if i['id'] == iid)


def _tier(value, th, pcts):
    for j, t in enumerate(th):
        if value >= t:
            return pcts[j], j
    return pcts[len(th)], len(th)


def _tier_text(value, unit, th, j):
    if j == 0:
        rng = f'{_fmt(th[0])}{unit} 이상'
    elif j >= len(th):
        rng = f'{_fmt(th[-1])}{unit} 미만'
    else:
        rng = f'{_fmt(th[j])}{unit} 이상 {_fmt(th[j - 1])}{unit} 미만'
    return f'{_fmt(value)}{unit} → {rng}'


def _weights(rows, warn, label):
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


def _context(spec, project, warn):
    pj = project or {}
    sc = spec['scoring']
    specialty = pj.get('specialty')
    if specialty not in ('교량 및 터널', '수리시설', '항만', '건축'):
        raise ValueError('사업 정보에서 해당 전문분야를 선택해 주세요.')
    target = {'분야별 책임기술인': 'fl', '분야별 참여기술인': 'fm'}.get(pj.get('overlap_target'))
    if target is None:
        raise ValueError('사업 정보에서 업무중첩도 평가 대상(분야별 책임기술인/참여기술인)을 선택해 주세요.')
    base = {it['id']: float(it['max']) for it in spec['items']}
    maxes = dict(base)
    pct_adj = spec.get('adjust_pct', 20)
    for iid, v in (pj.get('adjust') or {}).items():
        v = num(v)
        if iid not in base or v is None:
            continue
        lo, hi = base[iid] * (1 - pct_adj / 100.0), base[iid] * (1 + pct_adj / 100.0)
        if v < lo - 1e-9 or v > hi + 1e-9:
            warn.add(f"'{_item_name(spec, iid)}' 배점 {_fmt(v)}점이 고시 허용 범위({_fmt(lo)}~{_fmt(hi)}점, ±{pct_adj}%)를 벗어났습니다.")
        maxes[iid] = v
    total_max = sum(maxes.values())
    if abs(total_max - 100) > 0.01:
        warn.add(f'배점 합계가 {_fmt(total_max)}점입니다(고시의 합계는 100점).')
    return {'specialty': specialty, 'allow_other': specialty not in sc['specialty_no_other'], 'overlap_target': target,
            'maxes': maxes, 'total_max': total_max, 'fields': _weights(pj.get('fields'), warn, '평가 대상 분야 구성')}


def _row(spec, ctx, iid, pct, basis, note='', score=None, digits=2):
    mx = ctx['maxes'][iid]
    s = mx * pct / 100.0 if score is None else score
    if pct is None:
        pct = (s / mx * 100.0) if mx else 0.0
    return {'id': iid, 'name': _item_name(spec, iid), 'group': _group_of(spec, iid), 'max': rnd(mx, digits),
            'pct': round(pct, 4), 'score': rnd(s, digits), 'basis': basis, 'note': note}


# ---------------------------------------------------------------- 참여기술인 1명의 항목별 비율
def _metric(spec, ctx, key, own, other, p, label, warn):
    """key: 'lead.career' 등. 해당 전문분야 + 전문분야 외(60% 한도) 값으로 구간표 비율(0~100)과 근거문."""
    sc = spec['scoring']
    g = sc['grids'][key]
    a, b = num(p.get(own)), num(p.get(other))
    if a is None and b is None:
        return None, f'{label}: {g["unit"]} 입력 없음'
    a = a or 0.0
    b = b or 0.0
    cap_txt = ''
    if b > 0 and not ctx['allow_other']:
        warn.add(f'{label}: 건축분야는 해당 전문분야 외 경력·실적을 인정하지 않아 제외했습니다.')
        b_eff = 0.0
        cap_txt = ' (전문분야 외 불인정)'
    else:
        cap = g['th'][-1] - sc['other_step']
        b_eff = min(b, cap)
        if b > cap:
            cap_txt = f'(전문분야 외 {_fmt(b)}{g["unit"]}은 배점 60% 한도로 {_fmt(rnd(cap, 3))}{g["unit"]}까지만 인정)'
    eff = a + b_eff
    pct, j = _tier(eff, g['th'], sc['grid_pct'])
    txt = f"{_fmt(a)}{g['unit']} + {_fmt(rnd(b_eff, 3))}{g['unit']} = {_fmt(rnd(eff, 3))}{g['unit']} {_tier_text(rnd(eff, 3), g['unit'], g['th'], j).split('→')[1].strip()} → {pct}%"
    return pct, f'{label} {txt}{cap_txt}'


def _transfer(spec, p):
    if p.get('transfer_exempt'):
        return 1.0
    return spec['scoring']['transfer_factor'].get(p.get('transfer') or '해당 없음', 1.0)


def _team(spec, ctx, persons, warn):
    sc = spec['scoring']
    maxes = ctx['maxes']
    items = []
    team = persons.get('team') or {}

    def add(iid, pct, basis, note='', score=None):
        items.append(_row(spec, ctx, iid, pct, basis, note, score))

    def zero(iid, basis):
        add(iid, 0.0, basis, score=0.0)

    # --- 책임기술인
    lead = persons.get('lead') or {}
    label = '책임기술인'
    for crit, own, other in (('career', 'career', 'career_other'), ('cnt', 'cnt', 'cnt_other'), ('amt', 'amt', 'amt_other')):
        iid = f'lead.{crit}'
        if not lead:
            warn.add(f'{label}: 입력 없음 → 0점 처리')
            zero(iid, f'{label}: 입력 없음')
            continue
        pct, text = _metric(spec, ctx, iid, own, other, lead, f'{label} {"경력" if crit == "career" else "실적(건수)" if crit == "cnt" else "실적(금액)"}', warn)
        if pct is None:
            warn.add(f'{text} → 0점 처리')
            zero(iid, text)
            continue
        if crit == 'career':
            tf = _transfer(spec, lead)
            if tf != 1.0:
                pct = pct * tf
                text += f' × 이적 감소계수 {tf}'
        add(iid, pct, text)

    # --- 분야별 책임기술인 / 참여기술인 (분야별 점수배분율 가중)
    def weighted(iid, role, crit, rlabel):
        rows = ctx['fields']
        if not rows:
            warn.add(f'{rlabel}: 평가 대상 분야 구성이 없어 0점 처리')
            zero(iid, f'{rlabel}: 구성 없음')
            return
        pm = persons.get(role) or {}
        total, parts = 0.0, []
        for fname, w in rows:
            p = pm.get(fname) or {}
            lab = f'{rlabel}({fname})'
            if crit == 'grade':
                g = p.get('grade')
                table = sc['grade'][role]
                if not p or g in (None, ''):
                    pct, text = None, f'{lab}: 등급 미입력'
                elif g not in table:
                    warn.add(f'{lab}: 등급 \'{g}\'은(는) 등급표에 없어 0점 처리')
                    pct, text = 0.0, f'{lab} 등급 {g}: 표에 없음 → 0%'
                else:
                    pct, text = float(table[g]), f'{lab} 등급 {g} → {table[g]}%'
            else:
                own, other = {'career': ('career', 'career_other'), 'cnt': ('cnt', 'cnt_other'), 'amt': ('amt', 'amt_other')}[crit]
                names = {'career': '경력', 'cnt': '실적(건수)', 'amt': '실적(금액)'}
                if not p:
                    pct, text = None, f'{lab}: 입력 없음'
                else:
                    pct, text = _metric(spec, ctx, f'{role}.{crit}', own, other, p, f'{lab} {names[crit]}', warn)
                    if pct is not None and crit == 'career':
                        tf = _transfer(spec, p)
                        if tf != 1.0:
                            pct = pct * tf
                            text += f' × 이적 감소계수 {tf}'
            if pct is None:
                warn.add(f'{text} → 해당 분야 0점 처리')
                pct, text = 0.0, f'{text} → 0'
            total += w * pct
            parts.append(f'[{text} × 배분율 {rnd(w * 100, 1)}%]')
        add(iid, total, f'{rlabel} ' + ' + '.join(parts))

    weighted('fl.grade', 'fl', 'grade', '분야별 책임기술인 등급')
    weighted('fl.career', 'fl', 'career', '분야별 책임기술인 경력')
    weighted('fl.cnt', 'fl', 'cnt', '분야별 책임기술인 실적(건수)')
    weighted('fl.amt', 'fl', 'amt', '분야별 책임기술인 실적(금액)')
    weighted('fm.grade', 'fm', 'grade', '분야별 참여기술인 등급')
    weighted('fm.career', 'fm', 'career', '분야별 참여기술인 경력')
    weighted('fm.cnt', 'fm', 'cnt', '분야별 참여기술인 실적')

    # --- 업무중첩도
    ov = sc['overlap']

    def overlap_pct(p, cfg, lab):
        v = num(p.get('overlap'))
        if v is None:
            return None, f'{lab}: 중첩 기간 미입력'
        idx = next((i for i, b in enumerate(cfg['th']) if v < b), len(cfg['th']))
        pct = cfg['pct'][idx]
        if idx == 0:
            rng = f"{_fmt(cfg['th'][0])}{cfg['unit']} 미만"
        elif idx >= len(cfg['th']):
            rng = f"{_fmt(cfg['th'][-1])}{cfg['unit']} 이상"
        else:
            rng = f"{_fmt(cfg['th'][idx - 1])}{cfg['unit']} 이상 {_fmt(cfg['th'][idx])}{cfg['unit']} 미만"
        return pct, f'{lab} 중첩 {_fmt(v)}{cfg["unit"]} → {rng} → {pct}%'

    if not lead:
        zero('ovl.lead', '책임기술인: 입력 없음')
    else:
        pct, text = overlap_pct(lead, ov['lead'], '책임기술인')
        if pct is None:
            warn.add(f'{text} → 0점 처리')
            zero('ovl.lead', text)
        else:
            add('ovl.lead', pct, text)
    role = ctx['overlap_target']
    rlabel = '분야별 책임기술인' if role == 'fl' else '분야별 참여기술인'
    if not ctx['fields']:
        zero('ovl.field', '평가 대상 분야 구성 없음')
    else:
        pm = persons.get(role) or {}
        total, parts = 0.0, []
        for fname, w in ctx['fields']:
            p = pm.get(fname) or {}
            pct, text = overlap_pct(p, ov['field'], f'{rlabel}({fname})') if p else (None, f'{rlabel}({fname}): 입력 없음')
            if pct is None:
                warn.add(f'{text} → 해당 분야 0점 처리')
                pct, text = 0.0, f'{text} → 0'
            total += w * pct
            parts.append(f'[{text} × 배분율 {rnd(w * 100, 1)}%]')
        add('ovl.field', total, f'{rlabel}(업무중첩도 평가 대상): ' + ' + '.join(parts))

    dq = []
    if team.get('dq_lead_qual'):
        dq.append('책임기술인이 시행령 제9조 자격 부적격')
    return items, bool(team.get('excellent')), dq


# ---------------------------------------------------------------- 사업체 단위
def _member(spec, ctx, firm, warn):
    sc = spec['scoring']
    maxes = ctx['maxes']
    out = {}

    def put(iid, pct=None, basis='', score=None):
        mx = maxes[iid]
        s = mx * pct / 100.0 if score is None else score
        out[iid] = {'pct': (s / mx * 100.0 if mx else 0.0) if pct is None else pct, 'score': s, 'basis': basis}

    for iid, key, label in (('sim.cnt', 'sim_cnt', '유사과업 수행실적 건수'), ('sim.amt', 'sim_amt', '유사과업 수행실적 금액')):
        v = num(firm.get(key))
        if v is None:
            warn.add(f'{label} 미입력 → 0점 처리')
            put(iid, 0.0, f'{label} 미입력 → 0점', score=0.0)
        else:
            g = sc['grids'][iid]
            pct, j = _tier(v, g['th'], sc['grid_pct'])
            put(iid, pct, f"{label} {_tier_text(v, g['unit'], g['th'], j)} → {pct}%")

    r = sc['result']
    bad, vbad = num(firm.get('bad_cnt')) or 0.0, num(firm.get('very_bad_cnt')) or 0.0
    s = max(0.0, maxes['credit.result'] - r['bad'] * bad - r['very_bad'] * vbad)
    put('credit.result', None, f"{_fmt(maxes['credit.result'])}점 - 불량 {_fmt(bad)}건×0.5 - 매우 불량 {_fmt(vbad)}건×0.7 = {_fmt(rnd(s, 3))}점(0점 미만은 0점)", score=s)

    mf = math.ceil(num(firm.get('firm_stop_months')) or 0)
    mt = math.ceil(num(firm.get('tech_stop_months')) or 0)
    s = max(0.0, maxes['credit.stop'] - sc['stop']['per_month'] * (mf + mt))
    put('credit.stop', None, f"{_fmt(maxes['credit.stop'])}점 - 사업체 정지 {mf}개월×0.2 - 참여기술인 정지 {mt}개월×0.2 = {_fmt(rnd(s, 3))}점(1개월 미만은 1개월, 0점 미만은 0점)", score=s)

    cr = sc['credit']
    ctype, crate = firm.get('credit_type'), firm.get('credit_rating')
    if ctype in (None, '', '미제출') or crate in (None, ''):
        put('credit.finance', 0.0, '신용평가등급 미제출 → 0점', score=0.0)
    else:
        bond = crate if ctype != '기업어음' else cr['paper_to_bond'].get(crate)
        if bond is None or bond not in cr['bond_order']:
            warn.add(f'신용평가등급 {crate}({ctype})을 인식하지 못해 0점 처리')
            put('credit.finance', 0.0, f'신용평가등급 {crate}({ctype}) 인식 불가 → 0점', score=0.0)
        else:
            idx = cr['bond_order'].index(bond)
            bi = next((i for i, b in enumerate(cr['bounds']) if idx <= cr['bond_order'].index(b)), len(cr['bounds']))
            band = ('A- 이상', 'A- 미만 BBB- 이상', 'BBB- 미만 B- 이상', 'CCC+ 이하')[bi]
            pts = cr['points'][bi]
            put('credit.finance', None, f"{ctype} {crate}" + (f' (회사채 {bond}에 준함)' if ctype == '기업어음' else '') + f' → {band}(회사채 기준) → {pts}점(원 배점 3.0 기준)',
                score=pts * maxes['credit.finance'] / 3.0)

    # 개발실적: 건설신기술 0.5/건, 특허 0.3/건 × 경과기간 가중치 ÷ 출원자 수, 동일 내용은 높은 1건, 특허 합계 0.5점 한도
    dv = sc['dev']
    best = {}
    for i, r_ in enumerate(firm.get('dev_items') or []):
        t = r_.get('type')
        if t not in dv['base_points']:
            continue
        n = max(1.0, num(r_.get('applicants')) or 1.0)
        wt, wtxt = 1.0, ''
        if t == '특허':
            age = num(r_.get('age_years'))
            if age is None:
                warn.add('특허 개발실적의 출원 후 경과기간이 비어 있어 100%(5년 미만)로 계산했습니다.')
                age = 0.0
            wt = next((p for b, p in dv['patent_age'] if age < b), 0.0) / 100.0
            wtxt = f' × 경과 {_fmt(age)}년 {rnd(wt * 100)}%'
        pts = dv['base_points'][t] * wt / n
        grp = (r_.get('dup_group') or '').strip() or f'__{i}'
        text = f"{t} {dv['base_points'][t]}점{wtxt}" + (f'÷{_fmt(n)}명' if n > 1 else '') + f'={rnd(pts, 3)}'
        if grp not in best or pts > best[grp][0]:
            best[grp] = (pts, t, text)
    patent = sum(p for p, t, _x in best.values() if t == '특허')
    newtech = sum(p for p, t, _x in best.values() if t != '특허')
    total = newtech + min(patent, dv['patent_cap'])
    put('tech.dev', None, ('개발실적 없음 → 0점' if not best else ' + '.join(x for _p, _t, x in best.values()) +
                           (f' (특허 합계 {rnd(patent, 3)}점은 최대 {dv["patent_cap"]}점까지만 인정)' if patent > dv['patent_cap'] else '') +
                           f' = {rnd(total, 3)}점 (배점 {_fmt(maxes["tech.dev"])}점 상한)'), score=min(total, maxes['tech.dev']))

    # 활용실적
    us = sc['use']
    best = {}
    for i, r_ in enumerate(firm.get('use_items') or []):
        t = r_.get('type')
        if t not in us['base_points']:
            continue
        cnt = num(r_.get('use_count')) if num(r_.get('use_count')) is not None else 1.0
        amt = num(r_.get('use_amount')) or 0.0
        wc = next((w for b, w in us['count_weight'] if cnt >= b), 0.0)
        wa = next((w for b, w in us['amount_weight'] if amt >= b), 0.0)
        w = max(wc, wa)
        wt, wtxt = 1.0, ''
        if t == '특허':
            age = num(r_.get('age_years'))
            if age is None:
                warn.add('특허 활용실적의 출원 후 경과기간이 비어 있어 100%(5년 미만)로 계산했습니다.')
                age = 0.0
            wt = next((p for b, p in us['patent_age'] if age < b), 0.0) / 100.0
            wtxt = f' × 경과 {_fmt(age)}년 {rnd(wt * 100)}%'
        pts = us['base_points'][t] * w * cnt * wt
        grp = (r_.get('dup_group') or '').strip() or f'__{i}'
        text = f"{t} {us['base_points'][t]}점 × 가중치 {w}(건수 {_fmt(cnt)}건·금액 {_fmt(amt)}억 중 유리한 구간) × {_fmt(cnt)}건{wtxt} = {rnd(pts, 3)}"
        if grp not in best or pts > best[grp][0]:
            best[grp] = (pts, t, text)
    total = sum(p for p, _t, _x in best.values())
    put('tech.use', None, ('활용실적 없음 → 0점' if not best else ' + '.join(x for _p, _t, x in best.values()) + f' = {rnd(total, 3)}점 (배점 {_fmt(maxes["tech.use"])}점 상한)'),
        score=min(total, maxes['tech.use']))

    inv, sales = num(firm.get('invest_amount')), num(firm.get('sales_amount'))
    if inv is None or sales in (None, 0):
        warn.add('투자실적(투자액·건설부문 총매출액) 미입력 → 0점 처리')
        put('tech.invest', 0.0, '투자실적 미입력 → 0점', score=0.0)
    else:
        ratio = round(inv / sales * 100.0, 9)
        cfg = sc['invest']
        pts = next(p for b, p in cfg['points'] if ratio >= b)
        put('tech.invest', None, f"투자액 {_fmt(inv)}억 / 건설부문 총매출 {_fmt(sales)}억 = {rnd(ratio, 3)}% → {pts}점(원 배점 {cfg['base']}점 기준)",
            score=pts * maxes['tech.invest'] / cfg['base'])

    rate = num(firm.get('new_hire_rate'))
    if firm.get('reg_over_6m') is False:
        hire, hbasis = 0.0, '등록 후 6개월이 지나지 않아 가점 대상 아님'
    elif rate is None:
        hire, hbasis = 0.0, '신규 고용률 미입력 → 가점 없음'
    else:
        hire = next((p for b, p in sc['bonus_hire']['tiers'] if rate >= b), 0.0)
        hbasis = f'신규 고용률 {_fmt(rate)}% → 가점 {hire}점'
    return out, (hire, hbasis)


def _evaluate_bidder(spec, ctx, b, idx):
    digits = spec.get('rounding_digits', 2)
    sc = spec['scoring']
    name = (b.get('name') or '').strip() or f'입찰사 {idx + 1}'
    warn = Warn()
    persons = b.get('persons') or {}
    team_items, excellent, dq = _team(spec, ctx, persons, warn)
    items = list(team_items)
    members = [m for m in (b.get('members') or []) if isinstance(m, dict)]
    result_members = None

    if not members:
        calc, hire = _member(spec, ctx, b.get('firm') or {}, warn)
        for iid in MEMBER_ITEMS:
            c = calc[iid]
            items.append(_row(spec, ctx, iid, c['pct'], c['basis'], score=c['score']))
        hire_total, hire_basis = hire
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
            calc, hire = _member(spec, ctx, m.get('firm') or {}, mw)
            label = mname if mname.startswith('구성원') else f'구성원 {mname}'
            for t in mw.items:
                warn.add(f'[{label}] {t}')
            mres.append((mname, s / total_share, calc, hire))
        for iid in MEMBER_ITEMS:
            score, parts = 0.0, []
            for n, sh, calc, _h in mres:
                c = calc[iid]
                sn = rnd(c['score'], digits)
                score += sn * sh
                parts.append(f"[{n} 지분 {rnd(sh * 100, 1)}%: {c['basis']} = {_fmt(sn)}점 × {rnd(sh, 4)}]")
            items.append(_row(spec, ctx, iid, None, ' + '.join(parts), '공동이행: 구성원별 평가점수(소수 둘째자리) × 참여지분율 합산.', score=score))
        hire_total = sum(sh * h[0] for _n, sh, _c, h in mres)
        hire_basis = ' + '.join(f'[{n} 지분 {rnd(sh * 100, 1)}%: {h[1]} × {rnd(sh, 4)}]' for n, sh, _c, h in mres)
        result_members = [{'name': n, 'share': rnd(sh * 100, 2)} for n, sh, _c, _h in mres]

    order = {it['id']: i for i, it in enumerate(spec['items'])}
    items.sort(key=lambda it: order[it['id']])
    group_scores = {}
    for it in items:
        group_scores[it['group']] = rnd(group_scores.get(it['group'], 0.0) + it['score'], digits)
    base_total = rnd(sum(it['score'] for it in items), digits)

    ex_pts = sc['bonus_excellent'] if excellent else 0.0
    net_raw = hire_total + ex_pts
    cap = sc['net_cap']
    net = max(-cap, min(cap, net_raw))
    bparts = [f'신규 고용: {hire_basis}', ('우수 점검·진단기관 선정 가점 ' + _fmt(ex_pts) + '점') if excellent else '우수 점검·진단기관 가점 없음',
              f'가점 합계 {rnd(net_raw, 3)}점(상계 후 ±{cap}점 한도)']
    total = max(0.0, min(100.0, base_total + net))
    if base_total + net > 100:
        warn.add('가점 반영 후 100점을 초과해 100점으로 처리했습니다.')
    res = {'name': name, 'items': items, 'group_scores': group_scores, 'base_total': base_total,
           'bonus': {'score': rnd(net, digits), 'basis': ' / '.join(bparts), 'name': '가점(신규 고용·우수기관)'},
           'total': rnd(total, digits), 'disqualified': bool(dq), 'dq_reasons': dq, '_warn': warn.items}
    if result_members:
        res['members'] = result_members
    if dq:
        warn.add('실격 사유가 체크되어 순위에서 제외했습니다: ' + ', '.join(dq))
        res['_warn'] = warn.items
    return res


def evaluate(spec, project, bidders):
    warn = Warn()
    ctx = _context(spec, project, warn)
    results = [_evaluate_bidder(spec, ctx, b, i) for i, b in enumerate(bidders)]
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
