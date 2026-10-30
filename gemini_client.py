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
                _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    return _client


def _log(label, model, seconds, resp):
    um = getattr(resp, "usage_metadata", None)
    print(f"[gemini] {label or '-'} model={model} {seconds:.1f}s "
          f"in={getattr(um, 'prompt_token_count', None)} out={getattr(um, 'candidates_token_count', None)} "
          f"think={getattr(um, 'thoughts_token_count', None)}")


def generate(contents, model=None, temperature=None, json_mode=False, search=False, label="", thinking_budget=None):
    """한 번 호출해서 응답 객체(.text, .usage_metadata)를 돌려준다.

    contents: 문자열, 또는 [문자열, 파일 조각, ...]. 파일 조각은 `gemini_file_part()`가 만든 dict도 된다.
    json_mode: 응답을 JSON으로 강제한다. search: 구글 검색 그라운딩을 붙인다.
    thinking_budget: 0이면 사고(thinking)를 끈다. flash 계열만 가능하고 pro는 항상 사고하므로 무시한다.
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
    if thinking_budget is not None and "pro" not in model:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
    config = types.GenerateContentConfig(**kwargs) if kwargs else None
    t = time.time()
    resp = get_client().models.generate_content(model=model, contents=contents, config=config)
    _log(label, model, time.time() - t, resp)
    return resp


def generate_with_fallback(contents, models=None, temperature=None, label="", **kwargs):
    """models를 순서대로 시도해 처음 성공한 (응답, 사용한 모델)을 돌려준다. 전부 실패하면 마지막 예외를 올린다."""
    last = None
    for m in (models or main_fallbacks()):
        try:
            return generate(contents, model=m, temperature=temperature, label=label, **kwargs), m
        except Exception as e:
            last = e
            print(f"[gemini] {label or '-'} model={m} 실패: {type(e).__name__}: {str(e)[:200]}")
    raise last if last else RuntimeError("시도할 모델이 없습니다")
