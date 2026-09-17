import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from mcp.server.fastmcp import FastMCP

# 환경 변수에서 법제처 API 키 가져오기 (없으면 기본값 사용)
MOLEG_API_KEY = os.environ.get("MOLEG_API_KEY", "ksh8481")

# FastMCP 서버 생성
mcp = FastMCP("moleg_mcp_server")

# law.go.kr 검색 API가 반환하는 사건번호는 "법원명-연도-사건종류-번호" 형식인데
# (예: "서울중앙지방법원-2020-가합-560874"), 이 형식 그대로 검색하면 실제로
# 존재하는 판례인데도 검색결과가 0건으로 나오는 경우가 있음 - 실사용 중 발견
# (스크린샷으로 확인: law.go.kr에서 "검색결과가 없습니다"). 반면 법원명과
# 하이픈을 뺀 축약형("2020가합560874", 대법원 판례가 원래 쓰는 표기와 동일한
# 형식)으로 검색하면 안정적으로 정확히 1건이 나오는 걸 확인함. 그래서 링크를
# 만들기 전에 항상 이 축약형으로 정규화한다.
_JUDICIAL_CASE_NO_TAIL = re.compile(r'(\d{4})-([가-힣]+)-(\d+)$')


def _normalize_case_no_for_search(case_no: str) -> str:
    m = _JUDICIAL_CASE_NO_TAIL.search(case_no)
    return (m.group(1) + m.group(2) + m.group(3)) if m else case_no


def _precedent_search_link(case_no: str) -> str:
    """판례 인용에 쓸 링크를 만든다.

    law.go.kr의 판례 "상세" 페이지는 순수 자바스크립트 SPA라(precView() 함수가
    AJAX로 내용만 갈아끼움) 직접 딥링크가 존재하지 않는다. /판례/{id}나
    /precInfo.do?precSeq={id} 같은 그럴듯해 보이는 URL은 전부 접속해보면
    "찾을 수 없음" 오류 페이지로 뜬다 - 실사용 중 발견(AI가 이런 URL을
    지어내서 사용자가 클릭했더니 깨진 링크였음).
    대신 정확한 사건번호로 판례 검색결과 페이지를 열면 그 판례 1건이 그대로
    나오는 걸 확인했으므로, "상세페이지"가 아니라 "그 사건번호로 검색한
    결과 페이지"를 링크로 쓴다. (단, 검색어는 위에서 축약형으로 정규화한 값)
    """
    query = _normalize_case_no_for_search(case_no)
    return f"https://www.law.go.kr/precSc.do?menuId=7&subMenuId=45&tabMenuId=181&query={urllib.parse.quote(query)}"


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
        # 1. 사건번호로 판례일련번호 조회 (법원명이 붙은 전체 형식이 들어와도
        # 축약형으로 정규화 - 검색 안정성 문제는 _normalize_case_no_for_search 참고)
        search_url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={MOLEG_API_KEY}&target=prec&type=XML&query={urllib.parse.quote(_normalize_case_no_for_search(case_number))}"
        res = requests.get(search_url, timeout=5)
        res.encoding = 'utf-8'
        root = ET.fromstring(res.text)

        prec = root.find('prec')
        if prec is None:
            return f"No precedent found for case number: {case_number}"

        prec_id = prec.findtext('판례일련번호')
        search_case_name = prec.findtext('사건명', '')
        search_case_no = prec.findtext('사건번호', '')
        source = prec.findtext('데이터출처명', '')
        link = _precedent_search_link(search_case_no) if search_case_no else ""

        if not prec_id:
            return f"No precedent found for case number: {case_number}"

        # 2. 판례일련번호로 상세 조회
        # 주의: law.go.kr의 판례 상세조회는 데이터출처가 "대법원"인 판례만 원문이 있다.
        # "국세법령정보시스템"처럼 다른 기관에서 수집해 검색 색인만 제공하는 판례는
        # 상세조회를 해도 <Law>일치하는 판례가 없습니다</Law> 형태의 오류가 오는데,
        # 예전 코드는 이 오류를 감지하지 못해 그냥 빈 문자열들을 반환했었다
        # (실사용 중 발견: search_precedent_by_case_number가 항상 빈 결과를 냄).
        detail_url = f"https://www.law.go.kr/DRF/lawService.do?OC={MOLEG_API_KEY}&target=prec&ID={prec_id}&type=XML"
        res_detail = requests.get(detail_url, timeout=5)
        res_detail.encoding = 'utf-8'
        root_detail = ET.fromstring(res_detail.text)

        if root_detail.tag != 'PrecService':
            # 상세 원문 조회 실패 - 검색 단계에서 얻은 정보만이라도 정확하게 제공한다.
            note = f" (데이터출처: {source})" if source else ""
            return (
                f"Case Name: {search_case_name}\nCase Number: {search_case_no}\nLink: {link}\n\n"
                f"[Notice] law.go.kr에 이 판례의 전체 원문이 등록되어 있지 않아 판시사항/요지를 "
                f"가져올 수 없습니다{note}. 위 Link로 직접 확인하십시오."
            )

        case_no = root_detail.findtext('사건번호', '') or search_case_no
        case_name = root_detail.findtext('사건명', '') or search_case_name
        summary = root_detail.findtext('판결요지', '')
        content = root_detail.findtext('판례내용', '')

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

def _ordinance_detail_text(mst: str, max_len: int = 6000) -> str:
    """자치법규 상세조회(lawService.do target=ordin)로 조례 원문(조문 전체)을
    가져온다. search_ordinance는 이름/링크만 주지 검토에 필요한 실제 조문
    내용을 안 줘서, 사용자가 링크는 열리는데 AI가 "그 안에 뭐라고 쓰여
    있는지"는 검토를 못 하는 사고로 이어졌음(실사용 중 발견: "조례는 잘
    열리는데 왜 대답할 때 조례를 검토를 안 하는 것 같지"). 이 함수로 실제
    원문을 가져와 메인 프롬프트에 넣어야 AI가 조례 조문 자체를 검토할 수 있다.
    """
    try:
        url = f"https://www.law.go.kr/DRF/lawService.do?OC={MOLEG_API_KEY}&target=ordin&MST={mst}&type=XML"
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        root = ET.fromstring(res.text)

        lines = []
        for jo in root.findall('.//조'):
            title = jo.findtext('조제목', '') or ''
            content = (jo.findtext('조내용', '') or '').strip()
            if content:
                lines.append(content)
            if sum(len(l) for l in lines) >= max_len:
                break

        text = "\n".join(lines)
        return text[:max_len]
    except Exception as e:
        return f"(조례 원문 조회 실패: {e})"


# law.go.kr의 자치법규 검색은 "질의 문자열이 조례명에 그대로 다 들어있어야" 잡히는
# 엄격한(AND에 가까운) 매칭이다(실측: "도시계획위원회" 단독은 전국 44건이 잡히지만,
# "강남구 도시계획위원회"로 합치면 0건 - 실제 강남구 조례명은 "도시계획 조례"라
# "위원회"라는 글자가 제목에 없기 때문). LLM이 뽑은 조례검색키워드가 실제 조례
# 제목과 토씨 하나까지 같을 거라고 기대할 수 없으므로, 흔히 덧붙는 수식어를 하나씩
# 떼어내며 재시도한다(실사용 중 발견: "계속 조례를 못 찾아오는 것 같다" 문의).
_ORDINANCE_GENERIC_SUFFIXES = ['운영위원회', '심의위원회', '위원회', '운용위원회', '제도', '규정', '지침', '심의', '운영', '관리']


def _search_ordinance_once(jurisdiction: str, keyword: str):
    """검색 1회 시도. (results_lines, top_mst, top_name) 또는 결과 없으면 None."""
    query = f"{jurisdiction} {keyword}".strip()
    url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={MOLEG_API_KEY}&target=ordin&type=XML&query={urllib.parse.quote(query)}"
    res = requests.get(url, timeout=5)
    res.encoding = 'utf-8'
    root = ET.fromstring(res.text)

    results = []
    top_mst = None
    top_name = None
    for law in root.findall('.//law')[:5]:
        name = law.findtext('자치법규명', '')
        org = law.findtext('지자체기관명', '')
        kind = law.findtext('자치법규종류', '')
        mst = law.findtext('자치법규일련번호', '')
        if name:
            link = f"https://www.law.go.kr/자치법규/{urllib.parse.quote(name)}"
            results.append(f"- [{name}]({link}) ({org}, {kind})")
            if top_mst is None and mst:
                top_mst = mst
                top_name = name

    return (results, top_mst, top_name) if results else None


@mcp.tool()
def search_ordinance(keyword: str) -> str:
    """
    Search MOLEG (법제처) 자치법규(지방자치단체 조례/규칙) by keyword.
    Returns matching ordinance names, issuing jurisdiction, links, and the
    full article text of the top match (so the main analysis can actually
    review what the ordinance says, not just know that it exists).
    키워드에 지자체명(예: "남해군 공유재산")을 함께 넣으면 해당 지자체 조례로 좁혀진다.

    법제처 검색이 조례명과 정확히 일치해야 잡히는 엄격한 매칭이라, 첫 시도가
    비어있으면 흔한 수식어(위원회/규정/지침 등)를 떼어내며 최대 몇 차례 더
    시도한다(위 _ORDINANCE_GENERIC_SUFFIXES 설명 참고).
    """
    # keyword에 "지자체명 + 검색어"가 공백으로 합쳐져 들어오므로, 뒤쪽 검색어만
    # 잘라내며 재시도할 수 있도록 앞의 지자체명 부분과 분리한다. 지자체명이 정확히
    # 몇 단어인지는 알 수 없지만, 실제로는 항상 "지자체명 한 단어 + 검색어"
    # 형태로 호출되므로 첫 단어를 지자체명으로 본다.
    parts = keyword.strip().split(' ', 1)
    jurisdiction = parts[0] if parts else ''
    core_keyword = parts[1] if len(parts) > 1 else ''

    candidates = [core_keyword] if core_keyword else [keyword]
    for suffix in _ORDINANCE_GENERIC_SUFFIXES:
        if core_keyword.endswith(suffix) and len(core_keyword) > len(suffix):
            stripped = core_keyword[: -len(suffix)].strip()
            if stripped and stripped not in candidates:
                candidates.append(stripped)
    # 검색어가 "공유재산 변상금"처럼 띄어쓰기로 여러 단어가 합쳐진 경우, 그 전체가
    # 조례명과 정확히 일치할 가능성은 낮다(대개 "공유재산 관리 조례"처럼 앞 단어만
    # 제목에 쓰이고 "변상금"은 그 조례 안의 세부 조항일 뿐임). 위 접미사 제거로도
    # 못 찾으면 마지막으로 첫 단어만 남긴 가장 넓은 후보도 시도한다.
    first_word = core_keyword.split(' ', 1)[0] if ' ' in core_keyword else ''
    if first_word and first_word not in candidates:
        candidates.append(first_word)

    try:
        for cand in candidates:
            found = _search_ordinance_once(jurisdiction, cand)
            if found:
                results, top_mst, top_name = found
                output = "Found ordinances:\n" + "\n".join(results)
                if top_mst:
                    detail = _ordinance_detail_text(top_mst)
                    output += f"\n\n[가장 관련성 높은 조례 원문: '{top_name}']\n{detail}"
                return output

        return f"No ordinances found for keyword: {keyword}"
    except Exception as e:
        return f"Error searching ordinances: {str(e)}"

if __name__ == "__main__":
    import sys
    if "--sse" in sys.argv:
        mcp.run(transport='sse')
    else:
        # 서버 실행 (stdio 모드)
        mcp.run()
