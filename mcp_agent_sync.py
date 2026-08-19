"""
법제처(MOLEG) 법령/판례 검색 컨텍스트를 만드는 모듈.

예전에는 moleg_mcp.py의 검색 도구 3개(search_law, search_precedents_by_keyword,
search_precedent_by_case_number)를 LangGraph ReAct 에이전트에게 맡겨서
"어떤 도구를 언제 호출할지"와 "검색 결과를 어떻게 요약할지"까지 전부 LLM이
판단하게 했다(+ 그 전에는 그 에이전트를 별도 서브프로세스+SSE로 띄우기까지 했음).

그런데:
  1) 도구가 3개뿐인 단순 REST API 래퍼라, 에이전트를 돌릴 만큼 복잡한 판단이
     필요하지 않다 (매 요청마다 추가 LLM 호출 + 도구선택 루프 = 느려짐).
  2) 에이전트의 "요약" 단계 자체가 원문에 없는 오류를 만들어내는 사고가
     실제로 발생했다 (예: "재해영향평가"를 "환경영향평가법"으로 착각한 뒤
     그 착각한 요약문이 메인 분석 프롬프트로 그대로 들어감).

그래서 LLM의 역할은 "검색에 쓸 키워드/사건번호 추출"로 최소화하고, 법제처
검색 결과 원문은 요약하지 않고 그대로 메인 분석 프롬프트에 넘긴다. 최종
판단(및 반할루시네이션 가드)은 이미 강하게 걸려 있는 메인 분석 프롬프트
한 곳에서만 하도록 한다.
"""
import os
import re
import google.generativeai as genai

from moleg_mcp import search_law, search_precedents_by_keyword, search_precedent_by_case_number

# 대법원 판례 사건번호 패턴 (예: 2010두11641, 2018다12345)
_CASE_NO_PATTERN = re.compile(r'\d{2,4}[가-힣]\d{3,7}')


def _extract_keyword(query: str) -> str:
    """법제처 검색에 쓸 핵심 키워드 1개를 뽑는다. 실패하면 빈 문자열."""
    try:
        genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = (
            "다음 텍스트에서 대한민국 법제처(law.go.kr) 법령/판례 검색에 가장 적합한 "
            "핵심 명사 키워드 딱 1개(예: 영업손실보상, 재해영향평가, 하도급)만 추출해. "
            "다른 설명은 절대 하지 마.\n텍스트: " + query[:2000]
        )
        resp = model.generate_content(prompt)
        keyword = resp.text.strip().replace("'", "").replace('"', "").splitlines()[0].strip()
        return keyword[:15]
    except Exception as e:
        print(f"[mcp_agent_sync] keyword extraction failed: {e}")
        return ""


def get_mcp_context_sync(query: str, uploaded_file=None) -> str:
    if uploaded_file:
        query = f"{query}\n(첨부 파일명: {uploaded_file})"

    keyword = _extract_keyword(query)
    if not keyword:
        # 키워드 추출 자체가 실패해도 빈 컨텍스트보다는 질의 앞부분이라도 검색어로 쓰는 게 낫다.
        keyword = query.strip()[:15]

    sections = []

    # 질의/문서에 사건번호가 직접 인용돼 있으면 키워드 검색보다 우선해서 정확히 조회
    case_numbers = list(dict.fromkeys(_CASE_NO_PATTERN.findall(query)))[:3]
    for case_no in case_numbers:
        try:
            sections.append(f"[사건번호 '{case_no}' 조회 결과]\n{search_precedent_by_case_number(case_no)}")
        except Exception as e:
            sections.append(f"[사건번호 '{case_no}' 조회 실패: {e}]")

    if keyword:
        try:
            sections.append(f"[법령 검색 결과: '{keyword}']\n{search_law(keyword)}")
        except Exception as e:
            sections.append(f"[법령 검색 실패: {e}]")

        try:
            sections.append(f"[판례 검색 결과: '{keyword}']\n{search_precedents_by_keyword(keyword)}")
        except Exception as e:
            sections.append(f"[판례 검색 실패: {e}]")

    return "\n\n".join(sections)
