"""
사업수행능력평가(PQ) 점수 산정 엔진.

고시 [별표]의 배점·구간표를 JSON 명세(pq_specs/*.json)로 두고, 이 모듈이 그 명세대로 점수를 계산한다.
AI는 점수를 만들지 않는다 - 점수는 항상 결정적인 계산이다(입력값 -> 구간표 -> 배점 x 비율).
입력값 추출을 AI가 돕더라도(pq_extract.py) 사람이 확인한 값만 이 엔진에 들어온다.

계산 결과에는 항목마다 "어떤 입력이 어느 구간에 해당해 몇 %를 받았는지"를 풀어 쓴 근거(basis)가
붙어서, 평가위원이 고시와 대조해 검증할 수 있다.

현재 지원: bangjae(방재관리대책대행자의 사업수행능력 평가기준, 행정안전부 고시).
"""
import json
import math
import os
from decimal import Decimal, ROUND_HALF_UP

_SPEC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pq_specs')
_SPEC_CACHE = {}


# ---------------------------------------------------------------- 명세 로딩
def list_specs():
    """사용 가능한 평가기준 목록(+ 준비 중인 기준)."""
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


# ---------------------------------------------------------------- 공용 계산
def rnd(x, digits=2) -> float:
    """고시 [부표] Ⅰ.2: 소수점 셋째자리에서 반올림(half-up)."""
    q = Decimal(1).scaleb(-digits)
    # 4.875가 4.874999999999999로 계산되는 부동소수 오차로 반올림이 틀어지지 않도록 먼저 9자리로 정리한다.
    return float(Decimal(repr(round(float(x), 9))).quantize(q, rounding=ROUND_HALF_UP))


def num(v):
    """입력값을 숫자로. 비어 있으면(None/'') None, 숫자가 아니면 None."""
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def tier_ge(value, tiers):
    """value >= 기준값 인 첫 구간의 (비율, 기준값). tiers는 기준값 내림차순."""
    for bound, pct in tiers:
        if value >= bound:
            return pct, bound
    return tiers[-1][1], tiers[-1][0]


def tier_lt(value, tiers):
    """value < 상한 인 첫 구간의 (비율, 상한). tiers는 상한 오름차순."""
    for bound, pct in tiers:
        if value < bound:
            return pct, bound
    return tiers[-1][1], tiers[-1][0]


def _fmt(v):
    return ('%g' % round(v, 4)) if isinstance(v, (int, float)) else str(v)


def _band_text_ge(value, bound, unit, tiers):
    """'12.5년 → 11년 이상 13년 미만' 형태의 구간 설명."""
    higher = [b for b, _p in tiers if b > bound]
    upper = min(higher) if higher else None
    if bound <= -1e8:
        return f"{_fmt(value)}{unit} → {_fmt(upper)}{unit} 미만"
    if upper is None:
        return f"{_fmt(value)}{unit} → {_fmt(bound)}{unit} 이상"
    return f"{_fmt(value)}{unit} → {_fmt(bound)}{unit} 이상 {_fmt(upper)}{unit} 미만"


def _band_text_lt(value, bound, unit, tiers):
    lower = [b for b, _p in tiers if b < bound]
    low = max(lower) if lower else None
    if bound >= 1e8:
        return f"{_fmt(value)}{unit} → {_fmt(low)}{unit} 이상"
    if low is None:
        return f"{_fmt(value)}{unit} → {_fmt(bound)}{unit} 미만"
    return f"{_fmt(value)}{unit} → {_fmt(low)}{unit} 이상 {_fmt(bound)}{unit} 미만"


class Warn:
    def __init__(self):
        self.items = []

    def add(self, msg):
        if msg not in self.items:
            self.items.append(msg)


def relative_grades(raw_by_key: dict, spec: dict) -> dict:
    """평가위원 점수(raw)를 [별첨 4] 분포표대로 수·우·미·양·가로 배분한다.
    raw_by_key: {입찰사키: 점수(None이면 미제출)}. 반환: {입찰사키: '수'|'우'|'미'|'양'|'가'|'미제출'}.
    동점자는 같은 등급(높은 등급)으로 묶는다. 분포표는 2~40개사까지 있고, 그 이상은 10:20:40:20:10 비율로 배분한다."""
    labels = ['수', '우', '미', '양', '가']
    submitted = {k: v for k, v in raw_by_key.items() if v is not None}
    result = {k: '미제출' for k in raw_by_key}
    n = len(submitted)
    if n == 0:
        return result
    if n == 1:
        result[next(iter(submitted))] = '수'
        return result
    dist = spec['scoring']['relative_distribution'].get(str(n))
    if dist is None:
        ratios = [0.1, 0.2, 0.4, 0.2, 0.1]
        dist = [int(round(n * r)) for r in ratios]
        dist[2] += n - sum(dist)           # 합이 n이 되도록 '미'로 보정
    order = sorted(submitted.items(), key=lambda kv: -kv[1])
    idx = 0
    pos = 0
    grade_for_rank = []
    for gi, cnt in enumerate(dist):
        grade_for_rank += [labels[gi]] * cnt
    # 동점은 같은 등급(앞 순위의 등급)
    prev_score, prev_grade = None, None
    for key, score in order:
        if prev_score is not None and score == prev_score:
            result[key] = prev_grade
        else:
            g = grade_for_rank[pos] if pos < len(grade_for_rank) else labels[-1]
            result[key] = g
            prev_score, prev_grade = score, g
        pos += 1
    return result


# ---------------------------------------------------------------- 방재관리대책대행자
def _contribution_weights(project, warn):
    """프로젝트의 분야 구성 -> [(분야명, 업무기여도 비율(0~1), 종류(필수/추가))]."""
    rows = []
    total = 0.0
    for r in project.get('fields', []) or []:
        name = (r.get('name') or '').strip()
        pct = num(r.get('pct'))
        if not name or pct is None:
            continue
        rows.append((name, pct, r.get('kind') or '필수'))
        total += pct
    if not rows:
        warn.add('분야별책임기술인 구성(분야명·업무기여도)이 없어 분야별 항목은 0점으로 계산됩니다.')
        return []
    if abs(total - 100) > 0.01:
        warn.add(f'분야별 업무기여도 합계가 {_fmt(total)}%입니다(100%여야 합니다). 입력한 값을 {_fmt(total)}%로 나누어 정규화해 계산했습니다.')
    return [(n, p / total, k) for n, p, k in rows]


def _person_grade_pct(spec, role, grade):
    table = spec['scoring']['grade_lead' if role in ('lead', 'fl') else 'grade_member']['table']
    return table.get(grade)


def _eff_count(d, s, factor):
    return (d or 0) + (s or 0) * factor


def _score_item(item_max, pct):
    return item_max * pct / 100.0


def evaluate_bangjae(spec: dict, project: dict, bidders: list) -> dict:
    sc = spec['scoring']
    digits = spec.get('rounding_digits', 2)
    warn = Warn()
    adjust = project.get('adjust') or {}
    base_max = {it['id']: it['max'] for it in spec['items']}
    maxes = dict(base_max)
    adj_pct = spec.get('adjust_pct', 20)
    for iid, v in adjust.items():
        v = num(v)
        if iid in base_max and v is not None:
            lo, hi = base_max[iid] * (1 - adj_pct / 100.0), base_max[iid] * (1 + adj_pct / 100.0)
            if v < lo - 1e-9 or v > hi + 1e-9:
                warn.add(f"'{_item_name(spec, iid)}' 배점 {_fmt(v)}점이 고시 허용 범위({_fmt(lo)}~{_fmt(hi)}점, ±{adj_pct}%)를 벗어났습니다.")
            maxes[iid] = v
    total_max = sum(maxes.values())
    if abs(total_max - 100) > 0.01:
        warn.add(f'조정한 배점 합계가 {_fmt(total_max)}점입니다(고시의 합계는 100점).')

    fields = _contribution_weights(project, warn)
    use_transfer = bool(project.get('apply_transfer_penalty'))

    # 상대평가 등급(전체 입찰사가 필요)
    rel_mode = project.get('rel_mode_key') or ('relative' if str(project.get('rel_mode', '')).startswith('평가위원') else 'direct')
    keys = [str(i) for i in range(len(bidders))]
    tech_grades = mgmt_grades = None
    if rel_mode == 'relative':
        tech_grades = relative_grades({k: num((b.get('persons', {}).get('lead') or {}).get('tech_raw')) for k, b in zip(keys, bidders)}, spec)
        mgmt_grades = relative_grades({k: num((b.get('persons', {}).get('lead') or {}).get('mgmt_raw')) for k, b in zip(keys, bidders)}, spec)
        if len(bidders) < 2:
            warn.add('상대평가는 입찰사가 2개 이상일 때 의미가 있습니다(1개사는 수 등급으로 처리).')

    results = []
    for bi, b in enumerate(bidders):
        fn = _evaluate_jv_bangjae if b.get('members') else _evaluate_one_bangjae
        results.append(fn(spec, sc, maxes, fields, use_transfer, b, bi,
                          (tech_grades or {}).get(str(bi)), (mgmt_grades or {}).get(str(bi)),
                          rel_mode, digits))

    # 순위
    order = sorted(range(len(results)), key=lambda i: -results[i]['total'])
    rank = {}
    last_total, last_rank = None, 0
    for pos, i in enumerate(order, start=1):
        t = results[i]['total']
        if last_total is not None and abs(t - last_total) < 1e-9:
            rank[i] = last_rank
        else:
            rank[i] = pos
            last_total, last_rank = t, pos
    for i, r in enumerate(results):
        r['rank'] = rank[i]
        for w in r.pop('_warn'):
            warn.add(f"[{r['name']}] {w}")

    return {
        'spec_id': spec['id'],
        'maxes': maxes,
        'total_max': rnd(total_max, digits),
        'results': results,
        'warnings': warn.items,
    }


def _item_name(spec, iid):
    for it in spec['items']:
        if it['id'] == iid:
            return it['name']
    return iid


PERSON_GROUPS = ('A', 'E')       # 참여기술인·업무중복도: 팀(공동수급체 전체) 단위
FIRM_GROUPS = ('B', 'C', 'D')    # 대행자 실적·신용도·기술개발: 구성원별 평가 후 지분율 합산


def _evaluate_one_bangjae(spec, sc, maxes, fields, use_transfer, b, idx, tech_grade_auto, mgmt_grade_auto, rel_mode, digits,
                          part='all'):
    """part: 'all'(단독) / 'persons'(참여기술인·업무중복도만) / 'firm'(대행자 항목·가점만, 공동수급체 구성원 1개사용)."""
    real_w = Warn()
    w = Warn() if part == 'firm' else real_w
    name = (b.get('name') or '').strip() or f'입찰사 {idx + 1}'
    firm = b.get('firm') or {}
    persons = b.get('persons') or {}
    lead = persons.get('lead') or {}
    fl_map = persons.get('field_lead') or {}
    fm_map = persons.get('field_member') or {}
    items = []

    def add(iid, pct, basis, note=None, score=None):
        mx = maxes[iid]
        s = _score_item(mx, pct) if score is None else score
        items.append({
            'id': iid, 'name': _item_name(spec, iid), 'group': next(i['group'] for i in spec['items'] if i['id'] == iid),
            'max': rnd(mx, digits), 'pct': None if pct is None else round(pct, 4), 'score': rnd(s, digits),
            'basis': basis, 'note': note or '',
        })

    def zero(iid, basis):
        add(iid, 0, basis, score=0.0)

    def person_factor(p, label):
        if not use_transfer:
            return 1.0
        f = sc['transfer_factor'].get(p.get('transfer') or '해당 없음', 1.0)
        return f

    def person_item(p, role, iid, kind, label, tiers_key=None):
        """등급/경력/실적 항목 1개 계산 -> (점수에 곱할 비율(0~1) 또는 None, 근거문)."""
        if p is None or not p:
            return None, f'{label}: 입력 없음'
        if not p.get('eligible', True):
            return 0.0, f'{label}: 방재전문인력 인증서·보수교육 요건 미충족 → 0점(제3조제2항)'
        if kind == 'grade':
            g = p.get('grade')
            if g in (None, ''):
                return None, f'{label}: 등급 미입력'
            pct = _person_grade_pct(spec, role, g)
            if pct is None:
                return None, f'{label}: 알 수 없는 등급 {g}'
            text = f'{label} 등급 {g} → {pct}%'
        elif kind == 'career':
            v = num(p.get('career'))
            if v is None:
                return None, f'{label}: 경력 미입력'
            cfg = sc['tiers_ge'][tiers_key]
            pct, bound = tier_ge(v, cfg['tiers'])
            text = f"{label} 경력 {_band_text_ge(v, bound, cfg['unit'], cfg['tiers'])} → {pct}%"
        else:  # perf
            d, s_ = num(p.get('cnt_d')), num(p.get('cnt_s'))
            if d is None and s_ is None:
                return None, f'{label}: 실적 미입력'
            v = _eff_count(d, s_, sc['similar_factor'])
            cfg = sc['tiers_ge'][tiers_key]
            pct, bound = tier_ge(v, cfg['tiers'])
            text = (f"{label} 실적 {_fmt(d or 0)}건(대행) + {_fmt(s_ or 0)}건×80%(유사) = {_fmt(v)}건 "
                    f"{_band_text_ge(v, bound, cfg['unit'], cfg['tiers']).split('→')[1].strip()} → {pct}%")
        ratio = pct / 100.0
        f = person_factor(p, label)
        if f != 1.0:
            ratio *= f
            text += f' × 이적 감소계수 {f}'
        return ratio, text

    # ---- 사업책임기술인 -----------------------------------------------------------
    lead_label = '사업책임기술인'
    for iid, kind, tkey in (('lead.grade', 'grade', None), ('lead.career', 'career', 'lead.career')):
        ratio, text = person_item(lead, 'lead', iid, kind, lead_label, tkey)
        if ratio is None:
            w.add(text + ' → 0점 처리')
            zero(iid, text)
        else:
            add(iid, ratio * 100, text)

    # 실적 건수 / 금액 (사업책임기술인)
    if lead and lead.get('eligible', True):
        d, s_ = num(lead.get('cnt_d')), num(lead.get('cnt_s'))
        if d is None and s_ is None:
            w.add('사업책임기술인 실적건수 미입력 → 0점 처리')
            zero('lead.perf_cnt', '사업책임기술인 실적건수 미입력')
        else:
            v = _eff_count(d, s_, sc['similar_factor'])
            cfg = sc['tiers_ge']['lead.perf_cnt']
            pct, bound = tier_ge(v, cfg['tiers'])
            ratio = pct * person_factor(lead, '') / 100.0
            text = (f"사업책임기술인 실적건수 {_fmt(d or 0)}건(대행)+{_fmt(s_ or 0)}건×80%(유사)={_fmt(v)}건 "
                    f"{_band_text_ge(v, bound, cfg['unit'], cfg['tiers']).split('→')[1].strip()} → {pct}%")
            add('lead.perf_cnt', ratio * 100, text)
        da, sa = num(lead.get('amt_d')), num(lead.get('amt_s'))
        if da is None and sa is None:
            w.add('사업책임기술인 실적금액 미입력 → 0점 처리')
            zero('lead.perf_amt', '사업책임기술인 실적금액 미입력')
        else:
            v = _eff_count(da, sa, sc['similar_factor'])
            cfg = sc['tiers_ge']['lead.perf_amt']
            pct, bound = tier_ge(v, cfg['tiers'])
            ratio = pct * person_factor(lead, '') / 100.0
            text = (f"사업책임기술인 실적금액 {_fmt(da or 0)}억(대행)+{_fmt(sa or 0)}억×80%(유사)={_fmt(v)}억 "
                    f"{_band_text_ge(v, bound, cfg['unit'], cfg['tiers']).split('→')[1].strip()} → {pct}%")
            add('lead.perf_amt', ratio * 100, text)
    else:
        why = '요건 미충족 → 0점' if lead else '입력 없음 → 0점'
        zero('lead.perf_cnt', f'사업책임기술인 실적건수: {why}')
        zero('lead.perf_amt', f'사업책임기술인 실적금액: {why}')

    # 기술능력 / 업무관리능력 (수우미양가)
    for iid, gkey, auto, label in (('lead.tech', 'tech_grade', tech_grade_auto, '기술능력'),
                                   ('lead.mgmt', 'mgmt_grade', mgmt_grade_auto, '업무관리능력')):
        g = auto if rel_mode == 'relative' else lead.get(gkey)
        if g in (None, '', '미제출'):
            w.add(f'{label} 평가자료 미제출 또는 미입력 → 0점 처리')
            zero(iid, f'{label}: 평가자료 미제출 → 0점')
        else:
            pct = sc['relative_grade_pct'][g]
            how = '상대평가 자동 배분' if rel_mode == 'relative' else '등급 직접 입력'
            add(iid, pct, f'{label} {g} 등급({how}) → {pct}%')

    # ---- 분야별책임기술인 / 분야별참여기술인 (업무기여도 가중) ----------------------
    def weighted_group(role_key, p_map, iid, kind, tkey, label, role):
        if not fields:
            zero(iid, f'{label}: 분야 구성 없음')
            return
        total_ratio = 0.0
        parts = []
        missing = False
        for fname, wt, _kind in fields:
            p = p_map.get(fname) or {}
            ratio, text = person_item(p, role, iid, kind, f'{fname}', tkey)
            if ratio is None:
                missing = True
                w.add(f'{label}({fname}): {text.split(": ", 1)[-1]} → 해당 분야 0점 처리')
                ratio = 0.0
                text = f'{fname} 입력 없음 → 0'
            total_ratio += wt * ratio
            parts.append(f'[{text} × 업무기여도 {rnd(wt * 100, 1)}%]')
        add(iid, total_ratio * 100, f'{label}: ' + ' + '.join(parts))

    weighted_group('fl', fl_map, 'fl.grade', 'grade', None, '분야별책임기술인 등급', 'fl')
    weighted_group('fl', fl_map, 'fl.career', 'career', 'fl.career', '분야별책임기술인 경력', 'fl')
    weighted_group('fl', fl_map, 'fl.perf', 'perf', 'fl.perf', '분야별책임기술인 실적', 'fl')
    weighted_group('fm', fm_map, 'fm.grade', 'grade', None, '분야별참여기술인 등급', 'fm')
    weighted_group('fm', fm_map, 'fm.career', 'career', 'fm.career', '분야별참여기술인 경력', 'fm')
    weighted_group('fm', fm_map, 'fm.perf', 'perf', 'fm.perf', '분야별참여기술인 실적', 'fm')

    # ---- 전차용역 수행실적 ---------------------------------------------------------
    ps = sc['prev_service']
    lead_sum, fl_sum = 0.0, 0.0
    parts = []
    wmap = {n: wt for n, wt, _k in fields}
    for r in firm.get('prev_items') or []:
        el = num(r.get('elapsed'))
        if el is None:
            continue
        base = 0.0
        for limit, pts in ps['elapsed_points']:
            if el <= limit:
                base = pts
                break
        tech = (num(r.get('tech_rate')) if num(r.get('tech_rate')) is not None else 100.0) / 100.0
        form = (num(r.get('form_pct')) if num(r.get('form_pct')) is not None else 100.0) / 100.0
        vol = (num(r.get('volume_pct')) if num(r.get('volume_pct')) is not None else 100.0) / 100.0
        cur = r.get('cur_role') or 'lead'
        is_lead = cur in ('lead', '사업책임', '')
        field_rate = 1.0 if is_lead else wmap.get(cur, 0.0)
        if not is_lead and cur not in wmap:
            w.add(f"전차용역 항목의 금회 역할 '{cur}'이(가) 분야 구성에 없어 0으로 계산했습니다.")
        pts = base * field_rate * tech * form * vol
        parts.append(f"[{'사업책임' if is_lead else cur}: 완료후 {_fmt(el)}년 {base}점 × 분야별 {rnd(field_rate * 100, 1)}% "
                     f"× 기술인 {rnd(tech * 100, 1)}% × 발주형태 {rnd(form * 100, 1)}% × 사업량 {rnd(vol * 100, 1)}% = {rnd(pts, 4)}]")
        if cur in ('lead', '사업책임', ''):
            lead_sum += pts
        else:
            fl_sum += pts
    cap = ps['group_cap']
    lead_pts, fl_pts = min(lead_sum, cap), min(fl_sum, cap)
    total_prev = lead_pts + fl_pts
    base_prev_max = 1.0
    scaled = total_prev * (maxes['prev.service'] / base_prev_max)
    add('prev.service', None, ('전차용역 이력 없음 → 0점' if not parts else
                               ' + '.join(parts) + f' → 사업책임 {rnd(lead_pts, 3)}(상한 {cap}) + 분야별책임 {rnd(fl_pts, 3)}(상한 {cap})'),
        score=scaled, note='사업책임·분야별책임 각 0.5점 상한을 적용한 해석입니다. 별첨 6의 산식(배점×분야별×기술인×발주형태×사업량 적용률)을 그대로 사용했습니다.')

    # ---- 나. 대행자 수행실적(최근 5년) ---------------------------------------------
    w = Warn() if part == 'persons' else real_w
    d, s_ = num(firm.get('perf5_d_cnt')), num(firm.get('perf5_s_cnt'))
    if d is None and s_ is None:
        w.add('대행자 수행실적(건수) 미입력 → 0점 처리')
        zero('firm.perf_cnt', '대행자 수행실적 건수 미입력')
    else:
        v = _eff_count(d, s_, sc['similar_factor'])
        cfg = sc['tiers_ge']['firm.perf_cnt']
        pct, bound = tier_ge(v, cfg['tiers'])
        add('firm.perf_cnt', pct, f"대행자 5년 실적 {_fmt(d or 0)}건(대행)+{_fmt(s_ or 0)}건×80%(유사)={_fmt(v)}건 "
                                  f"{_band_text_ge(v, bound, cfg['unit'], cfg['tiers']).split('→')[1].strip()} → {pct}%")
    da, sa = num(firm.get('perf5_d_amt')), num(firm.get('perf5_s_amt'))
    if da is None and sa is None:
        w.add('대행자 수행실적(금액) 미입력 → 0점 처리')
        zero('firm.perf_amt', '대행자 수행실적 금액 미입력')
    else:
        v = _eff_count(da, sa, sc['similar_factor'])
        cfg = sc['tiers_ge']['firm.perf_amt']
        pct, bound = tier_ge(v, cfg['tiers'])
        add('firm.perf_amt', pct, f"대행자 5년 실적금액 {_fmt(da or 0)}억(대행)+{_fmt(sa or 0)}억×80%(유사)={_fmt(v)}억 "
                                  f"{_band_text_ge(v, bound, cfg['unit'], cfg['tiers']).split('→')[1].strip()} → {pct}%")

    # ---- 다. 신용도 -----------------------------------------------------------------
    months = (num(firm.get('suspend_months')) or 0) + (num(firm.get('tech_suspend_months')) or 0)
    # 1월 미만은 1월로 계산: 각각 올림
    m_firm = math.ceil(num(firm.get('suspend_months')) or 0)
    m_tech = math.ceil(num(firm.get('tech_suspend_months')) or 0)
    bad = num(firm.get('bad_point_deduct')) or 0
    pen = sc['penalty']['per_month'] * (m_firm + m_tech) + bad
    pen_score = max(0.0, maxes['credit.penalty'] - pen)
    add('credit.penalty', None,
        f"{_fmt(maxes['credit.penalty'])}점 - 영업정지 {m_firm}개월×0.2 - 기술인 자격·업무정지 {m_tech}개월×0.2 - 부실벌점 감점 {_fmt(bad)}점 = {_fmt(rnd(pen_score, 3))}점(0점 미만은 0점)",
        score=pen_score)

    ctype, crate = firm.get('credit_type'), firm.get('credit_rating')
    cr = sc['credit']
    if ctype in (None, '', '미제출') or crate in (None, ''):
        cscore = cr['points']['none'] * maxes['credit.finance'] / 3.0
        add('credit.finance', None, '신용평가등급 미제출 → 0점', score=cscore)
    else:
        bond = crate if ctype != '기업어음' else cr['paper_to_bond'].get(crate)
        if bond is None or bond not in cr['bond_order']:
            w.add(f'신용평가등급 {crate}({ctype})을 인식하지 못해 0점 처리')
            add('credit.finance', None, f'신용평가등급 {crate}({ctype}) 인식 불가 → 0점', score=0.0)
        else:
            rank_i = cr['bond_order'].index(bond)
            if rank_i <= cr['bond_order'].index('BBB-'):
                pts, band = cr['points']['ge_BBB-'], 'BBB- 이상(회사채 기준)'
            elif bond == 'CCC+ 이하':
                pts, band = cr['points']['le_CCC+'], 'CCC+ 이하(회사채 기준)'
            else:
                pts, band = cr['points']['lt_BBB-_ge_B-'], 'BBB- 미만 B- 이상(회사채 기준)'
            add('credit.finance', None, f"{ctype} {crate}" + (f' (회사채 {bond}에 준함)' if ctype == '기업어음' else '') +
                f" → {band} → {pts}점(원 배점 3.0 기준)",
                score=pts * maxes['credit.finance'] / 3.0)

    # ---- 라. 기술개발 및 투자실적 ----------------------------------------------------
    dev_rows = firm.get('dev_items') or []
    best = {}
    detail = []
    for i, r in enumerate(dev_rows):
        t = r.get('type')
        if t not in sc['dev_points']:
            continue
        age = num(r.get('age_years')) or 0
        applicants = max(1.0, num(r.get('applicants')) or 1.0)
        wt = 100.0
        if t in sc['dev_age_weight']:
            wt = 0.0
            for limit, pct in sc['dev_age_weight'][t]:
                if age < limit:
                    wt = pct
                    break
        pts = sc['dev_points'][t] * wt / 100.0 / applicants
        grp = (r.get('dup_group') or '').strip() or f'__{i}'
        if grp not in best or pts > best[grp][0]:
            best[grp] = (pts, f'{t} {sc["dev_points"][t]}점×{_fmt(wt)}%' + (f'÷{_fmt(applicants)}명' if applicants > 1 else '') + f'={rnd(pts, 3)}')
    dev_total = sum(p for p, _t in best.values())
    dev_score = min(dev_total, maxes['tech.dev'])
    add('tech.dev', None, ('개발실적 없음 → 0점' if not best else ' + '.join(t for _p, t in best.values()) +
                           f' = {rnd(dev_total, 3)}점 (배점 {_fmt(maxes["tech.dev"])}점 상한)'), score=dev_score)

    inv, sales = num(firm.get('invest_amount')), num(firm.get('sales_amount'))
    if inv is None or sales in (None, 0):
        w.add('투자실적(투자액·총매출액) 미입력 → 0점 처리')
        zero('tech.invest', '투자실적 미입력')
    else:
        ratio_pct = round(inv / sales * 100.0, 9)  # 부동소수 오차로 경계값이 아래 구간으로 밀리지 않게 함
        cfg = sc['tiers_ge']['tech.invest']
        pct, bound = tier_ge(ratio_pct, cfg['tiers'])
        add('tech.invest', pct, f"투자액 {_fmt(inv)}억 / 건설부문 총매출 {_fmt(sales)}억 = {rnd(ratio_pct, 3)}% "
                                f"{_band_text_ge(ratio_pct, bound, cfg['unit'], cfg['tiers']).split('→')[1].strip()} → {pct}%")

    use_rows = [r for r in (firm.get('use_items') or []) if r.get('type') in sc['dev_points']]
    use_cnt = len(use_rows)
    use_amt = num(firm.get('use_amount')) or 0
    if use_cnt == 0:
        add('tech.use', None, '활용실적 없음 → 0점', score=0.0)
    else:
        pts_sum = sum(sc['dev_points'][r['type']] for r in use_rows)
        wc = 0.0
        for limit, pct in sc['use_weight']['count']:
            if use_cnt >= limit:
                wc = pct
                break
        wa = 0.0
        for limit, pct in sc['use_weight']['amount']:
            if use_amt >= limit:
                wa = pct
                break
        wmax = max(wc, wa)
        s = min(pts_sum * wmax / 100.0, maxes['tech.use'])
        add('tech.use', None, f"활용 {use_cnt}건 점수합 {_fmt(pts_sum)}점 × 가중치 max(건수 {_fmt(wc)}%, 금액 {_fmt(use_amt)}억 {_fmt(wa)}%) = {_fmt(wmax)}% "
                              f"= {rnd(pts_sum * wmax / 100.0, 3)}점 (배점 {_fmt(maxes['tech.use'])}점 상한)", score=s)

    # ---- 마. 업무중복도 ---------------------------------------------------------------
    w = Warn() if part == 'firm' else real_w

    def overlap_pct_for(p, tiers_cfg):
        if p.get('overlap_error'):
            return 0.0, '중복도 평가자료 오류·누락 확인 → 0점(제6조제5항)', True
        v = num(p.get('overlap'))
        if v is None:
            return None, '업무중복도 미입력', False
        pct, bound = tier_lt(v, tiers_cfg['tiers'])
        return pct / 100.0, f"{_band_text_lt(v, bound, tiers_cfg['unit'], tiers_cfg['tiers'])} → {pct}%", False

    if not lead:
        zero('ovl.lead', '사업책임기술인 입력 없음')
    else:
        ratio, text, _z = overlap_pct_for(lead, sc['tiers_lt']['ovl.lead'])
        if ratio is None:
            w.add('사업책임기술인 업무중복도 미입력 → 0점 처리')
            zero('ovl.lead', '사업책임기술인 ' + text)
        else:
            add('ovl.lead', ratio * 100, '사업책임기술인 ' + text)
    if not fields:
        zero('ovl.fl', '분야 구성 없음')
    else:
        tot, parts = 0.0, []
        for fname, wt, kind in fields:
            p = fl_map.get(fname) or {}
            cfg = sc['tiers_lt']['ovl.fl.extra' if kind == '추가' else 'ovl.fl.required']
            ratio, text, _z = overlap_pct_for(p, cfg) if p else (None, '입력 없음', False)
            if ratio is None:
                w.add(f'분야별책임기술인({fname}) 업무중복도 미입력 → 해당 분야 0점 처리')
                ratio, text = 0.0, f'{fname} 미입력 → 0'
            tot += wt * ratio
            parts.append(f"[{fname}({kind}) {text} × 업무기여도 {rnd(wt * 100, 1)}%]")
        add('ovl.fl', tot * 100, '분야별책임기술인: ' + ' + '.join(parts))

    # ---- 가점 -------------------------------------------------------------------------
    hire = num(firm.get('new_hire_rate'))
    bonus = 0.0
    bonus_basis = '신규 고용율 미입력 → 가점 없음'
    if part == 'persons':
        bonus_basis = ''
    elif hire is not None:
        for bound, pts in spec['bonus']['tiers']:
            if hire >= bound:
                bonus = pts
                break
        bonus_basis = f'신규 고용율 {_fmt(hire)}% → 가점 {bonus}점'

    digits = spec.get('rounding_digits', 2)
    if part == 'persons':
        items = [it for it in items if it['group'] in PERSON_GROUPS]
    elif part == 'firm':
        items = [it for it in items if it['group'] in FIRM_GROUPS]
    group_scores = {}
    for it in items:
        group_scores[it['group']] = rnd(group_scores.get(it['group'], 0.0) + it['score'], digits)
    base_total = rnd(sum(it['score'] for it in items), digits)
    return {
        'name': name,
        'items': items,
        'group_scores': group_scores,
        'base_total': base_total,
        'bonus': {'score': rnd(bonus, digits), 'basis': bonus_basis, 'name': spec['bonus']['name']},
        'total': rnd(base_total + bonus, digits),
        '_warn': real_w.items,
    }


def _evaluate_jv_bangjae(spec, sc, maxes, fields, use_transfer, b, idx, tech_auto, mgmt_auto, rel_mode, digits):
    """공동이행방식 공동수급체: 참여기술인·업무중복도는 팀 단위 1회, 대행자 항목(나·다·라)과 가점은
    구성원별로 평가한 점수에 참여지분율을 곱해 합산한다([부표] Ⅱ.3, 별표 각 항목의 공동이행방식 규정)."""
    name = (b.get('name') or '').strip() or f'입찰사 {idx + 1}'
    members = [m for m in (b.get('members') or []) if isinstance(m, dict)]
    warns = Warn()
    shares = [num(m.get('share')) for m in members]
    if any(s is None or s <= 0 for s in shares):
        warns.add('공동수급체 구성원의 참여지분율이 비었거나 0 이하입니다. 지분율을 입력해 주세요(없는 구성원은 제외하고 계산했습니다).')
    keep = [(m, s) for m, s in zip(members, shares) if s is not None and s > 0]
    if not keep:
        raise ValueError(f"'{name}': 공동수급체 구성원의 참여지분율을 입력해 주세요.")
    total_share = sum(s for _m, s in keep)
    if abs(total_share - 100) > 0.01:
        warns.add(f'공동수급체 지분율 합계가 {_fmt(total_share)}%입니다(100%여야 합니다). 비율대로 환산해 계산했습니다.')

    team = _evaluate_one_bangjae(spec, sc, maxes, fields, use_transfer,
                                 {'name': name, 'firm': {'prev_items': (b.get('firm') or {}).get('prev_items') or []},
                                  'persons': b.get('persons') or {}},
                                 idx, tech_auto, mgmt_auto, rel_mode, digits, part='persons')
    for t in team.pop('_warn'):
        warns.add(t)

    member_res = []
    for mi, (m, s) in enumerate(keep):
        mname = (m.get('name') or '').strip() or f'구성원 {mi + 1}'
        r = _evaluate_one_bangjae(spec, sc, maxes, fields, use_transfer,
                                  {'name': mname, 'firm': m.get('firm') or {}, 'persons': {}},
                                  idx, None, None, rel_mode, digits, part='firm')
        for t in r.pop('_warn'):
            warns.add(f'[{"" if mname.startswith("구성원") else "구성원 "}{mname}] {t}')
        member_res.append((mname, s / total_share, r))

    firm_items = []
    firm_ids = [it['id'] for it in spec['items'] if it['group'] in FIRM_GROUPS]
    for iid in firm_ids:
        score = 0.0
        parts = []
        first = None
        for mname, sh, r in member_res:
            it = next(x for x in r['items'] if x['id'] == iid)
            first = first or it
            score += it['score'] * sh
            parts.append(f"[{mname} 지분 {rnd(sh * 100, 1)}%: {it['basis']} = {_fmt(it['score'])}점 × {rnd(sh, 4)}]")
        firm_items.append({
            'id': iid, 'name': first['name'], 'group': first['group'], 'max': first['max'],
            'pct': round(score / first['max'] * 100, 4) if first['max'] else 0.0,
            'score': rnd(score, digits), 'basis': ' + '.join(parts),
            'note': '공동이행방식: 구성원별 평가점수 × 참여지분율 합산(구성원별 점수는 소수 둘째자리까지 산정 후 곱함).',
        })
    bonus_score = sum(r['bonus']['score'] * sh for _n, sh, r in member_res)
    bonus_basis = ' + '.join(f"[{n} 지분 {rnd(sh * 100, 1)}%: {r['bonus']['basis']} × {rnd(sh, 4)}]" for n, sh, r in member_res)

    order = {it['id']: i for i, it in enumerate(spec['items'])}
    items = sorted(team['items'] + firm_items, key=lambda it: order[it['id']])
    group_scores = {}
    for it in items:
        group_scores[it['group']] = rnd(group_scores.get(it['group'], 0.0) + it['score'], digits)
    base_total = rnd(sum(it['score'] for it in items), digits)
    return {
        'name': name,
        'items': items,
        'group_scores': group_scores,
        'base_total': base_total,
        'bonus': {'score': rnd(bonus_score, digits), 'basis': bonus_basis, 'name': spec['bonus']['name']},
        'total': rnd(base_total + bonus_score, digits),
        'members': [{'name': n, 'share': rnd(sh * 100, 2), 'firm_total': rnd(r['base_total'] + r['bonus']['score'], digits)}
                    for n, sh, r in member_res],
        '_warn': warns.items,
    }


def _evaluate_cm(spec, project, bidders):
    import pq_cm  # 순환 import를 피하려고 호출 시점에 불러온다
    return pq_cm.evaluate(spec, project, bidders)


def _evaluate_env(spec, project, bidders):
    import pq_env
    return pq_env.evaluate(spec, project, bidders)


ENGINES = {'bangjae': evaluate_bangjae, 'cm': _evaluate_cm, 'env': _evaluate_env}


def evaluate(spec_id: str, project: dict, bidders: list) -> dict:
    spec = load_spec(spec_id)
    engine = ENGINES.get(spec.get('engine'))
    if engine is None:
        raise ValueError(f'지원하지 않는 평가기준: {spec_id}')
    out = engine(spec, project or {}, bidders or [])
    out['groups'] = spec['groups']
    return out
