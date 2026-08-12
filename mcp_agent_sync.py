import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool

# moleg_mcp.py의 @mcp.tool() 데코레이터는 원본 함수를 그대로 반환하므로
# (mcp.server.fastmcp.FastMCP.tool()의 decorator가 `return fn`),
# 별도 프로세스를 띄우고 SSE로 통신할 필요 없이 그냥 같은 프로세스 안에서 직접 호출한다.
# (이전에는 subprocess.Popen으로 moleg_mcp.py --sse를 띄우고 2초 대기 + SSE 왕복을
#  거쳤는데, 어차피 같은 코드베이스라 그 오버헤드가 전부 불필요했다.)
from moleg_mcp import (
    search_precedents_by_keyword as _search_precedents_by_keyword,
    search_precedent_by_case_number as _search_precedent_by_case_number,
    search_law as _search_law,
)


@tool
def search_precedents_by_keyword(keyword: str) -> str:
    """Search MOLEG precedents by keyword (키워드로 판례 검색)"""
    return _search_precedents_by_keyword(keyword)


@tool
def search_precedent_by_case_number(case_number: str) -> str:
    """Search MOLEG precedents exactly by Case Number (사건번호, e.g., '2010두11641')"""
    return _search_precedent_by_case_number(case_number)


@tool
def search_law(keyword: str) -> str:
    """Search MOLEG current laws (현행 법령) by keyword"""
    return _search_law(keyword)


_TOOLS = [search_precedents_by_keyword, search_precedent_by_case_number, search_law]

_SYS_MSG = (
    "당신은 대한민국 법제처(MOLEG) API를 다루는 최고 수준의 법률 정보 검색 AI입니다.\n"
    "사용자의 질의(query)를 분석하여 필요한 판례(사건번호 또는 키워드)와 법령을 검색 도구를 통해 모두 수집하세요.\n"
    "수집된 정보는 RAG 파이프라인의 '컨텍스트'로 직접 사용되므로, 사건명, 사건번호, 판결요지, 관련 법령의 구체적 조항 내용 등 원문의 핵심을 누락 없이 풍부하게 정리하여 답변해 주세요.\n"
    "검색 결과가 없다면 관련 정보가 없다고 명확히 답하세요."
)


def get_mcp_context_sync(query: str, uploaded_file=None) -> str:
    if uploaded_file:
        query += f"\n(참고로 사용자가 '{uploaded_file}'라는 파일을 첨부했습니다. 파일명에서 단서를 얻을 수 있습니다.)"

    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.environ.get('GEMINI_API_KEY'))
        agent_executor = create_react_agent(llm, _TOOLS)

        response = agent_executor.invoke({"messages": [("system", _SYS_MSG), ("user", query)]})
        return response["messages"][-1].content
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"MCP Agent error: {e}")
        return ""
