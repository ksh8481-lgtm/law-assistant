import json
import os

input_file = os.path.join(os.path.dirname(__file__), 'supervisor_checklist.json')
with open(input_file, 'r', encoding='utf-8') as f:
    old_data = json.load(f)

stages = {
    "착공 전": {"stage_id": "STG_PRE", "stage_name": "착공 전 단계", "checklists": []},
    "시공 중": {"stage_id": "STG_CON", "stage_name": "시공 중 단계", "checklists": []},
    "준공": {"stage_id": "STG_POST", "stage_name": "준공 단계", "checklists": []},
    "전체": {"stage_id": "STG_ALL", "stage_name": "전체 공통 단계", "checklists": []}
}

for item in old_data:
    phase = item['phase']
    stage = stages.get(phase)
    if not stage: continue
    
    # Parse law_reference to get law_name. Many have something like "건축법 / 주택법" or "산업안전보건기준에 관한 규칙"
    law_name = item['law_reference'].split('/')[0].strip()
    
    new_item = {
        "task_id": f"TSK_{stage['stage_id']}_{item['id']:02d}",
        "category": item['category'],
        "task_name": item['check_item'],
        "law_name": law_name,
        "article_num": "",  # To be filled dynamically or left empty for general search
        "description": f"점검방법: {item['inspection_method']} / 중요도: {'필수' if item['is_critical'] else '일반'}",
        "memo": "추가 참고할 토목/건축 실무 팁이 여기에 표시됩니다.",
        "is_checked": False
    }
    stage['checklists'].append(new_item)

new_data = {
    "project_stages": [stages["착공 전"], stages["시공 중"], stages["준공"], stages["전체"]]
}

with open(input_file, 'w', encoding='utf-8') as f:
    json.dump(new_data, f, ensure_ascii=False, indent=4)

print("Conversion complete.")
