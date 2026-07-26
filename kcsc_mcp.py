import os
import json
import re

class KCSCMCPEngine:
    def __init__(self):
        self.data_path = os.path.join(os.path.dirname(__file__), 'data', 'kcsc_standards.json')
        self.standards = []
        self._load_data()

    def _load_data(self):
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    self.standards = json.load(f)
                print(f"[KCSCMCPEngine] Loaded {len(self.standards)} KCSC standards from local DB.")
            except Exception as e:
                print(f"[KCSCMCPEngine] Error loading {self.data_path}: {e}")
        else:
            print(f"[KCSCMCPEngine] File not found: {self.data_path}")

    def search_kcsc_standards(self, query: str, max_results: int = 5) -> str:
        """
        KCSC (국가건설기준센터) KDS/KCS 표준시방서 및 설계기준을 키워드로 검색합니다.
        예: '흙막이', '콘크리트 압축강도', '가시설', '배수공서'
        """
        if not self.standards:
            return "[KCSC 검색 결과 없음: 로컬 데이터베이스가 비어 있습니다.]"

        query_terms = [t.strip().lower() for t in query.split() if len(t.strip()) > 1]
        if not query_terms:
            query_terms = [query.strip().lower()]

        results = []
        for std in self.standards:
            code = std.get('code', '')
            title = std.get('title', '')
            std_type = std.get('type', 'KDS')
            
            # 1. 제목이나 코드 매치
            title_lower = title.lower()
            code_lower = code.lower()
            
            score = 0
            for term in query_terms:
                if term in title_lower or term in code_lower:
                    score += 5
            
            # 2. 내용 매치
            matched_sections = []
            for chunk in std.get('chunks', []):
                sec_name = chunk.get('section', '')
                content = chunk.get('content', '')
                content_clean = re.sub(r'<[^>]+>', ' ', content).strip()
                content_lower = content_clean.lower()
                
                chunk_match = False
                for term in query_terms:
                    if term in content_lower or term in sec_name.lower():
                        chunk_match = True
                        score += 2
                        break
                
                if chunk_match and len(matched_sections) < 2:
                    matched_sections.append(f"  - [{sec_name}] {content_clean[:250]}...")

            if score > 0:
                results.append({
                    'score': score,
                    'code': f"{std_type} {code}",
                    'title': title,
                    'sections': matched_sections
                })

        # 정렬 후 반환
        results.sort(key=lambda x: x['score'], reverse=True)
        top_results = results[:max_results]

        if not top_results:
            return f"[KCSC 검색 결과 없음: '{query}' 관련 국가건설기준을 찾을 수 없습니다.]"

        output = f"=== [KCSC 국가건설기준 MCP 검색 결과: '{query}'] ===\n"
        for idx, r in enumerate(top_results):
            output += f"\n[{idx+1}] {r['code']} - {r['title']}\n"
            if r['sections']:
                output += "\n".join(r['sections']) + "\n"
            else:
                output += "  (제목 일치 - 세부 규정 확인 요망)\n"

        return output

    def get_statutory_cost_guidelines(self, project_domain: str) -> str:
        """
        국토교통부 및 고용노동부 고시에 따른 법정 필수 경비(산업안전보건비, 환경보전비 등) 요율 안내
        """
        guide = "=== [건설공사 법정 필수 경비 계상 적정성 기준 (고시 요율)] ===\n\n"
        guide += "1. [산업안전보건관리비] (고용노동부 고시 제2023-49호)\n"
        guide += "   - 대상: 총공사금액 2천만원 이상 모든 건설공사\n"
        guide += "   - 일반건설(갑)(건축/토목 일반): 5억~50억 미만(1.86% + 5,349,000원), 50억 이상(1.97%)\n"
        guide += "   - 일반건설(을)(도로개설, 교량, 하천정비, 철도): 5억~50억 미만(1.99% + 5,499,000원), 50억 이상(2.10%)\n"
        guide += "   - 중기건설(설비, 펌프장 등): 5억~50억 미만(2.15% + 5,750,000원), 50억 이상(2.27%)\n"
        guide += "   ※ [감사 지적 포인트]: 도급금액 기준 산출 요율보다 미달 계상했거나, 대상이 아닌 항목(예: 민원예방품 등)을 안전보건비로 집행하려 하는지 대조 필수!\n\n"
        
        guide += "2. [환경보전비] (건설기술 진흥법 제66조, 시행규칙 제61조)\n"
        guide += "   - 대상: 환경영향평가, 소규모 환경영향평가 대상 공사 및 배출시설 설치 공사\n"
        guide += "   - 요율: 직접공사비의 0.3% ~ 1.5% 이상 계상 (비산먼지 방진막, 세륜시설, 폐기물 처리비 등)\n\n"
        
        guide += "3. [건설공사 품질관리비] (건진법 시행규칙 별표6)\n"
        guide += "   - 품질시험비 및 품질관리 활동비 계상 의무 (누락 시 준공 전 환수 및 감사 지적 대상)\n\n"
        
        guide += "4. [퇴직공제부금비] (건설근로자의 고용개선 등에 관한 법률 제10조)\n"
        guide += "   - 공공공사 추정금액 1억원 이상 대상 (직접노무비의 일정 비율 법정 반영)\n"
        return guide

    def build_kcsc_context_for_llm(self, project_name: str, domain: str, review_modes: list, extracted_text: str) -> str:
        """
        LLM에게 전달할 맞춤형 KCSC 및 지침 RAG 컨텍스트 생성
        """
        context = f"### [LAW ASSISTANT - KCSC MCP 및 지침 검토 데이터베이스] ###\n\n"
        
        # 1. 법정 경비 체크
        if "cost" in review_modes:
            context += self.get_statutory_cost_guidelines(domain) + "\n\n"
            
        # 2. 키워드 기반 KCSC 자동 검색 (텍스트에서 주요 공종 단어 추출하여 검색)
        keywords_to_search = []
        if "굴착" in extracted_text or "터파기" in extracted_text or "흙막이" in extracted_text or "가시설" in extracted_text:
            keywords_to_search.extend(["흙막이", "가시설", "굴착"])
        if "콘크리트" in extracted_text or "철근" in extracted_text or "양생" in extracted_text:
            keywords_to_search.extend(["콘크리트", "철근배근"])
        if "포장" in extracted_text or "아스팔트" in extracted_text or "도로" in extracted_text or domain == "civil":
            keywords_to_search.extend(["도로포장", "토공사"])
        if "하천" in extracted_text or "제방" in extracted_text or "호안" in extracted_text or domain == "water":
            keywords_to_search.extend(["하천제방", "배수구조물"])
        if "건축" in extracted_text or "철거" in extracted_text or "석면" in extracted_text or domain == "building":
            keywords_to_search.extend(["건축물 해체", "건축구조"])
            
        # 기본 단어 추가
        if not keywords_to_search:
            keywords_to_search = ["공통설계기준", "안전관리"]
            
        context += "=== [본 공사 연관 핵심 국가건설기준 (KCSC KDS/KCS) 추출 데이터] ===\n"
        searched_set = set()
        for kw in keywords_to_search:
            if kw not in searched_set:
                searched_set.add(kw)
                context += self.search_kcsc_standards(kw, max_results=2) + "\n"
                
        return context

# 싱글톤 인스턴스
kcsc_engine = KCSCMCPEngine()
