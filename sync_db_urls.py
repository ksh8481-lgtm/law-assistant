import json
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
law_urls_path = os.path.join(base_dir, 'data', 'law_urls.json')
db_path = os.path.join(base_dir, 'supervisor_db.json')

with open(law_urls_path, 'r', encoding='utf-8') as f:
    law_urls = json.load(f)

with open(db_path, 'r', encoding='utf-8') as f:
    db = json.load(f)

for stage in db.get("project_stages", []):
    for task in stage.get("checklists", []):
        law_name = task.get("law_name")
        if law_name in law_urls:
            task["law_url"] = law_urls[law_name]
            print(f"Updated: {law_name} -> {task['law_url']}")

with open(db_path, 'w', encoding='utf-8') as f:
    json.dump(db, f, ensure_ascii=False, indent=4)

print("supervisor_db.json updated successfully.")
