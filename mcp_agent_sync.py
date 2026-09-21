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

from moleg_mcp import search_law, search_precedents_by_keyword, search_precedent_by_case_number, search_ordinance, search_laws_with_text
from korea_regions import find_jurisdiction_in_text, BASIC_REGIONS, METROPOLITAN_REGIONS

_VALID_REGIONS = set(BASIC_REGIONS) | set(METROPOLITAN_REGIONS)

# 대법원 판례 사건번호 패턴 (예: 2010두11641, 2018다12345)
_CASE_NO_PATTERN = re.compile(r'\d{2,4}[가-힣]\d{3,7}')


def _extract_keyword_and_jurisdiction(query: str) -> tuple:
    """(keyword, jurisdiction, ordinance_keyword, law_names, topic_keywords)를 돌려준다.

    법제처 검색에 쓸 핵심 키워드 1개, 지자체(예: 남해군) 이름, 그리고 자치법규
    (조례) 검색에 쓸 별도 키워드를 뽑는다. 실패하면 전부 빈 문자열.

    (예전에는 키워드만 뽑았는데, 그러면 "남해군이 ~조례에 따라~"처럼 지자체 조례가
    실제로 관련된 질문에서도 조례를 전혀 검색하지 않고 "확인이 필요합니다"라고만
    안내하는 문제가 있었음 - 실사용 중 발견.)

    조례검색용 키워드를 법령/판례 검색 키워드와 분리한 이유: "현장조치 행동매뉴얼
    작성 용역을 재난관리기금으로 집행해도 되는지" 같은 질의는 사업명("현장조치
    행동매뉴얼")과 그 재원이 되는 제도명("재난관리기금")이 서로 다른데, 조례는
    거의 항상 제도/기금/위원회 이름으로 지어진다("OO군 재난관리기금 운용 조례"
    같은 식이지 "OO군 현장조치 행동매뉴얼 조례"라는 조례는 존재하지 않는다).
    하나의 키워드만 뽑아 양쪽에 다 쓰면, 사업명 쪽으로 쏠려서 실제로 존재하는
    조례를 검색어 자체가 틀려서 못 찾는 사고로 이어졌다(실사용 중 발견: "남해군
    재난관리기금 운용ㆍ관리 조례"가 실제 존재하는데도, 조례 검색에 "현장조치
    행동매뉴얼"을 써서 결과가 안 나옴).
    """
    try:
        genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = (
            "다음 텍스트에서 다섯 가지를 뽑아서 정확히 '키워드|지자체명|조례검색키워드|법령명들|조문키워드들' "
            "형식의 한 줄로만 답해. 다른 설명은 절대 하지 마. 구분자 파이프(|)는 정확히 "
            "4개만 써야 한다.\n"
            "- 키워드: 대한민국 법제처(law.go.kr) 법령/판례 검색에 가장 적합한 핵심 명사 1개 "
            "(예: 영업손실보상, 재해영향평가, 하도급)\n"
            "- 지자체명: 텍스트에 특정 시/군/구 등 기초/광역 지방자치단체 이름이 명시되어 "
            "있으면 그 이름만 정확히(예: 남해군, 수원시, 강남구). 다른 단어와 절대 함께 "
            "쓰지 말 것. 없으면 비워둬.\n"
            "- 조례검색키워드: 지방자치단체 조례/규칙 검색에 쓸 명사 1개. 사업명이나 문서명이 "
            "아니라, 그 사업의 재원이 되는 기금명, 관련 제도명, 위원회명, 인허가 대상 등 "
            "'조례 제목에 실제로 들어갈 법한' 단어를 골라라(예: 사업명이 '현장조치 행동매뉴얼 "
            "작성 용역'이고 재원이 '재난관리기금'이면, 조례검색키워드는 '재난관리기금'). "
            "특정할 게 없으면 위 '키워드'와 동일하게 써도 됨.\n"
            "- 법령명들: 이 질의를 검토하려면 조문을 봐야 하는 핵심 법률의 '정식 법령명'을 "
            "쉼표로 구분해 최대 2개(시행령/시행규칙은 쓰지 말고 법률명만; 예: 공익사업을 위한 "
            "토지 등의 취득 및 보상에 관한 법률, 재난 및 안전관리 기본법). 확실히 존재하는 "
            "정식 명칭만 쓰고 확신이 없으면 비워둬.\n"
            "- 조문키워드들: 그 법령 안에서 관련 조문을 찾아내는 데 쓸 핵심어를 쉼표로 3~6개 "
            "(예: 영업손실,영업의 폐지,휴업,사업인정고시일,무허가건축물).\n"
            "예시: '하도급|남해군|하도급|건설산업기본법|하도급,직접시공' 또는 "
            "'영업손실보상||영업손실|공익사업을 위한 토지 등의 취득 및 보상에 관한 법률|영업손실,휴업,폐업'\n"
            "텍스트: " + query[:8000]
        )
        resp = model.generate_content(prompt)
        line = resp.text.strip().splitlines()[0].strip()
        parts = line.split('|')
        keyword = parts[0].strip().replace("'", "").replace('"', "")[:15]
        law_names = [x.strip() for x in (parts[3] if len(parts) > 3 else "").split(',') if x.strip()][:2]
        topic_keywords = [x.strip() for x in (parts[4] if len(parts) > 4 else "").split(',') if x.strip()][:6]
        jurisdiction_raw = parts[1].strip().replace("'", "").replace('"', "")[:10] if len(parts) > 1 else ""
        ordinance_keyword = parts[2].strip().replace("'", "").replace('"', "")[:15] if len(parts) > 2 else keyword

        # 지자체명은 LLM이 가끔 다른 단어와 뒤섞어 반환하는 사고가 있었으므로
        # (예: "남해군, 재난관리기"), 실제 존재하는 지자체명 화이트리스트와
        # 정확히 일치할 때만 신뢰한다. 안 맞으면 아래 get_mcp_context_sync의
        # find_jurisdiction_in_text 결정적 보완 로직에 맡긴다.
        jurisdiction = jurisdiction_raw if jurisdiction_raw in _VALID_REGIONS else ""

        return keyword, jurisdiction, ordinance_keyword, law_names, topic_keywords
    except Exception as e:
        print(f"[mcp_agent_sync] keyword/jurisdiction extraction failed: {e}")
        return "", "", "", [], []


def get_mcp_context_sync(query: str, uploaded_file=None) -> str:
    if uploaded_file:
        query = f"{query}\n(첨부 파일명: {uploaded_file})"

    keyword, jurisdiction, ordinance_keyword, law_names, topic_keywords = _extract_keyword_and_jurisdiction(query)
    if not keyword:
        # 키워드 추출 자체가 실패해도 빈 컨텍스트보다는 질의 앞부분이라도 검색어로 쓰는 게 낫다.
        keyword = query.strip()[:15]

    if not jurisdiction:
        # LLM 추출은 비용/속도 때문에 텍스트 앞부분(8,000자)만 보므로, 그보다 뒤에
        # 지자체명이 나오는 긴 첨부문서에서는 놓칠 수 있다. 이 경우 전체 텍스트를
        # 결정적으로(LLM 없이) 훑어서 실제 존재하는 지자체명을 찾아내는 것으로
        # 보완한다 (실사용 중 발견: "조례를 왜 못 읽어오지" 문의 - 지자체명이
        # 8,000자 자르기 지점 이후에 있어 통째로 놓쳤던 사례).
        jurisdiction = find_jurisdiction_in_text(query)

    sections = []

    # 질의/문서에 사건번호가 직접 인용돼 있으면 키워드 검색보다 우선해서 정확히 조회
    case_numbers = list(dict.fromkeys(_CASE_NO_PATTERN.findall(query)))[:3]
    for case_no in case_numbers:
        try:
            sections.append(f"[사건번호 '{case_no}' 조회 결과]\n{search_precedent_by_case_number(case_no)}")
        except Exception as e:
            sections.append(f"[사건번호 '{case_no}' 조회 실패: {e}]")

    # 정식 법령명으로 조문 원문을 가져온다(일반 키워드 검색은 결과가 0건인 경우가 많고
    # 이름/링크만 줘서 AI가 조문 내용을 검토하지 못했음).
    if law_names:
        try:
            law_text = search_laws_with_text(law_names, topic_keywords or [keyword])
            if law_text:
                sections.append(law_text)
        except Exception as e:
            sections.append(f"[법령 원문 조회 실패: {e}]")

    if keyword:
        try:
            sections.append(f"[법령 검색 결과: '{keyword}']\n{search_law(keyword)}")
        except Exception as e:
            sections.append(f"[법령 검색 실패: {e}]")

        try:
            sections.append(f"[판례 검색 결과: '{keyword}']\n{search_precedents_by_keyword(keyword)}")
        except Exception as e:
            sections.append(f"[판례 검색 실패: {e}]")

    # 지자체명이 특정됐을 때만 자치법규(조례/규칙)를 검색한다. 지자체 없이 키워드만으로
    # 검색하면 전국 수백 개 지자체의 동명 조례가 뒤섞여 나와 오히려 혼란을 줌.
    # 검색어는 일반 법령/판례 검색용 keyword가 아니라 ordinance_keyword를 쓴다
    # (위 _extract_keyword_and_jurisdiction 설명 참고 - 조례는 사업명이 아니라
    # 기금/제도명으로 검색해야 실제로 찾아진다).
    search_kw = ordinance_keyword or keyword
    if jurisdiction and search_kw:
        try:
            ord_result = search_ordinance(f'{jurisdiction} {search_kw}')
            # ordinance_keyword로도 못 찾으면(예: "개발행위"는 조례 제목엔 안 쓰이고
            # "도시계획 조례" 안의 세부 내용일 뿐인 경우), 일반 법령검색용 keyword로도
            # 한 번 더 시도해본다 - LLM이 두 후보 중 하나는 실제 조례 제목과 더 가깝게
            # 뽑을 때가 있다(실사용 중 발견: "강남구 도시계획위원회 심의 대상 개발행위"
            # 질의에서 ordinance_keyword="개발행위"는 실패했지만 일반 keyword 쪽이
            # 조례 제목에 더 가까운 경우가 있음).
            if ord_result.startswith("No ordinances found") and keyword and keyword != search_kw:
                retry = search_ordinance(f'{jurisdiction} {keyword}')
                if not retry.startswith("No ordinances found"):
                    ord_result = retry
                    search_kw = keyword
            sections.append(f"[자치법규(조례) 검색 결과: '{jurisdiction} {search_kw}']\n{ord_result}")
        except Exception as e:
            sections.append(f"[자치법규 검색 실패: {e}]")

    return "\n\n".join(sections)
