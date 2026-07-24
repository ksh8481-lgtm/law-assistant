import os
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from mcp.server.fastmcp import FastMCP

# 환경 변수에서 법제처 API 키 가져오기 (없으면 기본값 사용)
MOLEG_API_KEY = os.environ.get("MOLEG_API_KEY", "ksh8481")

# FastMCP 서버 생성
mcp = FastMCP("moleg_mcp_server")

@mcp.tool()
def search_precedents_by_keyword(keyword: str) -> str:
    """
    Search MOLEG (법제처) precedents by a keyword (키워드로 판례 검색).
    Returns a summary of matched precedents including their Case Numbers (사건번호) and Precedent IDs.
    """
    try:
        search_url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={MOLEG_API_KEY}&target=prec&type=XML&query={urllib.parse.quote(keyword)}"
        res = requests.get(search_url, timeout=5)
        res.encoding = 'utf-8'
        root = ET.fromstring(res.text)
        
        results = []
        for prec in root.findall('prec')[:5]:  # 상위 5개 반환
            case_name = prec.findtext('사건명', '')
            case_no = prec.findtext('사건번호', '')
            prec_id = prec.findtext('판례일련번호', '')
            court = prec.findtext('선고법원', '')
            date = prec.findtext('선고일자', '')
            results.append(f"- [{prec_id}] {case_name} ({court}, {date}, 사건번호: {case_no})")
            
        if not results:
            return f"No precedents found for keyword: {keyword}"
            
        return "Found precedents:\n" + "\n".join(results) + "\n\nUse search_precedent_by_case_number or search_precedent_detail to get full text."
    except Exception as e:
        return f"Error searching precedents: {str(e)}"

@mcp.tool()
def search_precedent_by_case_number(case_number: str) -> str:
    """
    Search MOLEG precedents exactly by Case Number (사건번호, e.g., '2010두11641').
    Returns the full text / summary of the precedent.
    """
    try:
        # 1. 사건번호로 판례일련번호 조회
        search_url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={MOLEG_API_KEY}&target=prec&type=XML&query={urllib.parse.quote(case_number)}"
        res = requests.get(search_url, timeout=5)
        res.encoding = 'utf-8'
        root = ET.fromstring(res.text)
        
        prec_id = None
        for prec in root.findall('prec')[:1]:
            prec_id = prec.findtext('판례일련번호')
            
        if not prec_id:
            return f"No precedent found for case number: {case_number}"
            
        # 2. 판례일련번호로 상세 조회
        detail_url = f"https://www.law.go.kr/DRF/lawService.do?OC={MOLEG_API_KEY}&target=prec&ID={prec_id}&type=XML"
        res_detail = requests.get(detail_url, timeout=5)
        res_detail.encoding = 'utf-8'
        root_detail = ET.fromstring(res_detail.text)
        
        case_no = root_detail.findtext('사건번호', '')
        case_name = root_detail.findtext('사건명', '')
        summary = root_detail.findtext('판결요지', '')
        content = root_detail.findtext('판례내용', '')
        
        result_text = f"Case Name: {case_name}\nCase Number: {case_no}\n\n[Summary]\n{summary}\n\n"
        if not summary and content:
            result_text += f"[Content]\n{content[:1500]}... (truncated)"
            
        return result_text
    except Exception as e:
        return f"Error fetching precedent details for case {case_number}: {str(e)}"

@mcp.tool()
def search_law(keyword: str) -> str:
    """
    Search MOLEG (법제처) current laws (현행 법령) by keyword.
    Returns matching law names and their links.
    """
    try:
        law_url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={MOLEG_API_KEY}&target=law&type=XML&query={urllib.parse.quote(keyword)}"
        res = requests.get(law_url, timeout=5)
        res.encoding = 'utf-8'
        root = ET.fromstring(res.text)
        
        laws = []
        for law in root.findall('.//law')[:5]:
            name = law.findtext('법령명한글', '')
            if name:
                link = f"https://www.law.go.kr/법령/{urllib.parse.quote(name)}"
                laws.append(f"- [{name}]({link})")
                
        if not laws:
            return f"No laws found for keyword: {keyword}"
            
        return "Found laws:\n" + "\n".join(laws)
    except Exception as e:
        return f"Error searching laws: {str(e)}"

if __name__ == "__main__":
    import sys
    if "--sse" in sys.argv:
        mcp.run(transport='sse')
    else:
        # 서버 실행 (stdio 모드)
        mcp.run()
