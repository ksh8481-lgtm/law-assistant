"""
개발사업 스마트 법규 검토: 사용자가 입력한 값에서 **확정되는** 룰 엔진 변수를 만든다.

지식 기반(law_knowledge_base.json)의 조건은 total_project_cost(원), total_budget(억 원), total_area_sqm, location_type, facility_type처럼
같은 뜻의 변수를 규칙마다 다른 이름으로 쓴다. 이 값들을 AI 추출기가 짐작해서 채우면 규칙이 발동했다 안 했다 한다(남해군 중기지방재정계획·투자심사 등).
사업비·면적·필지 주소처럼 입력에서 확실히 아는 값은 여기서 직접 만들어 AI 추출값 위에 덮어쓴다. 모르는 것(공사비, 계약금액, 굴착 깊이 …)은 만들지 않는다.
"""
import re

_COUNTY = re.compile(r'(?:^|\s)[가-힣]+군(?:\s|$)')          # "남해군"처럼 '군' 단위 시군구 토큰
_CITY = re.compile(r'(?:^|\s)[가-힣]+(?<!광역)시(?:\s|$)')   # "창원시" (광역시·특별시는 제외하려고 아래에서 따로 거른다)


def _text(*parts):
    return ' '.join(str(p or '') for p in parts)


def derive_flags(project_name, project_type, budget_eok, total_area, description, parcels):
    """입력에서 확정되는 변수 dict. 조건이 참일 때만 True인 표시 변수는 거짓이면 아예 만들지 않는다(모르는 값과 아닌 값을 구분하지 않으려고)."""
    flags = {}
    try:
        b = float(budget_eok)
    except (TypeError, ValueError):
        b = 0.0
    if b > 0:
        flags['total_budget'] = b                           # 억 원
        flags['total_project_cost'] = b * 100_000_000       # 원
    try:
        a = float(total_area)
    except (TypeError, ValueError):
        a = 0.0
    if a > 0:
        flags['total_area_sqm'] = a
        flags['land_area'] = a
        flags['development_area'] = a

    addrs = [str(p.get('address') or '') for p in (parcels or [])]
    if addrs:
        county = all(_COUNTY.search(x) for x in addrs)
        city = any(_CITY.search(x) and '광역시' not in x and '특별시' not in x for x in addrs)
        if county and not city:
            flags['location_type'] = 'county'               # 군 지역 사업(투자심사 기준 등이 군/도로 나뉜다)

    text = _text(project_name, description)
    if '도로' in text and '하천' not in text:
        flags['facility_type'] = 'road'
    elif '하천' in text and '도로' not in text:
        flags['facility_type'] = 'river'
    if '도로' in text and re.search(r'굴착|매설|관로', text):
        flags['has_road_excavation'] = True                 # 도로를 굴착해 지하매설물을 넣거나 바꾸는 공사
    if parcels:
        flags['has_parcels'] = True
    return flags
