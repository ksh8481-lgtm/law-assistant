import os
import json
import urllib.parse
import xml.etree.ElementTree as ET
import requests

API_KEY = "ksh8481"

# We import TARGET_LAWS from crawler.py
import crawler

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'law_urls.json')

def fetch_law_xml(search_url):
    try:
        res = requests.get(search_url, timeout=10)
        if res.status_code == 200:
            return ET.fromstring(res.content)
    except Exception as e:
        print(f"Request failed: {e}")
    return None

def main():
    law_urls = {}
    print("Generating law_urls.json mapping...")
    
    for law_name in crawler.TARGET_LAWS:
        mst_id = None
        target_type = None
        
        # 1. Try 'law' target
        search_url_law = f"https://www.law.go.kr/DRF/lawSearch.do?OC={API_KEY}&target=law&type=XML&query={urllib.parse.quote(law_name)}"
        root = fetch_law_xml(search_url_law)
        
        if root is not None:
            for law in root.findall('.//law'):
                name = law.find('법령명한글').text if law.find('법령명한글') is not None else ""
                if name and name.replace(" ", "") == law_name.replace(" ", ""):
                    mst_id = law.find('법령일련번호').text
                    target_type = 'law'
                    break
                    
            if not mst_id:
                for law in root.findall('.//law'):
                    name = law.find('법령명한글').text if law.find('법령명한글') is not None else ""
                    if name and law_name.replace(" ", "") in name.replace(" ", ""):
                        mst_id = law.find('법령일련번호').text
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
                        target_type = 'admrul'
                        break
                
                if not mst_id:
                    for admrul in root.findall('.//admrul'):
                        name = admrul.find('행정규칙명').text if admrul.find('행정규칙명') is not None else ""
                        if name and law_name.replace(" ", "") in name.replace(" ", ""):
                            mst_id = admrul.find('행정규칙일련번호').text
                            target_type = 'admrul'
                            break

        if mst_id and target_type:
            if target_type == 'law':
                law_urls[law_name] = f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={mst_id}"
            else:
                law_urls[law_name] = f"https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq={mst_id}"
            print(f"[OK] {law_name} -> {law_urls[law_name]}")
        else:
            print(f"[FAIL] Could not find {law_name}")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(law_urls, f, ensure_ascii=False, indent=4)
        
    print(f"Successfully generated {OUTPUT_FILE} with {len(law_urls)} entries.")

if __name__ == "__main__":
    main()
