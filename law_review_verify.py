"""
개발사업 스마트 법규 검토(law_review) 결과의 후처리: AI가 만든 인허가·의무 목록을 결정적인 규칙과 법령 원문으로 다시 점검한다.

[왜 필요한가]
AI 한 번의 답을 그대로 쓰면 아래 문제가 실제로 확인됐다(남해읍 도시계획도로 샘플, 운영 서버).
- 토목공사인데 건축법 착공신고가 들어갔다(프롬프트로 금지해도 지켜지지 않는다).
- 조문 번호는 실제로 있어도 내용이 맞지 않는 인용: 예비준공검사 -> 지침 제99조(기성고 지급자재), 도로대장 등재 -> 도로법 제27조(행위제한).
- 룰 엔진(law_knowledge_base.json)이 정한 필수 항목을 AI가 빠뜨려도 알 수 없다.

[하는 일 - 모두 AI의 판단이 아니라 규칙·원문 대조이고, 항목을 조용히 바꾸지 않는다]
1. 공종 불일치 제외: 토목·조경 공사에 건축 법령 항목이 있으면 목록에서 빼되, 빠진 항목과 이유를 '제외된 항목'으로 남긴다.
2. 룰 엔진 필수 항목 보완: 조건이 맞은 지식 기반 규칙이 결과에 없으면 '룰 엔진 보완'으로 표시해 덧붙인다.
3. 조문 대조: 인용한 조문이 법제처 원문에 있는지, 삭제되지 않았는지, 실제 제목과 항목 내용이 같은 분야인지(기존 citation_check의 판정기)를 항목마다 표시한다.
   내용이 다르다고 자동으로 지우지는 않고 "내용 불일치 의심"으로 눈에 띄게 표시해 사람이 판단하게 한다(맞는 인용을 지우는 부작용이 더 크다).
"""
import concurrent.futures
import re

CIVIL_TYPES = ('토목공사', '조경공사')
# 토목·조경 공사에는 해당하지 않는 건축 분야 법령(공백·가운뎃점 제거 후 앞부분으로 비교)
ARCH_LAW_PREFIXES = ('건축법', '건축서비스산업진흥법', '건축물관리법', '녹색건축물조성지원법', '건축물의에너지절약설계기준')
PHASE_OF_RULE = {'design': 'design', 'construction': 'construction', 'design, construction': 'design', 'both': 'design'}
JUDGE_CHUNK = 8
_ADM_SUFFIXES = ('지침', '고시', '예규', '훈령', '요령', '기준', '규정')
_ART = re.compile(r'제\s*(\d+)\s*조(?:\s*의\s*(\d+))?')

STATUS_LABEL = {
    'ok': '원문 확인', 'mismatch': '내용 불일치 의심', 'missing': '조문 없음', 'deleted': '삭제된 조문',
    'unchecked': '원문 대조 불가', 'rule': '룰 엔진 보완',
}


def _nospace(s):
    return re.sub(r'[\s·ㆍ‧,()\[\]]', '', s or '')


def _items(result):
    """결과 안의 모든 항목(permits + phases)을 (목록, 항목) 쌍으로 돌려준다."""
    out = []
    for it in result.get('permits') or []:
        out.append(('permits', it))
    for ph, lst in (result.get('phases') or {}).items():
        for it in lst or []:
            out.append((ph, it))
    return out


def _title_of(item):
    return item.get('name') or item.get('task') or ''


# ---------------------------------------------------------------- 1. 공종 불일치 제외
def exclude_mismatched_trade(result, project_type):
    """토목·조경 공사 결과에서 건축 법령 항목을 뺀다. 빠진 항목 [{name, law, article, reason}]을 돌려준다."""
    if project_type not in CIVIL_TYPES:
        return []
    excluded = []

    def is_arch(item):
        return _nospace(item.get('law_name')).startswith(tuple(_nospace(p) for p in ARCH_LAW_PREFIXES))

    if result.get('permits'):
        keep = []
        for it in result['permits']:
            if is_arch(it):
                excluded.append(it)
            else:
                keep.append(it)
        result['permits'] = keep
    for ph, lst in list((result.get('phases') or {}).items()):
        keep = []
        for it in lst or []:
            if is_arch(it):
                excluded.append(it)
            else:
                keep.append(it)
        result['phases'][ph] = keep
    return [{'name': _title_of(it), 'law': it.get('law_name'), 'article': it.get('article'),
             'reason': f"{project_type}에는 건축 분야 법령({it.get('law_name')})이 해당하지 않아 제외했습니다."} for it in excluded]


# ---------------------------------------------------------------- 2. 룰 엔진 필수 항목 보완
_ACTION_WORDS = ('수립', '제출', '작성', '실시', '신청', '이행', '의뢰', '시행', '대상여부', '여부', '확인', '및')


def _core(name):
    """항목 이름에서 동작어(수립·제출·작성 …)를 떼어 핵심 이름만 남긴다. "안전관리계획서 수립"과 "안전관리계획서 제출"은 같은 항목으로 본다."""
    n = _nospace(name)
    for w in _ACTION_WORDS:
        n = n.replace(w, '')
    return n


def _present(rule, existing):
    """규칙(KB)의 항목이 이미 결과에 있는가. existing = 결과 항목 이름들의 _core 목록."""
    name = _core(rule.get('name'))
    if len(name) < 4:
        return False
    return any(name in n or (len(n) >= 4 and n in name) for n in existing)


def split_rules_by_trade(rules, project_type):
    """토목·조경 공사에 해당하지 않는 건축 분야 규칙을 나눈다. (쓸 규칙, 제외된 규칙 정보) - 건축 법령을 근거로 하거나 이름에 '건축'이 들어간 규칙."""
    if project_type not in CIVIL_TYPES:
        return list(rules or []), []
    prefixes = tuple(_nospace(x) for x in ARCH_LAW_PREFIXES)
    keep, skipped = [], []
    for r in rules or []:
        first_law = re.split(r'\s*제\s*\d', r.get('law_link') or '', maxsplit=1)[0]
        if '건축' in (r.get('name') or '') or _nospace(first_law).startswith(prefixes):
            skipped.append({'name': r.get('name'), 'law': r.get('law_link') or '', 'article': '',
                            'reason': f"룰 엔진 항목이지만 {project_type}에는 해당하지 않는 건축 분야 항목이라 덧붙이지 않았습니다."})
        else:
            keep.append(r)
    return keep, skipped


def merge_rule_items(result, rules):
    """조건이 맞은 지식 기반 규칙 가운데 결과에 없는 것을 덧붙인다. 덧붙인 항목 [{name, phase}]을 돌려준다."""
    existing = [_core(_title_of(it)) for _ph, it in _items(result)]
    phases = result.setdefault('phases', {})
    added, seen = [], set()
    for rule in rules or []:
        key = _nospace(rule.get('name'))
        if not key or key in seen:
            continue
        seen.add(key)
        if _present(rule, existing):
            continue
        ph = PHASE_OF_RULE.get(rule.get('phase'), 'design')
        phases.setdefault(ph, []).append({
            'task': rule.get('name'), 'law_link': rule.get('law_link') or '', 'desc': rule.get('desc') or '',
            'verify': {'status': 'rule', 'title': '', 'note': (
                '서버의 지식 기반(룰 엔진)이 이 사업에 해당한다고 보고 덧붙인 필수 항목입니다(AI 결과에는 없던 항목). '
                + (f"해당 조건: {rule.get('condition')[:140]}. " if rule.get('condition') and rule.get('condition').strip() != 'True' else '')
                + '사업과의 관련성을 확인하십시오.')},
        })
        existing.append(_core(rule.get('name')))
        added.append({'name': rule.get('name'), 'phase': ph})
    return added


# ---------------------------------------------------------------- 3. 조문 대조
def _is_adm(name):
    n = _nospace(name)
    return n.endswith(tuple(_nospace(s) for s in _ADM_SUFFIXES)) and not n.endswith('시행규칙')


def _label(law_name, no, br):
    return f"{law_name} 제{no}조" + (f"의{br}" if br else '')


def verify_citations(result, loader, judge):
    """항목마다 item['verify'] = {status, title, note}를 붙인다. loader(key)->{'art':{(조,가지):(제목,본문)}}|None, judge(list)->{idx:{verdict,reason}}.
    상태 개수를 돌려준다."""
    todo = []        # 판정 대상
    laws = {}        # (is_adm, nospace name) -> 법령 또는 None
    keys = set()
    for _ph, it in _items(result):
        if it.get('verify'):
            continue
        name = (it.get('law_name') or '').strip()
        toks = _ART.findall(it.get('article') or '')
        if name and toks:
            keys.add((_is_adm(name), _nospace(name)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for k, law in zip(keys, ex.map(lambda k: _safe(loader, k), keys)):
            laws[k] = law

    for _ph, it in _items(result):
        if it.get('verify'):
            continue
        name = (it.get('law_name') or '').strip()
        toks = _ART.findall(it.get('article') or '')
        if not name or not toks:
            why = '별표를 인용한 항목이라 조문 번호 대조 대상이 아닙니다. 법적 근거 링크로 별표 원문을 확인하십시오.' if re.search(r'별표', it.get('article') or '') \
                else '법령명 또는 조문 번호가 없어 원문과 대조하지 못했습니다.'
            it['verify'] = {'status': 'unchecked', 'title': '', 'note': why}
            continue
        law = laws.get((_is_adm(name), _nospace(name)))
        if not law or not law.get('art'):
            it['verify'] = {'status': 'unchecked', 'title': '', 'note': '법제처에서 이 법령의 원문을 가져오지 못해 대조하지 못했습니다.'}
            continue
        problem = None
        for no, br in toks:
            ent = law['art'].get((int(no), int(br) if br else 0))
            if ent is None:
                problem = ('missing', f"{_label(name, no, br)}는 현행 법령 원문에서 찾을 수 없습니다(번호 오류이거나 삭제된 조문일 수 있습니다).")
                break
            title, body = ent
            if re.match(r'^제\d+조(?:의\d+)?\s*삭제', (body or '').strip()):
                problem = ('deleted', f"{_label(name, no, br)}는 삭제된 조문입니다.")
                break
        if problem:
            it['verify'] = {'status': problem[0], 'title': '', 'note': problem[1]}
            continue
        no, br = toks[0]
        title, body = law['art'][(int(no), int(br) if br else 0)]
        it['verify'] = {'status': 'ok', 'title': title or '', 'note': ''}
        for no_i, br_i in toks[:4]:           # 조문을 여럿 인용했으면 조문마다 판정한다(제17조(검사)·제18조(대가의 지급)처럼 합쳐서 한 항목을 뒷받침할 수 있다)
            t_i, b_i = law['art'][(int(no_i), int(br_i) if br_i else 0)]
            todo.append((it, {'label': _label(name, no_i, br_i), 'law_display': name, 'no': no_i, 'br': br_i or '', 'title': t_i or '', 'body': b_i or '',
                              'claim': (f"{_title_of(it)}: {it.get('desc') or it.get('reason') or ''}")[:320]}))

    chunks = [todo[i:i + JUDGE_CHUNK] for i in range(0, len(todo), JUDGE_CHUNK)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        verdicts = list(ex.map(lambda ch: _safe(judge, [x for _i, x in ch]) or {}, chunks))
    votes = {}       # id(item) -> [(판정, 이유)]
    for ch, vd in zip(chunks, verdicts):
        for idx, (it, _x) in enumerate(ch):
            d = vd.get(idx) or {}
            votes.setdefault(id(it), (it, []))[1].append((d.get('verdict'), d.get('reason', '')))
    for it, vs in votes.values():
        if vs and all(v == 'unsupported' for v, _r in vs):         # 인용한 조문이 전부 다른 분야일 때만 의심으로 표시한다
            it['verify'] = {'status': 'mismatch', 'title': it['verify']['title'],
                            'note': f"실제 조문은 「{it['verify']['title'] or '제목 없음'}」에 관한 것으로, 이 항목의 내용과 다른 분야로 보입니다. {vs[0][1]}".strip()}

    counts = {k: 0 for k in STATUS_LABEL}
    for _ph, it in _items(result):
        counts[(it.get('verify') or {}).get('status', 'unchecked')] = counts.get((it.get('verify') or {}).get('status', 'unchecked'), 0) + 1
    return counts


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception as e:                      # 검증 한 건이 실패해도 분석 전체는 계속한다
        print(f"[law_review_verify] 조회·판정 실패: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------- 묶음
def postprocess(result, project_type, rules, loader=None, judge=None, warnings=None):
    """결과(dict)를 제자리에서 점검해 result['verification']을 붙인다. 어떤 단계가 실패해도 원래 결과는 그대로 돌려준다."""
    if loader is None or judge is None:
        import citation_check
        loader = loader or citation_check._load_any
        judge = judge or citation_check._judge
    info = {'excluded': [], 'added': [], 'counts': {}, 'warnings': list(warnings or []), 'steps_failed': []}
    def merge_step():
        usable, skipped = split_rules_by_trade(rules, project_type)
        info['added'] = merge_rule_items(result, usable)
        info['excluded'] = info['excluded'] + skipped

    for step, fn in (
        ('공종 점검', lambda: info.__setitem__('excluded', exclude_mismatched_trade(result, project_type))),
        ('필수 항목 보완', merge_step),
        ('조문 대조', lambda: info.__setitem__('counts', verify_citations(result, loader, judge))),
    ):
        try:
            fn()
        except Exception as e:
            print(f"[law_review_verify] {step} 단계 오류: {type(e).__name__}: {e}")
            info['steps_failed'].append(step)
    result['verification'] = info
    return result
