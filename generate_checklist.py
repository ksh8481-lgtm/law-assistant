import json
import os

items = [
    # 행정 및 기본 법규
    {"phase": "착공 전", "category": "행정/기본", "law_reference": "건설기술 진흥법", "check_item": "건설공사 감독 및 감리 업무 수행계획 수립 및 인력 배치 적정성 확인", "is_critical": False, "inspection_method": "서류 확인"},
    {"phase": "착공 전", "category": "행정/기본", "law_reference": "건축법 / 주택법", "check_item": "인허가(건축허가서) 조건 사항 확인 및 설계도서 일치 여부 사전 검토", "is_critical": True, "inspection_method": "도면 및 인허가 서류 대조"},
    {"phase": "시공 중", "category": "행정/기본", "law_reference": "건설산업기본법", "check_item": "하도급 적법성(불법 다단계 하도급 금지) 및 건설업 등록 기준 유지 확인", "is_critical": True, "inspection_method": "하도급 계약서 및 건설업 등록증 확인"},
    {"phase": "준공", "category": "행정/기본", "law_reference": "건축법", "check_item": "사용승인(준공)을 위한 준공도면, 검측서류, 품질시험성과 총괄표 확인", "is_critical": False, "inspection_method": "서류 및 현장 대조"},
    
    # 계약 및 기성 관리
    {"phase": "시공 중", "category": "계약/기성", "law_reference": "공사계약 일반조건", "check_item": "설계변경 사유 발생 시 실정보고 및 계약금액 조정 적정성 검토", "is_critical": False, "inspection_method": "서류 검토 (물가변동, 공기연장 포함)"},
    
    # 현장 안전 및 보건 관리
    {"phase": "전체", "category": "안전/보건", "law_reference": "중대재해 처벌 등에 관한 법률", "check_item": "경영책임자 및 현장 총괄자의 안전보건 확보 의무 이행 및 관리체계 구축", "is_critical": True, "inspection_method": "서류 및 현장 점검"},
    {"phase": "착공 전", "category": "안전/보건", "law_reference": "산업안전보건법", "check_item": "산업안전보건관리비 산정 적정성 및 위험성 평가 계획 수립 확인", "is_critical": True, "inspection_method": "계획서 검토"},
    {"phase": "시공 중", "category": "안전/보건", "law_reference": "산업안전보건기준에 관한 규칙", "check_item": "추락 방지망, 안전난간, 개구부 덮개 등 가설 안전시설물 설치 상태 확인", "is_critical": True, "inspection_method": "육안 및 실측 (사진촬영)"},
    {"phase": "시공 중", "category": "안전/보건", "law_reference": "가설공사 표준시방서", "check_item": "거푸집, 동바리, 비계 등 임시 가설구조물 조립 전 구조검토 및 시공 상태", "is_critical": True, "inspection_method": "현장 점검"},
    {"phase": "시공 중", "category": "안전/보건", "law_reference": "건설기계관리법", "check_item": "타워크레인, 굴착기 등 장비 반입 전 정기검사, 보험, 조종사 면허 확인", "is_critical": True, "inspection_method": "등록증 및 면허증 확인"},
    {"phase": "시공 중", "category": "안전/보건", "law_reference": "지하안전관리에 관한 특별법", "check_item": "10m 이상 굴착 시 지하안전평가 협의내용 이행 및 흙막이 계측 모니터링", "is_critical": True, "inspection_method": "계측 데이터 확인 및 현장 점검"},
    {"phase": "시공 중", "category": "안전/보건", "law_reference": "화재예방 관련 법률", "check_item": "용접 등 화기 작업 시 임시소방시설(소화기 등) 비치 및 화재감시자 배치", "is_critical": True, "inspection_method": "육안 검사"},
    
    # 품질 및 시공 기준
    {"phase": "착공 전", "category": "품질/시공", "law_reference": "건설공사 품질관리 업무지침", "check_item": "품질시험계획서 수립, 품질관리자 배치, 현장 시험실 규모 적정성", "is_critical": False, "inspection_method": "계획서 및 현장 확인"},
    {"phase": "시공 중", "category": "품질/시공", "law_reference": "국가건설기준 (KCS/KDS)", "check_item": "설계도면 및 표준시방서(KCS)에 따른 시공 여부 검측", "is_critical": True, "inspection_method": "현장 검측"},
    {"phase": "시공 중", "category": "품질/시공", "law_reference": "한국산업표준 (KS 규격)", "check_item": "반입되는 철근, 시멘트, 방수재 등 주요 자재의 자재공급원 승인 및 KS 정품 여부", "is_critical": True, "inspection_method": "송장 및 KS 인증서 확인"},
    {"phase": "시공 중", "category": "품질/시공", "law_reference": "레미콘·아스콘 품질관리 지침", "check_item": "현장 반입 레미콘 슬럼프, 공기량, 염화물 테스트 실시", "is_critical": True, "inspection_method": "현장 시험 입회 및 사진"},
    
    # 환경 관리 및 오염 통제
    {"phase": "착공 전", "category": "환경/오염", "law_reference": "석면안전관리법", "check_item": "철거 공사 시 사전 석면조사 결과 확인 및 전문 해체 업체 투입 여부", "is_critical": True, "inspection_method": "조사서 및 계약서 확인"},
    {"phase": "착공 전", "category": "환경/오염", "law_reference": "대기 및 소음·진동관리법", "check_item": "비산먼지 발생사업 신고 및 특정공사 사전신고 완료 여부", "is_critical": False, "inspection_method": "신고 필증 확인"},
    {"phase": "시공 중", "category": "환경/오염", "law_reference": "대기환경보전법", "check_item": "세륜기(바퀴 씻는 기계), 방진벽 설치 및 살수차 정상 운영", "is_critical": True, "inspection_method": "현장 순찰"},
    {"phase": "시공 중", "category": "환경/오염", "law_reference": "건설폐기물의 처리 등에 관한 법률", "check_item": "건설폐기물 성상별 분리배출 및 '올바로시스템' 전자인계서 등록 적법 반출", "is_critical": True, "inspection_method": "시스템 확인 및 현장 보관소 점검"},
    {"phase": "시공 중", "category": "환경/오염", "law_reference": "물환경보전법 / 하수도법", "check_item": "비점오염원(흙탕물) 저감용 가설 침사지 운영 및 가설 화장실 적법 처리", "is_critical": False, "inspection_method": "현장 점검"},
    {"phase": "시공 중", "category": "환경/오염", "law_reference": "토양환경보전법", "check_item": "굴착 중 유류 등 오염토양 발견 시 즉시 공사 중지 및 정화 조치 명령", "is_critical": True, "inspection_method": "현장 확인"},
    
    # 자연재해 및 방재 관리
    {"phase": "시공 중", "category": "재해/방재", "law_reference": "자연재해대책법", "check_item": "우기 대비 가배수로, 임시 침사지 확보 및 덮개(천막) 등 절개지 사면 안정 조치", "is_critical": True, "inspection_method": "현장 순찰 및 사진촬영"},
    {"phase": "준공", "category": "재해/방재", "law_reference": "자연재해대책법", "check_item": "설계도서 및 재해영향평가서에 따른 영구 저류지(저류조) 완공 확인", "is_critical": False, "inspection_method": "현장 실측"},
    
    # 기타 영향평가 및 심의
    {"phase": "시공 중", "category": "기타", "law_reference": "교육환경 보호에 관한 법률", "check_item": "통학로 안전대책(차량 통제) 이행 및 학교 주변 소음/분진 관리", "is_critical": True, "inspection_method": "소음 측정 및 순찰"},
    {"phase": "착공 전", "category": "기타", "law_reference": "매장문화재 보호 법률", "check_item": "착공 전 지표조사 이행 확인 및 작업자 대상 '유물 발견 시 신고' 교육", "is_critical": False, "inspection_method": "조사서 및 교육일지"},
    {"phase": "시공 중", "category": "기타", "law_reference": "도시교통정비 촉진법", "check_item": "교통영향평가에 따른 가감속차로 확보 및 신호수/교통통제요원 상시 배치", "is_critical": True, "inspection_method": "현장 확인"},
    {"phase": "시공 중", "category": "기타", "law_reference": "지자체 심의/조례", "check_item": "건축/경관 심의 결과 원안(마감재 색채 등) 준수 및 지역 자재 사용 권장 사항", "is_critical": False, "inspection_method": "승인 자재 대조"}
]

for idx, item in enumerate(items):
    item['id'] = idx + 1

file_path = r"c:\Users\ksh84\OneDrive\Desktop\antig\kshantigravity\backend\supervisor_checklist.json"
with open(file_path, "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=4)

print(f"Created {file_path} with {len(items)} items.")
