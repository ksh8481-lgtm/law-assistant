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

# 이미 링크/URL/코드인 구간은 건너뛴다.
_SKIP = re.compile(r'(\[[^\]\n]*\]\([^)\n]*\)|https?://\S+|`[^`\n]*`)')

# 「법령명」 형태(이름 자체가 인식 안 되는 법령도 링크)
_BRACKETED = re.compile(r'[「『]([^」』\n]{2,60}?(?:법|법률|령|규칙))[」』](' + _ARTICLE + r'?)')


def _nospace(s: str) -> str:
    return re.sub(r'\s+', '', s)


def _link(label: str, name: str, article: str = "") -> str:
    url = LAW_URL + urllib.parse.quote(_nospace(name), safe='')
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
            known[_nospace(nm)] = _nospace(nm)
        _KNOWN_CACHE = known
    known = dict(_KNOWN_CACHE)
    for nm in (extra or []):
        if nm:
            known[_nospace(nm)] = _nospace(nm)
    return known


def _name_pattern(name: str) -> str:
    """공백 유무/위치가 달라도 매칭되도록 글자 사이에 선택적 공백을 허용하는 패턴."""
    chars = [re.escape(c) for c in _nospace(name)]
    return r'\s?'.join(chars)


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
        known_re = re.compile(r'[「『]?(' + alt + r')[」』]?(' + _ARTICLE + r'?)')

    def process(seg: str) -> str:
        out = []
        for part in _SKIP.split(seg):
            if _SKIP.fullmatch(part):
                out.append(part)
                continue
            # 1) 「법령명」 표기를 먼저 링크로 만들되, 2단계(known)가 방금 만든 링크를
            #    다시 건드리지 않도록 자리표시자로 잠시 치환해 둔다.
            holders = []

            def repl_bracket(m):
                name, art = m.group(1), m.group(2) or ""
                holders.append(_link(m.group(0), known.get(_nospace(name), name), art))
                return _OPEN + str(len(holders) - 1) + _CLOSE
            part = _BRACKETED.sub(repl_bracket, part)

            # 2) 알려진 법령명(약칭 포함)
            if known_re is not None:
                def repl_known(m):
                    name, art = m.group(1), m.group(2) or ""
                    canon = known.get(_nospace(name), _nospace(name))
                    return _link(m.group(0), canon, art)
                part = known_re.sub(repl_known, part)

            part = re.sub(_OPEN + r"(\d+)" + _CLOSE, lambda m: holders[int(m.group(1))], part)
            out.append(part)
        return "".join(out)

    # 코드블록은 통째로 제외
    pieces = re.split(r'(```.*?```)', text, flags=re.S)
    return "".join(p if p.startswith('```') else process(p) for p in pieces)
