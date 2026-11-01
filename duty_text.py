"""
'법정 의무 마스터' 페이지(duty_list)가 쓰는 법령 본문 처리.

[왜 따로 뺐나]
예전에는 app.py 안에서 본문을 "항 내용 전부 -> 호 내용 전부" 순서로 이어 붙이고(목은 빠짐), 글자 수 1,500자로 기계적으로 잘랐다.
그러면 (1) 호가 엉뚱한 항 뒤에 붙고 목 내용이 사라지며, (2) 조문 중간에서 끊겨 모델이 조 번호를 못 찾아 추측하거나
"조 번호 확인 필요"라고 쓰고(법제처 링크도 깨진다), (3) 항·호 텍스트가 비어 있으면 조각 하나가 통째로 오류가 났다.

[방식]
- 조문단위를 문서 순서 그대로(조문 -> 항 -> 호 -> 목) 읽어 조 번호가 붙은 조문 목록으로 만든다.
- 조각은 조문 경계에서만 자른다. 한 조문이 너무 길면 줄 단위로 나누되 조각 머리에 어느 조인지 적는다.
- 모델이 돌려준 조 번호는 그 조각에 실제로 있는 조인지 서버가 대조해서 `article_verified`로 표시한다.
- 큰 법령은 채팅 질문과 관련된 조문 위주로 골라 담는다(앞 3만 자만 자르면 뒷부분 조문을 아예 못 본다).
"""
import re
import threading
from collections import OrderedDict

import requests
import xml.etree.ElementTree as ET

CHUNK_SIZE = 1800            # 조각 하나의 목표 글자 수. 조문 하나가 이보다 길면 줄 단위로 나눈다.
_TEXT_TAGS = ('조문내용', '항내용', '호내용', '목내용')

_CACHE = OrderedDict()       # 법령일련번호 -> 파싱 결과. 서버를 다시 띄우면 사라진다.
_LOCK = threading.Lock()
_MAX_ENTRIES = 16


def _norm_space(s):
    return (s or "").replace("\r", "").strip()


def article_label(no, branch=None):
    """조문번호 '10', 가지번호 '2' -> '제10조의2'"""
    no = (no or "").strip()
    if not no:
        return ""
    branch = (branch or "").strip()
    return f"제{no}조" + (f"의{branch}" if branch else "")


def article_text(art):
    """조문단위 하나를 조문 -> 항 -> 호 -> 목 문서 순서 그대로 줄바꿈으로 이어 붙인다. 비어 있는 항목은 건너뛴다."""
    lines = []
    for el in art.iter():
        if el.tag in _TEXT_TAGS:
            t = _norm_space(el.text)
            if t:
                lines.append(t)
    return "\n".join(lines)


def parse_law(xml_text):
    """법제처 lawService XML -> {"name","enforce_date","articles":[{"label","title","text"}]}.
    장·절 제목(조문여부가 '전문')은 조문이 아니므로 뺀다."""
    root = ET.fromstring(xml_text)
    info = root.find('기본정보')
    arts = []
    for art in root.findall('.//조문단위'):
        if _norm_space(art.findtext('조문여부')) != '조문':
            continue
        label = article_label(art.findtext('조문번호'), art.findtext('조문가지번호'))
        text = article_text(art)
        if not label or not text:
            continue
        arts.append({"label": label, "title": _norm_space(art.findtext('조문제목')), "text": text})
    return {
        "name": _norm_space(info.findtext('법령명_한글')) if info is not None else "",
        "enforce_date": _norm_space(info.findtext('시행일자')) if info is not None else "",
        "articles": arts,
    }


def fetch_law(lsi_seq, law_key, timeout=10):
    """법령 하나를 가져와 파싱하고(최근 16개 캐시) 돌려준다. 법제처 응답이 XML이 아니거나 조문이 없으면 ValueError."""
    with _LOCK:
        hit = _CACHE.get(lsi_seq)
        if hit is not None:
            _CACHE.move_to_end(lsi_seq)
            return hit
    res = requests.get(
        f"https://www.law.go.kr/DRF/lawService.do?OC={law_key}&target=law&type=XML&MST={lsi_seq}", timeout=timeout)
    try:
        law = parse_law(res.text)
    except ET.ParseError as e:
        raise ValueError(f"법제처 응답을 읽지 못했습니다: {e}")
    if not law["articles"]:
        raise ValueError("법제처에서 조문을 찾지 못했습니다.")
    law["chunks"] = chunk_articles(law["articles"])
    with _LOCK:
        _CACHE[lsi_seq] = law
        _CACHE.move_to_end(lsi_seq)
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.popitem(last=False)
    return law


def chunk_articles(articles, size=CHUNK_SIZE):
    """조문 경계에서만 잘라 [{"text","labels"}]로 묶는다. 한 조문이 size보다 길면 줄 단위로 나누고 조각마다 조 번호를 붙인다."""
    chunks, cur_text, cur_labels = [], [], []
    cur_len = 0

    def flush():
        nonlocal cur_text, cur_labels, cur_len
        if cur_text:
            chunks.append({"text": "\n\n".join(cur_text), "labels": cur_labels})
        cur_text, cur_labels, cur_len = [], [], 0

    for art in articles:
        pieces = [art["text"]]
        if len(art["text"]) > size:
            pieces, buf = [], ""
            for line in art["text"].split("\n"):
                if buf and len(buf) + len(line) + 1 > size:
                    pieces.append(buf)
                    buf = ""
                buf = f"{buf}\n{line}" if buf else line
            if buf:
                pieces.append(buf)
        for i, piece in enumerate(pieces):
            block = piece if i == 0 else f"〔{art['label']} 계속〕\n{piece}"
            if cur_len and cur_len + len(block) > size:
                flush()
            cur_text.append(block)
            if art["label"] not in cur_labels:
                cur_labels.append(art["label"])
            cur_len += len(block) + 2
    flush()
    return chunks


_ART_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")


def normalize_article(s):
    """'제5조제3항'·'제 5 조 의2' -> 기본 조 번호('제5조', '제5조의2'). 조 번호가 없으면 None."""
    m = _ART_RE.search(s or "")
    if not m:
        return None
    return f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")


def verify_duties(duties, labels):
    """모델이 돌려준 의무 목록의 조 번호를 그 조각에 실제로 있던 조(labels)와 대조한다.
    - 조각에 있는 조이면 `article_verified`=True
    - 번호가 없거나 자리표시자인데 조각에 조가 하나뿐이면 그 조로 채운다(True)
    - 그 밖에는 False(화면에서 링크를 달지 않고 경고 표시)
    같은 조·같은 제목의 중복도 여기서 걸러낸다. 목록이 아닌 값이나 딕셔너리가 아닌 항목은 버린다."""
    if not isinstance(duties, list):
        return []
    known = set(labels or [])
    only = labels[0] if labels and len(set(labels)) == 1 else None
    out, seen = [], set()
    for d in duties:
        if not isinstance(d, dict):
            continue
        d = dict(d)
        base = normalize_article(str(d.get("article", "")))
        if base and base in known:
            d["article_verified"] = True
        elif not base and only:
            d["article"] = only
            d["article_verified"] = True
        else:
            d["article_verified"] = False
        key = (normalize_article(str(d.get("article", ""))) or str(d.get("article", "")),
               re.sub(r"\s+", "", str(d.get("duty_title", ""))))
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def select_for_question(articles, question, limit=30000):
    """채팅용 본문. 전체가 limit 안이면 전부, 아니면 질문 낱말이 많이 나온 조문부터 limit까지 골라 법령 순서대로 돌려준다.
    (text, 발췌여부)"""
    full = "\n\n".join(a["text"] for a in articles)
    if len(full) <= limit:
        return full, False
    try:
        from qa_grounding import _terms
        terms = _terms(question or "", 14)
    except Exception:
        terms = []

    def score(a):
        return sum(a["text"].count(t) + 3 * a["title"].count(t) for t in terms)

    ranked = sorted(range(len(articles)), key=lambda i: (-score(articles[i]), i))
    picked, used = set(), 0
    for i in ranked:
        n = len(articles[i]["text"]) + 2
        if used + n > limit:
            continue
        picked.add(i)
        used += n
    return "\n\n".join(articles[i]["text"] for i in sorted(picked)), True
