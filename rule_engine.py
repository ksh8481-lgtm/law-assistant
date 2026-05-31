import json
import os

def evaluate_knowledge_base(params):
    """
    params 딕셔너리를 받아서 law_knowledge_base.json의 조건식(condition)을 평가한 뒤,
    참(True)인 법령 목록을 반환합니다.
    """
    kb_path = os.path.join(os.path.dirname(__file__), 'law_knowledge_base.json')
    if not os.path.exists(kb_path):
        return []
        
    with open(kb_path, 'r', encoding='utf-8') as f:
        laws = json.load(f)
        
    matched_laws = []
    
    # 안전한 eval 환경 (허용된 변수만)
    # params: {'budget': 150, 'budget_nat': 0, 'total_area': 12000, 'has_mountain': True, 'has_farmland': False, 'is_public': True, 'is_construction': True, 'excavation_depth': 12, 'floors': 3}
    safe_env = {
        'budget': float(params.get('budget', 0)),
        'budget_nat': float(params.get('budget_nat', 0)),
        'total_area': float(params.get('total_area', 0)),
        'has_mountain': bool(params.get('has_mountain', False)),
        'has_farmland': bool(params.get('has_farmland', False)),
        'is_public': bool(params.get('is_public', True)), # 발주청 기본값 True
        'is_construction': bool(params.get('is_construction', True)),
        'excavation_depth': float(params.get('excavation_depth', 0)),
        'floors': int(params.get('floors', 0)),
        'True': True,
        'False': False
    }
    
    for law in laws:
        condition_str = law.get('condition', 'False')
        try:
            # 보안: 빌트인 함수 등 사용 차단
            if eval(condition_str, {"__builtins__": {}}, safe_env):
                matched_laws.append(law)
        except Exception as e:
            print(f"Rule evaluation error for {law.get('id')}: {e}")
            
    return matched_laws
