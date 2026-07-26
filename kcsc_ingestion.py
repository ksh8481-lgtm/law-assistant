import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

def get_with_retry(url, params, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, verify=False, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"[{attempt+1}/{max_retries}] API 에러: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"[{attempt+1}/{max_retries}] 요청 실패: {e}")
        time.sleep(2)
    return None

def fetch_and_chunk_kcsc():
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    load_dotenv(env_path)
    api_key = os.getenv('KCSC_API_KEY')
    if not api_key:
        print("KCSC_API_KEY가 설정되지 않았습니다.")
        return

    # 1. CodeList 조회 (5개만 시범 조회)
    list_url = "https://kcsc.re.kr/OpenApi/CodeList"
    # CodeList 파라미터는 소문자 key 사용이 확인됨
    list_params = {
        "key": api_key,
        "pageNo": 1,
        "numOfRows": 5
    }

    print("CodeList API 호출 중...")
    code_list = get_with_retry(list_url, list_params)
    if not code_list:
        print("CodeList를 가져오지 못했습니다.")
        return

    viewer_url = "https://kcsc.re.kr/OpenApi/CodeViewer"
    final_data = []

    # 2. 각 코드별 CodeViewer 조회 및 Chunking
    for idx, item in enumerate(code_list):
        code_type = item.get('codeType', 'KDS')
        code_no = item.get('code', '')
        code_name = item.get('name', '')
        
        print(f"[{idx+1}/5] CodeViewer 호출 중: {code_type} {code_no} ({code_name})")
        # CodeViewer는 Type, Code, Key를 파라미터로 요구함
        viewer_params = {
            "Key": api_key,
            "Type": code_type,
            "Code": code_no
        }
        
        viewer_data = get_with_retry(viewer_url, viewer_params)
        if not viewer_data:
            print(f"{code_type} {code_no} 상세 데이터를 가져오지 못했습니다.")
            continue

        # Chunking 전처리 로직
        # API 응답 구조: List 필드 안에 Sort, Title, Contents 가 있음
        sections = []
        if isinstance(viewer_data, dict):
            # 단일 객체로 올 경우
            viewer_data = [viewer_data]
            
        for doc in viewer_data:
            doc_list = doc.get("list", [])
            if not doc_list:
                continue
                
            for section in doc_list:
                title = section.get("title", "")
                contents = section.get("contents", "")
                sort_no = section.get("sort", 0)
                
                # Title 또는 Sort 단위를 하나의 청크로 처리 (항목 번호 기준)
                if title or contents:
                    chunk = {
                        "codeType": code_type,
                        "code": code_no,
                        "codeName": code_name,
                        "sectionTitle": title,
                        "sortNo": sort_no,
                        "contents": contents
                    }
                    sections.append(chunk)
                    
        final_data.append({
            "document": f"{code_type} {code_no} {code_name}",
            "chunks": sections
        })
        time.sleep(1) # API 부하 방지

    # 3. 데이터 저장
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(data_dir, exist_ok=True)
    save_path = os.path.join(data_dir, 'kcsc_standards.json')
    
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
        
    print(f"\n총 {len(final_data)}개의 기준 문서에 대한 수집 및 분할 완료.")
    print(f"저장 위치: {save_path}")

if __name__ == "__main__":
    fetch_and_chunk_kcsc()
