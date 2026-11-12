import os
import math
import re
import time
import datetime
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET
import requests
from mcp.server.fastmcp import FastMCP

# 환경 변수에서 법제처 API 키 가져오기 (없으면 기본값 사용)
MOLEG_API_KEY = os.environ.get("MOLEG_API_KEY", "ksh8481")

# FastMCP 서버 생성
mcp = FastMCP("moleg_mcp_server")


def _fetch_law_xml_with_retry(url: str, timeout: float = 12, retries: int = 2):
    """law.go.kr 호출 + XML 파싱까지 묶어서 재시도하는 공용 함수.

    예전엔 timeout=5(짧으면 10)로 requests.get만 직접 호출하고 재시도가
    전혀 없었다. 그 뒤 1차로 "네트워크 예외만 1회 재시도"하도록 고쳤지만,
    실사용 중 배포 환경(Cloudtype)에서 여전히 "통신 오류로 조례를 확인할
    수 없었다"는 사고가 재발했다 - 로컬 PC에서 같은 API를 여러 번 호출하면
    항상 정상 응답하는데, 배포 서버에서만 실패하는 걸 보면 순수 타임아웃
    보다는 응답 자체는 왔지만 예상한 XML 구조가 아닌 경우(요청 제한, 일시적
    서버 오류 응답 등)일 가능성이 있다. 그래서 "요청"뿐 아니라 "XML 파싱"
    까지 한 단위로 묶어 재시도 횟수를 2회로 늘리고, 매 재시도 간격도
    점진적으로 늘렸다(0.5s, 1.5s). 그래도 끝내 실패하면 마지막 예외 메시지에
    상태코드와 응답 앞부분을 덧붙여, 다음에 같은 문제가 재발했을 때 서버
    로그에서 실제 원인(순수 타임아웃인지, HTTP 오류 응답인지, 다른 XML
    구조인지)을 바로 구분할 수 있게 한다.
    """
    last_err = None
    for attempt in range(retries + 1):
        try:
            res = requests.get(url, timeout=timeout)
            if res.status_code != 200:
                raise RuntimeError(f"HTTP {res.status_code}: {res.text[:200]}")
            res.encoding = 'utf-8'
            return ET.fromstring(res.text)
        except Exception as e:
            last_err = e
            print(f"[moleg_mcp] law.go.kr 호출 실패(시도 {attempt + 1}/{retries + 1}): {type(e).__name__}: {e}")
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise last_err

# ---------------------------------------------------------------------------
# 법령해석례(법제처가 중앙행정기관·지자체 질의에 공식 회신한 법령 해석)
#
# 왜 필요한가: 시행령 조문만으로는 "처음 협의가 없었던 계획의 변경에도 재협의 기준을 적용하는가", "지정이 감소하면 재협의 대상인가"처럼
# 조문이 직접 답하지 않는 쟁점이 많고, 이런 쟁점에는 법제처 해석례가 있는 경우가 많다(실사용 중 발견: 관광단지 면적 변경 + 재해영향평가
# 질의에서 다른 AI 답변은 법제처 해석 25-0166을 근거로 들었는데 이 프로그램은 해석례를 아예 조회하지 않았다). lawSearch(target=expc)가
# 안건명(제목)을 검색하며 여러 단어를 모두 포함해야 걸리므로(실측: "재해영향평가 면적" 5건, "관광단지 재해영향평가" 0건) 짧은 검색어 여러 개로
# 찾아 합치고, 제목에 질의 용어가 많이 든 순으로 골라 상위 몇 건은 질의요지·회답을 함께 가져온다.
# ---------------------------------------------------------------------------
def _interp_link(seq: str) -> str:
    return f"https://www.law.go.kr/LSW/expcInfoP.do?expcSeq={seq}"      # (API 주소에는 인증키가 들어 있어 쓰지 않는다)


def _interp_search_one(query: str, display: int = 10) -> list:
    root = _fetch_law_xml_with_retry(
        f"https://www.law.go.kr/DRF/lawSearch.do?OC={MOLEG_API_KEY}&target=expc&type=XML"
        f"&query={urllib.parse.quote(query)}&display={display}")
    out = []
    for e in root.findall('.//expc'):
        seq = (e.findtext('법령해석례일련번호') or '').strip()
        if seq:
            out.append({'seq': seq, 'title': (e.findtext('안건명') or '').strip(), 'no': (e.findtext('안건번호') or '').strip(),
                        'org': (e.findtext('회신기관명') or '').strip(), 'date': (e.findtext('회신일자') or '').strip()})
    return out


def _interp_detail(seq: str, max_len: int = 700) -> dict:
    root = _fetch_law_xml_with_retry(f"https://www.law.go.kr/DRF/lawService.do?OC={MOLEG_API_KEY}&target=expc&type=XML&ID={seq}")

    def clip(tag, n):
        t = re.sub(r'\s+', ' ', (root.findtext(tag) or '')).strip()
        return t if len(t) <= n else t[:n] + '…'
    return {'question': clip('질의요지', max_len), 'answer': clip('회답', max_len)}


def search_interpretations(queries: list, relevance_terms: list, max_items: int = 4, detail_items: int = 3) -> str:
    """법령해석례를 queries(짧은 검색어 목록)로 찾아 합치고 relevance_terms가 제목에 많이 든 순으로 max_items건을 골라 돌려준다.
    상위 detail_items건은 질의요지·회답도 붙인다. 못 찾으면 빈 문자열. 네트워크 오류는 흡수한다(보조 자료이므로 답변을 막지 않는다)."""
    from concurrent.futures import ThreadPoolExecutor
    queries = [q for q in dict.fromkeys(q.strip() for q in queries if q and q.strip())][:8]
    if not queries:
        return ""

    def one(q):
        try:
            return _interp_search_one(q)
        except Exception as e:
            print(f"[moleg_mcp] 법령해석례 검색 실패({q}): {type(e).__name__}: {e}")
            return []
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(one, queries))
    merged = {}
    for hits in results:
        for h in hits:
            merged.setdefault(h['no'] or h['seq'], h)          # 같은 안건번호가 여러 일련번호로 나오는 일이 있어 안건번호로 합친다
    if not merged:
        return ""
    # 같은 사안을 여러 기관·여러 안건번호로 회신한 해석례는 제목이 같다(실측: 24-0880·25-0165·25-0166). 하나로 합치고 나머지 번호는 덧붙인다.
    by_title = {}
    for h in merged.values():
        key = re.sub(r'\s+', '', h['title'])
        by_title.setdefault(key, []).append(h)
    merged = {}
    for group in by_title.values():
        group.sort(key=lambda h: (h['date'], h['no']), reverse=True)
        rep = dict(group[0])
        rep['also'] = sorted(g['no'] for g in group[1:] if g['no'])
        merged[rep['no'] or rep['seq']] = rep
    terms = [_kw_norm(t) for t in dict.fromkeys(relevance_terms) if t and len(t) >= 2]

    def score(h):
        title = _kw_norm(h['title'])
        return sum(1 for t in terms if t in title)
    # 제목에 질의 용어가 많이 든 순, 같으면 최신 회신일이 먼저
    ranked = sorted(merged.values(), key=lambda h: (score(h), h['date']), reverse=True)[:max_items]
    ranked = [h for h in ranked if score(h) > 0] or ranked[:1]
    lines = ["[법령해석례(법제처 공식 회신) 검색 결과] 아래는 법제처가 질의기관에 회신한 해석례입니다. 질문의 사실관계와 같지 않을 수 있으므로 '유사 사안의 해석례'로만 "
             "인용하고, 안건번호와 링크를 함께 쓰십시오. 아래에 적힌 질의요지·회답 밖의 내용은 지어내지 마십시오."]

    def detail(h):
        try:
            return _interp_detail(h['seq'])
        except Exception as e:
            print(f"[moleg_mcp] 법령해석례 상세 조회 실패({h['no']}): {type(e).__name__}: {e}")
            return None
    with ThreadPoolExecutor(max_workers=3) as ex:
        details = list(ex.map(detail, ranked[:detail_items]))
    for i, h in enumerate(ranked):
        d = details[i] if i < len(details) else None
        also = f"; 같은 사안의 다른 회신 안건번호: {', '.join(h['also'])}" if h.get('also') else ''
        lines.append(f"- [{h['org'] or '법제처'} 해석례 {h['no']}]({_interp_link(h['seq'])}) ({h['date']}{also}) {h['title']}")
        if d and (d['question'] or d['answer']):
            lines.append(f"  · 질의요지: {d['question']}")
            lines.append(f"  · 회답: {d['answer']}")
    return "\n".join(lines)


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
        root = _fetch_law_xml_with_retry(search_url)

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
        root = _fetch_law_xml_with_retry(search_url)

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
        root_detail = _fetch_law_xml_with_retry(detail_url)

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
        root = _fetch_law_xml_with_retry(law_url)
        
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

def _fetch_law_root(mst: str, timeout: float = 20):
    """법령 본문 XML을 한 번만 조회해서 파싱된 루트를 돌려준다.

    _law_articles_from_root와 _recent_buchik_from_root가 둘 다 이 함수가 반환한
    같은 root를 나눠 쓴다 - 예전엔 두 함수가 각자 독립적으로 이 URL을 다시 조회해서,
    한 법령을 조회할 때마다 law.go.kr에 같은 XML을 두 번 요청하고 있었다(실사용 중
    발견: _law_detail_text 하나가 항상 네트워크 왕복을 2번씩 함)."""
    url = f"https://www.law.go.kr/DRF/lawService.do?OC={MOLEG_API_KEY}&target=law&MST={mst}&type=XML"
    return _fetch_law_xml_with_retry(url, timeout=timeout)


def _law_articles_from_root(root) -> list:
    """이미 조회된 법령 XML 루트에서 조문 목록을 [(조문 전체 텍스트)]로 돌려준다.
    장/절 제목(조문여부='전문')은 제외하고 실제 조문만 반환. 항/호/목 내용까지
    문서 순서대로 이어붙인다."""
    articles = []
    for jo in root.findall('.//조문단위'):
        if (jo.findtext('조문여부', '') or '').strip() != '조문':
            continue
        parts = []
        for el in jo.iter():
            if el.tag in ('조문내용', '항내용', '호내용', '목내용') and el.text and el.text.strip():
                parts.append(el.text.strip())
        if parts:
            articles.append("\n".join(parts))
    return articles


def _law_articles(mst: str) -> list:
    """법령 본문 조회(lawService.do target=law)로 조문 목록을 가져온다.
    (mst만 있고 아직 root를 조회한 적이 없을 때 쓰는 진입점. root를 이미 갖고 있다면
    _law_articles_from_root를 직접 쓰는 게 중복 조회를 피할 수 있다.)"""
    return _law_articles_from_root(_fetch_law_root(mst))


def _recent_buchik_from_root(root, max_len: int = 1500) -> str:
    """이미 조회된 법령 XML 루트에서 최근 부칙(시행일·유예기간·경과조치 등)을 뽑아낸다.

    law.go.kr은 부칙을 본문 조문과 별도 섹션(부칙단위/부칙내용)으로만 제공하고 조
    단위로 쪼개지 않으며, 조문만 훑는 로직은 부칙 내용을 원천적으로 놓친다. 부칙에는
    "이 법은 공사금액 50억원 미만 건설공사에는 공포 후 3년간 적용하지 않는다" 같은,
    특정 요건이 지금 실제로 적용되는지 판단하는 데 결정적인 시행일·유예기간·경과조치가
    담겨 있는데, 이 갭 때문에 AI가 이미 끝난 유예기간을 여전히 유효한 것처럼 오래된
    지식으로 답하는 사고로 이어졌다(실사용 중 발견: 착공계 검토에서 중대재해처벌법의
    "50억원 미만 유예"가 2024.1.27 이미 끝났는데도 여전히 적용 중인 기준처럼 답함).

    법이 수십 차례 개정된 경우 부칙이 수십 개까지 쌓이므로(예: 건설산업기본법 61개),
    전부 넣을 수 없어 최근 개정분 최대 3개만 가져온다. 항상 "가장 최근 것부터" 순서대로
    채우고, 예산이 부족해 하나가 안 들어가면 그 자리에서 멈춘다(그보다 더 오래된,
    당연히 덜 관련 있을 항목으로 건너뛰어 채우지 않는다 - 예전엔 이렇게 건너뛰다가
    정작 예산 안에 들어갔어야 할 최근 항목을 통째로 놓치는 사고가 있었음)."""
    blocks = [(b.findtext('부칙내용', '') or '').strip() for b in root.findall('.//부칙단위')]
    blocks = [b for b in blocks if b]
    if not blocks:
        return ""
    # XML 순서는 오래된 개정 -> 최근 개정 순이므로, 뒤에서부터(최근 것부터) 담는다.
    picked, total = [], 0
    for b in reversed(blocks):
        if picked and total + len(b) > max_len:
            break
        picked.append(b)
        total += len(b)
        if len(picked) >= 3:
            break
    return "\n\n".join(picked)


def _law_recent_buchik(mst: str, max_len: int = 1500) -> str:
    """법령의 최근 부칙을 mst로 직접 조회한다. (root를 이미 갖고 있다면
    _recent_buchik_from_root를 직접 쓰는 게 중복 조회를 피할 수 있다.)"""
    try:
        root = _fetch_law_root(mst)
    except Exception:
        return ""
    return _recent_buchik_from_root(root, max_len)


def _kw_norm(t: str) -> str:
    """공백/'의'를 뺀 형태로도 비교한다("영업손실" <-> 조문의 "영업의 손실")."""
    return t.replace(" ", "").replace("의", "")


def _rank_by_keywords(texts: list, keywords: list) -> list:
    """텍스트 조각(조문/별표 조각)을 질의 키워드와의 관련도로 순위를 매겨 [(점수, 인덱스)]로 돌려준다.

    조각의 첫 줄(제목)에 키워드가 있으면 가중치를 4배로 주고, 여러 조각에 흔히 나오는 키워드는
    IDF로 가중치를 낮춘다. 최고점의 35% 미만은 우연히 키워드 하나만 스친 잡음으로 보고 버린다."""
    kws = [k for k in dict.fromkeys(keywords) if k and len(k) >= 2]
    norm_texts = [_kw_norm(a) for a in texts]
    n = len(texts)
    idf = {}
    for k in kws:
        nk = _kw_norm(k)
        df = sum(1 for a in norm_texts if nk in a)
        idf[k] = math.log((n + 1) / (df + 1)) if df else 0.0
    scored = []
    for idx, art in enumerate(texts):
        first = art.splitlines()[0][:100] if art else ''
        title = _kw_norm(first)
        na = norm_texts[idx]
        score = 0.0
        for k in kws:
            nk = _kw_norm(k)
            score += idf[k] * (4 * (nk in title) + min(na.count(nk), 3))
        if score > 0:
            scored.append((score, idx))
    scored.sort(key=lambda x: -x[0])
    if scored:
        scored = [x for x in scored if x[0] >= scored[0][0] * 0.35]
    return scored


def _law_detail_text(mst: str, keywords: list, max_len: int = 6000, include_byeolpyo: bool = False) -> str:
    """법령 전체(수백 개 조문)를 프롬프트에 다 넣을 수 없으므로, 질의 핵심어가 조문
    제목/내용에 많이 등장하는 조문만 골라 원문 그대로 넘긴다(제목 일치에 가중치).
    이렇게 원문을 넘겨야 AI가 "원문이 없어 일반 원칙으로 설명"하는 대신 실제
    조문에 근거해 요건/예외를 검토할 수 있다(실사용 중 발견: 영업손실보상 질의에서
    법령은 이름·링크만 주어 조문 원문 없이 일반론으로만 답함).

    XML을 한 번만 조회(_fetch_law_root)해서 조문과 부칙 추출에 같은 root를 나눠 쓴다."""
    try:
        root = _fetch_law_root(mst)
        articles = _law_articles_from_root(root)
    except Exception as e:
        return f"(법령 원문 조회 실패: {e})"

    scored = _rank_by_keywords(articles, keywords)

    picked, total = [], 0
    for score, idx in scored:
        art = articles[idx]
        if total + len(art) > max_len and picked:
            continue
        picked.append(idx)
        total += len(art)
        if total >= max_len:
            break
    body = "\n\n".join(articles[i][:2500] for i in sorted(picked))

    # 시행령·시행규칙은 시간·횟수·기준 같은 수치가 조문이 아니라 별표 표에 있는 경우가 많다. 키워드와 관련 있는 별표만 최대 2개,
    # 각 2,500자까지 붙인다(기본은 끔 - 첫 질의응답 경로의 동작과 프롬프트 크기를 바꾸지 않기 위해).
    if include_byeolpyo:
        try:
            from duty_text import byeolpyo_from_root
            bps = byeolpyo_from_root(root)
            ranked = _rank_by_keywords([f"{b['title']}\n{b['text']}" for b in bps], keywords)
            for _score, i in ranked[:2]:
                body += f"\n\n[{bps[i]['label']}] {bps[i]['title']}\n{bps[i]['text'][:2500]}"
        except Exception as e:
            print(f"[moleg_mcp] 별표 추출 실패(무시): {type(e).__name__}: {e}")

    buchik = _recent_buchik_from_root(root)
    if buchik:
        body += (
            "\n\n[부칙(최근 개정분) - 시행일·유예기간·경과조치. 조문 내용이 실제로 "
            "'지금' 적용되는지는 여기 명시된 시행일/유예기간을 기준으로 반드시 확인할 것]\n"
            + buchik
        )
    return body


def search_laws_with_text(law_names: list, topic_keywords: list,
                          per_law_len: int = 5000, per_name_max: int = 2,
                          max_total_len: int = 20000, skip_msts=None, include_byeolpyo: bool = False) -> str:
    """정식 법령명(예: 공익사업을 위한 토지 등의 취득 및 보상에 관한 법률)으로 검색해,
    그 법령과 시행령/시행규칙 중 질의와 관련된 조문 원문을 가져온다.

    law.go.kr 법령 검색은 정식 법령명/약칭이 아니면 결과가 0건이다(실측: "영업손실보상"
    0건, "토지보상법"은 성공). 그래서 일반 키워드가 아니라 법령명으로 검색해야 한다.

    예전엔 "총 fetch 개수"를 law_names 전체에 걸쳐 하나의 전역 카운터(max_laws=3)로
    제한했는데, 법령 하나가 보통 법률+시행령+시행규칙 3단계를 다 갖고 있어서 law_names의
    첫 번째 법령이 그 예산을 혼자 다 써버리고 두 번째 법령은 한 건도 못 가져오는 사고로
    이어졌다(실사용 중 발견: 착공계 검토에서 "안전관리계획서/품질관리계획서/유해위험방지
    계획서/퇴직공제/기술지도계약" 등 서로 다른 법령 4~5개를 한 번에 물어보는데, 건설기술
    진흥법(법+시행령+시행규칙)이 예산을 다 써서 중대재해처벌법이 아예 빠짐 -> "이미
    끝난 유예기간을 여전히 적용 중"이라고 오판). 이제 법령마다 개별적으로
    per_name_max(기본 2: 법률+시행령)만큼만 가져와서, 여러 법령을 요청하면 그 개수만큼
    고르게 커버되도록 한다.

    다만 per_name_max만 있고 law_names 개수 자체에는 상한이 없으면(호출부가 4~5개를
    넘겨도 이 함수는 그대로 다 처리한다), 프롬프트에 들어가는 법령 원문 총량이 무제한으로
    커질 수 있다. max_total_len으로 전체 합계에도 상한을 둬서, 법령이 여러 개 걸린
    질의에서도 프롬프트 크기가 과도하게 불어나지 않게 한다."""
    seen = set(skip_msts or ())      # 이미 프롬프트에 통째로 들어 있는 법령(법정 의무 마스터 채팅의 선택 법령)은 다시 가져오지 않는다
    notes = []

    # 1) 이름마다 정식명 계열(법/시행령/시행규칙) 후보를 찾는다. 약칭 검색이면 첫 결과의 정식명 기준으로 계열을 잡는다.
    families = []                     # (law_names 안의 순서, 이름, [(법령명, 일련번호), ...])
    for idx, name in enumerate(law_names):
        try:
            root = _fetch_law_xml_with_retry(
                f"https://www.law.go.kr/DRF/lawSearch.do?OC={MOLEG_API_KEY}&target=law&type=XML"
                f"&query={urllib.parse.quote(name)}")
        except Exception as e:
            notes.append(f"[법령 '{name}' 검색 실패: {e}]")
            continue
        hits = [(l.findtext('법령명한글', ''), l.findtext('법령일련번호', ''))
                for l in root.findall('.//law')]
        if not hits:
            notes.append(f"[법령 '{name}': 법제처 정식명칭 검색에서 찾지 못해 원문을 싣지 못했습니다(정식 명칭이 아니거나 검색이 일시적으로 실패했을 수 있습니다)]")
            continue
        base = hits[0][0]
        family = []
        for nm, mst in hits:
            if len(family) >= per_name_max:
                break
            if not mst or mst in seen or not nm.startswith(base):
                continue
            seen.add(mst)
            family.append((nm, mst))
        families.append((idx, name, family))

    def fetch(nm, mst):
        text = _law_detail_text(mst, topic_keywords, per_law_len, include_byeolpyo)
        link = f"https://www.law.go.kr/법령/{urllib.parse.quote(nm)}"
        return f"[법령 원문 발췌: {nm}] ({link})\n{text}" if text else ""

    # 2) 질의가 가리키는 법령마다 본 법률(계열의 첫 번째)은 분량 상한과 상관없이 먼저 모두 가져온다.
    #    예전에는 상한(max_total_len)을 이름 순서대로 앞에서부터 썼다. 그래서 LLM이 목록 앞쪽에 둔 법령의 법·시행령·시행규칙이
    #    상한을 다 쓰면 뒤쪽 법령이 통째로 빠졌고, AI는 "제공된 법령 데이터베이스에 원문이 없다"며 직접 찾아보라고 답했다
    #    (실사용 중 발견: 관광단지 면적 변경 시 재해영향평가 질의에서 목록은 [재난안전기본법, 관광진흥법, 자연재해대책법]이었고
    #    재난안전기본법 3단계 + 관광진흥법이 20,000자를 채워 정작 핵심인 자연재해대책법이 빠짐).
    docs = {}                         # (이름 순서, 계열 안 순서) -> 본문 구획
    total_len = 0
    relevance = {}                    # 이름 순서 -> 본 법률 발췌 안에서 질의 핵심어가 나온 횟수(시행령 등 추가분의 우선순위)
    kws = [_kw_norm(k) for k in dict.fromkeys(topic_keywords or []) if k and len(k) >= 2]
    for idx, name, family in families:
        if not family:
            continue
        sec = fetch(*family[0])
        if sec:
            docs[(idx, 0)] = sec
            total_len += len(sec)
            body = _kw_norm(sec)
            relevance[idx] = sum(body.count(k) for k in kws)
    # 3) 시행령·시행규칙은 상한이 남은 만큼만, 질의와 더 관련 있는 법령(본 법률 발췌에 핵심어가 많은 순)부터 채운다.
    skipped = []
    ordered = sorted((f for f in families if len(f[2]) > 1), key=lambda f: (-relevance.get(f[0], 0), f[0]))
    # 시행령(계열의 두 번째)을 모든 법령에 대해 먼저, 시행규칙(세 번째)은 그다음에 채운다. 한 법령의 시행령·시행규칙을 몰아서 채우면
    # 그 법령의 시행규칙이 다른 법령의 시행령보다 먼저 상한을 써 버린다(측정: 관광단지 질의에서 자연재해대책법 시행규칙이 관광진흥법 시행령을 밀어냄).
    max_tier = max((len(f[2]) for f in ordered), default=1)
    for tier in range(1, max_tier):
        for idx, name, family in ordered:
            if tier >= len(family):
                continue
            nm, mst = family[tier]
            if total_len >= max_total_len:
                skipped.append(nm)
                continue
            sec = fetch(nm, mst)
            if sec:
                docs[(idx, tier)] = sec
                total_len += len(sec)
    sections = [docs[k] for k in sorted(docs)]
    if skipped:
        # 싣지 못한 법령을 AI에게 알린다. 알리지 않으면 "원문이 없다"를 "그런 법령이 없다/DB에 없다"로 오해한다.
        sections.append("[분량 제한으로 이번 답변에 원문 발췌를 싣지 못한 법령: " + ", ".join(skipped)
                        + " - 이 법령의 조문은 제공되지 않았으므로 단정하지 말고, 필요하면 확인이 필요하다고 안내하십시오]")
    return "\n\n".join(sections + notes)


# ---------------------------------------------------------------------------
# 행정규칙(고시·훈령·예규·지침) 원문 + 별표
#
# 왜 필요한가: 위 search_laws_with_text는 target=law(법률/시행령/시행규칙)만 조회하고, 그마저
# 조문(조문단위)만 읽어 별표(별표단위)를 프롬프트에 넣지 않았다. 그런데 실무 기준은 고시의 조문과
# 별표에 있는 경우가 많다(실사용 중 발견: "건설사업관리 인원 산정 시 기술지원기술인을 빼도 되나?"
# 질의에서, 「건설엔지니어링 대가 등에 관한 기준」 제9조 ① "시공단계의 기술인수는 기술지원기술인수를
# 포함한다"와 별표 2 바목 "단순 10%·보통 15%·복잡 20%"를 가져오지 못해, AI가 조문 번호도 수치도
# 못 대고 '일정 비율' 같은 일반론만 답함). 법제처 API(target=admrul)는 별표 전문(표 포함)을
# 텍스트로 이미 내려주고 있으므로, 이쪽에서 요청해서 질의와 관련된 조문/별표 조각만 골라 넘긴다.
# ---------------------------------------------------------------------------
_ADM_TTL = 6 * 3600          # 이름 -> 현행 일련번호 조회 결과 캐시 시간(초)
_ADM_DOC_CACHE_MAX = 8       # 파싱된 본문 캐시 개수(고시 1건이 수 MB일 수 있어 작게 유지)
_ADM_LOCK = threading.Lock()
_ADM_LOOKUP = {}             # 공백제거 이름 -> (만료시각, meta | None)
_ADM_DOCS = {}               # 행정규칙일련번호 -> 파싱된 문서(dict). 개정되면 일련번호가 바뀌므로 안전.

_ADM_ART_HEAD = re.compile(r'^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:\(([^)]*)\))?')
_ADM_STRUCT_HEAD = re.compile(r'^\s*제\s*\d+\s*[편장절관]')      # "제1장 총칙" 같은 장/절 제목
_BP_BOX_ONLY = re.compile(r'^[\s┌┐└┘├┤┬┴┼─━│┃┏┓┗┛┣┫┳┻╋═║╔╗╚╝╠╣╦╩╬]+$')
_BP_TOP = re.compile(r'^\s{0,4}\d{1,2}\.\s')                    # "3. 건설사업관리 직접경비 ..."
_BP_MOK = re.compile(r'^\s{0,8}[가-하]\.\s')                    # "바. 기술지원기술인(시공단계...)"


def _ad_key(name: str) -> str:
    key = re.sub(r'\s+', '', name or '')
    for ch in '·・･•∙⋅':
        key = key.replace(ch, 'ㆍ')
    return key


def _fmt_ymd(ymd: str) -> str:
    ymd = (ymd or '').strip()
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if len(ymd) == 8 and ymd.isdigit() else ymd


def _admrul_search(query: str, nw: int = 0) -> list:
    """lawSearch(target=admrul) 결과를 dict 목록으로. nw=0이면 기본(현행), 3이면 시행예정, 2면 연혁."""
    url = (f"https://www.law.go.kr/DRF/lawSearch.do?OC={MOLEG_API_KEY}&target=admrul&type=XML"
           f"&query={urllib.parse.quote(query)}&display=20" + (f"&nw={nw}" if nw else ""))
    root = _fetch_law_xml_with_retry(url)
    hits = []
    for a in root.findall('.//admrul'):
        hits.append({
            'name': (a.findtext('행정규칙명') or '').strip(),
            'mst': (a.findtext('행정규칙일련번호') or '').strip(),
            'ymd': (a.findtext('시행일자') or '').strip(),
            'org': (a.findtext('소관부처명') or '').strip(),
            'kind': (a.findtext('행정규칙종류') or '').strip(),
            'current': (a.findtext('현행연혁구분') or '현행').strip() == '현행',
        })
    return hits


def _admrul_pending_ymd(meta: dict) -> str:
    """현재 시행 중인 본문 외에, 아직 시행 전인 개정본(시행예정)이 있으면 그 시행일을 돌려준다."""
    today = datetime.date.today().strftime('%Y%m%d')
    try:
        future = [h['ymd'] for h in _admrul_search(meta['name'], nw=3)
                  if _ad_key(h['name']) == _ad_key(meta['name']) and h['mst'] != meta['mst'] and h['ymd'] > today]
        return min(future) if future else ''
    except Exception as e:
        print(f"[moleg_mcp] 시행예정 조회 실패({meta['name']}): {type(e).__name__}: {e}")
        return ''


def _lookup_admrul(name: str):
    """행정규칙명 -> 현행 본문의 meta(dict) 또는 None. 이름이 정확히 같은 현행본만 신뢰하고,
    정확히 일치가 없을 때만(6자 이상) 이름이 포함된 가장 짧은 이름을 쓴다. 조회 실패는 캐시하지 않는다."""
    key = _ad_key(name)
    if len(key) < 4:
        return None
    now = time.time()
    with _ADM_LOCK:
        cached = _ADM_LOOKUP.get(key)
        if cached and cached[0] > now:
            return cached[1]
    try:
        hits = [h for h in _admrul_search(name) if h['current'] and h['mst']]
    except Exception as e:
        print(f"[moleg_mcp] 행정규칙 검색 실패({name}): {type(e).__name__}: {e}")
        return None
    exact = sorted((h for h in hits if _ad_key(h['name']) == key), key=lambda h: h['ymd'], reverse=True)
    if exact:
        meta = exact[0]
    elif len(key) >= 6:
        fuzzy = sorted((h for h in hits if key in _ad_key(h['name'])), key=lambda h: len(h['name']))
        meta = fuzzy[0] if fuzzy else None
    else:
        meta = None
    if meta:
        meta = dict(meta, pending=_admrul_pending_ymd(meta))
    with _ADM_LOCK:
        _ADM_LOOKUP[key] = (now + _ADM_TTL, meta)
    return meta


def _chunk_byeolpyo(content: str, max_chunk: int = 1800) -> list:
    """별표 본문(표는 박스 문자 텍스트)을 '호(1.)·목(가.)' 경계로 잘라 [(상위 호 제목, 본문)]으로 돌려준다.
    별표 1건이 수십만 자일 수 있어 통째로 프롬프트에 넣을 수 없으므로, 질의와 관련된 조각만 고르기 위한 단위다.
    표의 테두리 줄은 버리고 칸 구분은 ' | '로 줄여서 글자 수를 아낀다."""
    chunks, cur, cur_len, top, cur_top = [], [], 0, '', ''

    def flush():
        nonlocal cur, cur_len
        if cur:
            chunks.append((cur_top, "\n".join(cur)))
        cur, cur_len = [], 0

    for raw in (content or '').replace('\r', '').split('\n'):
        if not raw.strip() or _BP_BOX_ONLY.match(raw):
            continue
        line = re.sub(r'\s*[│┃║]\s*', ' | ', raw).strip(' |')
        line = re.sub(r'[ 　]{2,}', ' ', line).strip()
        if not line:
            continue
        if _BP_TOP.match(raw):
            flush()
            top = line[:80]
        elif _BP_MOK.match(raw):
            flush()
        elif cur and cur_len + len(line) > max_chunk:
            flush()
        if not cur:
            cur_top = top
        cur.append(line)
        cur_len += len(line) + 1
    flush()
    return chunks


def _bp_label(no: int, br: int) -> str:
    return f"별표 {no}" + (f"의{br}" if br else "")


def _load_admrul_doc(mst: str) -> dict:
    """행정규칙 본문을 한 번만 가져와 {'info','articles','byeolpyo','buchik','pool'}로 파싱해 캐시한다.
    pool은 질의 관련 조각 선택용: [(종류('art'|'bp'), 헤더, 본문)]."""
    with _ADM_LOCK:
        doc = _ADM_DOCS.get(mst)
    if doc:
        return doc
    root = _fetch_law_xml_with_retry(
        f"https://www.law.go.kr/DRF/lawService.do?OC={MOLEG_API_KEY}&target=admrul&ID={mst}&type=XML", timeout=40)
    if root.tag != 'AdmRulService':
        raise RuntimeError(f"예상과 다른 응답({root.tag})")
    base = root.find('행정규칙기본정보')
    info = {
        'name': (base.findtext('행정규칙명') or '').strip() if base is not None else '',
        'ymd': (base.findtext('시행일자') or '').strip() if base is not None else '',
        'org': (base.findtext('소관부처명') or '').strip() if base is not None else '',
        'kind': (base.findtext('행정규칙종류') or '').strip() if base is not None else '',
        'current': ((base.findtext('현행여부') or 'Y').strip() == 'Y') if base is not None else True,
    }
    articles = []
    for e in root.findall('.//조문내용'):
        text = (e.text or '').strip()
        if not text or _ADM_STRUCT_HEAD.match(text):
            continue
        m = _ADM_ART_HEAD.match(text)
        articles.append({
            'no': int(m.group(1)) if m else 0, 'br': int(m.group(2)) if m and m.group(2) else 0,
            'title': (m.group(3) or '') if m else '', 'text': text})
    byeolpyo = []
    for b in root.findall('.//별표단위'):
        if (b.findtext('별표구분') or '').strip() not in ('별표', ''):
            continue
        no = (b.findtext('별표번호') or '').strip()
        br = (b.findtext('별표가지번호') or '').strip()
        byeolpyo.append({
            'no': int(no) if no.isdigit() else 0, 'br': int(br) if br.isdigit() else 0,
            'title': (b.findtext('별표제목') or '').strip(), 'content': b.findtext('별표내용') or ''})
    buchik = [(x.text or '').strip() for x in root.findall('.//부칙내용') if (x.text or '').strip()]

    pool = [('art', '', a['text'][:2500]) for a in articles]
    for bp in byeolpyo:
        label = _bp_label(bp['no'], bp['br'])
        for top, body in _chunk_byeolpyo(bp['content']):
            ctx = f" · {top}" if top and not body.startswith(top[:20]) else ''
            pool.append(('bp', f"[{label}: {bp['title']}{ctx}]", body))
    doc = {'info': info, 'articles': articles, 'byeolpyo': byeolpyo, 'buchik': buchik, 'pool': pool}
    with _ADM_LOCK:
        if len(_ADM_DOCS) >= _ADM_DOC_CACHE_MAX:
            _ADM_DOCS.pop(next(iter(_ADM_DOCS)))
        _ADM_DOCS[mst] = doc
    return doc


def load_admrul_by_name(name: str):
    """(meta, doc) 또는 (None, None). 인용 검증기(citation_check)가 고시 조문/별표 원문을 대조할 때 쓴다."""
    meta = _lookup_admrul(name)
    if not meta:
        return None, None
    try:
        return meta, _load_admrul_doc(meta['mst'])
    except Exception as e:
        print(f"[moleg_mcp] 행정규칙 본문 조회 실패({name}): {type(e).__name__}: {e}")
        return None, None


def _admrul_detail_text(doc: dict, keywords: list, max_len: int = 7000) -> str:
    """질의 키워드와 관련 높은 조문/별표 조각만 원문 그대로 골라 이어붙인다(최근 부칙, 별표 목록 포함)."""
    pool = doc['pool']
    scored = _rank_by_keywords([p[2] for p in pool], keywords)
    picked, total = [], 0
    for _score, idx in scored:
        size = len(pool[idx][2])
        if total + size > max_len and picked:
            continue
        picked.append(idx)
        total += size
        if total >= max_len:
            break
    parts = []
    for idx in sorted(picked):
        kind, header, body = pool[idx]
        parts.append(body if kind == 'art' else f"{header}\n{body}")
    if not parts:
        toc = "; ".join(f"제{a['no']}조({a['title']})" for a in doc['articles'][:40] if a['no'])
        parts.append(f"(질의 키워드와 일치하는 조문/별표 조각을 찾지 못했습니다. 조문 목차: {toc})")
    body = "\n\n".join(parts)
    if doc['byeolpyo']:
        body += "\n\n[이 고시의 별표 목록] " + "; ".join(
            f"{_bp_label(b['no'], b['br'])} {b['title']}" for b in doc['byeolpyo'])
    # 부칙은 오래된 개정 -> 최근 개정 순이므로 뒤에서부터 최대 3개만 담는다.
    recent, used = [], 0
    for b in reversed(doc['buchik']):
        if recent and used + len(b) > 1500:
            break
        recent.append(b[:1500])
        used += len(b)
        if len(recent) >= 3:
            break
    if recent:
        body += ("\n\n[부칙(최근 개정분) - 시행일·경과조치. 조문이 지금 적용되는지는 여기 명시된 시행일을 기준으로 확인할 것]\n"
                 + "\n\n".join(recent))
    return body


def search_admrul_with_text(names: list, topic_keywords: list,
                            per_len: int = 7000, max_total_len: int = 16000) -> str:
    """정식 행정규칙명(고시·훈령·예규·지침)으로 현행 본문을 조회해, 질의와 관련된 조문과 별표 조각을
    원문 그대로 돌려준다. 헤더에 소관·종류·시행일·현행 여부를 밝혀서 답변이 시행일을 함께 인용할 수 있게 하고,
    시행 전 개정본이 있으면 그 사실도 알린다. 이름이 정확히 일치하는 현행본이 없으면 아무것도 지어내지 않고 건너뛴다.

    헤더를 '[법령 원문 발췌: ...]'가 아닌 '[행정규칙 원문 발췌: ...]'로 쓰는 이유: 앞의 헤더는 링크 자동 생성
    (law_linkify)이 /법령/ 주소로 연결하는 법령명 목록에 쓰이므로, 고시가 섞이면 잘못된 주소가 만들어진다."""
    names = [n for n in dict.fromkeys(names or []) if n]
    if not names:
        return ""

    def prepare(name):
        meta, doc = load_admrul_by_name(name)
        return name, meta, doc

    with ThreadPoolExecutor(max_workers=min(3, len(names))) as ex:
        prepared = list(ex.map(prepare, names))

    sections, seen, total = [], set(), 0
    today = datetime.date.today().strftime('%Y-%m-%d')
    for name, meta, doc in prepared:
        if not meta or not doc or meta['mst'] in seen:
            continue
        if total >= max_total_len:
            break
        seen.add(meta['mst'])
        text = _admrul_detail_text(doc, topic_keywords, min(per_len, max_total_len - total))
        info = doc['info']
        link = f"https://www.law.go.kr/행정규칙/{urllib.parse.quote(meta['name'])}"
        status = "현행" if info['current'] else "현행 아님"
        head = (f"[행정규칙 원문 발췌: {meta['name']}] ({info['org']} {info['kind']}, "
                f"시행 {_fmt_ymd(info['ymd'])}, {status}, 법제처 조회 {today}) ({link})")
        if meta.get('pending'):
            head += (f"\n※ {_fmt_ymd(meta['pending'])} 시행 예정인 개정본이 있습니다. 아래는 현재 시행 중인 본문이며, "
                     f"시행일 이후에는 달라질 수 있습니다.")
        sections.append(f"{head}\n{text}")
        total += len(text)
    return "\n\n".join(sections)


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
        root = _fetch_law_xml_with_retry(url)

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
    root = _fetch_law_xml_with_retry(url)

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
