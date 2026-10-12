"""
사업수행능력평가(PQ) 입력값 AI 추출 보조 모듈.

입찰사가 낸 서류(자기평가서, 실적증명서, 경력증명서 등)에서 점수 계산에 필요한 "입력값"만 AI가 뽑아낸다.
점수는 AI가 만들지 않는다 - 뽑은 값은 화면에서 사람이 확인·수정한 뒤 pq_engine이 고시 공식대로 계산한다.

환각을 막기 위한 설계:
- 서류에 명시된 값만 옮기게 하고, 없거나 불확실하면 null로 두게 한다(추측·계산 금지, 서류에 합계가 있으면 그 합계 사용).
- 값마다 서류 속 근거 문구(evidence)를 함께 받아 화면에 보여준다.
- 서버가 명세(spec)의 필드 정의대로 결과를 걸러낸다(없는 필드 버림, 숫자·선택지 검증).
"""
import json
import re


def _field_line(f):
    t = f.get('type')
    extra = ''
    if t == 'select':
        extra = ' 선택지=' + '/'.join(f.get('options', []))
    unit = f.get('unit')
    kind = {'number': '숫자', 'select': '선택', 'checkbox': 'true/false', 'text': '문자열', 'role_select': '문자열'}.get(t, t)
    return f"- {f['key']}: {f['label']} ({kind}{'·' + unit if unit else ''}){extra}"


def build_prompt(spec, project_fields, announce_date, bidder_name):
    """입찰사 1개 사의 서류에서 값을 뽑는 프롬프트."""
    form = spec['form']
    lines = []
    lines.append('[대행자(회사) 항목 - firm]')
    for sec in form['firm']:
        lines.append(f"# {sec['title']}")
        lines += [_field_line(f) for f in sec['fields']]
    for rows in form.get('firm_rows', []):
        lines.append(f"# {rows['title']}  (배열 firm.{rows['key']}, 항목 1건당 1행)")
        lines += ['  - ' + _field_line(c)[2:] for c in rows['columns']]
    lines.append('')
    lines.append('[기술인 항목 - persons]')
    for role, label in (('lead', '사업책임기술인(1명)'), ('field_lead', '분야별책임기술인(분야마다 1명)'),
                        ('field_member', '분야별참여기술인(분야마다 1명)')):
        lines.append(f"# persons.{role} - {label}")
        lines += [_field_line(f) for f in form['persons'][role]['fields']]
    names = [(r.get('name') or '').strip() for r in project_fields if (r.get('name') or '').strip()]
    return f"""너는 공공 용역 사업수행능력평가(PQ) 서류에서 값을 옮겨 적는 보조자다. 점수는 계산하지 마라. 서류에 적힌 값만 옮겨라.

[평가 대상] 입찰사: {bidder_name or '(이름 미상)'} / 평가 기준: {spec['name']}
[입찰공고일] {announce_date or '(미입력)'}  ← 기간(최근 5년·10년·1년·3년)은 이 날짜 기준이다.
[분야별 구성(분야명)] {', '.join(names) if names else '(없음)'}  ← persons.field_lead / persons.field_member 의 키는 반드시 이 분야명 그대로 써라.

[엄격한 규칙]
1. 서류에 명시된 값만 쓴다. 서류에 없거나 불확실하면 null. 절대 추측하지 말고, 평균·보정·임의 환산을 하지 마라.
2. 서류에 합계(건수·금액·경력 합계)가 이미 적혀 있으면 그 값을 쓴다. 개별 실적 목록만 있고 합계가 없을 때만 직접 세되, 입찰공고일 기준 기간 안에 준공된 것만 센다. 그 경우 evidence에 "목록에서 직접 집계"라고 적어라.
3. 대행업무(방재관리대책 대행업무) 실적과 유사용역 실적은 구분해서 각각 적는다. 구분이 서류에 없으면 대행업무 칸이 아니라 null로 두고 evidence에 사유를 적는다.
4. 금액은 억원 단위 숫자로, 경력은 년 단위 숫자(개월은 12로 나눈 소수), 비율은 % 숫자로 적는다.
5. 선택지가 있는 필드는 선택지 중 하나와 정확히 같은 값만 쓴다. 맞는 게 없으면 null.
6. 확인할 수 없는 기술인·분야는 객체를 비워두거나 생략한다(지어내지 마라).
7. 모든 값에는 evidence(서류에서 베낀 30자 이내 문구 + 위치)를 키 경로로 붙인다. evidence 없는 값은 쓰지 마라.

[추출할 항목]
{chr(10).join(lines)}

[출력 형식 - 오직 JSON 한 개만, 설명 금지]
{{
  "firm": {{"필드키": 값, ...}},
  "firm_rows": {{"dev_items": [{{...}}], "use_items": [{{...}}], "prev_items": [{{...}}]}},
  "persons": {{
    "lead": {{"필드키": 값, ...}},
    "field_lead": {{"분야명": {{"필드키": 값, ...}}}},
    "field_member": {{"분야명": {{"필드키": 값, ...}}}}
  }},
  "evidence": {{"firm.perf5_d_cnt": "근거 문구(위치)", "persons.lead.career": "근거 문구(위치)", "persons.field_lead.수자원개발.grade": "..."}}
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
    by_key = {f['key']: f for f in fields}
    for k, v in raw.items():
        f = by_key.get(k)
        if not f:
            continue
        c = _coerce(f, v)
        if c is not None:
            out[k] = c
    return out


def parse_response(spec, project_fields, text):
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

    names = [(r.get('name') or '').strip() for r in project_fields if (r.get('name') or '').strip()]
    persons_raw = raw.get('persons') or {}
    persons = {'lead': _clean_obj(form['persons']['lead']['fields'], persons_raw.get('lead')),
               'field_lead': {}, 'field_member': {}}
    for role in ('field_lead', 'field_member'):
        for fname, obj in (persons_raw.get(role) or {}).items():
            if fname in names:
                c = _clean_obj(form['persons'][role]['fields'], obj)
                if c:
                    persons[role][fname] = c
            else:
                notes.append(f"서류에서 찾은 분야 '{fname}'은(는) 평가 대상 분야 구성에 없어 제외했습니다.")

    evidence = {}
    for k, v in (raw.get('evidence') or {}).items():
        if isinstance(k, str) and isinstance(v, str) and v.strip():
            evidence[k] = v.strip()[:160]
    return {'firm': firm, 'persons': persons}, evidence, notes
