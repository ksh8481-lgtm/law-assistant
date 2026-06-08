import os
import requests
import xml.etree.ElementTree as ET
import urllib.parse
import time

API_KEY = "ksh8481"
TARGET_LAWS = [
    "민법"
]

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'laws')
os.makedirs(OUTPUT_DIR, exist_ok=True)

def crawl_laws():
    print("Starting law crawler for remaining laws...")
    for law_name in TARGET_LAWS:
        print(f"Searching for: {law_name}")
        search_url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={API_KEY}&target=law&type=XML&query={urllib.parse.quote(law_name)}"
        res = requests.get(search_url, timeout=10)
        
        if res.status_code != 200:
            print(f"Failed to search {law_name}")
            continue
            
        root = ET.fromstring(res.content)
        # Find exact or best match
        mst_id = None
        exact_name = None
        for law in root.findall('.//law'):
            name = law.find('법령명한글').text
            if name:
                if name.replace(" ", "") == law_name.replace(" ", ""):
                    mst_id = law.find('법령일련번호').text
                    exact_name = name
                    break
        
        if not mst_id:
            for law in root.findall('.//law'):
                name = law.find('법령명한글').text
                if name and law_name.replace(" ", "") in name.replace(" ", ""):
                    mst_id = law.find('법령일련번호').text
                    exact_name = name
                    break
                
        if not mst_id:
            print(f"Could not find exact match for {law_name}")
            continue
            
        print(f"Found MST ID: {mst_id} for {exact_name}. Fetching full details...")
        
        # Add retry loop
        detail_res = None
        for _ in range(3):
            try:
                detail_url = f"https://www.law.go.kr/DRF/lawService.do?OC={API_KEY}&target=law&MST={mst_id}&type=XML"
                detail_res = requests.get(detail_url, timeout=15)
                if detail_res.status_code == 200:
                    break
            except Exception as e:
                print(f"Retry {law_name}... error: {e}")
                time.sleep(3)
                
        if not detail_res or detail_res.status_code != 200:
            print(f"Failed to fetch details for {exact_name}")
            continue
            
        # Parse XML properly decoding text
        detail_root = ET.fromstring(detail_res.content)
        
        # Build Markdown content
        md_content = f"# {exact_name}\n\n"
        
        # 1. 조문 내용 (Articles)
        md_content += "## 본문 (조문)\n\n"
        for jomun in detail_root.findall('.//조문단위'):
            jomun_title = jomun.find('조문내용')
            if jomun_title is not None and jomun_title.text:
                md_content += f"{jomun_title.text.strip()}\n"
            
            # 항, 호 처리
            for hang in jomun.findall('.//항내용'):
                if hang.text:
                    md_content += f"  {hang.text.strip()}\n"
            for ho in jomun.findall('.//호내용'):
                if ho.text:
                    md_content += f"    {ho.text.strip()}\n"
            md_content += "\n"
            
        # 2. 별표 내용 (Attached Tables)
        md_content += "## 별표 및 서식 (Attached Tables)\n\n"
        tables_found = False
        for byul in detail_root.findall('.//별표단위'):
            byul_title = byul.find('별표제목')
            if byul_title is not None and byul_title.text:
                md_content += f"### {byul_title.text.strip()}\n"
                tables_found = True
            
            byul_content = byul.find('별표내용')
            if byul_content is not None and byul_content.text:
                # API provides pre-formatted text/HTML for tables
                md_content += "```text\n"
                md_content += f"{byul_content.text.strip()}\n"
                md_content += "```\n\n"
                
        if not tables_found:
            md_content += "이 법령에는 별표 및 서식이 없습니다.\n"
            
        # Save to file
        safe_filename = exact_name.replace(" ", "_").replace("/", "_") + ".md"
        file_path = os.path.join(OUTPUT_DIR, safe_filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        print(f"Saved {exact_name} to {safe_filename} ({len(md_content)} chars)")
        time.sleep(2) # Respect API limits

    print("Crawling complete.")

if __name__ == "__main__":
    crawl_laws()
