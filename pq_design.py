"""
설계 등 건설엔지니어링사업자 사업수행능력 평가 엔진 (pq_engine의 'design' 엔진).

기준: 경상남도 건설엔지니어링사업자 사업수행능력 세부평가기준 [별표 1](경상남도 공고 제2026-1486호).
점수는 입력값을 [별표 1]의 구간표에 적용한 결정적 계산이며(AI 관여 없음), 항목마다 근거 문장(basis)을 남긴다.

구조
- 팀 단위(group A 참여기술인, group E 업무중첩도, 젊은기술인 가점, 실격): 공동수급체여도 한 번만 평가한다.
- 사업체 단위(group B~D, 신규 고용 가점): 단독이면 1회, 공동이행이면 구성원별로 평가한다. 합산 방식은 항목마다 고시가 다르다.
  · 유사실적 건수·금액: 구성원 값 × 지분율을 합산한 뒤 구간표 적용
  · 투자실적: 구성원 비율 × 지분율을 합산한 뒤 구간표 적용
  · 수행성과·전차 실적·영업정지(업무정지·벌점)·재정건실도: 구성원별 점수 × 지분율 합산
  · 개발·활용실적: 구성원별 점수 × 지분율 합산 후 배점 상한 적용
"""
import math

from pq_engine import Warn, _fmt, num, relative_grades, rnd

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
    has_prev = bool(pj.get('has_prev'))
    skip_tech = bool(pj.get('skip_tech'))
    rel = 'relative' if str(pj.get('rel_mode', '')).startswith('평가위원') else 'direct'
    full, step = num(pj.get('overlap_full')), num(pj.get('overlap_step'))
    if full is None or full <= 0 or step is None or step <= 0:
        raise ValueError('사업 정보에 업무중첩도 만점기준(%)과 차등폭(%)을 입력해 주세요(발주청이 정하는 값입니다).')
    style = 'le' if str(pj.get('overlap_style', '')).startswith('이하') else ('lt' if str(pj.get('overlap_style', '')).startswith('미만') else None)
    if style is None:
        raise ValueError('사업 정보에서 업무중첩도 구간 경계 방식(이하·초과 / 미만·이상)을 선택해 주세요.')
    if not (200 <= full <= 300):
        warn.add(f'업무중첩도 만점기준 {_fmt(full)}%가 고시 범위(200~300%)를 벗어났습니다.')

    base = {it['id']: float(it['max']) for it in spec['items']}
    tech_amt = float(sc['tech_points']['with_prev' if has_prev else 'no_prev'])
    base['prev.firm'] = 1.0 if has_prev else 0.0
    base['prev.person'] = 1.0 if has_prev else 0.0
    base['edu'] = 1.0 if has_prev else 2.0
    base['lead.tech'] = 0.0 if skip_tech else tech_amt
    base['lead.cnt'] = 5.0 + (tech_amt if skip_tech else 0.0)
    dynamic = {it['id'] for it in spec['items'] if it.get('dynamic')}

    maxes = dict(base)
    pct_adj = spec.get('adjust_pct', 20)
    for iid, v in (pj.get('adjust') or {}).items():
        v = num(v)
        if iid not in base or v is None or iid in dynamic:
            continue
        lo, hi = base[iid] * (1 - pct_adj / 100.0), base[iid] * (1 + pct_adj / 100.0)
        if v < lo - 1e-9 or v > hi + 1e-9:
            warn.add(f"'{_item_name(spec, iid)}' 배점 {_fmt(v)}점이 고시 허용 범위({_fmt(lo)}~{_fmt(hi)}점, ±{pct_adj}%)를 벗어났습니다.")
        maxes[iid] = v
    total_max = sum(maxes.values())
    if abs(total_max - 100) > 0.01:
        warn.add(f'배점 합계가 {_fmt(total_max)}점입니다(고시의 합계는 100점).')
    staff = [(r.get('name') or '').strip() for r in (pj.get('staff_list') or []) if (r.get('name') or '').strip()]
    return {'has_prev': has_prev, 'skip_tech': skip_tech, 'rel': rel, 'no_result': num(pj.get('no_result_score')),
            'ov_full': full, 'ov_step': step, 'ov_style': style, 'maxes': maxes, 'total_max': total_max,
            'fields': _weights(pj.get('fields'), warn, '평가 대상 분야 구성'), 'staff': staff}


def _row(spec, ctx, iid, pct, basis, note='', score=None, digits=2):
    mx = ctx['maxes'][iid]
    s = mx * pct / 100.0 if score is None else score
    if pct is None:
        pct = (s / mx * 100.0) if mx else 0.0
    return {'id': iid, 'name': _item_name(spec, iid), 'group': _group_of(spec, iid), 'max': rnd(mx, digits),
            'pct': round(pct, 4), 'score': rnd(s, digits), 'basis': basis, 'note': note}


def _transfer(spec, p):
    if p.get('transfer_exempt'):
        return 1.0
    return spec['scoring']['transfer_factor'].get(p.get('transfer') or '해당 없음', 1.0)


# ---------------------------------------------------------------- 참여기술인 1명
def _person(spec, ctx, role, p, label, warn):
    """등급·경력·실적 비율(0~100, 이적계수 반영) 또는 None(미입력)과 근거문. 책임기술인 최소 요건 미달 사유도 돌려준다."""
    sc = spec['scoring']
    tf = _transfer(spec, p)
    ttxt = f' × 이적계수 {tf}' if tf != 1.0 else ''
    out, texts = {}, {}

    g = p.get('grade')
    tbl = sc['grade'][role]
    if g in (None, ''):
        out['grade'], texts['grade'] = None, f'{label}: 등급 미입력'
    elif g not in tbl or g == 'base':
        warn.add(f'{label}: 등급 \'{g}\'은(는) 등급표에 없어 0점 처리')
        out['grade'], texts['grade'] = 0.0, f'{label} 등급 {g}: 표에 없음 → 0%'
    else:
        out['grade'] = tbl[g] / tbl['base'] * 100.0 * tf
        texts['grade'] = f"{label} {g} → {_fmt(tbl[g])}점/{_fmt(tbl['base'])}점{ttxt}"

    gr = sc['grids']
    c = num(p.get('career'))
    if c is None:
        out['career'], texts['career'] = None, f'{label}: 경력 미입력'
    else:
        g_ = gr[f'{role}.career']
        pct, j = _tier(c, g_['th'], sc['grid_pct'])
        out['career'] = pct * tf
        texts['career'] = f"{label} 경력 {_tier_text(c, g_['unit'], g_['th'], j)} → {pct}%{ttxt}"

    a, b = num(p.get('cnt')), num(p.get('cnt_field'))
    if a is None and b is None:
        out['cnt'], texts['cnt'] = None, f'{label}: 실적 미입력'
    else:
        fac = sc['other_field_factor'][role]
        eff = (a or 0.0) + (b or 0.0) * fac
        g_ = gr[f'{role}.cnt']
        pct, j = _tier(eff, g_['th'], sc['grid_pct'])
        out['cnt'] = pct * tf
        texts['cnt'] = f"{label} 실적 {_fmt(a or 0)}건+{_fmt(b or 0)}건×{fac}={_fmt(rnd(eff, 3))}건 {_tier_text(rnd(eff, 3), g_['unit'], g_['th'], j).split('→')[1].strip()} → {pct}%{ttxt}"
    return out, texts


def _overlap_pct(ctx, v):
    """업무중첩비율(%) -> 비율(100/90/80/70/60)과 설명."""
    full, step, style = ctx['ov_full'], ctx['ov_step'], ctx['ov_style']
    pcts = [100, 90, 80, 70, 60]
    for i in range(4):
        bound = full + step * i
        if (v <= bound) if style == 'le' else (v < bound):
            if i == 0:
                rng = f"{_fmt(full)}% {'이하' if style == 'le' else '미만'}"
            else:
                lo = full + step * (i - 1)
                rng = (f"{_fmt(lo)}% 초과 {_fmt(bound)}% 이하" if style == 'le' else f"{_fmt(lo)}% 이상 {_fmt(bound)}% 미만")
            return pcts[i], rng
    lo = full + step * 3
    return pcts[4], (f'{_fmt(lo)}% 초과' if style == 'le' else f'{_fmt(lo)}% 이상')


def _prev_pts(table, elapsed):
    for bound, pts in table:
        if elapsed < bound:
            return pts
    return 0.0


def _team(spec, ctx, persons, tech_grade, warn):
    sc = spec['scoring']
    maxes = ctx['maxes']
    items, dq = [], []
    lead = persons.get('lead') or {}
    team = persons.get('team') or {}

    def add(iid, pct, basis, note='', score=None):
        if maxes.get(iid, 0) <= 0:
            return
        items.append(_row(spec, ctx, iid, pct, basis, note, score))

    def zero(iid, basis):
        add(iid, 0.0, basis, score=0.0)

    # --- 책임기술인
    label = '책임기술인'
    if not lead:
        warn.add(f'{label}: 입력 없음 → 0점 처리')
        for iid in ('lead.grade', 'lead.career', 'lead.cnt', 'lead.tech', 'ovl.lead'):
            zero(iid, f'{label}: 입력 없음')
    else:
        r, t = _person(spec, ctx, 'lead', lead, label, warn)
        for crit in ('grade', 'career', 'cnt'):
            iid = f'lead.{crit}'
            if r[crit] is None:
                warn.add(f'{t[crit]} → 0점 처리')
                zero(iid, t[crit])
            else:
                add(iid, r[crit], t[crit])
        # 최소 경력·실적 요건(같은 사업분야): 3년·3건 미만이면 실격
        mn = sc['lead_min']
        c, n = num(lead.get('career')), num(lead.get('cnt'))
        if c is not None and c < mn['career']:
            dq.append(f"책임기술인 경력 {_fmt(c)}년이 최소 {mn['career']}년 미달")
        if n is not None and n < mn['cnt']:
            dq.append(f"책임기술인 같은 사업분야 실적 {_fmt(n)}건이 최소 {mn['cnt']}건 미달")
        if maxes['lead.tech'] > 0:
            g = tech_grade
            if g in (None, '', '미제출'):
                warn.add('책임기술인 기술능력·업무관리능력 평가 미제출·미입력 → 0점 처리')
                zero('lead.tech', '기술능력·업무관리능력: 평가서 미제출 → 0점')
            else:
                pct = sc['relative_grade_pct'][g]
                how = '상대평가 자동 배분' if ctx['rel'] == 'relative' else '등급 직접 입력'
                add('lead.tech', pct, f'기술능력·업무관리능력 {g} 등급({how}) → 배점 {_fmt(maxes["lead.tech"])}점 × {pct}%')

    # --- 분야별 책임/참여기술인
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
            if not p:
                pct, text = None, f'{lab}: 입력 없음'
            else:
                r, t = _person(spec, ctx, role, p, lab, warn)
                pct, text = r[crit], t[crit]
            if pct is None:
                warn.add(f'{text} → 해당 분야 0점 처리')
                pct, text = 0.0, f'{text} → 0'
            total += w * pct
            parts.append(f'[{text} × 배분율 {rnd(w * 100, 1)}%]')
        add(iid, total, f'{rlabel} ' + ' + '.join(parts))

    for role, rlabel in (('fl', '분야별 책임기술인'), ('fm', '분야별 참여기술인')):
        for crit, cname in (('grade', '등급'), ('career', '경력'), ('cnt', '실적')):
            weighted(f'{role}.{crit}', role, crit, f'{rlabel} {cname}')

    # --- 교육훈련 / 참여기술인 전차 실적
    people = [lead] if lead else []
    for role in ('fl', 'fm'):
        pm = persons.get(role) or {}
        people += [pm.get(n) or {} for n, _w in ctx['fields']]
    n_all = len(people) if people else 0
    if maxes['edu'] > 0:
        if n_all == 0:
            warn.add('참여기술인이 없어 교육훈련 0점 처리')
            zero('edu', '참여기술인 없음')
        else:
            e = sc['edu']
            n2 = sum(1 for p in people if p.get('edu_training') == '2주 이상')
            n1 = sum(1 for p in people if p.get('edu_training') == '1주 이상 2주 미만')
            share = (n2 * e['full'] + n1 * e['half']) / n_all
            add('edu', None, f"2주 이상 {n2}명×1 + 1주 이상 2주 미만 {n1}명×0.5 = {_fmt(n2 + 0.5 * n1)}, 평가대상 {n_all}명으로 나눈 {rnd(share * 100, 1)}% × 배점 {_fmt(maxes['edu'])}점",
                score=maxes['edu'] * share)
    if maxes['prev.person'] > 0:
        pp = sc['prev_person']
        parts, total = [], 0.0
        le = num(lead.get('prev_elapsed')) if lead else None
        if le is not None:
            rate = (num(lead.get('prev_rate')) if num(lead.get('prev_rate')) is not None else 100.0) / 100.0
            pts = _prev_pts(pp['elapsed'], le) * rate
            total += pts
            parts.append(f'[책임기술인: 완료 후 {_fmt(le)}년 {_prev_pts(pp["elapsed"], le)}점 × 인정률 {rnd(rate * 100, 1)}% = {rnd(pts, 3)}]')
        fl_sum, fl_parts = 0.0, []
        for fname, _w in ctx['fields']:
            p = (persons.get('fl') or {}).get(fname) or {}
            e_ = num(p.get('prev_elapsed'))
            if e_ is None:
                continue
            rate = (num(p.get('prev_rate')) if num(p.get('prev_rate')) is not None else 100.0) / 100.0
            pts = _prev_pts(pp['elapsed'], e_) * rate
            fl_sum += pts
            fl_parts.append(f'{fname} {rnd(pts, 3)}')
        if fl_parts:
            nf = num(team.get('prev_fl_fields'))
            if not nf:
                nf = float(len(fl_parts))
                warn.add('전차건설엔지니어링의 분야 수가 비어 있어 전차 참여 분야별 책임기술인 수로 나누었습니다. 전차 분야 수를 입력해 주세요.')
            total += fl_sum / nf
            parts.append(f"[분야별 책임기술인: ({' + '.join(fl_parts)}) ÷ 전차 분야 {_fmt(nf)}개 = {rnd(fl_sum / nf, 3)}]")
        s = min(total, maxes['prev.person'])
        add('prev.person', None, ('전차건설엔지니어링 참여기술인 없음 → 0점' if not parts else ' + '.join(parts) + f' = {rnd(total, 3)}점(배점 {_fmt(maxes["prev.person"])}점 한도)'), score=s)

    # --- 업무중첩도
    def ov(p, lab):
        v = num(p.get('overlap_pct'))
        if v is None:
            return None, f'{lab}: 중첩비율 미입력'
        pct, rng = _overlap_pct(ctx, v)
        return pct, f'{lab} 중첩 {_fmt(v)}% → {rng} → {pct}%'

    if not lead:
        zero('ovl.lead', '책임기술인: 입력 없음')
    else:
        pct, text = ov(lead, '책임기술인')
        if pct is None:
            warn.add(f'{text} → 0점 처리')
            zero('ovl.lead', text)
        else:
            add('ovl.lead', pct, text)
    for role, rlabel in (('fl', '분야별 책임기술인'), ('fm', '분야별 참여기술인')):
        iid = f'ovl.{role}'
        pm = persons.get(role) or {}
        targets = [(n, w, pm.get(n) or {}) for n, w in ctx['fields'] if (pm.get(n) or {}).get('ovl_target')]
        if not targets:
            warn.add(f'{rlabel}: 업무중첩도 평가 대상(주 공종 분야 3~5개)이 체크되지 않아 0점 처리')
            zero(iid, f'{rlabel}: 평가 대상 없음')
            continue
        wsum = sum(w for _n, w, _p in targets) or 1.0
        total, parts = 0.0, []
        for n, w, p in targets:
            pct, text = ov(p, f'{rlabel}({n})')
            if pct is None:
                warn.add(f'{text} → 해당 분야 0점 처리')
                pct, text = 0.0, f'{text} → 0'
            total += (w / wsum) * pct
            parts.append(f'[{text} × 대상 분야 내 배분율 {rnd(w / wsum * 100, 1)}%]')
        add(iid, total, f'{rlabel} 업무중첩도(주 공종 분야 {len(targets)}개): ' + ' + '.join(parts))
    if not ctx['staff']:
        warn.add('실무기술인 구성이 없어 업무중첩도(실무기술인) 0점 처리')
        zero('ovl.staff', '실무기술인: 구성 없음')
    else:
        sm = persons.get('staff') or {}
        total, parts = 0.0, []
        for n in ctx['staff']:
            pct, text = ov(sm.get(n) or {}, f'실무기술인({n})') if sm.get(n) else (None, f'실무기술인({n}): 입력 없음')
            if pct is None:
                warn.add(f'{text} → 해당 기술인 0점 처리')
                pct, text = 0.0, f'{text} → 0'
            total += pct
            parts.append(f'[{text}]')
        add('ovl.staff', total / len(ctx['staff']), '실무기술인 ' + ' + '.join(parts) + f' → {len(ctx["staff"])}명 평균')

    # --- 젊은기술인 참여 가점
    yc, yt = num(team.get('young_cnt')), num(team.get('young_total'))
    if yc is None or not yt:
        young, ybasis = 0.0, '젊은기술인 참여 인원 미입력 → 가점 없음'
    else:
        ratio = round(yc / yt * 100.0, 9)
        young = next((p for b, p in sc['bonus_young']['tiers'] if ratio >= b), 0.0)
        ybasis = f'젊은기술인 {_fmt(yc)}명 / 전체 {_fmt(yt)}명 = {rnd(ratio, 2)}% → 가점 {young}점'
    if team.get('dq_other'):
        dq.append('그 밖의 실격 사유(발주청 확인)')
    return items, (young, ybasis), dq


# ---------------------------------------------------------------- 사업체 1곳의 원자료
def _member_raw(spec, ctx, firm, warn):
    sc = spec['scoring']
    maxes = ctx['maxes']
    raw = {}
    raw['sim_cnt'], raw['sim_amt'] = num(firm.get('sim_cnt')), num(firm.get('sim_amt'))
    raw['perf_avg'] = num(firm.get('perf_avg'))

    # 사업체 전차: 경과기간 점수 × 인정률
    pe = num(firm.get('prev_firm_elapsed'))
    if pe is None:
        raw['prev_firm'] = (0.0, '전차건설엔지니어링 수행실적 없음 → 0점')
    else:
        rate = (num(firm.get('prev_firm_rate')) if num(firm.get('prev_firm_rate')) is not None else 100.0) / 100.0
        base = _prev_pts(sc['prev_firm']['elapsed'], pe)
        raw['prev_firm'] = (base * rate, f'전차 완료 후 {_fmt(pe)}년 {base}점 × 인정률 {rnd(rate * 100, 1)}%')

    # 업무정지·벌점 등: 7점에서 차감
    st = sc['stop']
    mf, mt = math.ceil(num(firm.get('stop_months')) or 0), math.ceil(num(firm.get('tech_stop_months')) or 0)

    def table_deduct(v):
        if v is None:
            return 0.0, '없음'
        for bound, ded in st['penalty_table']:
            if v >= bound:
                return ded, f'평균벌점 {_fmt(v)}점 → -{_fmt(ded)}점'
        return 0.0, f'평균벌점 {_fmt(v)}점 → 감점 없음'

    bf, tf_ = table_deduct(num(firm.get('bad_avg_firm')))
    bt, tt_ = table_deduct(num(firm.get('bad_avg_tech')))
    ded = st['per_month'] * (mf + mt) + bf + bt
    mx = maxes['credit.stop']
    s = max(0.0, mx - ded)
    raw['stop'] = (s, f"{_fmt(mx)}점 - 사업자 영업정지 {mf}개월×0.2 - 참여기술인 정지 {mt}개월×0.2 - 사업자 벌점({tf_}) - 참여기술인 벌점({tt_}) = {_fmt(rnd(s, 3))}점(0점 미만은 0점)")

    cr = sc['credit']
    ctype, crate = firm.get('credit_type'), firm.get('credit_rating')
    if ctype in (None, '', '미제출') or crate in (None, ''):
        raw['finance'] = (0.0, '신용평가등급 미제출 → 0점')
    else:
        bond = crate if ctype != '기업어음' else cr['paper_to_bond'].get(crate)
        if bond is None or bond not in cr['bond_order']:
            warn.add(f'신용평가등급 {crate}({ctype})을 인식하지 못해 0점 처리')
            raw['finance'] = (0.0, f'신용평가등급 {crate}({ctype}) 인식 불가 → 0점')
        else:
            ri = cr['bond_order'].index(bond)
            if ri <= cr['bond_order'].index('BBB-'):
                pts, band = cr['points']['ge_BBB-'], 'BBB- 이상(회사채 기준)'
            elif bond == 'CCC+ 이하':
                pts, band = cr['points']['le_CCC+'], 'CCC+ 이하(회사채 기준)'
            else:
                pts, band = cr['points']['lt_BBB-_ge_B-'], 'BBB- 미만 B- 이상(회사채 기준)'
            raw['finance'] = (pts, f"{ctype} {crate}" + (f' (회사채 {bond}에 준함)' if ctype == '기업어음' else '') + f' → {band} → {pts}점(원 배점 3.0 기준)')

    # 개발실적(상한 적용 전 점수): 건설신기술 2.0, 특허 1.0, 실용신안 0.5 × 경과기간 가중치 ÷ 출원자 수, 동일 내용은 높은 1건
    dv = sc['dev']
    best = {}
    for i, r_ in enumerate(firm.get('dev_items') or []):
        t = r_.get('type')
        if t not in dv['base_points']:
            continue
        n = max(1.0, num(r_.get('applicants')) or 1.0)
        wt, wtxt = 1.0, ''
        if t in dv['age']:
            age = num(r_.get('age_years'))
            if age is None:
                warn.add(f'{t} 개발실적의 출원 후 경과기간이 비어 있어 100%(5년 미만)로 계산했습니다.')
                age = 0.0
            wt = next((p for b, p in dv['age'][t] if age < b), 0.0) / 100.0
            wtxt = f' × 경과 {_fmt(age)}년 {rnd(wt * 100)}%'
        pts = dv['base_points'][t] * wt / n
        grp = (r_.get('dup_group') or '').strip() or f'__{i}'
        text = f"{t} {dv['base_points'][t]}점{wtxt}" + (f'÷{_fmt(n)}명' if n > 1 else '') + f'={rnd(pts, 3)}'
        if grp not in best or pts > best[grp][0]:
            best[grp] = (pts, text)
    raw['dev'] = (sum(p for p, _x in best.values()), ' + '.join(x for _p, x in best.values()))

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
        if t in us['age']:
            age = num(r_.get('age_years'))
            if age is None:
                warn.add(f'{t} 활용실적의 출원 후 경과기간이 비어 있어 100%(5년 미만)로 계산했습니다.')
                age = 0.0
            wt = next((p for b, p in us['age'][t] if age < b), 0.0) / 100.0
            wtxt = f' × 경과 {_fmt(age)}년 {rnd(wt * 100)}%'
        pts = us['base_points'][t] * w * cnt * wt
        grp = (r_.get('dup_group') or '').strip() or f'__{i}'
        text = f"{t} {us['base_points'][t]}점 × 가중치 {w}(건수 {_fmt(cnt)}건·금액 {_fmt(amt)}억 중 유리한 구간) × {_fmt(cnt)}건{wtxt} = {rnd(pts, 3)}"
        if grp not in best or pts > best[grp][0]:
            best[grp] = (pts, text)
    raw['use'] = (sum(p for p, _x in best.values()), ' + '.join(x for _p, x in best.values()))

    inv, sales = num(firm.get('invest_amount')), num(firm.get('sales_amount'))
    raw['invest'] = None if (inv is None or sales in (None, 0)) else (round(inv / sales * 100.0, 9), inv, sales)

    rate_ = num(firm.get('new_hire_rate'))
    if firm.get('reg_over_6m') is False:
        raw['hire'] = (0.0, '등록 후 6개월이 지나지 않아 가점 대상 아님')
    elif rate_ is None:
        raw['hire'] = (0.0, '신규 고용률 미입력 → 가점 없음')
    else:
        pts = next((p for b, p in sc['bonus_hire']['tiers'] if rate_ >= b), 0.0)
        raw['hire'] = (pts, f'신규 고용률 {_fmt(rate_)}% → 가점 {pts}점')
    return raw


def _firm_items(spec, ctx, members, warn):
    """members: [(이름, 지분(0~1), raw)]. 단독이면 지분 1. 항목마다 고시의 합산 방식을 적용한다."""
    sc = spec['scoring']
    maxes = ctx['maxes']
    digits = spec.get('rounding_digits', 2)
    jv = len(members) > 1 or members[0][0] is not None
    items = []

    def tag(n, sh):
        return f'[{n} 지분 {rnd(sh * 100, 1)}%: ' if jv else '['

    def add(iid, pct, basis, note='', score=None):
        if maxes.get(iid, 0) <= 0:
            return
        items.append(_row(spec, ctx, iid, pct, basis, note, score))

    # 유사실적 건수·금액: 구성원 값 × 지분율 합산 후 구간
    for iid, key, label in (('sim.cnt', 'sim_cnt', '유사건설엔지니어링 수행실적 건수'), ('sim.amt', 'sim_amt', '유사건설엔지니어링 수행실적 금액')):
        vals = [(n, sh, r[key]) for n, sh, r in members]
        if all(v is None for _n, _s, v in vals):
            warn.add(f'{label} 미입력 → 0점 처리')
            add(iid, 0.0, f'{label} 미입력 → 0점', score=0.0)
            continue
        total = sum(sh * (v or 0.0) for _n, sh, v in vals)
        g = sc['grids'][iid]
        pct, j = _tier(rnd(total, 3), g['th'], sc['grid_pct'])
        txt = ''
        if jv:
            txt = ' + '.join(f"{tag(n, sh)}{_fmt(v or 0)}{g['unit']}]" for n, sh, v in vals) + f' = {_fmt(rnd(total, 3))}{g["unit"]}(실적×지분율 합산) / '
        add(iid, pct, f"{txt}{label} {_tier_text(rnd(total, 3), g['unit'], g['th'], j)} → {pct}%")

    # 수행성과: 구성원별 점수 × 지분율
    rs = sc['result']
    mx = maxes['result']
    parts, total = [], 0.0
    for n, sh, r in members:
        avg = r['perf_avg']
        if avg is not None:
            pct, _j = _tier(avg, [t[0] for t in rs['tiers'][:-1]], [t[1] for t in rs['tiers']])
            s = mx * pct / 100.0
            txt = f'수행성과 평균 {_fmt(avg)}점 → {pct}% = {_fmt(rnd(s, 3))}점'
        elif ctx['no_result'] is not None:
            s = ctx['no_result']
            txt = f'해당 발주청 수행성과 없음 → 기본 {_fmt(s)}점'
        else:
            warn.add('건설엔지니어링 수행성과가 비어 있고 기본 점수도 정해지지 않아 0점 처리')
            s, txt = 0.0, '수행성과 미입력 → 0점'
        total += rnd(s, digits) * sh
        parts.append(f'{tag(n, sh)}{txt}]' + (f' × {rnd(sh, 4)}' if jv else ''))
    add('result', None, ' + '.join(parts), '고시: 수행성과가 없는 사업체에는 1.8 또는 1.6점을 부여할 수 있음(입찰공고 시 제시). 공동수급체는 분담비율 가중치의 합.', score=total)

    # 전차 실적(사업체)
    if maxes['prev.firm'] > 0:
        total, parts = 0.0, []
        for n, sh, r in members:
            pts, txt = r['prev_firm']
            total += rnd(pts, digits) * sh
            parts.append(f'{tag(n, sh)}{txt} = {_fmt(rnd(pts, 3))}점]' + (f' × {rnd(sh, 4)}' if jv else ''))
        add('prev.firm', None, ' + '.join(parts), score=min(total, maxes['prev.firm']))

    # 업무정지·벌점 / 재정건실도: 구성원별 점수 × 지분율
    for iid, key in (('credit.stop', 'stop'), ('credit.finance', 'finance')):
        total, parts = 0.0, []
        for n, sh, r in members:
            s, txt = r[key]
            if key == 'finance':
                s = s * maxes['credit.finance'] / 3.0
            total += rnd(s, digits) * sh
            parts.append(f'{tag(n, sh)}{txt}]' + (f' × {rnd(sh, 4)}' if jv else ''))
        add(iid, None, ' + '.join(parts), score=total)

    # 개발·활용: 점수 × 지분율 합산 후 상한
    for iid, key, label in (('tech.dev', 'dev', '개발실적'), ('tech.use', 'use', '활용실적')):
        total, parts = 0.0, []
        for n, sh, r in members:
            s, txt = r[key]
            total += s * sh
            parts.append(f'{tag(n, sh)}{txt or "없음"} = {_fmt(rnd(s, 3))}점]' + (f' × {rnd(sh, 4)}' if jv else ''))
        capped = min(total, maxes[iid])
        add(iid, None, f'{label}: ' + ' + '.join(parts) + f' = {_fmt(rnd(total, 3))}점 (배점 {_fmt(maxes[iid])}점 상한)', score=capped)

    # 투자실적: 비율 × 지분율 합산 후 구간
    inv = sc['invest']
    ratios = [(n, sh, r['invest']) for n, sh, r in members]
    if all(v is None for _n, _s, v in ratios):
        warn.add('투자실적(투자액·건설부문 총매출액) 미입력 → 0점 처리')
        add('tech.invest', 0.0, '투자실적 미입력 → 0점', score=0.0)
    else:
        if any(v is None for _n, _s, v in ratios):
            warn.add('투자실적이 비어 있는 구성원은 비율 0%로 계산했습니다.')
        total = sum(sh * (v[0] if v else 0.0) for _n, sh, v in ratios)
        total = round(total, 9)
        pts = next(p for b, p in inv['points'] if total >= b)
        txt = ''
        if jv:
            txt = ' + '.join(f"{tag(n, sh)}{rnd(v[0] if v else 0.0, 3)}%]" for n, sh, v in ratios) + f' = {rnd(total, 3)}%(비율×지분율 합산) / '
        else:
            v = ratios[0][2]
            txt = f'투자액 {_fmt(v[1])}억 / 건설부문 총매출 {_fmt(v[2])}억 = '
        add('tech.invest', None, f"{txt}{rnd(total, 3)}% → {pts}점(원 배점 {inv['base']}점 기준)", score=pts * maxes['tech.invest'] / inv['base'])

    hire_total = sum(sh * r['hire'][0] for _n, sh, r in members)
    hire_basis = ' + '.join(f"{tag(n, sh)}{r['hire'][1]}]" + (f' × {rnd(sh, 4)}' if jv else '') for n, sh, r in members)
    return items, hire_total, hire_basis


def _evaluate_bidder(spec, ctx, b, idx, tech_grade):
    digits = spec.get('rounding_digits', 2)
    name = (b.get('name') or '').strip() or f'입찰사 {idx + 1}'
    warn = Warn()
    persons = b.get('persons') or {}
    team_items, (young, ybasis), dq = _team(spec, ctx, persons, tech_grade, warn)
    items = list(team_items)
    members = [m for m in (b.get('members') or []) if isinstance(m, dict)]
    result_members = None
    if not members:
        raw = _member_raw(spec, ctx, b.get('firm') or {}, warn)
        f_items, hire_total, hire_basis = _firm_items(spec, ctx, [(None, 1.0, raw)], warn)
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
        mlist = []
        for mi, (m, s) in enumerate(keep):
            mname = (m.get('name') or '').strip() or f'구성원 {mi + 1}'
            mw = Warn()
            raw = _member_raw(spec, ctx, m.get('firm') or {}, mw)
            label = mname if mname.startswith('구성원') else f'구성원 {mname}'
            for t in mw.items:
                warn.add(f'[{label}] {t}')
            mlist.append((mname, s / total_share, raw))
        f_items, hire_total, hire_basis = _firm_items(spec, ctx, mlist, warn)
        result_members = [{'name': n, 'share': rnd(sh * 100, 2)} for n, sh, _r in mlist]
    items += f_items

    order = {it['id']: i for i, it in enumerate(spec['items'])}
    items.sort(key=lambda it: order[it['id']])
    group_scores = {}
    for it in items:
        group_scores[it['group']] = rnd(group_scores.get(it['group'], 0.0) + it['score'], digits)
    base_total = rnd(sum(it['score'] for it in items), digits)
    bonus = hire_total + young
    total = max(0.0, min(100.0, base_total + bonus))
    if base_total + bonus > 100:
        warn.add('가점 반영 후 100점을 초과해 100점으로 처리했습니다.')
    res = {'name': name, 'items': items, 'group_scores': group_scores, 'base_total': base_total,
           'bonus': {'score': rnd(bonus, digits), 'basis': f'신규 고용: {hire_basis} / 젊은기술인 참여: {ybasis}', 'name': '가점(신규 고용·젊은기술인 참여)'},
           'total': rnd(total, digits), 'disqualified': bool(dq), 'dq_reasons': dq, '_warn': warn.items}
    if result_members:
        res['members'] = result_members
    if dq:
        warn.add('실격 사유로 순위에서 제외했습니다: ' + ', '.join(dq))
        res['_warn'] = warn.items
    return res


def evaluate(spec, project, bidders):
    warn = Warn()
    ctx = _context(spec, project, warn)
    grades = [(b.get('persons') or {}).get('lead', {}).get('tech_grade') for b in bidders]
    if ctx['rel'] == 'relative' and not ctx['skip_tech']:
        keys = [str(i) for i in range(len(bidders))]
        raw = {k: num(((b.get('persons') or {}).get('lead') or {}).get('tech_raw')) for k, b in zip(keys, bidders)}
        g = relative_grades(raw, spec)
        grades = [g[k] for k in keys]
        if len(bidders) < 2:
            warn.add('상대평가는 입찰사가 2개 이상일 때 의미가 있습니다(1개사는 수 등급으로 처리).')
    results = [_evaluate_bidder(spec, ctx, b, i, grades[i]) for i, b in enumerate(bidders)]
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
