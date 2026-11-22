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
  GEMINI_MAIN_MODEL         본 답변 모델 (기본 gemini-3.8-flash)
  GEMINI_FAST_MODEL         인용 판정·서류 정리·도면 읽기 등 가벼운 호출 모델 (기본 gemini-3.8-flash)
  GEMINI_LIGHT_MODEL        키워드·법령명 추출 같은 아주 짧은 호출 모델 (기본 gemini-3.5-flash-lite)
  GEMINI_MAIN_FALLBACKS     본 답변 실패 시 순서대로 시도할 모델들(쉼표) (기본 "<MAIN>,<FAST>,gemini-3.6-flash"에서 중복 제거)

[모델 교체 이력 - 2026-11-22]
  구글이 gemini-2.5-pro / gemini-2.5-flash 를 폐기해 2026-12-01부터 요청이 각각 gemini-3.8-flash / gemini-3.5-flash-lite 로 자동 연결되고
  API 규칙도 바뀐다(thinking_budget -> thinking_level, temperature 등 샘플링 설정 제거). 같은 질문(관광단지 면적 변경 + 재해영향평가)을 모델 조합별로 돌린 측정은
  docs/작업기록/2026-11-22_gemini-모델-교체.md 참고. 새 모델 규칙은 아래 thinking_config_for 와 generate 의 재시도에서 흡수한다.
  CITATION_VERIFY_MODE      구글검색 인용 검증 패스: off(기본) | pro | flash  (아래 citation_verify_model 설명 참고)
"""
import os
import re
import threading
import time

API_VERSION = os.environ.get("GEMINI_API_VERSION", "v1beta")   # JSON 모드·검색 그라운딩·사고 설정이 모두 되는 버전
_client = None
_client_lock = threading.Lock()


def main_model() -> str:
    return os.environ.get("GEMINI_MAIN_MODEL", "gemini-3.8-flash")


def fast_model() -> str:
    return os.environ.get("GEMINI_FAST_MODEL", "gemini-3.8-flash")


def light_model() -> str:
    """키워드·법령명·고시명 추출 같은 입력이 짧은 호출용(가장 싸고 빠르다: 호출당 1~3초). 정확도가 필요한 판정·서류 정리·도면 읽기에는 쓰지 않는다."""
    return os.environ.get("GEMINI_LIGHT_MODEL", "gemini-3.5-flash-lite")


RESERVE_MODEL = "gemini-3.6-flash"          # 주 모델이 막혔을 때의 마지막 예비(이전 세대 Flash, 공식 문서에서 계속 지원 중)


def main_fallbacks() -> list:
    raw = os.environ.get("GEMINI_MAIN_FALLBACKS", "")
    models = [m.strip().replace("models/", "") for m in raw.split(",") if m.strip()]
    if models:
        return models
    return list(dict.fromkeys([main_model(), fast_model(), RESERVE_MODEL]))     # 같은 모델이 겹치면 한 번만


def model_generation(model: str) -> int:
    """'gemini-3.8-flash' -> 3, 'gemini-2.5-pro' -> 2, 알 수 없으면 0."""
    m = re.match(r"gemini-(\d+)", (model or "").replace("models/", ""))
    return int(m.group(1)) if m else 0


def thinking_config_for(model, thinking_budget=None, thinking_level=None):
    """모델 세대에 맞는 사고(thinking) 설정을 만든다. 없으면 None(모델 기본값).

    Gemini 3 이상은 토큰 예산(thinking_budget) 대신 단계(thinking_level: minimal/low/medium/high)를 받는다. 실측(2026-11-22, 짧은 질문):
      gemini-3.8-flash     : 기본(medium) 사고 700~900토큰 9~10초 / low 는 사고 없음 3초 / minimal 은 400 오류("not supported")
      gemini-3.5-flash-lite: 모든 단계 허용, 기본은 사고 없음 1.3초 / medium 약 600토큰 3초 / thinking_budget=0 은 400 오류
    그래서 예산이 오면 단계로 바꾼다: 0 -> (lite: minimal, 그 밖: low), 1024 이하 -> low, 8192 이하 -> medium, 그 위 -> high.
    thinking_level 을 직접 주면 그것이 우선한다. Gemini 2.x 는 예전처럼 예산을 쓴다(pro 는 사고를 끌 수 없어 0 은 무시)."""
    from google.genai import types
    model = (model or "").replace("models/", "")
    if model_generation(model) >= 3:
        level = (thinking_level or "").lower() or None
        if level is None and thinking_budget is not None:
            if thinking_budget <= 0:
                level = "minimal" if "lite" in model else "low"
            elif thinking_budget <= 1024:
                level = "low"
            elif thinking_budget <= 8192:
                level = "medium"
            else:
                level = "high"
        if level is None:
            return None
        if level == "minimal" and "lite" not in model:
            level = "low"                                              # minimal 은 lite 에서만 된다
        return types.ThinkingConfig(thinking_level=level.upper())
    if thinking_budget is not None and not (thinking_budget == 0 and "pro" in model):
        return types.ThinkingConfig(thinking_budget=thinking_budget)
    return None


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


def generate(contents, model=None, temperature=None, json_mode=False, search=False, label="", thinking_budget=None, thinking_level=None):
    """한 번 호출해서 응답 객체(.text, .usage_metadata)를 돌려준다.

    contents: 문자열, 또는 [문자열, 파일 조각, ...]. 파일 조각은 `gemini_file_part()`가 만든 dict도 된다.
    json_mode: 응답을 JSON으로 강제한다. search: 구글 검색 그라운딩을 붙인다.
    thinking_budget: 사고(thinking) 토큰 상한. 0이면 끈다(2.5-flash만 가능, 2.5-pro는 항상 사고하므로 0은 무시). 양수는 pro에도 적용.
      Gemini 3 이상 모델에서는 자동으로 thinking_level 로 바뀐다(thinking_config_for 참고).
      실측(2.5-flash): 키워드 추출처럼 단순한 호출도 사고에 1,000~2,000토큰을 써서 7~12초가 걸렸다.
    thinking_level: 'minimal'|'low'|'medium'|'high'. Gemini 3 이상에서만 적용되고 2.x 에서는 무시한다."""
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
    tc = thinking_config_for(model, thinking_budget, thinking_level)
    if tc is not None:
        kwargs["thinking_config"] = tc

    def call(kw):
        config = types.GenerateContentConfig(**kw) if kw else None
        return get_client().models.generate_content(model=model, contents=normalize_contents(contents), config=config)
    t = time.time()
    try:
        try:
            resp = call(kwargs)
        except Exception as e:
            ge = as_gemini_error(e)
            # 새 모델이 사고 설정·샘플링 설정을 거부(400)하면 그 설정만 빼고 한 번 더 부른다(모델이 바뀌면서 규칙이 달라지는 일이 반복돼서 호출이 통째로 실패하지 않게).
            if ge.kind == "bad_request" and ("thinking_config" in kwargs or "temperature" in kwargs):
                slim = {k: v for k, v in kwargs.items() if k not in ("thinking_config", "temperature")}
                print(f"[gemini] {label or '-'} model={model} 400 -> 사고·temperature 설정을 빼고 재시도: {ge.cause[:120]}")
                resp = call(slim)
            else:
                raise
    except Exception as e:
        ge = as_gemini_error(e)
        print(f"[gemini] {label or '-'} model={model} 실패 kind={ge.kind} {ge.cause[:160]}")
        raise ge from e
    _log(label, model, time.time() - t, resp)
    return resp


def generate_with_fallback(contents, models=None, temperature=None, label="", **kwargs):
    """models를 순서대로 시도해 처음 성공한 (응답, 사용한 모델)을 돌려준다. 전부 실패하면 마지막 예외를 올린다."""
    last = None
    models = list(dict.fromkeys(models or main_fallbacks()))       # 본 모델과 가벼운 모델이 같으면 같은 모델을 두 번 부르지 않는다
    if len(models) == 1 and models[0] != RESERVE_MODEL:
        models.append(RESERVE_MODEL)                               # 한 모델뿐이면 이전 세대를 마지막 예비로 둔다
    for m in models:
        try:
            return generate(contents, model=m, temperature=temperature, label=label, **kwargs), m
        except Exception as e:
            last = as_gemini_error(e)
            print(f"[gemini] {label or '-'} model={m} 실패: kind={last.kind} {last.cause[:200]}")
            if last.kind in FAIL_FAST_KINDS:
                break                                         # 크레딧 소진·인증 오류는 모델을 바꿔도 똑같이 실패한다
    raise last if last else RuntimeError("시도할 모델이 없습니다")
