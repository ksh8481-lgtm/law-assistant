"""
사업수행능력평가(PQ) 입력값 AI 추출 보조 모듈.

입찰사가 낸 서류(자기평가서, 실적증명서, 경력증명서 등)에서 점수 계산에 필요한 "입력값"만 AI가 뽑아낸다.
점수는 AI가 만들지 않는다 - 뽑은 값은 화면에서 사람이 확인·수정한 뒤 pq_engine이 고시 공식대로 계산한다.

환각을 막기 위한 설계:
- 서류에 명시된 값만 옮기게 하고, 없거나 불확실하면 null로 두게 한다(추측·계산 금지, 서류에 합계가 있으면 그 합계 사용).
- 값마다 서류 속 근거 문구(evidence)를 함께 받아 화면에 보여준다.
- 서버가 명세(spec)의 필드 정의대로 결과를 걸러낸다(없는 필드 버림, 숫자·선택지 검증).
- 실격·감점처럼 평가자가 판단해야 하는 항목(필드의 no_ai 표시)은 AI에게 묻지도, 받지도 않는다.
"""
import json
import re

DEFAULT_RULES = [
    '대행업무(방재관리대책 대행업무) 실적과 유사용역 실적은 구분해서 각각 적는다. 구분이 서류에 없으면 대행업무 칸이 아니라 null로 두고 evidence에 사유를 적는다.',
]


def _field_line(f):
    t = f.get('type')
    extra = ''
    if t == 'select':
        extra = ' 선택지=' + '/'.join(f.get('options', []))
    unit = f.get('unit')
    kind = {'number': '숫자', 'select': '선택', 'checkbox': 'true/false', 'text': '문자열', 'role_select': '문자열'}.get(t, t)
    return f"- {f['key']}: {f['label']} ({kind}{'·' + unit if unit else ''}){extra}"


def _ai_fields(fields):
    return [f for f in fields if not f.get('no_ai')]


def _scope_names(project, scope):
    return [(r.get('name') or '').strip() for r in (project.get(scope) or []) if (r.get('name') or '').strip()]


def build_prompt(spec, project, bidder_name):
    """입찰사 1개 사의 서류에서 값을 뽑는 프롬프트."""
    form = spec['form']
    lines = ['[대행자(회사) 항목 - firm]']
    for sec in form['firm']:
        fs = _ai_fields(sec['fields'])
        if not fs:
            continue
        lines.append(f"# {sec['title']}")
        lines += [_field_line(f) for f in fs]
    for rows in form.get('firm_rows', []):
        lines.append(f"# {rows['title']}  (배열 firm_rows.{rows['key']}, 항목 1건당 1행)")
        lines += ['  - ' + _field_line(c)[2:] for c in _ai_fields(rows['columns'])]
    lines.append('')
    lines.append('[기술인 항목 - persons]')
    scope_notes = []
    for role, d in form['persons'].items():
        fs = _ai_fields(d['fields'])
        if not fs:
            continue
        scope = d.get('scope')
        if scope:
            names = _scope_names(project, scope)
            lines.append(f"# persons.{role} - {d['label']} (분야마다 1명, 키는 분야명)")
            scope_notes.append(f"persons.{role}의 키는 반드시 다음 분야명 그대로: {', '.join(names) if names else '(없음)'}")
        else:
            lines.append(f"# persons.{role} - {d['label']}")
        lines += [_field_line(f) for f in fs]

    rules = spec['form'].get('extract_rules') or DEFAULT_RULES
    rule_text = '\n'.join(f'{i}. {r}' for i, r in enumerate(
        ['서류에 명시된 값만 쓴다. 서류에 없거나 불확실하면 null. 절대 추측하지 말고, 평균·보정·임의 환산을 하지 마라.',
         '서류에 합계(건수·금액·경력 합계)가 이미 적혀 있으면 그 값을 쓴다. 개별 실적 목록만 있고 합계가 없을 때만 직접 세되, 입찰공고일 기준 기간 안에 준공된 것만 센다. 그 경우 evidence에 "목록에서 직접 집계"라고 적어라.']
        + list(rules)
        + ['금액·경력·비율은 각 항목에 표시된 단위(억원·년·개월·건·%)로 적는다(개월은 년으로 바꾸지 말고 항목의 단위를 따른다).',
           '선택지가 있는 필드는 선택지 중 하나와 정확히 같은 값만 쓴다. 맞는 게 없으면 null.',
           '확인할 수 없는 기술인·분야는 객체를 비워두거나 생략한다(지어내지 마라).',
           '모든 값에는 evidence(서류에서 베낀 30자 이내 문구 + 위치)를 키 경로로 붙인다. evidence 없는 값은 쓰지 마라.'], start=1))
    persons_example = ',\n'.join(
        f'    "{role}": ' + ('{"분야명": {"필드키": 값, ...}}' if d.get('scope') else '{"필드키": 값, ...}')
        for role, d in form['persons'].items() if _ai_fields(d['fields']))
    rows_example = ', '.join('"%s": [{...}]' % r['key'] for r in form.get('firm_rows', []))
    return f"""너는 공공 용역 사업수행능력평가(PQ) 서류에서 값을 옮겨 적는 보조자다. 점수는 계산하지 마라. 서류에 적힌 값만 옮겨라.

[평가 대상] 입찰사: {bidder_name or '(이름 미상)'} / 평가 기준: {spec['name']}
[입찰공고일] {project.get('announce_date') or '(미입력)'}  ← 기간(최근 1년·3년·5년·10년)은 이 날짜 기준이다.
[분야 구성] {' / '.join(scope_notes) if scope_notes else '(없음)'}

[엄격한 규칙]
{rule_text}

[추출할 항목]
{chr(10).join(lines)}

[출력 형식 - 오직 JSON 한 개만, 설명 금지]
{{
  "firm": {{"필드키": 값, ...}},
  "firm_rows": {{{rows_example}}},
  "persons": {{
{persons_example}
  }},
  "evidence": {{"firm.필드키": "근거 문구(위치)", "persons.역할.필드키": "근거 문구(위치)", "persons.역할.분야명.필드키": "..."}}
}}
"""


def _coerce(f, v):
    t = f.get('type')
    if v is None or v == '':
        return None
    if t == 'number':
        try:
            x = float(str(v).replace(',', '').replace('%', '').strip())
        except (TypeError, ValueError):
            return None
        if f.get('min') is not None and x < f['min']:
            return None
        return int(x) if x == int(x) and abs(x) < 1e12 else x
    if t == 'select':
        s = str(v).strip()
        return s if s in f.get('options', []) else None
    if t == 'checkbox':
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ('true', '1', 'yes', '예')
    if t in ('text', 'role_select'):
        return str(v).strip()[:60]
    return None


def _clean_obj(fields, raw):
    out = {}
    if not isinstance(raw, dict):
        return out
    by_key = {f['key']: f for f in _ai_fields(fields)}
    for k, v in raw.items():
        f = by_key.get(k)
        if not f:
            continue
        c = _coerce(f, v)
        if c is not None:
            out[k] = c
    return out


def parse_response(spec, project, text):
    """AI 응답 문자열 -> (입찰사 입력값 dict, evidence dict, 안내 목록). 스키마에 맞게 걸러낸다."""
    notes = []
    m = re.search(r'\{.*\}', text or '', re.S)
    if not m:
        raise ValueError('AI 응답에서 JSON을 찾지 못했습니다.')
    raw = json.loads(m.group(0))
    form = spec['form']

    firm_fields = [f for sec in form['firm'] for f in sec['fields']]
    firm = _clean_obj(firm_fields, raw.get('firm'))

    raw_rows = raw.get('firm_rows') or {}
    for rows in form.get('firm_rows', []):
        cleaned = []
        for r in (raw_rows.get(rows['key']) or []):
            c = _clean_obj(rows['columns'], r)
            if c:
                cleaned.append(c)
        firm[rows['key']] = cleaned

    persons_raw = raw.get('persons') or {}
    persons = {}
    for role, d in form['persons'].items():
        scope = d.get('scope')
        if scope:
            names = _scope_names(project, scope)
            persons[role] = {}
            for fname, obj in (persons_raw.get(role) or {}).items():
                if fname in names:
                    c = _clean_obj(d['fields'], obj)
                    if c:
                        persons[role][fname] = c
                else:
                    notes.append(f"서류에서 찾은 분야 '{fname}'은(는) 평가 대상 분야 구성에 없어 제외했습니다.")
        else:
            persons[role] = _clean_obj(d['fields'], persons_raw.get(role))

    evidence = {}
    for k, v in (raw.get('evidence') or {}).items():
        if isinstance(k, str) and isinstance(v, str) and v.strip():
            evidence[k] = v.strip()[:160]
    return {'firm': firm, 'persons': persons}, evidence, notes
