import json
import os
import ast


class _Missing:
    """값을 모르는 변수. 비교(<, <=, >, >=, ==, !=)는 모두 거짓이고 참/거짓 판정도 거짓이다.

    예전에는 모르는 변수를 False(= 0)로 읽었다. 그러면 `distance_to_school_m <= 4`처럼 '작다'를 묻는 조건이 변수 없이도 참이 되어
    어떤 사업에도 "교육시설 안전성평가"·"예비준공검사"가 붙었다. 모르면 조건을 만족한 것으로 보지 않는다.
    """
    __slots__ = ()

    def __bool__(self):
        return False

    def _no(self, other):
        return False

    __lt__ = __le__ = __gt__ = __ge__ = __eq__ = __ne__ = _no
    __hash__ = object.__hash__

    def __repr__(self):
        return '<값 모름>'


_MISSING = _Missing()


class SafeDict(dict):
    def __missing__(self, key):
        return _MISSING


def _load_kb():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, 'law_knowledge_base.json')
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print("Error loading Knowledge Base:", e)
        return []


def _names(condition):
    try:
        return {n.id for n in ast.walk(ast.parse(condition)) if isinstance(n, ast.Name)}
    except Exception:
        return set()


def get_all_variables():
    vars_set = set()
    for rule in _load_kb():
        condition = rule.get('condition', '')
        if condition and condition != 'True':
            vars_set.update(_names(condition))
    return sorted(list(vars_set))


def evaluate_knowledge_base(params):
    """조건식이 참인 규칙을 돌려준다. 조건 `True`인 규칙(어느 사업에나 해당)은 항상 포함한다.
    조건에 쓰인 변수를 하나도 모르면(`not is_xxx`처럼 모르는 값을 부정해서 참이 되는 경우 포함) 그 규칙은 해당하지 않는 것으로 본다."""
    known = {k: v for k, v in (params or {}).items() if v is not None}
    safe_params = SafeDict(known)
    matched_rules = []
    for rule in _load_kb():
        condition = rule.get('condition', 'False')
        if condition.strip() != 'True' and not (_names(condition) & known.keys()):
            continue
        try:
            # 안전하게 eval 실행 (내장 함수 사용 불가)
            if eval(condition, {"__builtins__": {}}, safe_params):
                matched_rules.append(rule)
        except Exception:
            # 조건식 오류 시 무시
            pass
    return matched_rules
