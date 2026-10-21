"""
AI 답변에 달린 법령 조문 링크를 법제처 실제 조문 원문과 대조해, 원문과 맞지 않는 인용에 경고를
붙이는 후처리 검증기.

[왜 필요한가]
AI가 "관광진흥법 제17조에 따라 사업계획 승인 시 수영장업 신고가 의제된다"처럼 그럴듯한
조항번호를 지어내는 일이 반복된다(실사용 중 발견: 실제 제17조는 "관광숙박업 등의 등록심의
위원회"로 체육시설 언급이 전혀 없음). 구글 검색으로 AI가 스스로 검증하게 하는 패스
(app.verify_law_citations_via_search)는 확률적이라 같은 오류를 어떤 때는 잡고 어떤 때는 놓친다.
이 모듈은 AI의 기억이나 검색에 맡기지 않고, 답변에 인용된 "법령명 제N조"마다 법제처 API에서
그 조문의 실제 제목·본문을 가져와 (1) 그런 조문이 존재하는지, (2) AI가 그 조문에 붙인 주장이
조문 내용과 맞는지를 판정한다.

[동작]
1. 이미 linkify_law_citations()를 거친 최종 텍스트에서 law.go.kr/법령/<법령명>/제N조 링크를 찾는다
   (링크 URL에 법령명·조번호가 정규화돼 들어 있어서 AI가 쓴 이름을 따로 추측할 필요가 없다).
2. 법령별로 lawService.do?LM=<법령명> 으로 조문 전체를 한 번 가져와 캐시한다.
3. 링크가 달린 문장(주장)과 실제 조문 본문을 LLM에 한 번에 보내 supported/unsupported/unsure를
   받는다(조문 원문을 함께 주므로 기억에 의존하는 검증이 아님).
4. unsupported이거나 조문이 아예 없으면 해당 링크 바로 뒤에 ⚠️ 경고와 실제 조문 제목을 붙인다.

네트워크/LLM 호출이 실패하면 아무것도 바꾸지 않고 원문을 그대로 돌려준다(검증 실패가 답변
자체를 막지 않도록).
"""
import os
import re
import json
import urllib.parse
import threading
from concurrent.futures import ThreadPoolExecutor

# 링크 텍스트 안에 [별표 2] 같은 대괄호가 한 단계 들어 있어도 한 링크로 인식
_LINK_TEXT = r'\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]'
# URL 안에 공백이 있어도(AI가 고시명을 "건설엔지니어링 대가 등에 관한 기준"처럼 띄어쓰기 그대로 URL에 쓰는 일이 잦다) 한 링크로 인식한다.
_LAW_LINK = re.compile(r'(' + _LINK_TEXT + r')\((https?://(?:www\.)?law\.go\.kr/[^)\n]*)\)')
_ART_PATH = re.compile(r'^https?://(?:www\.)?law\.go\.kr/법령/([^/?#]+)/제(\d+)조(?:의(\d+))?$')
_TITLE = re.compile(r'^제\d+조(?:의\d+)?\(([^)]*)\)')
_LAW_ONLY_PATH = re.compile(r'^https?://(?:www\.)?law\.go\.kr/법령/([^/?#]+)$')
# 고시·훈령·예규·지침(행정규칙) 링크: /행정규칙/<이름>[/제N조]
_ADM_ART_PATH = re.compile(r'^https?://(?:www\.)?law\.go\.kr/행정규칙/([^/?#]+)/제(\d+)조(?:의(\d+))?$')
_ADM_ONLY_PATH = re.compile(r'^https?://(?:www\.)?law\.go\.kr/행정규칙/([^/?#]+)$')
_PERCENT = re.compile(r'(\d+(?:\.\d+)?)\s*(?:%|퍼센트)')
_BYEOLPYO = re.compile(r'별표\s*(\d+)(?:\s*의\s*(\d+))?')
_BYEOLPYO_AFTER = re.compile(r'^\s*\[?\s*별표\s*(\d+)(?:\s*의\s*(\d+))?\s*\]?')
# 주장 문장에서 "테마파크업", "수영장업"처럼 업종을 가리키는 단어(일반어는 제외)
_BUSINESS_TERM = re.compile(r'[가-힣]{2,}업')
_GENERIC_BUSINESS = {'사업', '영업', '관광사업', '공사업', '건설업', '산업', '기업', '직업', '작업', '학업', '농업', '수업'}

# 큰따옴표 안의 문구(법 조문을 그대로 옮겼다는 표시)
_DQUOTE = re.compile(r'["\u201c]([^"\u201c\u201d\n]{10,220})["\u201d]')
_NORM_STRIP = re.compile(r"[\s.,;:·ㆍ()\[\]「」『』'\"\u201c\u201d\u2018\u2019<>\u2026~\-]")
QUOTE_MIN_OVERLAP = 0.55    # 인용문의 4글자 조각 중 원문에 실제로 있는 비율이 이보다 낮으면 "원문과 다름"

# 법 개정으로 이름이 바뀐 용어(옛 이름 -> 현행 이름, 해당 법령). AI는 학습 당시의 옛 이름을 즐겨 쓴다.
# 단, 실제 법령 XML을 조회해 "옛 이름은 본문 조문/별표에 없고 현행 이름은 있다"가 확인될 때만 경고한다.
RENAMED_TERMS = [
    ('종합유원시설업', '종합테마파크업', '관광진흥법'),
    ('일반유원시설업', '일반테마파크업', '관광진흥법'),
    ('기타유원시설업', '기타테마파크업', '관광진흥법'),
    ('유원시설업', '테마파크업', '관광진흥법'),
]

MAX_CITATIONS = 12          # 한 답변에서 검증할 인용 개수 상한(LLM 프롬프트 크기/지연 제한)
ARTICLE_TEXT_LEN = 900      # LLM에 보낼 조문 본문 길이 상한(글자)
CLAIM_LEN = 320             # LLM에 보낼 주장 문장 길이 상한(글자)

_LAW_CACHE = {}             # 법령명(공백 제거) -> {(조, 가지): (제목, 본문)} | None
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 64


def _moleg():
    # moleg_mcp는 FastMCP를 import하므로 필요할 때만 불러온다.
    import moleg_mcp
    return moleg_mcp


def _load_law(name_nospace: str):
    """법령명(공백 제거) -> {'art': {(조,가지): (제목, 본문)}, 'bp': {(별표,가지): (제목, 내용)}}.
    조회 실패/없는 법령이면 None."""
    with _CACHE_LOCK:
        if name_nospace in _LAW_CACHE:
            return _LAW_CACHE[name_nospace]
    articles = None
    byeolpyo = {}
    try:
        m = _moleg()
        url = (f"https://www.law.go.kr/DRF/lawService.do?OC={m.MOLEG_API_KEY}"
               f"&target=law&LM={urllib.parse.quote(name_nospace)}&type=XML")
        root = m._fetch_law_xml_with_retry(url, timeout=20, retries=1)
        if root.tag == '법령':
            articles = {}
            for jo in root.findall('.//조문단위'):
                if (jo.findtext('조문여부', '') or '').strip() != '조문':
                    continue
                no = (jo.findtext('조문번호', '') or '').strip()
                br = (jo.findtext('조문가지번호', '') or '').strip()
                if not no.isdigit():
                    continue
                parts = [el.text.strip() for el in jo.iter()
                         if el.tag in ('조문내용', '항내용', '호내용', '목내용') and el.text and el.text.strip()]
                if not parts:
                    continue
                body = "\n".join(parts)
                t = _TITLE.match(parts[0])
                articles[(int(no), int(br) if br.isdigit() else 0)] = ((t.group(1) if t else ''), body)
            for b in root.findall('.//별표단위'):
                bno = (b.findtext('별표번호', '') or '').strip()
                bbr = (b.findtext('별표가지번호', '') or '').strip()
                if not bno.isdigit() or (b.findtext('별표구분', '') or '').strip() not in ('별표', ''):
                    continue
                byeolpyo[(int(bno), int(bbr) if bbr.isdigit() else 0)] = (
                    (b.findtext('별표제목', '') or '').strip(), (b.findtext('별표내용', '') or ''))
    except Exception as e:
        print(f"[citation_check] 법령 조회 실패({name_nospace}): {type(e).__name__}: {e}")
        articles = None
    # 일시적인 조회 실패(None)는 캐시하지 않는다 - 다음 요청에서 다시 시도할 수 있게.
    law = {'art': articles, 'bp': byeolpyo} if articles is not None else None
    if law is not None:
        with _CACHE_LOCK:
            if len(_LAW_CACHE) >= _CACHE_MAX:
                _LAW_CACHE.pop(next(iter(_LAW_CACHE)))
            _LAW_CACHE[name_nospace] = law
    return law


def _load_admrul(name_nospace: str):
    """고시·훈령·예규·지침 이름 -> _load_law와 같은 {'art', 'bp'} 구조. 현행본을 못 찾거나 조회 실패면 None.
    (본문 파싱과 캐시는 moleg_mcp가 한다 - 답변용 원문 조회와 같은 캐시를 써서 중복 호출이 없다.)"""
    try:
        _meta, doc = _moleg().load_admrul_by_name(name_nospace)
    except Exception as e:
        print(f"[citation_check] 행정규칙 조회 실패({name_nospace}): {type(e).__name__}: {e}")
        return None
    if not doc:
        return None
    art = {}
    for a in doc['articles']:
        if a['no']:
            art.setdefault((a['no'], a['br']), (a['title'], a['text']))
    bp = {(b['no'], b['br']): (b['title'], b['content']) for b in doc['byeolpyo'] if b['no']}
    return {'art': art, 'bp': bp}


def _load_any(key):
    """key = (고시 여부, 이름). 고시면 target=admrul, 아니면 target=law로 조회한다."""
    is_adm, name = key
    return _load_admrul(name) if is_adm else _load_law(name)


def _plain(text: str) -> str:
    """마크다운 링크/강조/코드 표시를 걷어낸 평문(주장 문장을 LLM에 보내기 위한 용도)."""
    text = re.sub(_LINK_TEXT + r'\([^)\n]*\)', lambda m: m.group(0)[1:m.group(0).index('](')], text)
    return re.sub(r'[*`>#]+', '', text).strip()


def _claim_for(text: str, link_start: int) -> str:
    """링크가 포함된 줄을 주장 문장으로 쓴다(너무 길면 링크 주변만)."""
    line_start = text.rfind('\n', 0, link_start) + 1
    line_end = text.find('\n', link_start)
    line_end = len(text) if line_end == -1 else line_end
    line = _plain(text[line_start:line_end])
    if len(line) <= CLAIM_LEN:
        return line
    rel = max(0, min(len(line) - CLAIM_LEN, len(_plain(text[line_start:link_start])) - CLAIM_LEN // 2))
    return line[rel:rel + CLAIM_LEN]


def _bp_label(no: int, br: int) -> str:
    return f"별표 {no}" + (f"의{br}" if br else "")


def _find_citations(text: str):
    cites = []
    matches = list(_LAW_LINK.finditer(text))
    for i, m in enumerate(matches):
        url = urllib.parse.unquote(m.group(2))
        label = m.group(1)[1:-1]
        line_start = text.rfind('\n', 0, m.start()) + 1
        line_end = text.find('\n', m.end())
        line_end = len(text) if line_end == -1 else line_end
        prev_end = matches[i - 1].end() if i > 0 else 0
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        before = text[max(prev_end, line_start, m.start() - 220):m.start()]
        # 한 줄에 인용이 여러 개면 문장 속 수치가 어느 인용의 것인지 알 수 없어 수치 대조를 건너뛴다.
        line_cites = sum(1 for x in matches if line_start <= x.start() < line_end)
        adm = bool(_ADM_ART_PATH.match(url) or _ADM_ONLY_PATH.match(url))
        art = _ADM_ART_PATH.match(url) if adm else _ART_PATH.match(url)
        if art:
            after = text[m.end():min(next_start, line_end, m.end() + 220)]
            cites.append({
                'kind': 'art', 'adm': adm, 'law': re.sub(r'\s+', '', art.group(1)),
                'no': int(art.group(2)), 'br': int(art.group(3)) if art.group(3) else 0,
                'label': label, 'end': m.end(), 'claim': _claim_for(text, m.start()),
                'near': before + ' ' + after, 'after': after, 'line_cites': line_cites,
            })
            continue
        base = _ADM_ONLY_PATH.match(url) if adm else _LAW_ONLY_PATH.match(url)
        if not base:
            continue
        # 법령 본문 링크 뒤에 "[별표 1]"이 붙거나, 링크 라벨 안에 "별표 1"이 들어 있는 경우
        bp = _BYEOLPYO.search(label)
        end = m.end()
        if not bp:
            after_m = _BYEOLPYO_AFTER.match(text[m.end():m.end() + 24])
            if after_m:
                bp, end = after_m, m.end() + after_m.end()
        if bp:
            cites.append({
                'kind': 'bp', 'adm': adm, 'law': re.sub(r'\s+', '', base.group(1)),
                'no': int(bp.group(1)), 'br': int(bp.group(2)) if bp.group(2) else 0,
                'label': label, 'end': end, 'claim': _claim_for(text, m.start()),
                'near': '', 'line_cites': line_cites,
            })
    return cites


def _norm(t: str) -> str:
    return _NORM_STRIP.sub('', t)


def _grams(t: str, n: int = 4) -> set:
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def _check_quotes(c, article_body: str):
    """인용 앞뒤(같은 줄, 이웃 링크 사이)에 큰따옴표로 옮긴 문구가 있으면, 그 문구가 실제 조문 원문에
    있는지 4글자 조각 단위로 대조한다. 거의 없으면(예: 옛 용어로 쓴 정의문) 경고 문구를 돌려준다.
    주제만 맞으면 통과시키는 LLM 판정이 놓치는 '그럴듯하게 틀린 인용문'을 잡기 위한 결정적 검사."""
    body_norm = _norm(article_body)
    body_grams = _grams(body_norm)
    for q in _DQUOTE.findall(c.get('near', '')):
        for chunk in re.split(r'\u2026|\.\.\.', q):
            qn = _norm(chunk)
            if len(qn) < 10 or not re.search(r'[가-힣]', qn):
                continue
            g = _grams(qn)
            ratio = len(g & body_grams) / len(g) if g else 1.0
            if ratio < QUOTE_MIN_OVERLAP:
                label = f"제{c['no']}조" + (f"의{c['br']}" if c['br'] else '')
                ho = re.findall(r'제(\d+)호', c.get('label', '') + ' ' + c.get('after', '')[:40])
                best, best_score = '', -1
                for line in article_body.split(chr(10)):
                    score = len(g & _grams(_norm(line)))
                    if ho and re.match(r'\s*' + ho[-1] + r'[.]', line):
                        score += 1000      # 인용한 호(예: 제6호) 줄을 우선
                    if score > best_score:
                        best, best_score = line.strip(), score
                return (f" ⚠️(인용문 불일치: 따옴표 안의 문구가 실제 {label} 원문과 다릅니다. 원문 해당 부분: "
                        f"'{best[:110]}')")
    return None


def fix_renamed_terms(text: str):
    """법 개정으로 바뀐 옛 용어(유원시설업 등)를 현행 용어로 교정하고, 교정했으면 상단에 안내문을 붙인다.
    반환: (교정된 텍스트, 교정 횟수).

    경고만 붙이는 방식으로는 부족했다(실사용 중 확인: 같은 질문을 세 번 돌렸더니 두 번은 '유원시설업'을
    본문에서 9번, 25번 쓰는데 경고는 몇 개뿐). 법령 XML로 "옛 용어는 현행 본문 조문/별표에 없고 새 용어는
    있다"가 확인된 개명(RENAMED_TERMS)은 1:1 대응이므로 본문을 직접 현행 용어로 바꾼다. 링크 안은 건드리지 않는다."""
    link_spans = [(m.start(), m.end()) for m in re.finditer(_LINK_TEXT + r'\([^)\n]*\)', text)]
    replaced = []
    for old, new, law_name in RENAMED_TERMS:      # 긴 옛 이름(종합유원시설업 등)부터 처리된다
        if old not in text or law_name not in text:
            continue
        law = _load_law(law_name)
        if not law:
            continue
        bodies = [b for _t, b in law['art'].values()] + [t + (c or '') for t, c in law['bp'].values()]
        if any(old in b for b in bodies) or not any(new in b for b in bodies):
            continue      # 현행 법령에도 옛 이름이 남아 있거나, 새 이름이 확인 안 되면 교정하지 않는다
        def _sub(m, _old=old, _new=new):
            if any(a <= m.start() < b for a, b in link_spans):
                return m.group(0)
            replaced.append((_old, _new, law_name))
            return _new
        text = re.sub(re.escape(old), _sub, text)
        # 치환으로 길이가 바뀌었으므로 링크 구간을 다시 계산한다.
        link_spans = [(m.start(), m.end()) for m in re.finditer(_LINK_TEXT + r'\([^)\n]*\)', text)]
    if not replaced:
        return text, 0
    # "현행법상 '옛용어'라는 용어는 사용되지 않으며 ..." 같은 용어 부존재 설명은 옛 용어가 새 용어로 바뀌면
    # "'테마파크업'이라는 용어는 사용되지 않으며, '테마파크업'이 ..."처럼 스스로 모순되므로 그 설명 자체를 지운다.
    for _o, new_term, _l in dict.fromkeys((o, n, l) for o, n, l in replaced):
        q = r"['\"“‘]?" + re.escape(new_term) + r"['\"”’]?"
        text = re.sub(r"\s*\((?:[^()]*?)" + q + r"(?:이)?라는\s*용어[^()]*\)", "", text)
        text = re.sub(r"[^.\n]*" + q + r"(?:이)?라는\s*용어는\s*(?:사용되지|존재하지|없)[^.\n]*[.]\s*", "", text)
    pairs = list(dict.fromkeys((o, n, l) for o, n, l in replaced))
    desc = ", ".join(f"'{o}' → '{n}'" for o, n, _l in pairs)
    notice = (f"> ⚠️ **용어 자동 교정**: 법 개정으로 {pairs[0][2]}의 용어가 바뀌어({desc}) "
              f"답변 속 옛 용어를 현행 용어로 교정했습니다.{chr(10)}{chr(10)}")
    return notice + text, len(replaced)


def _select(cites):
    """같은 (법령, 조)는 첫 등장 위주로 먼저 채우고, 상한까지만 검증한다."""
    seen, first, rest = set(), [], []
    for c in cites:
        key = (c['kind'], c.get('adm', False), c['law'], c['no'], c['br'])
        (rest if key in seen else first).append(c)
        seen.add(key)
    return (first + rest)[:MAX_CITATIONS]


def _judge(items):
    """LLM에 (주장, 실제 조문)을 한 번에 보내 판정을 받는다. 실패하면 {}."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-2.5-flash')
        blocks = []
        for i, it in enumerate(items):
            blocks.append(
                f"[{i}]\n판정 대상 인용(문장 속 표기): {it['label']}\n"
                f"법령: {it['law_display']}\n조문: 제{it['no']}조" + (f"의{it['br']}" if it['br'] else '') +
                f"\n실제 조문 제목: {it['title'] or '(제목 없음)'}\n실제 조문 본문: {it['body'][:ARTICLE_TEXT_LEN]}\n"
                f"답변에서의 주장(문장): {it['claim']}\n")
        prompt = (
            "너는 법령 인용 검수자다. 아래 각 항목은 어떤 답변이 특정 조문을 근거로 든 문장('답변에서의 주장(문장)')과, "
            "그 조문의 '실제 조문 제목/본문'이다. 각 항목마다 '판정 대상 인용'이 가리키는 조문에 대해 그 문장이 설명하는 "
            "주제가, 실제 조문의 제목·주제와 같은 분야인지만 판정해라.\n"
            "- supported: 문장이 그 조문에 대해 말하는 주제가 실제 조문의 제목/주제와 같은 분야다.\n"
            "- unsupported: 문장이 그 조문에 대해 말하는 주제가 실제 조문의 제목/주제와 다른 분야다. "
            "(예: 문장은 그 조문이 '인허가 의제 규정'이라고 설명하는데 실제 조문은 '위원회 구성'에 관한 것인 경우.) "
            "주제가 명백히 다를 때만 이걸 써라.\n"
            "- unsure: 그 외 전부(주제가 비슷하거나 애매함. 구체적 수치·세부 요건의 일치 여부는 본문이 잘려 있을 수 있으므로 "
            "판단하지 말고 unsure로 둔다).\n"
            "주의: 한 문장에 여러 조문 인용이 함께 있을 수 있다. 문장 속 다른 조문에 관한 설명은 무시하고, 오직 '판정 대상 인용'이 "
            "가리키는 조문에 관해 문장이 말하는 내용만 본다. 예: '甲法 제5조에 따라 乙法 제9조의 신고를 한 것으로 본다'라는 "
            "문장에서 乙法 제9조 항목은 '乙法 제9조가 신고에 관한 조문인가?'만 본다(의제 규정이 甲法 제5조에 있는지는 "
            "甲法 제5조 항목에서 판단한다).\n"
            "오직 JSON 배열만 출력해라. 형식: [{\"id\":0,\"verdict\":\"supported\",\"reason\":\"한 줄\"}, ...]\n\n"
            + "\n".join(blocks)
        )
        resp = model.generate_content(prompt, generation_config={
            "temperature": 0, "response_mime_type": "application/json"})
        raw = (resp.text or '').strip()
        try:
            data = json.loads(raw)
        except Exception:
            data = json.loads(re.search(r'\[.*\]', raw, re.S).group(0))
        return {int(d['id']): d for d in data if isinstance(d, dict) and 'id' in d}
    except Exception as e:
        print(f"[citation_check] 판정 호출 실패(원문 유지): {type(e).__name__}: {e}")
        return {}


def _business_terms(claim: str) -> list:
    """주장 문장에서 "테마파크업"처럼 구체적인 업종을 가리키는 단어만 뽑는다(일반어 제외)."""
    out = []
    for tok in _BUSINESS_TERM.findall(claim):
        if tok not in _GENERIC_BUSINESS and len(tok) >= 3 and tok not in out:
            out.append(tok)
    return out


def _sibling_names(name: str):
    """법령명(공백 제거)의 같은 계열(법/시행령/시행규칙) 이름들."""
    if name.endswith('시행규칙'):
        base = name[:-4]
    elif name.endswith('시행령'):
        base = name[:-3]
    else:
        base = name
    return [n for n in (base, base + '시행령', base + '시행규칙') if n != name]


_HINT_WORDS = ('시설', '설비', '기준', '범위', '종류', '허가', '신고', '등록', '과태료', '처분', '준수')


def _find_related_byeolpyo(c, terms, claim, own_law=None):
    """제목에 업종 용어가 들어 있는 별표를 같은 법령과 같은 계열(법/시행령/시행규칙)에서 찾는다.
    주장 문장과 제목이 공유하는 키워드(시설/기준/허가 등)가 많은 별표를 우선한다.
    고시는 시행령/시행규칙 계열이 없으므로 이미 불러온 자기 자신(own_law)만 본다."""
    best, best_score = None, -1
    names = [c['law']] if c.get('adm') else [c['law']] + _sibling_names(c['law'])
    for name in names:
        other = own_law if (c.get('adm') or name == c['law']) and own_law is not None else _load_law(name)
        if not other:
            continue
        for (no, br), (title, _content) in other['bp'].items():
            if name == c['law'] and (no, br) == (c['no'], c['br']):
                continue
            if not any(t in title for t in terms):
                continue
            score = sum(1 for w in _HINT_WORDS if w in title and w in claim)
            if score > best_score:
                best, best_score = (name, no, br, title), score
    return best


def _check_byeolpyo(c, law, terms):
    """별표 인용 검증(결정적).
    - 그 별표가 없으면 ⚠️ 경고.
    - 주장에 나온 업종 용어가 별표 제목/내용 어디에도 없으면 ⚠️ 경고(+관련 별표 후보).
    - 용어가 내용에는 있지만 제목에는 없고, 같은 계열의 다른 별표 '제목'에 그 용어가 있으면 💡 참고 후보를 안내한다
      (예: 시행령 별표 1 '관광사업의 등록기준'에도 '테마파크업' 단어가 나오지만, 테마파크업의 시설기준은
      시행규칙 별표 1의2 '테마파크업의 시설 및 설비기준'이다).
    문제 없으면 None."""
    label = _bp_label(c['no'], c['br'])
    bp = law['bp'].get((c['no'], c['br']))
    if bp is None:
        return f" ⚠️(원문 확인 결과 이 법령에는 {label}가 존재하지 않습니다)"
    if not terms:
        return None
    title, content = bp
    in_content = any(t in title + chr(10) + content for t in terms)
    if in_content and any(t in title for t in terms):
        return None
    related = _find_related_byeolpyo(c, terms, c['claim'], own_law=law)
    hint = f"{related[0]} {_bp_label(related[1], related[2])}('{related[3]}')" if related else ''
    if not in_content:
        return (f" ⚠️(별표 불일치: 이 법령의 {label}는 '{title}'이며 '{terms[0]}' 관련 내용이 없습니다."
                + (f" 관련 별표 후보: {hint}." if hint else '') + " 이 인용은 확인이 필요합니다)")
    if hint:
        return f" 💡(참고: {label}의 제목은 '{title}'입니다. '{terms[0]}' 관련 별표는 {hint}일 수 있습니다. 확인 필요)"
    return None


def _check_percent(c, body: str):
    """문장에 적힌 비율(예: '15%')이 인용한 조문/별표 원문에 실제로 있는지 대조한다(결정적).
    '그럴듯하게 틀린 수치'는 주제만 보는 LLM 판정이 놓친다(예: 별표 2 바목의 '단순 10%·보통 15%·복잡 20%'를
    '일반 5%'처럼 바꿔 적는 경우). 한 줄에 인용이 여러 개면 비율이 어느 인용의 것인지 알 수 없어 건너뛰고,
    문장 속 비율 중 하나라도 원문에 있으면 통과시킨다(오탐을 줄이려고 경고가 아닌 참고 💡로만 알린다)."""
    if c.get('line_cites', 1) != 1:
        return None
    claimed = {float(x) for x in _PERCENT.findall(c.get('claim', ''))}
    if not claimed:
        return None
    in_body = {float(x) for x in _PERCENT.findall(body)}
    if claimed & in_body:
        return None
    label = _bp_label(c['no'], c['br']) if c['kind'] == 'bp' else f"제{c['no']}조" + (f"의{c['br']}" if c['br'] else '')
    shown = ", ".join(f"{v:g}%" for v in sorted(claimed))
    return f" 💡(참고: 문장의 비율({shown})이 인용한 {label} 원문에서 확인되지 않습니다. 원문 확인 필요)"


def annotate_unverified_citations(text: str) -> str:
    """linkify 이후의 최종 텍스트에서, 실제 조문/별표와 맞지 않는 법령 인용 뒤에 ⚠️ 경고를 붙인다.
    어떤 단계에서든 실패하면 원문을 그대로 돌려준다."""
    try:
        if not text:
            return text
        text, _fixed = fix_renamed_terms(text)
        cites = _select(_find_citations(text))
        if not cites:
            return text

        # 법령(target=law)·고시(target=admrul)별 조문/별표 원문을 병렬로 가져온다(1회씩, 캐시됨).
        keys = list(dict.fromkeys((c.get('adm', False), c['law']) for c in cites))
        with ThreadPoolExecutor(max_workers=min(4, len(keys))) as ex:
            loaded = dict(zip(keys, ex.map(_load_any, keys)))

        notes = {}          # end 위치 -> 붙일 경고 문구

        def add_note(end, note):
            if note:
                notes[end] = notes[end] + note if end in notes else note

        to_judge = []
        for c in cites:
            law = loaded.get((c.get('adm', False), c['law']))
            if law is None:
                continue    # 법령/고시 조회 실패·미존재: 판단 불가 -> 그대로 둔다
            if c['kind'] == 'bp':
                add_note(c['end'], _check_byeolpyo(c, law, _business_terms(c['claim'])))
                bp = law['bp'].get((c['no'], c['br']))
                if bp is not None:
                    add_note(c['end'], _check_percent(c, bp[0] + chr(10) + bp[1]))
                continue
            art = law['art'].get((c['no'], c['br']))
            if art is None:
                label = f"제{c['no']}조" + (f"의{c['br']}" if c['br'] else '')
                add_note(c['end'], f" ⚠️(원문 확인 결과 {label}는 존재하지 않는 조문입니다)")
                continue
            add_note(c['end'], _check_quotes(c, art[1]))
            add_note(c['end'], _check_percent(c, art[1]))
            to_judge.append({**c, 'law_display': c['law'], 'title': art[0], 'body': art[1]})

        verdicts = _judge(to_judge) if to_judge else {}
        for i, it in enumerate(to_judge):
            v = verdicts.get(i)
            if v and v.get('verdict') == 'unsupported':
                label = f"제{it['no']}조" + (f"의{it['br']}" if it['br'] else '')
                title = f"'{it['title']}'" if it['title'] else '다른 내용'
                add_note(it['end'], f" ⚠️(원문 불일치: 실제 {label}는 {title}입니다. 이 인용은 확인이 필요합니다)")

        if not notes:
            return text
        out, last = [], 0
        for end in sorted(notes):
            out.append(text[last:end])
            out.append(notes[end])
            last = end
        out.append(text[last:])
        return "".join(out)
    except Exception as e:
        print(f"[citation_check] 검증 실패(원문 유지): {type(e).__name__}: {e}")
        return text
