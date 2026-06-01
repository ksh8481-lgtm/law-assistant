import json
import os
import ast

class SafeDict(dict):
    def __missing__(self, key):
        return False

def get_all_variables():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, 'law_knowledge_base.json')
    if not os.path.exists(file_path):
        return []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            kb = json.load(f)
    except:
        return []
        
    vars_set = set()
    for rule in kb:
        condition = rule.get('condition', '')
        if condition and condition != 'True':
            try:
                vars_set.update([n.id for n in ast.walk(ast.parse(condition)) if isinstance(n, ast.Name)])
            except:
                pass
    return sorted(list(vars_set))

def evaluate_knowledge_base(params):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, 'law_knowledge_base.json')
    
    if not os.path.exists(file_path):
        return []
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            kb = json.load(f)
    except Exception as e:
        print("Error loading Knowledge Base:", e)
        return []
        
    matched_rules = []
    safe_params = SafeDict(params)
    
    for rule in kb:
        condition = rule.get('condition', 'False')
        try:
            # 안전하게 eval 실행 (내장 함수 사용 불가)
            if eval(condition, {"__builtins__": {}}, safe_params):
                matched_rules.append(rule)
        except Exception as e:
            # 조건식 오류 시 무시
            pass
            
    return matched_rules
