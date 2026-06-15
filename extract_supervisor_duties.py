import os
import glob
import json
import time
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get('GEMINI_API_KEY')
if not API_KEY:
    print("No GEMINI_API_KEY found.")
    exit(1)

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-pro')

laws_dir = os.path.join(os.path.dirname(__file__), 'data', 'laws')
md_files = glob.glob(os.path.join(laws_dir, '*.md'))

all_duties = []

system_instruction = """
당신은 대한민국 건설공사 분야 최고 수준의 법규 분석가입니다.
제공된 법령/지침 텍스트를 읽고, **'공사감독관', '감독자', 또는 '발주청'이 공사 현장에서 반드시 수행해야 하는 업무, 검측 사항, 확인 서류 의무**를 모두 추출하세요.

결과는 반드시 아래 JSON 배열(Array) 포맷으로만 출력하십시오. (마크다운 백틱 없이 순수 JSON만 반환)
[
    {
        "phase": "착공 전" 또는 "시공 중" 또는 "준공" 중 택1,
        "category": "행정/기본" 또는 "안전/보건" 또는 "품질/시공" 또는 "환경/오염" 또는 "재해/방재" 또는 "기타" 중 택1,
        "task_name": "핵심 점검 항목 이름 (예: 품질시험계획서 확인)",
        "article_num": "관련 조항 번호 (예: 제14조)",
        "description": "상세한 업무 내용 및 점검 방법 요약",
        "memo": "이 항목을 수행할 때 토목 기술사 관점의 실무 팁 (1문장)"
    }
]
- 추출할 의무가 없다면 빈 배열 []을 반환하세요.
- JSON 외에 다른 설명은 절대 추가하지 마세요.
"""

for idx, file_path in enumerate(md_files):
    law_name = os.path.basename(file_path).replace('.md', '').replace('_', ' ')
    print(f"[{idx+1}/{len(md_files)}] Analyzing {law_name}...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    if len(content) < 100:
        continue
        
    prompt = f"{system_instruction}\n\n[법령 텍스트]\n{content[:150000]}"
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith('```json'):
            text = text[7:]
        if text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
            
        data = json.loads(text)
        if isinstance(data, list):
            for item in data:
                item['law_name'] = law_name
                all_duties.append(item)
    except Exception as e:
        print(f"Error parsing {law_name}: {e}")
        
    time.sleep(2)

stages = {
    "착공 전": {"stage_id": "STG_PRE", "stage_name": "착공 전 단계", "checklists": []},
    "시공 중": {"stage_id": "STG_CON", "stage_name": "시공 중 단계", "checklists": []},
    "준공": {"stage_id": "STG_POST", "stage_name": "준공 단계", "checklists": []},
    "전체": {"stage_id": "STG_ALL", "stage_name": "전체 공통 단계", "checklists": []}
}

task_counter = 1
for item in all_duties:
    phase = item.get('phase', '전체')
    if phase not in stages:
        phase = '전체'
        
    stage = stages[phase]
    
    new_item = {
        "task_id": f"TSK_{stage['stage_id']}_{task_counter:03d}",
        "category": item.get('category', '기타'),
        "task_name": item.get('task_name', '무제'),
        "law_name": item.get('law_name', ''),
        "article_num": item.get('article_num', ''),
        "description": item.get('description', ''),
        "memo": item.get('memo', ''),
        "is_checked": False
    }
    stage['checklists'].append(new_item)
    task_counter += 1

final_data = {
    "project_stages": [stages["착공 전"], stages["시공 중"], stages["준공"], stages["전체"]]
}

out_path = os.path.join(os.path.dirname(__file__), 'supervisor_db.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(final_data, f, ensure_ascii=False, indent=4)

print(f"Successfully extracted {len(all_duties)} duties and saved to {out_path}.")
