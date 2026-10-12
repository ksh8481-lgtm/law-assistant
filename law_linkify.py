"""
AI 답변 속 법령 인용을 결정적으로(LLM 없이) law.go.kr 링크로 바꿔주는 후처리.

프롬프트로 "법령은 항상 링크로 쓰라"고 지시해도 AI가 일부만 링크하고 나머지는 맨 텍스트로
남기는 일이 반복돼서(실사용 중 발견), 답변이 완성된 뒤 서버에서 한 번 더 훑어
    - 알려진 법령명(약칭/정식명/로컬 DB 법령명/이번 검색에서 가져온 법령명, 시행령/시행규칙 포함)
    - 「법령명」 형태로 괄호 표기된 법령명
에 대해 링크를 붙인다. "제N조"가 바로 뒤따르면 조문까지 연결한다.
이미 마크다운 링크이거나 URL인 부분은 건드리지 않는다.
"""
import os
import re
import urllib.parse

LAW_URL = "https://www.law.go.kr/법령/"

# app.py의 LAW_ABBREVIATIONS와 같은 약칭 -> 정식명(공백 없음). 여기서 자체 보유하는 이유는
# app.py를 import하면 순환 참조가 되기 때문. 약칭이 늘면 양쪽에 추가해야 함.
ABBREVIATIONS = {
    '토지보상법': '공익사업을위한토지등의취득및보상에관한법률',
    '국토계획법': '국토의계획및이용에관한법률',
    '지방계약법': '지방자치단체를당사자로하는계약에관한법률',
    '건진법': '건설기술진흥법',
    '건산법': '건설산업기본법',
    '시설물안전법': '시설물의안전및유지관리에관한특별법',
    '지하안전법': '지하안전관리에관한특별법',
    '재난안전법': '재난및안전관리기본법',
    '건설폐기물법': '건설폐기물의재활용촉진에관한법률',
}
_SUFFIXES = ['', ' 시행령', ' 시행규칙']

_ARTICLE = r'(?:\s*제\s?\d+조(?:의\s?\d+)?)'
# 제N조 뒤의 "제1항 제2호 가목" 같은 하위 표기. law.go.kr URL은 조 단위까지만 지원하므로
# 링크 라벨에만 포함시키고 URL에는 넣지 않는다.
_SUBITEM = r'(?:\s*제\s?\d+(?:항|호|목))*'

# 이미 링크/URL/코드인 구간은 건너뛴다.
# 링크 텍스트 안에 "[별표 2]" 같은 대괄호가 들어 있는 링크(예: [법령명 시행령 [별표 2] 제목](url))도
# 하나의 링크로 인식해야 한다. 예전 정규식(\[[^\]\n]*\])은 안쪽 ']'에서 끊겨서 그런 링크를
# 못 알아보고, 그 안의 법령명에 또 링크를 씌워 "링크 안의 링크"를 만들었다(실사용 중 발견).
_LINK_TEXT = r'\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]'
_SKIP = re.compile(r'(' + _LINK_TEXT + r'\([^)\n]*\)|https?://\S+|`[^`\n]*`)')

# 가운뎃점: 공식 법령명은 'ㆍ'(U+318D)인데 AI는 '·' 등 비슷한 문자로 쓰는 일이 잦다.
_DOT_VARIANTS = '·・･•∙⋅'
_DOT_CLASS = '[ㆍ' + _DOT_VARIANTS + ']'

# 「법령명」 형태(이름 자체가 인식 안 되는 법령도 링크)
_BRACKETED = re.compile(r'[「『]([^」』\n]{2,60}?(?:법|법률|령|규칙))[」』](' + _ARTICLE + r'?)' + _SUBITEM)

# AI가 법령 인용을 링크 없이 "[법령명 제10조 제1항]"처럼 대괄호로만 감싸 쓰는 경우가 많다.
# 그 안의 법령명에 링크를 씌우면 "[[법령명 제10조](url) 제1항]"처럼 바깥 대괄호가 화면에
# 그대로 남아 지저분하므로, 링크 아닌 대괄호 인용은 대괄호를 벗겨낸다.
_PLAIN_BRACKET_CITATION = re.compile(r'\[([^\[\]\n]{2,120}?제\s?\d+조[^\[\]\n]*?)\](?!\()')

# AI가 법령 인용을 `[관광진흥법 제17조]`처럼 백틱(인라인 코드)으로 감싸 쓰는 일이 있다. 그러면 아래
# _SKIP이 코드 구간을 통째로 건너뛰어서 링크가 하나도 안 걸린다(실사용 중 발견: 답변 속 조문
# 인용 대부분이 링크 없이 코드 글씨로만 표시됨). 내용이 "법령명(+ 제N조 ...)" 형태인 코드
# 구간만 백틱을 벗겨 일반 텍스트로 되돌린다. `KDS 14 20 00`이나 파일명 같은 진짜 코드는 법/령/
# 규칙으로 끝나지 않으므로 건드리지 않는다.
# 이미 완성된 마크다운 링크 전체를 백틱으로 감싼 경우(`[판례명](url)`)도 코드로 보여서 링크가 안 눌린다.
_CODE_LINK = re.compile(r'`(' + _LINK_TEXT + r'\([^)\n]*\))`')
_CODE_CITATION = re.compile(
    r'`\[?([^`\n\[\]]{2,120}?(?:법|법률|령|규칙)(?:\s*제\s?\d+조(?:의\s?\d+)?(?:\s*제\s?\d+(?:항|호|목))*)?)\]?`')


def _nospace(s: str) -> str:
    return re.sub(r'\s+', '', s)


def _canon_dots(text: str) -> str:
    for ch in _DOT_VARIANTS:
        text = text.replace(ch, 'ㆍ')
    return text


def _link(label: str, name: str, article: str = "") -> str:
    url = LAW_URL + urllib.parse.quote(_canon_dots(_nospace(name)), safe='')
    art = _nospace(article)
    if art:
        url += "/" + urllib.parse.quote(art, safe='')
    return f"[{label}]({url})"


def _local_law_names() -> list:
    """data/laws/*.md 파일명(공백이 _로 된 법령명)을 법령명으로 복원."""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'laws')
    for cand in (base, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'laws')):
        if os.path.isdir(cand):
            return [os.path.splitext(f)[0].replace('_', ' ') for f in os.listdir(cand) if f.endswith('.md')]
    return []


_KNOWN_CACHE = None
# 자리표시자용 사설(private-use) 문자 - 본문에 등장할 일이 없다.
_OPEN, _CLOSE = chr(0xE000), chr(0xE001)


def _known_names(extra=None) -> dict:
    """{공백제거 이름: 정식(공백제거) 이름}. 약칭도 정식명으로 연결."""
    global _KNOWN_CACHE
    if _KNOWN_CACHE is None:
        known = {}
        for abbr, full in ABBREVIATIONS.items():
            for suf in _SUFFIXES:
                known[_nospace(abbr + suf)] = _nospace(full + suf)
                known[_nospace(full + suf)] = _nospace(full + suf)
        for nm in _local_law_names():
            known[_canon_dots(_nospace(nm))] = _canon_dots(_nospace(nm))
        _KNOWN_CACHE = known
    known = dict(_KNOWN_CACHE)
    for nm in (extra or []):
        if nm:
            # 법률 하나만 가져왔어도 AI는 같은 계열의 "OO법 시행령/시행규칙 제N조"를 자주 인용한다.
            # 그 변형 이름도 알려진 이름으로 등록하지 않으면 "법"만 링크되고 "시행령"이 링크 밖에
            # 남아(실사용 중 확인) 시행령 조문/별표 인용이 링크도 검증도 안 된다.
            base = nm
            for suf in ('시행규칙', '시행령'):
                if _nospace(nm).endswith(suf):
                    base = nm[:len(nm) - len(suf)].rstrip()
                    break
            for variant in (base, base + ' 시행령', base + ' 시행규칙'):
                canon = _canon_dots(_nospace(variant))
                known[canon] = canon
    return known


def _name_pattern(name: str) -> str:
    """공백 유무/위치가 달라도 매칭되도록 글자 사이에 선택적 공백을 허용하는 패턴."""
    chars = [_DOT_CLASS if c == 'ㆍ' else re.escape(c) for c in _nospace(_canon_dots(name))]
    return r'\s?'.join(chars)


_LAW_LINK_WITH_URL = re.compile(r'(' + _LINK_TEXT + r')\((https?://(?:www\.)?law\.go\.kr/[^)\s]*)\)')
_SUPPORTED_ARTICLE_PATH = re.compile(r'/제\d+조(?:의\d+)?')


def _fix_law_url(url: str) -> str:
    """AI가 직접 쓴 law.go.kr 법령 링크의 URL을 우리가 검증한 형태로만 남긴다.

    law.go.kr의 /법령/<법령명> 과 /법령/<법령명>/제N조(의M) 는 열리지만, AI는 종종
    존재하지 않는 하위 경로를 지어낸다 - 실사용 중 발견: ".../체육시설의설치·이용에관한법률시행령/별표2"
    같은 링크를 쓰는데 실제로 열면 "국가법령정보센터 | 오류페이지"가 뜬다. 지원되지 않는
    하위 경로(별표/서식 등)는 떼어내고 법령 본문 링크로 낮추며(링크가 오류 페이지로 가는 것보다
    법령 페이지로 가는 게 낫다), 법령명은 공백 제거 + 가운뎃점 공식 표기로 통일한다."""
    decoded = urllib.parse.unquote(url)
    m = re.match(r'(https?://(?:www\.)?law\.go\.kr/법령/)([^/?#]+)(/[^?#]*)?$', decoded)
    if not m:
        return url  # 행정규칙/자치법규/LSW 등 다른 형태는 건드리지 않는다
    base, name, rest = m.group(1), m.group(2), m.group(3) or ''
    if rest and not _SUPPORTED_ARTICLE_PATH.fullmatch(rest):
        rest = ''
    fixed = base + urllib.parse.quote(_canon_dots(_nospace(name)), safe='')
    if rest:
        fixed += '/' + urllib.parse.quote(rest[1:], safe='')
    return fixed


_ANY_LINK = re.compile(r'(' + _LINK_TEXT + r')\(([^)\n]*)\)')
_BROKEN_LAW_SCHEME = re.compile(r'^(?:https?[.:]+/*)?(?:www\.)?law\.go\.kr', re.I)


def _fix_link_target(label_md: str, target: str) -> str:
    """마크다운 링크 하나의 대상(괄호 안)이 URL로 쓸 수 없는 형태면 바로잡는다.

    1) 스킴이 깨진 법제처 주소("https.www.law.go.kr/...", "law.go.kr/...")는 https://www.law.go.kr 로 복구한다.
       (실사용 중 발견: AI가 가끔 "https."처럼 써서 링크가 상대경로로 열려 깨진다.)
    2) 대상이 URL이 아니라 문구인 경우("[관광진흥법 제16조](정확한 근거 조항 확인 필요)" - 검증 패스가 틀린
       조항의 URL을 지우며 남기는 형태)는 링크를 풀어 평문으로 돌린다. 그대로 두면 클릭 시 엉뚱한 상대경로로
       이동한다. 평문이 된 인용은 뒤이은 linkify/citation_check가 다시 링크를 달고 실제 조문과 대조한다."""
    t = target.strip()
    if _BROKEN_LAW_SCHEME.match(t):
        rest = re.sub(r'^(?:https?[.:]+/*)?(?:www\.)?law\.go\.kr', '', t, flags=re.I)
        return f"{label_md}(https://www.law.go.kr{rest})"
    if t.startswith(('http://', 'https://', '#', 'mailto:')):
        return f"{label_md}({target})"
    if t.startswith('/') and not re.search(r'[가-힣\s]', t):
        return f"{label_md}({target})"          # 정상적인 사이트 내 경로
    return f"{label_md[1:-1]} ({t})"            # URL이 아닌 대상 -> 평문


def _repair_ai_links(text: str) -> str:
    text = _ANY_LINK.sub(lambda m: _fix_link_target(m.group(1), m.group(2)), text)
    return _LAW_LINK_WITH_URL.sub(lambda m: f"{m.group(1)}({_fix_law_url(m.group(2))})", text)


def extract_law_names_from_context(context: str) -> list:
    """검색 컨텍스트('[법령 원문 발췌: 이름]')에서 이번에 가져온 법령명을 뽑는다."""
    return re.findall(r'\[법령 원문 발췌: ([^\]\n]+)\]', context or '')


def linkify_law_citations(text: str, extra_names=None) -> str:
    if not text:
        return text
    known = _known_names(extra_names)
    # 긴 이름부터 시도해야 "…시행규칙"이 "…법"에 먼저 먹히지 않는다.
    names = sorted(known, key=len, reverse=True)
    known_re = None
    if names:
        alt = "|".join(_name_pattern(n) for n in names)
        known_re = re.compile(r'[「『]?(' + alt + r')[」』]?(' + _ARTICLE + r'?)' + _SUBITEM)

    def process(seg: str) -> str:
        out = []
        for part in _SKIP.split(seg):
            if _SKIP.fullmatch(part):
                out.append(part)
                continue
            # 1) 「법령명」 표기를 먼저 링크로 만들되, 2단계(known)가 방금 만든 링크를
            #    다시 건드리지 않도록 자리표시자로 잠시 치환해 둔다.
            holders = []
            part = _PLAIN_BRACKET_CITATION.sub(r'\1', part)

            def repl_bracket(m):
                name, art = m.group(1), m.group(2) or ""
                holders.append(_link(m.group(0), known.get(_canon_dots(_nospace(name)), name), art))
                return _OPEN + str(len(holders) - 1) + _CLOSE
            part = _BRACKETED.sub(repl_bracket, part)

            # 2) 알려진 법령명(약칭 포함)
            if known_re is not None:
                def repl_known(m):
                    name, art = m.group(1), m.group(2) or ""
                    canon = known.get(_canon_dots(_nospace(name)), _canon_dots(_nospace(name)))
                    return _link(m.group(0), canon, art)
                part = known_re.sub(repl_known, part)

            part = re.sub(_OPEN + r"(\d+)" + _CLOSE, lambda m: holders[int(m.group(1))], part)
            out.append(part)
        return "".join(out)

    # 코드블록은 통째로 제외
    pieces = re.split(r'(```.*?```)', text, flags=re.S)
    return "".join(
        p if p.startswith('```') else process(_repair_ai_links(_CODE_LINK.sub(r'\1', _CODE_CITATION.sub(r'\1', p))))
        for p in pieces)
