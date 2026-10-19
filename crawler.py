import os
import requests
import xml.etree.ElementTree as ET
import urllib.parse
import time
import zipfile
import io
import re
import sys
import threading
import traceback

API_KEY = "ksh8481"
TARGET_LAWS = [
    "지방자치단체를 당사자로 하는 계약에 관한 법률",
    "건설기술 진흥법",
    "건설산업기본법",
    "재난 및 안전관리 기본법",
    "시설물의 안전 및 유지관리에 관한 특별법",
    "지속가능한 기반시설 관리 기본법",
    "공유재산 및 물품 관리법",
    "국유재산법",
    "도로법",
    "자연재해대책법",
    "농어촌정비법",
    "민법",
    "건설공사 사업관리방식 검토기준 및 업무수행지침",
    "건설공사 안전관리 업무수행 지침",
    "건설공사 품질관리 업무지침",
    "시설물의 안전 및 유지관리 실시 등에 관한 지침",
    "우수유출저감대책 및 시설에 관한 기준",
    "지방자치단체 입찰 및 계약집행기준",
    "지방자치단체 입찰시 낙찰자 결정기준",
    "재해영향평가등의 협의 실무지침",
    "급경사지 재해예방에 관한 법률",
    "하천법",
    "소하천정비법",
    "저수지ㆍ댐의 안전관리 및 재해예방에 관한 법률",
    "소규모 공공시설 안전관리 등에 관한 법률",
    "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률",
    "농어촌도로 정비법",
    "공유수면 관리 및 매립에 관한 법률",
    "어촌ㆍ어항법",
    "국토의 계획 및 이용에 관한 법률",
    "지하안전관리에 관한 특별법",
    "공간정보의 구축 및 관리 등에 관한 법률",
    "건축법",
    "건축물관리법",
    "건축서비스산업 진흥법",
    "산지관리법",
    "농지법",
    "수도법",
    "하수도법",
    "환경영향평가법",
    "도시교통정비 촉진법",
    "해양공간계획 및 관리에 관한 법률",
    "해양이용영향평가법",
    "건설폐기물의 재활용촉진에 관한 법률",
    "폐기물관리법",
    "대기환경보전법",
    "소음·진동관리법",
    "물환경보전법",
    "지방회계법",
    "지방자치단체 보조금 관리에 관한 법률",
    "지방자치단체 기금관리기본법",
    "연안관리법",
    "매장유산 보호 및 조사에 관한 법률",
    "문화유산의 보존 및 활용에 관한 법률"
]

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'laws')
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {'User-Agent': 'Mozilla/5.0'}


def _mask(url):
    """로그에 인증키(OC)가 그대로 찍히지 않게 가린다."""
    return re.sub(r'OC=[^&]+', 'OC=***', url)


def http_get(url, tries=3, timeout=(10, 60), **kwargs):
    """GET 요청. 실패(예외·200 아님)하면 잠시 쉬었다가 최대 tries번 재시도하고, 끝내 실패하면 None.
    timeout=(연결, 읽기) 초 - 시간 제한이 없으면 서버가 응답을 흘려보낼 때 1시간 가까이 매달릴 수 있다."""
    last = None
    for i in range(1, tries + 1):
        try:
            res = requests.get(url, timeout=timeout, **kwargs)
            if res.status_code == 200:
                return res
            last = f"HTTP {res.status_code}"
        except Exception as e:
            last = repr(e)
        print(f"  [재시도 {i}/{tries}] {_mask(url)[:110]} -> {last}", flush=True)
        if i < tries:
            time.sleep(3 * i)
    print(f"Request failed after {tries} tries: {_mask(url)[:110]} -> {last}", flush=True)
    return None


def fetch_law_xml(search_url):
    res = http_get(search_url, headers=HEADERS)
    if res is None:
        return None
    try:
        return ET.fromstring(res.content)
    except Exception as e:
        print(f"XML parse failed: {e!r} ({_mask(search_url)[:110]})", flush=True)
        return None


def _norm(name):
    """법령명 비교용: 공백을 없애고 가운뎃점 변형(·ㆍ・∙)을 하나로 맞춘다(예: 소음·진동관리법 / 소음ㆍ진동관리법)."""
    return re.sub(r'[\s·ㆍ・∙‧]', '', name or '')

def extract_text_from_hwpx(hwpx_bytes):
    texts = []
    try:
        with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as z:
            for name in z.namelist():
                if name.startswith('Contents/section'):
                    xml_data = z.read(name)
                    xml_str = xml_data.decode('utf-8', errors='ignore')
                    xml_str = re.sub(r'\sxmlns="[^"]+"', '', xml_str, count=1)
                    xml_str = re.sub(r'hp:', '', xml_str)
                    
                    root = ET.fromstring(xml_str)
                    for p in root.iter('p'):
                        p_texts = []
                        for t in p.iter('t'):
                            if t.text:
                                p_texts.append(t.text)
                        if p_texts:
                            texts.append(''.join(p_texts))
    except Exception as e:
        print(f"Failed to parse HWPX: {e}")
    return '\n\n'.join(texts)

def process_law(law_name):
    print(f"Searching for: {law_name}")
    
    # 1. Try 'law' target
    search_url_law = f"https://www.law.go.kr/DRF/lawSearch.do?OC={API_KEY}&target=law&type=XML&query={urllib.parse.quote(law_name)}"
    root = fetch_law_xml(search_url_law)
    
    target_type = None
    mst_id = None
    exact_name = None
    
    if root is not None:
        for law in root.findall('.//law'):
            name = law.find('법령명한글').text if law.find('법령명한글') is not None else ""
            if name and _norm(name) == _norm(law_name):
                mst_id = law.find('법령일련번호').text
                exact_name = name
                target_type = 'law'
                break
                
        if not mst_id:
            for law in root.findall('.//law'):
                name = law.find('법령명한글').text if law.find('법령명한글') is not None else ""
                if name and _norm(law_name) in _norm(name):
                    mst_id = law.find('법령일련번호').text
                    exact_name = name
                    target_type = 'law'
                    break

    # 2. If not found, try 'admrul' target
    if not mst_id:
        search_url_admrul = f"https://www.law.go.kr/DRF/lawSearch.do?OC={API_KEY}&target=admrul&type=XML&query={urllib.parse.quote(law_name)}"
        root = fetch_law_xml(search_url_admrul)
        if root is not None:
            for admrul in root.findall('.//admrul'):
                name = admrul.find('행정규칙명').text if admrul.find('행정규칙명') is not None else ""
                if name and _norm(name) == _norm(law_name):
                    mst_id = admrul.find('행정규칙일련번호').text
                    exact_name = name
                    target_type = 'admrul'
                    break
            
            if not mst_id:
                for admrul in root.findall('.//admrul'):
                    name = admrul.find('행정규칙명').text if admrul.find('행정규칙명') is not None else ""
                    if name and _norm(law_name) in _norm(name):
                        mst_id = admrul.find('행정규칙일련번호').text
                        exact_name = name
                        target_type = 'admrul'
                        break

    if not mst_id:
        print(f"Could not find exact match for {law_name}")
        return False

    print(f"Found {target_type} ID: {mst_id} for {exact_name}. Fetching full details...")
    
    if target_type == 'law':
        detail_url = f"https://www.law.go.kr/DRF/lawService.do?OC={API_KEY}&target=law&MST={mst_id}&type=XML"
    else:
        detail_url = f"https://www.law.go.kr/DRF/lawService.do?OC={API_KEY}&target=admrul&ID={mst_id}&type=XML"
        
    detail_root = fetch_law_xml(detail_url)
    if detail_root is None:
        print(f"Failed to fetch details for {exact_name}")
        return False

    md_content = f"# {exact_name}\n\n"
    md_content += "## 본문 (조문)\n\n"
    
    extracted_text_length = 0
    
    if target_type == 'law':
        for jomun in detail_root.findall('.//조문단위'):
            jomun_title = jomun.find('조문내용')
            if jomun_title is not None and jomun_title.text:
                md_content += f"{jomun_title.text.strip()}\n"
                extracted_text_length += len(jomun_title.text)
            
            for hang in jomun.findall('.//항내용'):
                if hang.text:
                    md_content += f"  {hang.text.strip()}\n"
                    extracted_text_length += len(hang.text)
            for ho in jomun.findall('.//호내용'):
                if ho.text:
                    md_content += f"    {ho.text.strip()}\n"
                    extracted_text_length += len(ho.text)
            md_content += "\n"
    else:
        # admrul
        texts = [t.text.strip() for t in detail_root.findall('.//조문내용') if t.text and t.text.strip()]
        if texts:
            content_str = "\n\n".join(texts)
            md_content += content_str + "\n\n"
            extracted_text_length += len(content_str)
            
    # Check for HWPX fallback if text is very short (e.g. < 1000 chars)
    if target_type == 'admrul' and extracted_text_length < 1000:
        hwpx_link = None
        for f in detail_root.findall('.//첨부파일'):
            names = f.findall('첨부파일명')
            links = f.findall('첨부파일링크')
            for n, l in zip(names, links):
                if n.text and n.text.strip().endswith('.hwpx'):
                    hwpx_link = l.text.strip()
                    break
            if hwpx_link: break
            
        if hwpx_link:
            print(f"Text is short. Downloading HWPX attachment from {hwpx_link}...")
            req = http_get(hwpx_link, tries=3, timeout=(10, 120), headers=HEADERS)
            if req is not None:
                print("Extracting HWPX text...")
                hwpx_text = extract_text_from_hwpx(req.content)
                if hwpx_text:
                    md_content += "\n\n## 본문 및 별표 (첨부파일 추출본)\n\n"
                    md_content += hwpx_text

    # Tables
    md_content += "\n\n## 별표 및 서식 (Attached Tables)\n\n"
    tables_found = False
    
    for byul in detail_root.findall('.//별표단위'):
        byul_title = byul.find('별표제목')
        if byul_title is not None and byul_title.text:
            md_content += f"### {byul_title.text.strip()}\n"
            tables_found = True
        
        byul_content = byul.find('별표내용')
        if byul_content is not None and byul_content.text:
            md_content += "```text\n"
            md_content += f"{byul_content.text.strip()}\n"
            md_content += "```\n\n"

    if target_type == 'admrul' and not tables_found:
        byul_contents = detail_root.findall('.//별표내용')
        for i, byul_content in enumerate(byul_contents):
            if byul_content.text and byul_content.text.strip():
                md_content += f"### 별표 {i+1}\n"
                tables_found = True
                md_content += "```text\n"
                md_content += f"{byul_content.text.strip()}\n"
                md_content += "```\n\n"

    if not tables_found:
        md_content += "이 규정에는 별표 및 서식이 없거나 텍스트로 제공되지 않습니다.\n"

    safe_filename = exact_name.replace(" ", "_").replace("/", "_") + ".md"
    file_path = os.path.join(OUTPUT_DIR, safe_filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print(f"Saved {exact_name} to {safe_filename} ({len(md_content)} chars)")
    time.sleep(1)
    return True

LAW_TIMEOUT = 180        # 법령 하나에 쓸 수 있는 최대 시간(초) - 응답이 멈춘 요청 하나가 하루치 갱신을 통째로 막지 않게 한다
TOTAL_BUDGET = 22 * 60   # 전체 처리 시간 예산(초) - 워크플로 제한(30분)에 걸려 취소되기 전에 스스로 마무리해 지금까지 받은 것을 커밋한다


TIMEOUT = object()


def run_with_timeout(fn, arg, timeout):
    """fn(arg)를 별도 스레드에서 실행해 timeout초 안에 끝나면 결과를 돌려주고, 못 끝나면 (TIMEOUT, 멈춘 위치)를 돌려준다.
    멈춘 스레드는 강제로 끝낼 수 없으므로 버려 두고(daemon) 다음 법령으로 넘어간다 - 프로그램 종료를 막지 않는다."""
    box = {}

    def target():
        try:
            box['result'] = fn(arg)
        except BaseException as e:  # 예외도 호출한 쪽으로 넘긴다
            box['error'] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        frame = sys._current_frames().get(t.ident)
        where = ''.join(traceback.format_stack(frame)[-6:]) if frame else ''
        return TIMEOUT, where
    if 'error' in box:
        raise box['error']
    return box['result'], ''



def crawl_laws():
    """법령 하나가 실패해도 나머지는 계속 받는다. 실패한 법령은 이전 파일이 그대로 남는다.
    전부 실패했을 때만(= 접속 자체가 막힌 경우) 종료 코드 1로 알려, 부분 실패 때문에 나머지 갱신이 통째로 버려지지 않게 한다.
    법령 하나가 LAW_TIMEOUT초 넘게 멈추면 어디서 멈췄는지 로그에 남기고 넘어가며, 전체가 TOTAL_BUDGET초를 넘기면 남은 법령은 다음 실행으로 미룬다."""
    print("Starting crawler...", flush=True)
    ok, failed, skipped = 0, [], []
    began = time.time()
    for i, law_name in enumerate(TARGET_LAWS):
        if time.time() - began > TOTAL_BUDGET:
            skipped = TARGET_LAWS[i:]
            print(f"::warning::처리 시간 예산({TOTAL_BUDGET // 60}분)을 넘겨 남은 {len(skipped)}건은 다음 실행으로 미룹니다.", flush=True)
            break
        t0 = time.time()
        try:
            res, where = run_with_timeout(process_law, law_name, LAW_TIMEOUT)
            if res is TIMEOUT:
                failed.append(law_name)
                print(f"::warning::{law_name}: {LAW_TIMEOUT}초 넘게 응답이 없어 건너뜁니다(이전 파일 유지). 멈춘 위치:\n{where}", flush=True)
            elif res:
                ok += 1
            else:
                failed.append(law_name)   # 찾지 못했거나 본문을 받지 못함 - 이전 파일 유지
        except Exception as e:
            failed.append(law_name)
            print(f"::warning::{law_name} 처리 중 예외: {e!r}", flush=True)
            traceback.print_exc()
            sys.stdout.flush()
        took = time.time() - t0
        if took > 60:
            print(f"  (참고) {law_name} 처리에 {took:.0f}초 걸림", flush=True)
    print(f"Crawling complete. 성공 {ok}건 / 실패 {len(failed)}건 / 미룸 {len(skipped)}건 (총 {time.time() - began:.0f}초)", flush=True)
    if failed:
        print("실패한 법령(이전 파일 유지): " + ", ".join(failed), flush=True)
    if ok == 0:
        print("::error::모든 법령 크롤링에 실패했습니다(법제처 API 접속 문제 가능성).", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    crawl_laws()
