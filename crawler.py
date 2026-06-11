import os
import requests
import xml.etree.ElementTree as ET
import urllib.parse
import time

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
    "지방자치단체 입찰 및 계약집행기준",
    "지방자치단체 입찰시 낙찰자 결정기준",
    "건설공사 사업관리방식 검토기준 및 업무수행지침",
    "건설공사 안전관리 업무수행 지침",
    "건설공사 품질관리 업무지침",
    "시설물의 안전 및 유지관리 실시 등에 관한 지침",
    "우수유출저감대책 및 시설에 관한 기준",
    "재해영향평가등의 협의 실무지침"
]

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'laws')
os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_law_xml(search_url):
    try:
        res = requests.get(search_url, timeout=30)
        if res.status_code == 200:
            return ET.fromstring(res.content)
    except Exception as e:
        print(f"Request failed: {e}")
    return None

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
            if name and name.replace(" ", "") == law_name.replace(" ", ""):
                mst_id = law.find('법령일련번호').text
                exact_name = name
                target_type = 'law'
                break
                
        if not mst_id:
            for law in root.findall('.//law'):
                name = law.find('법령명한글').text if law.find('법령명한글') is not None else ""
                if name and law_name.replace(" ", "") in name.replace(" ", ""):
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
                if name and name.replace(" ", "") == law_name.replace(" ", ""):
                    mst_id = admrul.find('행정규칙일련번호').text
                    exact_name = name
                    target_type = 'admrul'
                    break
            
            if not mst_id:
                for admrul in root.findall('.//admrul'):
                    name = admrul.find('행정규칙명').text if admrul.find('행정규칙명') is not None else ""
                    if name and law_name.replace(" ", "") in name.replace(" ", ""):
                        mst_id = admrul.find('행정규칙일련번호').text
                        exact_name = name
                        target_type = 'admrul'
                        break

    if not mst_id:
        print(f"Could not find exact match for {law_name}")
        return

    print(f"Found {target_type} ID: {mst_id} for {exact_name}. Fetching full details...")
    
    if target_type == 'law':
        detail_url = f"https://www.law.go.kr/DRF/lawService.do?OC={API_KEY}&target=law&MST={mst_id}&type=XML"
    else:
        detail_url = f"https://www.law.go.kr/DRF/lawService.do?OC={API_KEY}&target=admrul&ID={mst_id}&type=XML"
        
    detail_root = fetch_law_xml(detail_url)
    if detail_root is None:
        print(f"Failed to fetch details for {exact_name}")
        return

    md_content = f"# {exact_name}\n\n"
    md_content += "## 본문 (조문)\n\n"
    
    if target_type == 'law':
        for jomun in detail_root.findall('.//조문단위'):
            jomun_title = jomun.find('조문내용')
            if jomun_title is not None and jomun_title.text:
                md_content += f"{jomun_title.text.strip()}\n"
            
            for hang in jomun.findall('.//항내용'):
                if hang.text:
                    md_content += f"  {hang.text.strip()}\n"
            for ho in jomun.findall('.//호내용'):
                if ho.text:
                    md_content += f"    {ho.text.strip()}\n"
            md_content += "\n"
    else:
        # admrul
        texts = [t.text.strip() for t in detail_root.findall('.//조문내용') if t.text and t.text.strip()]
        if texts:
            md_content += "\n\n".join(texts) + "\n\n"
        else:
            md_content += "본문 내용이 텍스트로 제공되지 않았습니다. (법제처 시스템에 첨부파일 형태로만 존재하는 행정규칙입니다.)\n\n"

    md_content += "## 별표 및 서식 (Attached Tables)\n\n"
    tables_found = False
    
    # Process 별표단위 for both
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

    # Some admrul might just have <별표내용> at root without <별표단위>
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

def crawl_laws():
    print("Starting crawler...")
    for law_name in TARGET_LAWS:
        process_law(law_name)
    print("Crawling complete.")

if __name__ == "__main__":
    crawl_laws()
