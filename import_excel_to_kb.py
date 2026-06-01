import json
import os
import google.generativeai as genai
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()
GEMINI_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_KEY:
    print("Error: GEMINI_API_KEY is not set.")
    exit(1)

genai.configure(api_key=GEMINI_KEY)

available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
model_name = None
for preferred in ['models/gemini-1.5-pro-latest', 'models/gemini-1.5-pro', 'models/gemini-1.5-flash-latest', 'models/gemini-1.5-flash', 'models/gemini-pro', 'models/gemini-1.0-pro']:
    if preferred in available_models:
        model_name = preferred
        break
if not model_name and available_models:
    model_name = available_models[0]

print(f"Using model: {model_name}")
model = genai.GenerativeModel(model_name)

# 1. 엑셀 파싱 JSON 로드
with open('checklist_output.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 2. 유효한 행정절차 필터링
valid_items = []
for item in data:
    name = item.get('건설공사 시행 절차')
    desc = item.get('Unnamed: 2')
    law = item.get('Unnamed: 3')
    if name and desc and type(name) == str and len(name) > 2 and '행정절차' not in name:
        valid_items.append({
            "name": name.replace('\n', ''),
            "target": desc.replace('\n', ' ') if type(desc) == str else '',
            "law": law.replace('\n', ' ') if type(law) == str else ''
        })

print(f"Total valid items to process: {len(valid_items)}")

# 3. 프롬프트 작성 및 AI 호출 (배치 처리)
chunk_size = 20
all_rules = []

for i in range(0, len(valid_items), chunk_size):
    chunk = valid_items[i:i+chunk_size]
    print(f"Processing chunk {i//chunk_size + 1}/{(len(valid_items)+chunk_size-1)//chunk_size}...")
    
    prompt = f"""
당신은 대한민국 현행법(2026년 기준) 전문 AI입니다.
아래는 건설사업 행정절차 체크리스트(2025년 기준)입니다.
각 항목을 검토하여 현재 2026년 법률 기준(면적, 금액 등)이 여전히 맞는지 확인 및 보정하세요.
그리고 각 항목을 Rule Engine 형식의 JSON Array로 변환하여 출력하세요.

[입력 데이터]
{json.dumps(chunk, ensure_ascii=False, indent=2)}

[출력 JSON 형식 요구사항]
오직 JSON Array만 반환하세요 (마크다운 백틱 제외).
각 객체는 다음 키를 포함해야 합니다:
- "id": 영문 대문자로 식별자 생성 (예: "LAW_TRAFFIC")
- "name": 행정절차명
- "law_link": <a> 태그를 포함한 관련 법령 링크
- "phase": "design" 또는 "construction"
- "condition": 파이썬 수식 조건 (예: "budget >= 500" 또는 "total_area >= 10000" 등)
- "desc": 보정된 2026년 최신 기준을 반영한 명확한 요약 설명
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        
        rules = json.loads(text.strip())
        all_rules.extend(rules)
    except Exception as e:
        print(f"Error processing chunk: {e}")

# 4. 결과 저장
with open('new_rules.json', 'w', encoding='utf-8') as f:
    json.dump(all_rules, f, ensure_ascii=False, indent=2)

print(f"Successfully generated new_rules.json with {len(all_rules)} rules!")
