import json
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
law_urls_path = os.path.join(base_dir, 'data', 'law_urls.json')
law_urls_dict = {}
if os.path.exists(law_urls_path):
    with open(law_urls_path, 'r', encoding='utf-8') as f:
        law_urls_dict = json.load(f)

def process_item(item):
    if 'law_name' in item and item['law_name']:
        law_name = item['law_name']
        if law_name in law_urls_dict:
            item['law_url'] = law_urls_dict[law_name]
        else:
            import urllib.parse
            is_admrul = law_name.endswith('지침') or law_name.endswith('기준') or law_name.endswith('고시') or law_name.endswith('규정')
            base = 'https://www.law.go.kr/LSW/admRulSc.do?query=' if is_admrul else 'https://www.law.go.kr/LSW/lsSc.do?query='
            item['law_url'] = base + urllib.parse.quote(law_name)

test_json = {
    "permits": [
        {"law_name": "건축법", "article": "제11조"}
    ],
    "phases": {
        "design": [
            {"law_name": "건설공사 품질관리 업무지침", "article": "제10조"},
            {"law_name": "알수없는 임의 지침"}
        ]
    }
}

if 'permits' in test_json:
    for p in test_json['permits']: process_item(p)
if 'phases' in test_json:
    for phase_items in test_json['phases'].values():
        for t in phase_items: process_item(t)

print(json.dumps(test_json, indent=2, ensure_ascii=False))
