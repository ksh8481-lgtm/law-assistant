import json
import re

with open('law_knowledge_base.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for item in data:
    if 'law_link' in item and item['law_link'] is not None:
        # Remove all HTML tags
        clean_text = re.sub(r'<[^>]+>', '', item['law_link'])
        item['law_link'] = clean_text

with open('law_knowledge_base.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

print("Successfully cleaned HTML from law_knowledge_base.json")
