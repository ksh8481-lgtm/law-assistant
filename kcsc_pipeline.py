import os
import sys
import requests
import json
import re
import time
import urllib3
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. 인증 및 환경 설정
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(env_path)
API_KEY = os.getenv('KCSC_API_KEY')

if not API_KEY:
    print("Error: KCSC_API_KEY not found in .env")
    exit(1)

# 2. API 호출 명세
CODE_LIST_URL = "https://kcsc.re.kr/OpenApi/CodeList"
CODE_VIEWER_URL = "https://kcsc.re.kr/OpenApi/CodeViewer"

def fetch_with_retry(url, params, max_retries=3):
    for attempt in range(max_retries):
        try:
            # verify=False is often needed for Korean gov APIs with custom SSL certs
            res = requests.get(url, params=params, verify=False, timeout=10)
            if res.status_code == 200:
                try:
                    return res.json()
                except:
                    # Sometimes they return XML or HTML if there's an error
                    return res.text
            print(f"Attempt {attempt+1} failed with status {res.status_code}")
        except Exception as e:
            print(f"Attempt {attempt+1} exception: {e}")
        time.sleep(2)
    return None

def chunk_text(text):
    """
    본문 텍스트를 항목(Section) 번호 기준으로 분할합니다.
    예: '1. 일반사항', '1.1 적용범위'
    """
    chunks = []
    current_header = "개요"
    current_content = []
    
    # 정규식: 숫자로 시작하고 점이 붙은 뒤 공백이 오고 글자가 오는 형태 (예: "1. 일반사항", "1.1 목적")
    header_pattern = re.compile(r'^([0-9]+(\.[0-9]+)*)\.?\s+[가-힣A-Za-z]+')
    
    lines = text.split('\n')
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
            
        if header_pattern.match(stripped):
            if current_content:
                chunks.append({
                    "section": current_header,
                    "content": "\n".join(current_content).strip()
                })
            current_header = stripped
            current_content = []
        else:
            current_content.append(stripped)
            
    if current_content:
        chunks.append({
            "section": current_header,
            "content": "\n".join(current_content).strip()
        })
        
    return chunks

def main():
    print("Starting KCSC API Pipeline...")
    
    # 3. 데이터 수집
    list_params = {
        "key": API_KEY,
        "pageNo": 1,
        "numOfRows": 5  # 시범 조회 5개
    }
    
    print(f"Fetching CodeList...")
    list_data = fetch_with_retry(CODE_LIST_URL, list_params)
    
    if not list_data or not isinstance(list_data, list):
        print("Failed to fetch or parse CodeList data.")
        print(f"Response snippet: {str(list_data)[:200]}")
        return
        
    print(f"Successfully fetched {len(list_data)} codes. Slicing to first 5 for testing.")
    list_data = list_data[:5]
    
    final_data = []
    
    for item in list_data:
        full_code = item.get('fullCode')
        code_type = item.get('codeType')
        name = item.get('name')
        
        if not full_code:
            continue
            
        print(f"\nProcessing {code_type} {full_code}: {name}")
        
        # CodeViewer 호출
        # 정답 URL 형식: /OpenApi/CodeViewer/{codeType}/{fullCode}?key={api_key}
        viewer_url = f"{CODE_VIEWER_URL}/{code_type}/{full_code}"
        viewer_params = {
            "key": API_KEY
        }
        
        viewer_res = fetch_with_retry(viewer_url, viewer_params)
        
        chunks = []
        if viewer_res and isinstance(viewer_res, list) and len(viewer_res) > 0:
            doc = viewer_res[0]
            section_list = doc.get("list", [])
            
            if section_list:
                print(f"[Success] Extracted {len(section_list)} native sections.")
                for sec in section_list:
                    chunks.append({
                        "section": sec.get("title", ""),
                        "content": sec.get("contents", "")
                    })
            else:
                print(f"[Warning] Response received but no sections found.")
        else:
            print(f"[Failed] Empty or invalid response for {full_code}.")
            
        final_data.append({
            "code": full_code,
            "type": code_type,
            "title": name,
            "chunks": chunks
        })
        
        time.sleep(1) # API 부하 방지
        
    # 4. 결과 저장
    out_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, 'kcsc_standards.json')
    
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
        
    print(f"\n[Pipeline Complete] Saved to {out_file}")

if __name__ == "__main__":
    main()
