"""
후속 질의 채팅(`/api/chat/other_review`)에 넣을 법제처 원문 근거를 만든다.

[왜 필요한가]
첫 질의응답은 법제처에서 가져온 법령·고시 원문(조문과 별표)을 근거로 답한다. 그런데 후속 질문은 처음 질문 텍스트와
대화 기록만 받고 원문은 다시 가져오지 않아, 모델이 기억으로 답하며 원문에 없는 표현을 덧붙였다(운영 확인: 기술지원기술인
비율을 "10~20% 범위에서 발주청과 협의하여 결정"이라고 답함 - 범위는 맞지만 "협의하여 결정"은 고시 원문에 없다).

[방식]
- 첫 질의응답 때 어떤 법령·고시를 가져왔는지 이름만 기억해 둔다(`remember`). 프론트엔드가 `initial_context`를 그대로 되돌려
  주므로, 그 문자열의 해시를 키로 쓰면 프론트엔드를 고치지 않아도 연결된다. 원문 전체가 아니라 이름만 저장해 메모리가 작다.
- 후속 질문이 오면 그 이름들로 **새 질문의 낱말에 맞춰** 조문·별표를 다시 골라 담는다(`build_grounding`). 본문은 법제처
  호출 결과가 캐시돼 있어 대부분 빠르다.
- 서버를 다시 띄워서 기억이 사라졌거나 다른 경로로 들어온 대화는 LLM 없이 낱말 힌트만으로 고시를 고른다. 이 엔드포인트는
  gunicorn 기본 제한(30초) 안에 끝나야 하므로 후속 채팅에서는 LLM 추출 호출을 하지 않는다.
- 어떤 단계가 실패하거나 시간이 걸려도 채팅 자체는 막지 않고, 근거 없이 예전처럼 답한다.
"""
import hashlib
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

_CACHE = OrderedDict()          # 질의 해시 -> {"admruls": [이름...], "laws": [기본 법령명...]}
_LOCK = threading.Lock()
_MAX_ENTRIES = 128
GROUNDING_TIMEOUT_SEC = 12      # 근거 조회에 쓸 최대 시간(초). 넘으면 근거 없이 답한다.

GROUNDING_INSTRUCTION = (
    "[법제처 원문 - 이번 후속 질문과 관련해 서버가 법제처에서 직접 가져온 조문·별표 발췌]\n"
    "아래 원문에 있는 법령·고시의 조·항·별표·목 번호와 수치, 표현은 이미 확인된 것입니다. 답변의 법적 근거와 수치는 이 원문과\n"
    "앞선 대화에만 근거해서 쓰고, 원문에 없는 절차나 표현(예: 원문에 없는 '협의', '승인' 요건)을 덧붙이지 마세요. 고시를 인용할\n"
    "때는 조·별표·목 번호를 특정하고, 원문에 없는 내용은 '원문 확인 필요'라고 답하세요.\n"
    "원문이 질문의 경우(경계값, 예외, 공백 등)를 명시적으로 다루지 않으면 '해당 없음'이나 '의무 없음'으로 단정하지 말고, '원문이 이 경우를\n"
    "명시하지 않아 확인이 필요하다'고 답한 뒤 발주청 내부 검토나 소관 부처 질의를 권하세요. (예: 구간이 '60%초과'와 '60%미만'으로만\n"
    "나뉘어 있으면 정확히 60%는 원문이 다루지 않는 경우입니다.)\n\n")


# 후속 질문 요청의 첫 턴은 최초 질문이다. 아무 표시가 없으면 모델이 그것도 새 질문으로 보고 다시 답해서 답변이 길어지고 후속 질문이
# 묻힌다(운영 확인; 측정: 표시 전 6개 중 3개가 최초 질문을 재답변, 평균 858자 -> 표시 후 0개, 평균 488자).
PRIOR_QUESTION_NOTE = "[이미 답변이 끝난 최초 질문입니다. 맥락 참고용이며 다시 답하지 말고, 마지막의 후속 질문에만 답하세요.]\n"


def context_key(initial_context: str) -> str:
    return hashlib.sha1((initial_context or "").encode("utf-8", "ignore")).hexdigest()


def _base_law_names(names) -> list:
    """'건설기술 진흥법 시행령' 같은 계열 이름을 기본 법령명으로 줄이고 중복을 없앤다."""
    out, seen = [], set()
    for n in names:
        base = re.sub(r"\s*(시행규칙|시행령)\s*$", "", n or "").strip()
        key = re.sub(r"\s+", "", base)
        if base and key not in seen:
            seen.add(key)
            out.append(base)
    return out


def remember(initial_context: str, mcp_context: str) -> None:
    """첫 질의응답에서 가져온 법령·고시 이름을 후속 질문용으로 기억한다. 실패해도 조용히 무시한다."""
    try:
        import law_linkify
        entry = {
            "admruls": [i["name"] for i in law_linkify.extract_admrul_info_from_context(mcp_context)],
            "laws": _base_law_names(law_linkify.extract_law_names_from_context(mcp_context)),
        }
        with _LOCK:
            _CACHE[context_key(initial_context)] = entry
            _CACHE.move_to_end(context_key(initial_context))
            while len(_CACHE) > _MAX_ENTRIES:
                _CACHE.popitem(last=False)
    except Exception as e:
        print(f"[qa_grounding] 기억 실패(무시): {type(e).__name__}: {e}")


def recall(initial_context: str):
    with _LOCK:
        entry = _CACHE.get(context_key(initial_context))
        if entry:
            _CACHE.move_to_end(context_key(initial_context))
        return dict(entry) if entry else None


# 후속 질문은 첫 질의응답과 달리 LLM이 키워드를 뽑아 주지 않으므로(30초 제한 때문에 LLM 호출을 하지 않는다) 질문 속 낱말을
# 직접 뽑는다. 한국어는 조사·어미가 낱말에 붙어서 쓰이는데("토목공사에서", "공종이", "단순한지"), 그대로 쓰면 원문에 있는
# "토목공사", "공종", "단순한 공종"과 글자가 맞지 않아 관련 조문·별표 조각이 후보에서 빠진다(운영 재현: 별표 2 사목의 공종
# 구분표를 못 찾고 "원문에서 확인할 수 없다"고 답함). 그래서 흔한 조사·어미를 떼고, 개수 상한도 넉넉히 둔다.
_JOSA = sorted([
    "에서는", "에서", "으로", "에게", "까지", "부터", "이나", "이란", "인지", "한지", "해서", "하고", "하지", "할때", "해야",
    "에는", "에도", "과의", "와의", "이", "가", "은", "는", "을", "를", "의", "에", "로", "와", "과", "도", "만",
], key=len, reverse=True)
_STOP = {"어떻게", "어디", "무엇", "해당해", "구분해", "알려줘", "알려", "있나", "되나", "하나", "경우", "질문", "대한", "대해",
         "관련", "때문", "정말", "혹시", "그럼", "그러면", "정확히", "얼마", "몇퍼센트", "해줘", "해주세요"}


def _terms(text: str, limit: int = 14) -> list:
    out = []
    for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", text or ""):
        for _ in range(2):                      # "복잡한지는" -> "복잡한지" -> "복잡"처럼 조사·어미가 겹쳐 붙은 경우까지
            for suf in _JOSA:
                if tok.endswith(suf) and len(tok) - len(suf) >= 2:
                    tok = tok[:-len(suf)]
                    break
        if len(tok) >= 2 and tok not in _STOP and tok not in out:
            out.append(tok)
        if len(out) >= limit:
            break
    return out


def _keywords(initial_context: str, new_message: str) -> list:
    """후속 질문의 낱말을 앞에, 처음 질문의 낱말을 뒤에 둔다(처음 질문은 첨부 문서 본문이 섞여 있을 수 있어 앞부분만)."""
    seen, out = set(), []
    for t in _terms(new_message, 14) + _terms((initial_context or "")[:300], 6):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_grounding(initial_context: str, new_message: str) -> dict:
    """{"text": 근거 원문(없으면 ""), "adm_infos": 고시 정보 목록}. 어떤 경우에도 예외를 올리지 않는다."""
    empty = {"text": "", "adm_infos": []}
    try:
        from mcp_agent_sync import _hinted_admruls
        from moleg_mcp import search_admrul_with_text, search_laws_with_text
        import law_linkify

        entry = recall(initial_context) or {"admruls": [], "laws": []}
        # 처음 질문 때 가져온 고시 + 이번 질문/처음 질문의 낱말 힌트로 고른 고시(중복 제거, 순서 유지)
        adm_names, seen = [], set()
        for n in entry["admruls"] + _hinted_admruls(new_message) + _hinted_admruls((initial_context or "")[:600]):
            k = re.sub(r"\s+", "", n)
            if k not in seen:
                seen.add(k)
                adm_names.append(n)
        law_names = entry["laws"][:3]
        if not adm_names and not law_names:
            return empty

        keywords = _keywords(initial_context, new_message)
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            f_adm = pool.submit(search_admrul_with_text, adm_names[:3], keywords, 6000, 12000) if adm_names else None
            f_law = pool.submit(search_laws_with_text, law_names, keywords, 3500, 2, 9000) if law_names else None
            adm_text, law_text = "", ""
            for fut, label in ((f_adm, "고시"), (f_law, "법령")):
                if fut is None:
                    continue
                try:
                    res = fut.result(timeout=GROUNDING_TIMEOUT_SEC)
                    if label == "고시":
                        adm_text = res
                    else:
                        law_text = res
                except FutureTimeout:
                    print(f"[qa_grounding] {label} 원문 조회가 {GROUNDING_TIMEOUT_SEC}초를 넘어 건너뜁니다")
                except Exception as e:
                    print(f"[qa_grounding] {label} 원문 조회 실패(무시): {type(e).__name__}: {e}")
        finally:
            pool.shutdown(wait=False)

        text = "\n\n".join(t for t in (adm_text, law_text) if t)
        if not text:
            return empty
        return {"text": text, "adm_infos": law_linkify.extract_admrul_info_from_context(adm_text)}
    except Exception as e:
        print(f"[qa_grounding] 근거 생성 실패(무시): {type(e).__name__}: {e}")
        return empty
