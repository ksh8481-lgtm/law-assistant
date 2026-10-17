"""
환경영향평가업자 사업수행능력 평가 엔진 (pq_engine의 'env' 엔진).

기준: 환경영향평가업자의 사업수행능력 세부평가기준(기후에너지환경부 고시) [별표]·[부표].
점수는 입력값을 [별표]의 구간표에 적용한 결정적 계산이며(AI 관여 없음), 항목마다 근거 문장(basis)을 남긴다.

구조
- 참여자 능력평가(group A): 총괄·분야별 책임평가자·분야별 평가자 역할별 배점에 그 역할 평가자들의 비율 평균을 곱한다.
  평가자별 비율은 자격·경력·실적·업무여유도를 구간표/식에 적용한 값이고, 이적계수를 곱한다.
- 업체능력평가(group B~E): 단독이면 1회, 공동도급이면 구성원별로 수행실적·재정건실도·개발·투자실적·청년고용 가점을
  평가한 뒤 지분율을 곱해 합산한다. 부실평가·공동도급 가점·업체능력평가는 사업체 전체 기준 1회.
"""
import math

from pq_engine import Warn, _fmt, num, rnd

CX = {'단순사업': '단순', '복잡사업': '복잡'}
MEMBER_ITEMS = ('firm.cnt', 'firm.amt', 'credit.finance', 'tech.dev', 'tech.invest')


def _item_name(spec, iid):
    return next(i['name'] for i in spec['items'] if i['id'] == iid)


def _group_of(spec, iid):
    return next(i['group'] for i in spec['items'] if i['id'] == iid)


def _tier(value, th, pcts):
    """value >= th[j] 인 첫 j의 (pct, j). 모두 미달이면 마지막 pct(j=len(th))."""
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


def _context(spec, project, warn):
    pj = project or {}
    cx = CX.get(pj.get('complexity'))
    if cx is None:
        raise ValueError('사업 정보에서 사업 구분(단순사업/복잡사업)을 선택해 주세요.')
    sc = spec['scoring']
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
    ob = num(pj.get('overlap_base'))
    if ob is None or ob <= 0:
        ob = sc['free']['base_amount']
        warn.add(f'업무여유도 기준금액이 비어 있어 2025년 기준 {_fmt(ob)}억원으로 계산했습니다. 해당 연도 금액(생산자물가지수 반영)을 입력해 주세요.')
    names = {}
    for key in ('fl_list', 'fm_list'):
        names[key] = [(r.get('name') or '').strip() for r in (pj.get(key) or []) if (r.get('name') or '').strip()]
    return {'cx': cx, 'order_amount': num(pj.get('order_amount')), 'overlap_base': ob, 'maxes': maxes,
            'total_max': total_max, 'names': names}


def _row(spec, ctx, iid, pct, basis, note='', score=None, digits=2):
    mx = ctx['maxes'][iid]
    s = mx * pct / 100.0 if score is None else score
    if pct is None:
        pct = (s / mx * 100.0) if mx else 0.0
    return {'id': iid, 'name': _item_name(spec, iid), 'group': _group_of(spec, iid), 'max': rnd(mx, digits),
            'pct': round(pct, 4), 'score': rnd(s, digits), 'basis': basis, 'note': note}


# ---------------------------------------------------------------- 참여평가자 1명
def _person_ratios(spec, ctx, role, p, label, warn):
    """평가자 1명의 {'qual','career','perf','free'} 비율(0~1) 또는 None(미입력), 근거 문장 목록."""
    sc = spec['scoring']
    cx = ctx['cx']
    out, texts = {}, {}
    # 이적계수(자격·경력·실적·업무여유도 점수에 곱함)
    tf = 1.0
    if not p.get('transfer_exempt'):
        tf = sc['transfer_factor'].get(p.get('transfer') or '해당 없음', 1.0)
    ttxt = f' × 이적계수 {tf}' if tf != 1.0 else ''

    g = p.get('grade')
    table = sc['qual'][role][cx]
    if g in (None, ''):
        out['qual'], texts['qual'] = None, f'{label}: 자격 구분 미입력'
    elif g not in table:
        warn.add(f'{label}: 자격 구분 \'{g}\'은(는) 이 역할({"총괄" if role == "lead" else "분야별 책임평가자" if role == "fl" else "분야별 평가자"})·{cx}사업 표에서 인정되지 않아 0점 처리')
        out['qual'], texts['qual'] = 0.0, f'{label} {g}: 표에서 인정되지 않음 → 0%'
    else:
        out['qual'] = table[g] / 100.0 * tf
        texts['qual'] = f'{label} {g} → {table[g]}%{ttxt}'

    ca, cb = num(p.get('career_a')), num(p.get('career_b'))
    if ca is None and cb is None:
        out['career'], texts['career'] = None, f'{label}: 경력 미입력'
    else:
        cfg = sc['career']
        eff = (ca or 0.0) + (cb or 0.0) * cfg['other_factor']
        pct, j = _tier(eff, cfg['th'], cfg['pct'][role][cx])
        out['career'] = pct / 100.0 * tf
        texts['career'] = f"{label} 경력 {_fmt(ca or 0)}년+{_fmt(cb or 0)}년×0.6={_fmt(rnd(eff, 3))}년 {_tier_text(rnd(eff, 3), cfg['unit'], cfg['th'], j).split('→')[1].strip()} → {pct}%{ttxt}"

    ns = [num(p.get(k)) for k in ('n_a', 'n_b', 'n_c', 'n_d')]
    if all(n is None for n in ns):
        out['perf'], texts['perf'] = None, f'{label}: 실적 미입력'
    else:
        coef = sc['coef']
        cs = [coef['type'][0] * coef['project'][0], coef['type'][0] * coef['project'][1],
              coef['type'][1] * coef['project'][0], coef['type'][1] * coef['project'][1]]
        eff = sum((n or 0.0) * c for n, c in zip(ns, cs))
        cfg = sc['perf']
        pct, j = _tier(eff, cfg['th'], cfg['pct'][role][cx])
        out['perf'] = pct / 100.0 * tf
        texts['perf'] = f"{label} 실적 계수 적용 {_fmt(rnd(eff, 3))}건 {_tier_text(rnd(eff, 3), cfg['unit'], cfg['th'], j).split('→')[1].strip()} → {pct}%{ttxt}"

    x = num(p.get('overlap'))
    base = ctx['overlap_base']
    if p.get('overlap_error'):
        out['free'], texts['free'] = 0.0, f'{label}: 업무여유도 평가자료 오류·누락 확인 → 0점(제6조제4항)'
    elif x is None:
        out['free'], texts['free'] = None, f'{label}: 업무여유도(중복금액) 미입력'
    else:
        over = max(0.0, (x - base) / base)
        ratio = max(0.0, 1.0 - over)
        out['free'] = ratio * tf
        texts['free'] = (f"{label} 중복금액 {_fmt(x)}억 (기준 {_fmt(base)}억): 배점 × (1 - 초과분/기준금액 {_fmt(rnd(over, 3))})"
                         + (' → 기준금액의 2배 이상이라 0점' if x >= 2 * base else '') + f' = {rnd(ratio * 100, 1)}%{ttxt}')
    return out, texts


def _participants(spec, ctx, persons, warn):
    sc = spec['scoring']
    maxes = ctx['maxes']
    items = []
    crit_names = {'qual': '자격 및 등급', 'career': '경력', 'perf': '실적', 'free': '업무여유도'}
    roles = (('lead', '총괄', None), ('fl', '분야별 책임평가자', 'fl_list'), ('fm', '분야별 평가자', 'fm_list'))
    people = []   # 전체 평가대상(교육훈련·전차 계산용)
    for role, rlabel, scope in roles:
        if scope is None:
            plist = [(rlabel, persons.get('lead') or {})]
        else:
            m = persons.get(role) or {}
            plist = [(n, m.get(n) or {}) for n in ctx['names'][scope]]
        res = []
        for n, p in plist:
            label = rlabel if scope is None else f'{rlabel}({n})'
            r, t = _person_ratios(spec, ctx, role, p, label, warn)
            res.append((n, r, t))
            people.append(p)
        for crit in ('qual', 'career', 'perf', 'free'):
            iid = f'{crit}.{role}'
            if not res or not plist or (scope is None and not plist[0][1]):
                if scope is None:
                    warn.add(f'{rlabel}: 입력 없음 → {crit_names[crit]} 0점 처리')
                else:
                    warn.add(f'{rlabel}: 구성(평가자)이 없어 {crit_names[crit]} 0점 처리')
                items.append(_row(spec, ctx, iid, 0.0, f'{rlabel}: 입력 없음', score=0.0))
                continue
            total, parts = 0.0, []
            for n, r, t in res:
                v = r[crit]
                if v is None:
                    warn.add(f'{t.split(":")[0]}: {t.split(": ", 1)[-1]} → 해당 평가자 0점 처리')
                    v = 0.0
                total += v
                parts.append(f'[{t}]')
            ratio = total / len(res)
            basis = f"{rlabel} {crit_names[crit]}: " + ' + '.join(parts)
            if len(res) > 1:
                basis += f' → 평가자 {len(res)}명 평균 {rnd(ratio * 100, 2)}%'
            items.append(_row(spec, ctx, iid, ratio * 100, basis))

    # 교육훈련 / 전차 이해도: 평가대상 인원 대비 비율
    n_all = len(people)
    if n_all == 0:
        warn.add('참여평가자가 없어 교육훈련·과업의 이해도 0점 처리')
        items.append(_row(spec, ctx, 'edu', 0.0, '평가자 없음', score=0.0))
        items.append(_row(spec, ctx, 'prev', 0.0, '평가자 없음', score=0.0))
    else:
        e = sc['edu']
        n2 = sum(1 for p in people if p.get('edu_training') == '2주 이상')
        n1 = sum(1 for p in people if p.get('edu_training') == '1주 이상 2주 미만')
        pts = (e['2주 이상'] * n2 + e['1주 이상 2주 미만'] * n1) / n_all
        items.append(_row(spec, ctx, 'edu', None, f"2주 이상 {n2}명×{_fmt(e['2주 이상'])}점 + 1주 이상 2주 미만 {n1}명×{_fmt(e['1주 이상 2주 미만'])}점, 평가대상 {n_all}명으로 나눔 = {_fmt(rnd(pts, 3))}점(원 배점 2점 기준)",
                          score=pts * maxes['edu'] / 2.0))
        np_ = sum(1 for p in people if p.get('prev'))
        items.append(_row(spec, ctx, 'prev', None, f'전차 단계 참여 {np_}명 / 평가대상 {n_all}명 = {rnd(np_ / n_all * 100, 1)}%',
                          score=maxes['prev'] * np_ / n_all))
    return items


# ---------------------------------------------------------------- 사업체 단위
def _bucket(credit, ctype, crate):
    """신용평가등급 -> 0(BBB- 이상) / 1(BBB- 미만 B- 이상) / 2(CCC+ 이하), 알 수 없으면 None."""
    bond = crate if ctype != '기업어음' else credit['paper_to_bond'].get(crate)
    if bond is None or bond not in credit['bond_order']:
        return None, None
    if credit['bond_order'].index(bond) <= credit['bond_order'].index('BBB-'):
        return 0, bond
    return (2 if bond == 'CCC+ 이하' else 1), bond


def _member(spec, ctx, firm, warn):
    sc = spec['scoring']
    maxes = ctx['maxes']
    cx = ctx['cx']
    out = {}

    def put(iid, pct=None, basis='', score=None):
        mx = maxes[iid]
        s = mx * pct / 100.0 if score is None else score
        out[iid] = {'pct': (s / mx * 100.0 if mx else 0.0) if pct is None else pct, 'score': s, 'basis': basis}

    coef = sc['coef']
    cs = [coef['type'][0] * coef['project'][0], coef['type'][0] * coef['project'][1],
          coef['type'][1] * coef['project'][0], coef['type'][1] * coef['project'][1]]
    cn = [num(firm.get(k)) for k in ('cnt_a', 'cnt_b', 'cnt_c', 'cnt_d')]
    if all(v is None for v in cn):
        warn.add('환경영향평가등 수행건수 미입력 → 0점 처리')
        put('firm.cnt', 0.0, '수행건수 미입력 → 0점', score=0.0)
    else:
        eff = sum((v or 0.0) * c for v, c in zip(cn, cs))
        cfg = sc['firm_cnt']
        pct, j = _tier(eff, cfg['th'][cx], cfg['pct'])
        put('firm.cnt', pct, f"유사평가 실적 계수 적용 {_fmt(rnd(eff, 3))}건({cx}사업) {_tier_text(rnd(eff, 3), cfg['unit'], cfg['th'][cx], j).split('→')[1].strip()} → {pct}%")
    am = [num(firm.get(k)) for k in ('amt_a', 'amt_b', 'amt_c', 'amt_d')]
    oa = ctx['order_amount']
    if all(v is None for v in am):
        warn.add('환경영향평가등 수행금액 미입력 → 0점 처리')
        put('firm.amt', 0.0, '수행금액 미입력 → 0점', score=0.0)
    elif not oa:
        warn.add('발주 용역금액이 없어 수행금액(%)을 계산할 수 없습니다 → 0점 처리')
        put('firm.amt', 0.0, '발주 용역금액 없음 → 0점', score=0.0)
    else:
        eff = sum((v or 0.0) * c for v, c in zip(am, cs))
        ratio = eff / oa * 100.0
        cfg = sc['firm_amt']
        pct, j = _tier(ratio, cfg['th'][cx], cfg['pct'])
        put('firm.amt', pct, f"유사평가 실적금액 계수 적용 {_fmt(rnd(eff, 3))}억 / 발주 용역금액 {_fmt(oa)}억 = {rnd(ratio, 1)}%({cx}사업) {_tier_text(rnd(ratio, 1), cfg['unit'], cfg['th'][cx], j).split('→')[1].strip()} → {pct}%")

    size, ctype, crate = firm.get('company_size'), firm.get('credit_type'), firm.get('credit_rating')
    cr = sc['credit']
    if ctype in (None, '', '미제출') or crate in (None, ''):
        put('credit.finance', 0.0, '신용평가등급 미제출 → 0점', score=0.0)
    elif size not in cr['pct']:
        warn.add('재정상태 건실도: 기업 규모(대기업·중기업/소기업)가 입력되지 않아 0점 처리')
        put('credit.finance', 0.0, '기업 규모 미입력 → 0점', score=0.0)
    else:
        b, bond = _bucket(cr, ctype, crate)
        if b is None:
            warn.add(f'신용평가등급 {crate}({ctype})을 인식하지 못해 0점 처리')
            put('credit.finance', 0.0, f'신용평가등급 {crate}({ctype}) 인식 불가 → 0점', score=0.0)
        else:
            pct = cr['pct'][size][b]
            band = ('BBB- 이상', 'BBB- 미만 B- 이상', 'CCC+ 이하')[b]
            put('credit.finance', pct, f"{ctype} {crate}" + (f' (회사채 {bond}에 준함)' if ctype == '기업어음' else '') + f' → {band}, {size} → {pct}%')

    dev = sc['dev']
    total, parts = 0.0, []
    for r in firm.get('dev_items') or []:
        t = r.get('type')
        if t not in dev['coef']:
            continue
        a = dev['coef'][t]
        if t == '신기술':
            bw, btxt = 1.0, '신기술(보호기간 내) B=1.0'
        else:
            age = num(r.get('age_years'))
            if age is None:
                warn.add(f'{t} 개발실적의 경과 기간이 비어 있어 B=1.0(5년 미만)으로 계산했습니다.')
                age = 0.0
            bw = next((w for bound, w in dev['age'][t] if age < bound), 0.0)
            btxt = f'경과 {_fmt(age)}년 B={bw}'
        pts = dev['unit_point'] * a * bw
        total += pts
        parts.append(f"{t} {dev['unit_point']}×A{a}×{btxt}={rnd(pts, 3)}")
    s = min(total, maxes['tech.dev'])
    put('tech.dev', None, ('개발실적 없음 → 0점' if not parts else ' + '.join(parts) + f' = {rnd(total, 3)}점 (배점 {_fmt(maxes["tech.dev"])}점 상한)'), score=s)

    inv, sales = num(firm.get('invest_amount')), num(firm.get('sales_amount'))
    if inv is None or sales in (None, 0):
        warn.add('투자실적(투자액·총매출액) 미입력 → 0점 처리')
        put('tech.invest', 0.0, '투자실적 미입력 → 0점', score=0.0)
    else:
        ratio = round(inv / sales * 100.0, 9)  # 부동소수 오차로 경계값이 아래 구간으로 밀리지 않게 함
        cfg = sc['invest']
        pts = next(p for b, p in cfg['points'] if ratio >= b)
        put('tech.invest', None, f"투자액 {_fmt(inv)}억 / 총매출 {_fmt(sales)}억 = {rnd(ratio, 3)}% → {pts}점(원 배점 {cfg['base']}점 기준)",
            score=pts * maxes['tech.invest'] / cfg['base'])

    rate = num(firm.get('youth_rate'))
    if rate is None:
        youth, ybasis = 0.0, '신규 고용율 미입력 → 가점 없음'
    else:
        r0 = math.floor(rate)
        youth = next((p for b, p in sc['youth']['tiers'] if r0 >= b), 0.0)
        ybasis = f'신규 고용율 {_fmt(rate)}%(절삭 {r0}%) → 가점 {youth}점'
    return out, (youth, ybasis)


def _evaluate_bidder(spec, ctx, b, idx):
    digits = spec.get('rounding_digits', 2)
    sc = spec['scoring']
    maxes = ctx['maxes']
    name = (b.get('name') or '').strip() or f'입찰사 {idx + 1}'
    warn = Warn()
    persons = b.get('persons') or {}
    team = persons.get('team') or {}
    items = _participants(spec, ctx, persons, warn)

    members = [m for m in (b.get('members') or []) if isinstance(m, dict)]
    result_members = None
    if not members:
        calc, youth = _member(spec, ctx, b.get('firm') or {}, warn)
        for iid in MEMBER_ITEMS:
            c = calc[iid]
            items.append(_row(spec, ctx, iid, c['pct'], c['basis'], score=c['score']))
        youth_total, youth_basis = youth
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
            calc, youth = _member(spec, ctx, m.get('firm') or {}, mw)
            label = mname if mname.startswith('구성원') else f'구성원 {mname}'
            for t in mw.items:
                warn.add(f'[{label}] {t}')
            mres.append((mname, s / total_share, calc, youth))
        for iid in MEMBER_ITEMS:
            score, parts = 0.0, []
            for n, sh, calc, _y in mres:
                c = calc[iid]
                sn = rnd(c['score'], digits)
                score += sn * sh
                parts.append(f"[{n} 지분 {rnd(sh * 100, 1)}%: {c['basis']} = {_fmt(sn)}점 × {rnd(sh, 4)}]")
            items.append(_row(spec, ctx, iid, None, ' + '.join(parts), '공동도급: 구성원별 평가점수(소수 둘째자리) × 용역참여 지분율 합산.', score=score))
        youth_total = sum(sh * y[0] for _n, sh, _c, y in mres)
        youth_basis = ' + '.join(f'[{n} 지분 {rnd(sh * 100, 1)}%: {y[1]} × {rnd(sh, 4)}]' for n, sh, _c, y in mres)
        result_members = [{'name': n, 'share': rnd(sh * 100, 2)} for n, sh, _c, _y in mres]

    # 사업체 전체 기준 항목
    bad = sc['bad']
    ms = math.ceil(num(team.get('bad_suspend')) or 0)
    mo = math.ceil(num(team.get('bad_other')) or 0)
    nf, npo = num(team.get('bad_false')) or 0.0, num(team.get('bad_poor')) or 0.0
    ded = bad['suspend_per_month'] * ms + bad['false_each'] * nf + bad['poor_each'] * npo + bad['other_per_month'] * mo
    s = max(0.0, maxes['credit.bad'] - ded)
    items.append(_row(spec, ctx, 'credit.bad', None,
                      f"{_fmt(maxes['credit.bad'])}점 - 업무정지 {ms}개월×0.2 - 거짓작성·복제 {_fmt(nf)}건×4 - 부실작성 {_fmt(npo)}건×2 - 타 법령 정지 {mo}개월×0.2 = {_fmt(rnd(s, 3))}점(0점 미만은 0점)", score=s))
    items.append(_row(spec, ctx, 'tech.use', None, '활용실적은 평가분야 관련 기술 인정범위 확정(2028. 12. 31.) 시까지 적용을 배제하고 일괄 만점 부여', '고시: 한시적 적용 배제(일괄 2점 부여).', score=maxes['tech.use']))
    jv_pts = sc['jv_each'] * (int(bool(team.get('jv_12'))) + int(bool(team.get('jv_small'))))
    items.append(_row(spec, ctx, 'jv.bonus', None,
                      f"제1종↔제2종 {'해당' if team.get('jv_12') else '해당 없음'} + 제1종↔소기업 {'해당' if team.get('jv_small') else '해당 없음'} → 각 0.5점, 합 {_fmt(jv_pts)}점(배점 {_fmt(maxes['jv.bonus'])}점 한도)",
                      score=min(jv_pts, maxes['jv.bonus'])))
    org = num(team.get('org_score'))
    if org is not None and org > maxes['org.eval']:
        warn.add(f"업체능력평가 점수 {_fmt(org)}점이 배점 {_fmt(maxes['org.eval'])}점을 넘어 배점으로 제한했습니다.")
    items.append(_row(spec, ctx, 'org.eval', None, ('발주기관이 정한 업체능력평가 점수 ' + (f'{_fmt(org)}점' if org is not None else '없음(미적용) → 0점')),
                      '발주기관별로 필요한 항목(사업책임평가자 능력평가·참여의향서 등)만 2점 범위에서 선택 적용.',
                      score=min(max(org or 0.0, 0.0), maxes['org.eval'])))

    order = {it['id']: i for i, it in enumerate(spec['items'])}
    items.sort(key=lambda it: order[it['id']])
    group_scores = {}
    for it in items:
        group_scores[it['group']] = rnd(group_scores.get(it['group'], 0.0) + it['score'], digits)
    base_total = rnd(sum(it['score'] for it in items), digits)
    etc = num(team.get('etc_points')) or 0.0
    bonus = youth_total + etc
    bparts = [f'청년고용: {youth_basis}']
    if etc:
        bparts.append(f'발주청이 정한 기타 가·감점 {_fmt(etc)}점')
    total = max(0.0, min(100.0, base_total + bonus))
    if base_total + bonus > 100:
        warn.add('가점 반영 후 100점을 초과해 100점으로 처리했습니다.')
    res = {'name': name, 'items': items, 'group_scores': group_scores, 'base_total': base_total,
           'bonus': {'score': rnd(bonus, digits), 'basis': ' / '.join(bparts), 'name': '가점·감점(청년고용 등)'},
           'total': rnd(total, digits), '_warn': warn.items}
    if result_members:
        res['members'] = result_members
    return res


def evaluate(spec, project, bidders):
    warn = Warn()
    ctx = _context(spec, project, warn)
    results = [_evaluate_bidder(spec, ctx, b, i) for i, b in enumerate(bidders)]
    order = sorted(range(len(results)), key=lambda i: -results[i]['total'])
    last_total, last_rank = None, 0
    for pos, i in enumerate(order, start=1):
        t = results[i]['total']
        if last_total is not None and abs(t - last_total) < 1e-9:
            results[i]['rank'] = last_rank
        else:
            results[i]['rank'] = pos
            last_total, last_rank = t, pos
    for r in results:
        for w in r.pop('_warn'):
            warn.add(f"[{r['name']}] {w}")
    return {'spec_id': spec['id'], 'maxes': {k: rnd(v, 2) for k, v in ctx['maxes'].items()},
            'total_max': rnd(ctx['total_max'], 2), 'results': results, 'warnings': warn.items}
