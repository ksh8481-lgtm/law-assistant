"""
Gemini 호출 공용 래퍼 (신버전 SDK `google-genai` 기반).

[왜 만들었나]
- 구버전 `google.generativeai`는 종료 예정이다(로그에 "google.genai로 바꾸라"는 경고가 계속 뜬다). 앱이 구/신 SDK를
  섞어 쓰고 있어서 한곳으로 모은다. 모든 호출이 이 모듈을 거치면 SDK 교체나 모델 교체가 한 파일에서 끝난다.
- 모델 이름을 코드 곳곳에 흩어 두지 않고 여기서 고정한다. 예전에는 요청마다 `list_models()`로 목록을 받아 정렬해 쓰느라
  (1) 요청마다 네트워크 왕복이 생기고 (2) 구글이 모델 목록을 바꾸면 어떤 모델로 답했는지 알 수 없었다.
- 호출마다 모델·토큰·소요 시간을 한 줄로 남긴다(운영에서 어느 호출이 느리고 비싼지 보려는 용도).

[환경변수로 바꿀 수 있는 값]
  GEMINI_API_KEY            API 키
  GEMINI_MAIN_MODEL         본 답변 모델 (기본 gemini-2.5-pro)
  GEMINI_FAST_MODEL         키워드 추출·인용 판정 등 가벼운 호출 모델 (기본 gemini-2.5-flash)
  GEMINI_MAIN_FALLBACKS     본 답변 실패 시 순서대로 시도할 모델들(쉼표) (기본 "<MAIN>,<FAST>")
  CITATION_VERIFY_MODE      구글검색 인용 검증 패스: off(기본) | pro | flash  (아래 citation_verify_model 설명 참고)
"""
import os
import threading
import time

API_VERSION = os.environ.get("GEMINI_API_VERSION", "v1beta")   # JSON 모드·검색 그라운딩·사고 설정이 모두 되는 버전
_client = None
_client_lock = threading.Lock()


def main_model() -> str:
    return os.environ.get("GEMINI_MAIN_MODEL", "gemini-2.5-pro")


def fast_model() -> str:
    return os.environ.get("GEMINI_FAST_MODEL", "gemini-2.5-flash")


def main_fallbacks() -> list:
    raw = os.environ.get("GEMINI_MAIN_FALLBACKS", "")
    models = [m.strip().replace("models/", "") for m in raw.split(",") if m.strip()]
    return models or [main_model(), fast_model()]


def citation_verify_model():
    """구글검색 인용 검증 패스에 쓸 모델명. 'off'면 None(패스를 건너뜀). 기본은 off.

    기본을 off로 둔 근거(같은 초안에 틀린 인용을 심어 3회씩 측정, 질의응답 경로 기준):
      - pro   : 약 44초, 심은 오류 3/3 포착, 손상 없음.
      - flash : 32~46초(사고 때문에 pro와 비슷), 3회 중 1회 링크 8개 -> 2개로 손상.
      - flash(사고 끔): 10~14초지만 심은 오류 0/3 포착, 3회 중 2회 링크 대부분 유실 -> 검증 구실을 못 한다.
      - 서버 검증(citation_check)은 법 조문 번호 오류, 없는 조, 엉뚱한 조, 비율 오류 4유형을 각 3/3 표시한다.
        이 검증은 고치지 않고 경고만 붙이므로 틀린 인용이 조용히 바뀌지 않는다.
    다만 off는 서버가 링크로 인식하지 못하는 인용(링크 없는 KDS/KCS 코드 등)의 사실 확인을 하지 않는다.
    필요하면 CITATION_VERIFY_MODE=pro로 되돌린다."""
    mode = os.environ.get("CITATION_VERIFY_MODE", "off").strip().lower()
    if mode == "off":
        return None
    return main_model() if mode == "pro" else fast_model()


def get_client():
    """공용 클라이언트(스레드 안전). 락 없이 `if None: 만들기`만 하면 첫 호출이 겹칠 때 스레드마다 클라이언트를 만들고,
    나중에 만든 쪽이 전역을 덮어쓰며 먼저 만든 클라이언트가 정리(close)돼 그걸 쓰던 스레드가 "client has been closed"로
    실패한다(실측: 동시 8개 호출 중 2개 실패)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from google import genai
                from google.genai import types
                # API 버전을 직접 정한다. SDK는 버전이 오르면 기본값이 바뀔 수 있고(requirements가 고정되지 않아 재배포 때 최신이 설치된다),
                # v1에서는 JSON 모드(response_mime_type)가 거부된다("JSON mode is not enabled for api version v1" 400):
                # 2026-11-10 재배포 직후 법정 의무 마스터·PQ 서류 추출·법규 검토 인용 판정이 모두 실패했다.
                _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""),
                                       http_options=types.HttpOptions(api_version=API_VERSION))
                print(f"[gemini] google-genai {getattr(genai, '__version__', '?')}, API 버전 {API_VERSION}")
    return _client


# ---------------------------------------------------------------- 오류를 사용자가 알아볼 수 있는 말로
class GeminiError(Exception):
    """Gemini 호출 실패. str(e)는 사용자에게 그대로 보여 줘도 되는 문장이다(원인과 해야 할 일 + 짧은 오류 코드).
    kind: 'credits'(선불 크레딧 소진) | 'rate'(호출 한도·몰림) | 'key'(인증·권한) | 'overloaded'(서버 일시 장애) | 'bad_request'(입력 문제) | 'other'"""

    def __init__(self, kind, user_message, cause=""):
        super().__init__(user_message)
        self.kind = kind
        self.user_message = user_message
        self.cause = cause


# 같은 키로 부르는 다른 모델도 똑같이 실패하는 종류라 모델을 바꿔 다시 시도하지 않는다(시간만 낭비한다).
FAIL_FAST_KINDS = ("credits", "key")


def classify_error(e):
    """예외 -> (종류, 사용자용 문장). 문장에는 원인, 해야 할 일, 짧은 오류 코드를 넣는다."""
    code = getattr(e, "code", None)
    raw = str(e)
    low = raw.lower()
    status = str(getattr(e, "status", "") or "")
    tag = (f"오류 코드 {code}" if code else "") + (f" {status}" if status else "")
    tag = f" ({tag.strip()})" if tag.strip() else ""
    if "prepayment credits" in low or "credits are depleted" in low or "billing" in low and "depleted" in low:
        return "credits", ("AI 사용 크레딧(선불 잔액)이 모두 소진되어 AI 기능을 쓸 수 없습니다. 관리자가 Google AI Studio(https://ai.studio/projects)의 "
                           "결제 화면에서 크레딧을 충전하면 바로 다시 쓸 수 있습니다." + tag)
    if code in (401, 403) or "api key" in low or "permission_denied" in low or "unauthenticated" in low:
        return "key", ("AI 인증(API 키 또는 권한)에 문제가 있어 AI 기능을 쓸 수 없습니다. 관리자가 키와 결제 상태를 확인해야 합니다." + tag)
    if code == 429 or "quota" in low or "rate limit" in low or "resource_exhausted" in low or "resource exhausted" in low:
        return "rate", ("AI 호출이 한꺼번에 몰렸거나 사용 한도에 걸렸습니다. 1~2분 뒤 다시 시도해 주세요. 계속되면 관리자에게 알려 주세요." + tag)
    if code in (500, 502, 503, 504) or "unavailable" in low or "overloaded" in low or "deadline" in low or "timed out" in low or "timeout" in low:
        return "overloaded", ("AI 서버가 일시적으로 바쁘거나 응답이 늦습니다. 잠시 뒤 다시 시도해 주세요." + tag)
    if code == 400 or "invalid_argument" in low:
        return "bad_request", ("AI가 요청을 처리하지 못했습니다(입력 내용이나 형식 문제). 입력을 줄이거나 다른 파일로 다시 시도해 주세요." + tag)
    return "other", (f"AI 호출 중 오류가 났습니다: {raw[:150]}")


def as_gemini_error(e):
    """이미 GeminiError면 그대로, 아니면 분류해서 GeminiError 로 바꾼다."""
    if isinstance(e, GeminiError):
        return e
    kind, msg = classify_error(e)
    return GeminiError(kind, msg, cause=str(e)[:300])


def _log(label, model, seconds, resp):
    um = getattr(resp, "usage_metadata", None)
    print(f"[gemini] {label or '-'} model={model} {seconds:.1f}s "
          f"in={getattr(um, 'prompt_token_count', None)} out={getattr(um, 'candidates_token_count', None)} "
          f"think={getattr(um, 'thoughts_token_count', None)}")


def _part(p):
    """구 SDK 시절 형식의 조각을 신 SDK 형식으로 바꾼다. 문자열 -> {"text"}, 파일 객체(uri/mime_type) -> {"file_data"}."""
    if isinstance(p, str):
        return {"text": p}
    if isinstance(p, dict):
        return p
    uri, mime = getattr(p, "uri", None), getattr(p, "mime_type", None)
    if uri:
        return {"file_data": {"file_uri": uri, "mime_type": mime}}
    return p


def normalize_contents(contents):
    """구 SDK 형식의 contents를 신 SDK가 받는 형식으로 바꾼다(신 형식은 그대로 둔다).

    - 채팅 기록 {"role": "user"|"model", "parts": ["문자열", 파일객체, ...]} 의 parts 안 문자열/파일 객체를 변환한다.
      신 SDK는 parts 안의 맨 문자열을 받지 않는다.
    - 최상위 리스트의 문자열·파일 조각 dict는 신 SDK가 그대로 받으므로 건드리지 않는다.
    - 최상위 리스트에 파일 객체(uri/mime_type 속성)가 직접 들어 있으면 file_data로 바꾼다."""
    if isinstance(contents, list):
        out = []
        for c in contents:
            if isinstance(c, dict) and "parts" in c:
                out.append({**c, "parts": [_part(p) for p in c["parts"]]})
            elif isinstance(c, (str, dict)):
                out.append(c)
            else:
                out.append(_part(c))
        return out
    return contents


def get_file(name):
    """업로드해 둔 파일을 이름("files/...")으로 다시 가져온다(구 SDK의 genai.get_file 대체)."""
    return get_client().files.get(name=name)


def generate(contents, model=None, temperature=None, json_mode=False, search=False, label="", thinking_budget=None):
    """한 번 호출해서 응답 객체(.text, .usage_metadata)를 돌려준다.

    contents: 문자열, 또는 [문자열, 파일 조각, ...]. 파일 조각은 `gemini_file_part()`가 만든 dict도 된다.
    json_mode: 응답을 JSON으로 강제한다. search: 구글 검색 그라운딩을 붙인다.
    thinking_budget: 사고(thinking) 토큰 상한. 0이면 끈다(flash만 가능, pro는 항상 사고하므로 0은 무시). 양수는 pro에도 적용.
      실측(2.5-flash): 키워드 추출처럼 단순한 호출도 사고에 1,000~2,000토큰을 써서 7~12초가 걸렸다."""
    from google.genai import types
    model = (model or fast_model()).replace("models/", "")
    kwargs = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    if search:
        kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        # 검색 도구만 쓰는 호출이라 함수 자동호출(AFC)은 필요 없고, 켜 두면 불필요한 경고 로그가 남는다.
        kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
    # pro는 사고를 끌 수 없으므로(0 불가) 0만 무시하고, 양수 예산은 pro에도 적용한다(사고량 상한).
    if thinking_budget is not None and not (thinking_budget == 0 and "pro" in model):
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
    config = types.GenerateContentConfig(**kwargs) if kwargs else None
    t = time.time()
    try:
        resp = get_client().models.generate_content(model=model, contents=normalize_contents(contents), config=config)
    except Exception as e:
        ge = as_gemini_error(e)
        print(f"[gemini] {label or '-'} model={model} 실패 kind={ge.kind} {ge.cause[:160]}")
        raise ge from e
    _log(label, model, time.time() - t, resp)
    return resp


def generate_with_fallback(contents, models=None, temperature=None, label="", **kwargs):
    """models를 순서대로 시도해 처음 성공한 (응답, 사용한 모델)을 돌려준다. 전부 실패하면 마지막 예외를 올린다."""
    last = None
    for m in (models or main_fallbacks()):
        try:
            return generate(contents, model=m, temperature=temperature, label=label, **kwargs), m
        except Exception as e:
            last = as_gemini_error(e)
            print(f"[gemini] {label or '-'} model={m} 실패: kind={last.kind} {last.cause[:200]}")
            if last.kind in FAIL_FAST_KINDS:
                break                                         # 크레딧 소진·인증 오류는 모델을 바꿔도 똑같이 실패한다
    raise last if last else RuntimeError("시도할 모델이 없습니다")
