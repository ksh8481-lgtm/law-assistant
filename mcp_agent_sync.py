import os
import sys
import socket
import subprocess
import time
import asyncio
from mcp.client.sse import sse_client
from mcp import ClientSession
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool

# Global proc to keep server alive
_mcp_proc = None

def start_mcp_server():
    global _mcp_proc
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(('127.0.0.1', 8000)) == 0:
            return None # Already running
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_script = os.path.join(script_dir, "moleg_mcp.py")
    _mcp_proc = subprocess.Popen([sys.executable, mcp_script, "--sse"])
    time.sleep(2)
    return _mcp_proc

async def run_mcp_agent_async(user_input: str, uploaded_file=None) -> str:
    if uploaded_file:
        user_input += f"\n(참고로 사용자가 '{uploaded_file}'라는 파일을 첨부했습니다. 파일명에서 단서를 얻을 수 있습니다.)"
        
    async with sse_client("http://127.0.0.1:8000/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            @tool
            async def search_precedents_by_keyword(keyword: str) -> str:
                """Search MOLEG precedents by keyword (키워드로 판례 검색)"""
                res = await session.call_tool("search_precedents_by_keyword", arguments={"keyword": keyword})
                return "\n".join(c.text for c in res.content if hasattr(c, 'text'))
                
            @tool
            async def search_precedent_by_case_number(case_number: str) -> str:
                """Search MOLEG precedents exactly by Case Number (사건번호, e.g., '2010두11641')"""
                res = await session.call_tool("search_precedent_by_case_number", arguments={"case_number": case_number})
                return "\n".join(c.text for c in res.content if hasattr(c, 'text'))
                
            @tool
            async def search_law(keyword: str) -> str:
                """Search MOLEG current laws (현행 법령) by keyword"""
                res = await session.call_tool("search_law", arguments={"keyword": keyword})
                return "\n".join(c.text for c in res.content if hasattr(c, 'text'))

            llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", api_key=os.environ.get('GEMINI_API_KEY'))
            tools = [search_precedents_by_keyword, search_precedent_by_case_number, search_law]
            agent_executor = create_react_agent(llm, tools)
            
            sys_msg = (
                "당신은 대한민국 법제처(MOLEG) API를 다루는 최고 수준의 법률 정보 검색 AI입니다.\n"
                "사용자의 질의(query)를 분석하여 필요한 판례(사건번호 또는 키워드)와 법령을 검색 도구를 통해 모두 수집하세요.\n"
                "수집된 정보는 RAG 파이프라인의 '컨텍스트'로 직접 사용되므로, 사건명, 사건번호, 판결요지, 관련 법령의 구체적 조항 내용 등 원문의 핵심을 누락 없이 풍부하게 정리하여 답변해 주세요.\n"
                "검색 결과가 없다면 관련 정보가 없다고 명확히 답하세요."
            )
            
            response = await agent_executor.ainvoke({"messages": [("system", sys_msg), ("user", user_input)]})
            return response["messages"][-1].content

def get_mcp_context_sync(query: str, uploaded_file=None) -> str:
    start_mcp_server()
    # Windows asyncio policy workaround for Thread environments
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        return asyncio.run(run_mcp_agent_async(query, uploaded_file))
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"MCP Agent error: {e}")
        return ""
