import os
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from mcp.server.fastmcp import FastMCP

# 환경 변수에서 법제처 API 키 가져오기 (없으면 기본값 사용)
MOLEG_API_KEY = os.environ.get("MOLEG_API_KEY", "ksh8481")

# FastMCP 서버 생성
mcp = FastMCP("moleg_mcp_server")


def _precedent_search_link(case_no: str) -> str:
    """판례 인용에 쓸 링크를 만든다.

    law.go.kr의 판례 "상세" 페이지는 순수 자바스크립트 SPA라(precView() 함수가
    AJAX로 내용만 갈아끼움) 직접 딥링크가 존재하지 않는다. /판례/{id}나
    /precInfo.do?precSeq={id} 같은 그럴듯해 보이는 URL은 전부 접속해보면
    "찾을 수 없음" 오류 페이지로 뜬다 - 실사용 중 발견(AI가 이런 URL을
    지어내서 사용자가 클릭했더니 깨진 링크였음).
    대신 정확한 사건번호로 판례 검색결과 페이지를 열면 그 판례 1건이 그대로
    나오는 걸 확인했으므로, "상세페이지"가 아니라 "그 사건번호로 검색한
    결과 페이지"를 링크로 쓴다.
    """
    return f"https://www.law.go.kr/precSc.do?menuId=7&subMenuId=45&tabMenuId=181&query={urllib.parse.quote(case_no)}"


@mcp.tool()
def search_precedents_by_keyword(keyword: str) -> str:
    """
    Search MOLEG (법제처) precedents by a keyword (키워드로 판례 검색).
    Returns a summary of matched precedents including their Case Numbers (사건번호) and a working link.
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
            date = prec.findtext('선고일자', '')
            if case_no:
                link = _precedent_search_link(case_no)
                results.append(f"- [{case_name} (사건번호: {case_no})]({link}) - 선고일자: {date}")
            else:
                results.append(f"- {case_name} (선고일자: {date}, 사건번호 없음 - 링크 생성 불가)")

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

        link = _precedent_search_link(case_no) if case_no else ""
        result_text = f"Case Name: {case_name}\nCase Number: {case_no}\nLink: {link}\n\n[Summary]\n{summary}\n\n"
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

@mcp.tool()
def search_ordinance(keyword: str) -> str:
    """
    Search MOLEG (법제처) 자치법규(지방자치단체 조례/규칙) by keyword.
    Returns matching ordinance names, issuing jurisdiction, and links.
    키워드에 지자체명(예: "남해군 공유재산")을 함께 넣으면 해당 지자체 조례로 좁혀진다.
    """
    try:
        url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={MOLEG_API_KEY}&target=ordin&type=XML&query={urllib.parse.quote(keyword)}"
        res = requests.get(url, timeout=5)
        res.encoding = 'utf-8'
        root = ET.fromstring(res.text)

        results = []
        for law in root.findall('.//law')[:5]:
            name = law.findtext('자치법규명', '')
            org = law.findtext('지자체기관명', '')
            kind = law.findtext('자치법규종류', '')
            if name:
                link = f"https://www.law.go.kr/자치법규/{urllib.parse.quote(name)}"
                results.append(f"- [{name}]({link}) ({org}, {kind})")

        if not results:
            return f"No ordinances found for keyword: {keyword}"

        return "Found ordinances:\n" + "\n".join(results)
    except Exception as e:
        return f"Error searching ordinances: {str(e)}"

if __name__ == "__main__":
    import sys
    if "--sse" in sys.argv:
        mcp.run(transport='sse')
    else:
        # 서버 실행 (stdio 모드)
        mcp.run()
