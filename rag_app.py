import os
import asyncio
import streamlit as st
from dotenv import load_dotenv

# LangChain imports
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt.chat_agent_executor import create_react_agent
from langchain_core.tools import tool

# MCP imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 1. 환경변수 설정
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(env_path)
gemini_key = os.getenv('GEMINI_API_KEY')

# 페이지 설정
st.set_page_config(page_title="KCSC & 법제처 AI 어시스턴트", page_icon="🏛️", layout="centered")
st.title("🏛️ 건설기준 & 법령/판례 AI 어시스턴트 (MCP)")
st.markdown("KCSC 로컬 벡터 DB와 법제처 MCP 서버를 동시에 활용하여 질문에 답변하는 하이브리드 에이전트입니다.")

if not gemini_key:
    st.error("❌ GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해 주세요.")
    st.stop()

db_dir = os.path.join(os.path.dirname(__file__), 'chroma_db')
if not os.path.exists(db_dir):
    st.error(f"❌ 벡터 DB 폴더({db_dir})가 없습니다. 먼저 init_vectordb.py를 실행하세요.")
    st.stop()

@st.cache_resource
def load_rag_chain():
    # KCSC RAG 체인 로드
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-2",
        google_api_key=gemini_key
    )
    vectorstore = Chroma(persist_directory=db_dir, embedding_function=embeddings)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=gemini_key,
        temperature=0.2
    )

    return retriever

retriever = load_rag_chain()

# KCSC 검색을 위한 툴 정의
@tool
def search_kcsc_standards(query: str) -> str:
    """
    Search Korea Construction Standards Center (KCSC) database.
    Use this tool to answer questions about construction rules, foundations (기초), designs (설계), etc.
    """
    docs = retriever.invoke(query)
    if not docs:
        return "No relevant KCSC standards found."
    
    # Combine docs into a single string
    result = "[검색된 KCSC 원문]\\n"
    sources = []
    for d in docs:
        title = d.metadata.get('title', 'Unknown Title')
        section = d.metadata.get('section', 'Unknown Section')
        result += f"\\n[{title} ({section})]\\n{d.page_content}\\n"
        sources.append(f"- {title} ({section})")
        
    result += "\\n[KCSC Sources]\\n" + "\\n".join(sources)
    return result

from mcp.client.sse import sse_client
import sys
import socket
import subprocess
import time

@st.cache_resource
def start_mcp_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(('127.0.0.1', 8000)) == 0:
            return None
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_script = os.path.join(script_dir, "moleg_mcp.py")
    proc = subprocess.Popen([sys.executable, mcp_script, "--sse"])
    time.sleep(2)
    return proc

_mcp_proc = start_mcp_server()

async def run_mcp_agent(user_input: str):
    async with sse_client("http://127.0.0.1:8000/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            @tool
            async def search_precedents_by_keyword(keyword: str) -> str:
                """Search MOLEG precedents by keyword (키워드로 판례 검색)"""
                res = await session.call_tool("search_precedents_by_keyword", arguments={"keyword": keyword})
                return "\\n".join(c.text for c in res.content if hasattr(c, 'text'))
                
            @tool
            async def search_precedent_by_case_number(case_number: str) -> str:
                """Search MOLEG precedents exactly by Case Number (사건번호, e.g., '2010두11641')"""
                res = await session.call_tool("search_precedent_by_case_number", arguments={"case_number": case_number})
                return "\\n".join(c.text for c in res.content if hasattr(c, 'text'))
                
            @tool
            async def search_law(keyword: str) -> str:
                """Search MOLEG current laws by keyword (현행 법령 검색)"""
                res = await session.call_tool("search_law", arguments={"keyword": keyword})
                return "\\n".join(c.text for c in res.content if hasattr(c, 'text'))
            
            # KCSC 도구와 법제처 MCP 도구 결합
            tools = [search_kcsc_standards, search_precedents_by_keyword, search_precedent_by_case_number, search_law]
            
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=gemini_key,
                temperature=0.2
            )
            
            agent_executor = create_react_agent(
                llm, 
                tools,
                state_modifier="You are a legal and construction expert assistant in South Korea. Answer in Korean. ALWAYS cite your sources (법령명, 사건번호, KCSC 코드 등)."
            )
            
            # langgraph agent returns a dict with "messages"
            response = await agent_executor.ainvoke({"messages": [("user", user_input)]})
            return response["messages"][-1].content

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 대화 기록 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 사용자 입력 처리
if prompt := st.chat_input("예: 2010두11641 판례 알려줘 / 얕은기초 설계법이 뭐야?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user", avatar="👤").markdown(prompt)

    with st.spinner("에이전트가 적절한 도구를 선택하여 검색 중입니다..."):
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            response = asyncio.run(run_mcp_agent(prompt))
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
        except Exception as e:
            import traceback
            with open("error_log.txt", "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
            st.error("오류가 발생했습니다. 로그 파일을 확인합니다.")
