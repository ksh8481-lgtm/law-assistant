import os
import requests
import xml.etree.ElementTree as ET
import urllib.parse
import time
import zipfile
import io
import re

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
    "물환경보전법"
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
            req = requests.get(hwpx_link, headers={'User-Agent': 'Mozilla/5.0'})
            if req.status_code == 200:
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

def crawl_laws():
    print("Starting crawler...")
    for law_name in TARGET_LAWS:
        process_law(law_name)
    print("Crawling complete.")

if __name__ == "__main__":
    crawl_laws()
