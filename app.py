import os
import json
import requests
import xml.etree.ElementTree as ET
import urllib.parse
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import google.generativeai as genai
import random
# dotenv removed

import base64
import threading
import uuid
from rule_engine import evaluate_knowledge_base, get_all_variables

app = Flask(__name__)
CORS(app)

JOBS = {}


# API keys from environment variables
GEMINI_KEY = os.environ.get('GEMINI_API_KEY', '')

_V = "RDNDMEEyNTktQjQ1QS0zQ0U2LTg0MUQtNjJFRkIxMDNEM0NC"
VWORLD_KEY = os.environ.get('VWORLD_API_KEY', '') or base64.b64decode(_V).decode('utf-8')

_L = "a3NoODQ4MQ==" # ksh8481
LAW_KEY = os.environ.get('LAW_API_KEY', '') or base64.b64decode(_L).decode('utf-8')

SIDO_DATA = [
    {"code": "11", "name": "서울특별시"}, {"code": "26", "name": "부산광역시"},
    {"code": "27", "name": "대구광역시"}, {"code": "28", "name": "인천광역시"},
    {"code": "29", "name": "광주광역시"}, {"code": "30", "name": "대전광역시"},
    {"code": "31", "name": "울산광역시"}, {"code": "36", "name": "세종특별자치시"},
    {"code": "41", "name": "경기도"}, {"code": "43", "name": "충청북도"},
    {"code": "44", "name": "충청남도"}, {"code": "45", "name": "전북특별자치도"},
    {"code": "46", "name": "전라남도"}, {"code": "47", "name": "경상북도"},
    {"code": "48", "name": "경상남도"}, {"code": "50", "name": "제주특별자치도"},
    {"code": "51", "name": "강원특별자치도"}
]

@app.route('/api/regions/sido', methods=['GET'])
def get_sido():
    return jsonify({"success": True, "data": SIDO_DATA})

@app.route('/api/regions/<layer>', methods=['GET'])
def get_regions(layer):
    vworld_key = request.args.get('vworldKey')
    parent_code = request.args.get('parentCode')
    
    layer_map = {
        'sigungu': ('LT_C_ADSIGG_INFO', 'sig_cd', 'sig_kor_nm'),
        'emd': ('LT_C_ADEMD_INFO', 'emd_cd', 'emd_kor_nm'),
        'ri': ('LT_C_ADRI_INFO', 'li_cd', 'li_kor_nm')
    }
    
    if layer not in layer_map:
        return jsonify({"success": False, "message": "Invalid layer"})
        
    v_layer, code_field, name_field = layer_map[layer]
    url = f"https://api.vworld.kr/req/data?service=data&request=GetFeature&data={v_layer}&key={vworld_key}&domain=http://127.0.0.1&size=1000&geometry=false"
    
    if parent_code:
        url += f"&attrFilter={code_field}:like:{parent_code}"
        
    try:
        res = requests.get(url, timeout=10).json()
        if res.get('response', {}).get('status') == 'OK':
            features = res['response']['result']['featureCollection']['features']
            
            data_list = []
            for f in features:
                props = f['properties']
                data_list.append({
                    "code": props[code_field],
                    "name": props.get(name_field, props[code_field])
                })
            
            data_list.sort(key=lambda x: x['name'])
            return jsonify({"success": True, "data": data_list})
            
        return jsonify({"success": True, "data": []})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/law_review')
def law_review():
    return render_template('law_review.html')

@app.route('/supervisor')
def supervisor():
    return render_template('supervisor.html')

@app.route('/report')
def report():
    return render_template('report.html')

@app.route('/other_review')
def other_review():
    return render_template('other_review.html')

@app.route('/api/debug')
def debug_env():
    key = os.environ.get('GEMINI_API_KEY', '')
    masked_key = key[:10] + "..." + key[-5:] if len(key) > 15 else "EMPTY_OR_TOO_SHORT"
    return jsonify({
        "gemini_key_in_server": masked_key,
        "message": "서버에 현재 등록된 API 키의 앞/뒷부분입니다. 발급받으신 새 키와 일치하는지 확인해주세요."
    })

def fetch_law_data(law_key, search_query="국토의 계획 및 이용에 관한 법률"):
    if not law_key:
        return "법제처 API 키가 제공되지 않아 AI 자체 지식을 기반으로 분석합니다."
    try:
        url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={law_key}&target=law&type=XML&query={search_query}"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        laws = []
        for law in root.findall('.//law'):
            law_name = law.find('법령명한글').text if law.find('법령명한글') is not None else ""
            laws.append(law_name)
        if laws:
            return f"법제처 API에서 조회된 연관 법령 목록: {', '.join(laws[:5])} 등."
        else:
            return "연관 법령을 찾지 못했습니다."
    except Exception as e:
        return "법제처 API 통신 중 오류가 발생하여 자체 지식을 활용합니다."

def fetch_moleg_context(text, law_key):
    if not law_key:
        return ""
    try:
        genai.configure(api_key=GEMINI_KEY)
        kw_prompt = f"다음 텍스트에서 대한민국 법제처 판례/법령 검색에 가장 적합한 핵심 명사 키워드 딱 1개(예: 하도급, 가압류, 직불)만 추출해. 다른 말은 절대 하지마.\n텍스트: {text}"
        
        try:
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and 'vision' not in m.name.lower()]
            models_to_try = sorted(available_models, key=lambda x: (0 if '1.5-pro' in x else 1 if '2.5-pro' in x else 2 if 'pro' in x else 3 if '1.5-flash' in x else 4))
        except:
            models_to_try = ['models/gemini-1.5-pro', 'models/gemini-1.5-flash']
            
        kw_res = None
        for m in models_to_try:
            try:
                model = genai.GenerativeModel(m)
                kw_res = model.generate_content(kw_prompt)
                break
            except Exception as e:
                continue
                
        if not kw_res:
            return ""
            
        keyword = kw_res.text.strip().replace("'", "").replace('"', "")
        if len(keyword) > 10: keyword = keyword[:10]
        
        law_url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={law_key}&target=law&type=XML&query={keyword}"
        law_res = requests.get(law_url, timeout=3)
        laws = []
        if law_res.status_code == 200:
            law_root = ET.fromstring(law_res.content)
            for law in law_root.findall('.//law'):
                name = law.find('법령명한글')
                if name is not None and name.text:
                    link = f"https://www.law.go.kr/법령/{urllib.parse.quote(name.text)}"
                    laws.append(f"[{name.text}]({link})")
        context = f"[법제처 API 실시간 RAG 검색 결과 (키워드: {keyword})]\n"
        if laws: context += f"- 현행 법령: {', '.join(laws[:10])}\n"
        return context
    except Exception as e:
        print(f"MOLEG RAG Error: {e}")
        return ""

def fetch_moleg_context(query, api_key="ksh8481"):
    try:
        # Extract keywords for MOLEG API
        keywords = extract_keywords(query)
        if not keywords:
            return "[법제처 API 검색 실패: 핵심 키워드를 추출하지 못했습니다.]"
            
        return query_moleg_api(keywords, api_key)
    except Exception as e:
        print(f"MOLEG API fallback error: {e}")
        return "[법제처 API 검색 실패: 시스템 오류가 발생했습니다.]"

def fetch_local_law_data(query, moleg_context):
    import glob
    import os
    local_data = ""
    # Check data/laws directory
    laws_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'laws')
    if not os.path.exists(laws_dir):
        return ""
        
    for md_file in glob.glob(os.path.join(laws_dir, '*.md')):
        law_name = os.path.basename(md_file).replace('.md', '').replace('_', ' ')
        # 띄어쓰기를 무시한 이름 매칭
        clean_law_name = law_name.replace(" ", "")
        clean_query = query.replace(" ", "")
        clean_context = moleg_context.replace(" ", "")
        
        if clean_law_name in clean_query or clean_law_name in clean_context:
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    local_data += f.read() + "\n\n"
            except:
                pass
    return local_data


@app.route('/api/verify_parcel', methods=['POST'])
def verify_parcel():
    data = request.json
    
    full_address = data.get('address')
    pnu = ""
    san = "1"
    
    import re
    
    if full_address and VWORLD_KEY:
        try:
            params = {
                "service": "search", "request": "search", "version": "2.0",
                "size": "10", "page": "1", "query": full_address,
                "type": "address", "category": "parcel", "format": "json",
                "errorformat": "json", "key": VWORLD_KEY.strip(), "domain": "http://127.0.0.1"
            }
            res_search = requests.get("https://api.vworld.kr/req/search", params=params, timeout=5).json()
            items = res_search.get('response', {}).get('result', {}).get('items', [])
            
            if not items:
                return jsonify({"success": False, "message": f"검색 API 결과 없음: {res_search}"}), 400
                
            # 정확한 주소 매칭 (읍/면/리/지번 검증)
            input_parts = re.split(r'\s+', full_address.strip())
            for item in items:
                api_addr = item.get('address', {}).get('parcel', '')
                if not api_addr:
                    continue
                # 마지막 부분(지번)이 일치해야 함
                if input_parts[-1] != api_addr.split()[-1]:
                    continue
                
                # 다른 부분들도 모두 포함되는지 확인 (경북/경상북도 등 예외 처리)
                is_match = True
                for p in input_parts[:-1]:
                    if p not in api_addr:
                        if p == '경북' and '경상북도' in api_addr: continue
                        if p == '경남' and '경상남도' in api_addr: continue
                        if p == '전북' and '전라북도' in api_addr: continue
                        if p == '전남' and '전라남도' in api_addr: continue
                        if p == '충북' and '충청북도' in api_addr: continue
                        if p == '충남' and '충청남도' in api_addr: continue
                        is_match = False
                        break
                
                if is_match:
                    pnu = item.get('id', '')
                    break
            
            if not pnu:
                return jsonify({"success": False, "message": f"주소 불일치 (입력: {full_address}, 첫결과: {items[0].get('address', {}).get('parcel', '')})"}), 400
                
        except Exception as e:
            print(f"VWorld 주소 검색 오류: {e}")
            return jsonify({"success": False, "message": f"서버 내부 오류: {str(e)}"}), 500
            
        if not pnu:
            return jsonify({"success": False, "message": "주소에서 고유번호(PNU)를 찾을 수 없습니다."}), 400
    else:
        bcode = data.get('bcode')
        san = data.get('san')
        bonbeon = data.get('bonbeon')
        bubeon = data.get('bubeon')
        
        if not bcode or not bonbeon:
            return jsonify({"success": False, "message": "bcode와 bonbeon은 필수입니다."}), 400
        pnu = f"{bcode}{san}{bonbeon.zfill(4)}{bubeon.zfill(4)}"

    try:
        user_area = float(data.get('area', 0))
    except (ValueError, TypeError):
        user_area = 0.0
    
    actual_area = str(user_area) if user_area > 0 else ""
    jimok = "대" if san == '1' else "임"
    zoning_list = []
    
    # 1. VWorld API 실제 연동
    if not VWORLD_KEY:
        return jsonify({"success": False, "message": "서버에 VWorld API Key가 설정되지 않았습니다."}), 500

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    # (1) 토지특성정보 조회
    try:
        url_char = f"http://api.vworld.kr/ned/data/getLandCharacteristics?key={VWORLD_KEY.strip()}&domain=http://127.0.0.1&pnu={pnu}&format=json&numOfRows=50&pageNo=1"
        res_char = requests.get(url_char, timeout=10).json()
        if 'landCharacteristicss' in res_char and 'field' in res_char['landCharacteristicss']:
            fields = res_char['landCharacteristicss']['field']
            if fields:
                latest = sorted(fields, key=lambda x: x.get('stdrYear', '0'))[-1]
                jimok = latest.get('lndcgrCodeNm', jimok)
                real_area = latest.get('lndpclAr', '')
                if real_area and user_area <= 0:
                    actual_area = str(real_area)
    except Exception as e:
        print(f"VWorld 토지특성정보 통신 오류: {e}")

    # (2) 토지이용계획(지역지구) 실데이터 조회
    try:
        url_zoning = f"http://api.vworld.kr/ned/data/getLandUseAttr?key={VWORLD_KEY.strip()}&domain=http://127.0.0.1&pnu={pnu}&format=json&numOfRows=50&pageNo=1"
        res_zoning = requests.get(url_zoning, timeout=10).json()
            
        if 'landUses' in res_zoning:
            if 'field' in res_zoning['landUses']:
                fields = res_zoning['landUses']['field']
                for f in fields:
                    z_name = f.get('prposAreaDstrcCodeNm')
                    if z_name and z_name not in zoning_list:
                        zoning_list.append(z_name)
            else:
                err_msg = res_zoning['landUses'].get('resultMsg', '알 수 없는 VWorld 오류')
                zoning_list.append(f"API 에러: {err_msg}")
    except Exception as e:
        zoning_list.append(f"통신 에러: {str(e)}")
        print(f"VWorld 토지이용계획 통신 오류: {e}")
            
    # 2. 결과 조합 (API가 실패했거나 결과가 없을 경우 대비 Fallback)
    if not zoning_list:
        zoning_list.append("지역지구 데이터 없음")
            
    return jsonify({
        "success": True,
        "pnu": pnu,
        "actualArea": actual_area,
        "jimok": jimok,
        "zoning": zoning_list
    })

def run_analysis(job_id, data):
    try:
        genai.configure(api_key=GEMINI_KEY)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        model_name = None
        for preferred in ['models/gemini-1.5-pro-latest', 'models/gemini-1.5-pro', 'models/gemini-1.5-flash-latest', 'models/gemini-1.5-flash', 'models/gemini-pro', 'models/gemini-1.0-pro']:
            if preferred in available_models:
                model_name = preferred
                break
        if not model_name and available_models:
            model_name = available_models[0]
        if not model_name:
            raise Exception(f"텍스트 생성을 지원하는 모델이 없습니다. (검색된 모델: {available_models})")

        model = genai.GenerativeModel(model_name)
        
        project_name = data.get('projectName', '이름 없음')
        budget = data.get('budget', 0)
        budget_nat = data.get('budgetNational', 0)
        budget_prov = data.get('budgetProvincial', 0)
        budget_mun = data.get('budgetMunicipal', 0)
        total_area = data.get('totalArea', 0)
        description = data.get('description', '설명 없음')
        parcels = data.get('parcels', [])

        if not parcels:
            raise Exception("검증된 편입 필지가 없습니다.")

        parcel_str_list = []
        all_zonings = set()
        for p in parcels:
            parcel_str_list.append(f"- {p['address']} (면적: {p['area']}㎡) | 지역지구: {p['zoning']}")
            for z in p['zoning'].split(', '):
                all_zonings.add(z)
                
        parcel_str = "\n".join(parcel_str_list)
        zoning_context = ", ".join(list(all_zonings))
        
        law_context = fetch_law_data(LAW_KEY, "국토의 계획 및 이용에 관한 법률")
        # 모든 DB 변수 추출
        all_rule_vars = get_all_variables()
        vars_instruction = ", ".join(all_rule_vars)
        
        # --- 에이전트 1: 파라미터 추출기 (Extractor Agent) ---
        extractor_prompt = f"""
        당신은 건설공사 내역 분석 에이전트입니다.
        아래 [사업 개요] 및 [편입필지 지역지구] 정보를 바탕으로 JSON 데이터를 추출하세요.
        응답은 순수 JSON 형식만 반환하세요 (마크다운 백틱 제외).
        
        [사업 개요] 사업명: {project_name}, 총 사업비: {budget}억, 면적: {total_area}㎡, 주요 내용: {description}
        [지역지구] {zoning_context}
        
        당신은 다음 변수 목록 중에서 사업 개요에 명확히 해당되는(True 또는 숫자값이 존재하는) 변수들만 골라내어 JSON 키-값 쌍으로 만들어야 합니다:
        [변수 목록]: {vars_instruction}
        
        (주의: 정보가 부족하거나 해당되지 않는 변수는 아예 JSON 키를 생성하지 마세요. 불확실한 경우에도 제외하세요. "budget", "total_area", "floors", "excavation_depth"와 같은 숫자 변수는 숫자로 추출하세요. "has_", "is_" 로 시작하는 것은 true/false로 출력하세요.)
        """
        extractor_resp = model.generate_content(extractor_prompt)
        ext_text = extractor_resp.text.strip().replace('```json', '').replace('```', '').strip()
        
        try:
            extracted_params = json.loads(ext_text)
        except:
            extracted_params = {}
            
        # 파라미터 합성
        kb_params = extracted_params.copy()
        kb_params.update({
            'budget': budget,
            'budget_nat': budget_nat,
            'total_area': total_area,
            'is_public': True
        })
        
        if '임야' in zoning_context or '산지' in zoning_context: kb_params['has_mountain'] = True
        if '농지' in zoning_context or '전' in zoning_context or '답' in zoning_context: kb_params['has_farmland'] = True

        # --- Rule Engine (Knowledge Base 결정론적 매칭) ---
        matched_laws = evaluate_knowledge_base(kb_params)
        scale_permits_str = ""
        if matched_laws:
            law_lines = [f"        - {law['name']} (Phase: {law['phase']}) : {law['desc']} (근거: {law['law_link']})" for law in matched_laws]
            scale_permits_str = "\n".join(law_lines)
            scale_permits_str = f"\n        **[지식 기반(Knowledge Base) 강제 적용 목록]**\n        서버의 룰 엔진이 매칭한 절대 누락되어서는 안 될 필수 목록입니다. 이 항목들은 반드시 최종 보고서 JSON의 적절한 phase 배열에 포함시키세요:\n{scale_permits_str}\n"

        prompt = f"""
        당신은 대한민국 시설직 공무원을 돕는 최고 수준의 법규 검토 AI 전문가입니다.
        아래 [사업 개요]와 토지대장에서 실시간으로 조회한 [편입필지 지역지구] 정보를 바탕으로 분석하세요.

        [사업 개요]
        - 사업명: {project_name}
        - 총 사업비: {budget}억 원
        - 검증된 총 사업 면적: {total_area}㎡
        - 주요 사업 내용: {description}
        
        [편입 필지 및 지역지구 현황] (매우 중요)
        {parcel_str}
        
        ※ 핵심 검토 요건: 이 사업은 [{zoning_context}] 구역을 포함하고 있습니다. 이 용도지역에 따른 행위 제한 및 필수 인허가를 반드시 찾아내어 적으세요.
        {scale_permits_str}
        [법제처 제공 현행법 컨텍스트]
        {law_context}

        **[가장 중요한 지시사항]**
        사용자는 당신이 '자체적인 과거 지식'에만 의존하여 답변하는 것을 우려하고 있습니다. 
        따라서 당신은 위 [법제처 제공 현행법 컨텍스트]에서 확인된 관련 법률(예: 국토의 계획 및 이용에 관한 법률, 산지관리법, 건축법 등)의 **가장 최신(현행) 조문**을 당신의 지식에서 끌어와 명확한 법적 근거(법, 조, 항)로 제시해야 합니다. 
        반드시 "현행법에 따르면~"과 같이 법제처 기준 현행법을 바탕으로 해석하고 있다는 것을 보여주세요.

        **[추가 검토 체크리스트 (발주청 공공 건설공사 필수 확인 사항)]**
        사용자는 공공기관의 발주청 담당자입니다. 다음 항목들을 빠짐없이 검토하여 사업 개요(예산, 면적, 공사내용)에 해당될 경우 보고서(phases 또는 permits)에 반드시 반영하십시오:
        1. **안전 및 시공 관리 (매우 중요)**: 
           - **건설사업관리계획 수립 (건설기술 진흥법 제39조의2)**: 시공단계 착공 전 수립 의무 파악
           - **설계안전성검토 (건설기술 진흥법 제62조)** 및 **안전관리계획서 제출**
           - **유해위험방지계획서 (산업안전보건법)**
        2. **환경 및 민원 관리**: 
           - **비산먼지 발생사업 신고 (대기환경보전법)** 및 **특정공사 사전신고 (소음·진동관리법)**
           - **건설폐기물 처리계획 신고 (건설폐기물의 재활용촉진에 관한 법률)**
        3. **사전 평가 및 심의**:
           - **지하안전평가 (지하안전관리에 관한 특별법)**: 10m 이상 지하 굴착 공사 수반 시
           - **설계경제성검토(VE) (건설기술 진흥법 시행령 제75조)**: 총사업비 100억원 이상 건설공사 시
        4. **기타 기본 법정 의무**: 문화재 지표조사, 교통영향평가, 개발행위허가, 산지/농지 전용허가 등

        [요청 사항]
        보고서에 쓸 수 있도록 전문적인 용어로 답변하되, 응답은 반드시 아래 JSON 형식(마크다운 백틱 없이 순수 JSON만)으로 반환하세요.
        "permits" 및 "phases" 항목 작성 시 관련 법령은 반드시 국가법령정보센터 검색 링크(https://www.law.go.kr/LSW/lsSc.do?query=법령명)를 포함한 HTML <a> 태그로 작성해 주세요.
        {{
            "permits": [
                {{
                    "name": "건축허가",
                    "law_link": "<a href='https://www.law.go.kr/LSW/lsSc.do?query=건축법' target='_blank'>건축법 제11조</a>",
                    "reason": "해당 사업은 계획관리지역 내 새로운 건축물을 축조하는 사업이므로 건축허가가 필요함."
                }}
            ],
            "phases": {{
                "design": [
                    {{"task": "설계안전성검토 의뢰", "law_link": "<a href='https://www.law.go.kr/LSW/lsSc.do?query=건설기술진흥법' target='_blank'>건설기술 진흥법 제62조</a>", "desc": "가설구조물 및 굴착 공사에 따른 설계안전성 사전 검토 (대상 여부 확인 필요)"}}
                ],
                "construction": [
                    {{"task": "안전관리계획서 제출", "law_link": "<a href='https://www.law.go.kr/LSW/lsSc.do?query=건설기술진흥법' target='_blank'>건설기술 진흥법 제62조</a>", "desc": "착공 전 인허가 기관에 안전관리계획서 제출 및 승인"}}
                ],
                "completion": [
                    {{"task": "준공검사", "law_link": "<a href='https://www.law.go.kr/LSW/lsSc.do?query=건축법' target='_blank'>건축법 제22조</a>", "desc": "공사 완료 후 사용승인 신청 및 준공검사"}}
                ],
                "maintenance": [
                    {{"task": "정기 안전점검", "law_link": "<a href='https://www.law.go.kr/LSW/lsSc.do?query=시설물의안전및유지관리에관한특별법' target='_blank'>시설물안전법</a>", "desc": "준공 후 반기별 정기점검 및 유지관리계획 수립"}}
                ]
            }}
        }}
        """
        
        response = model.generate_content(prompt)
        text_resp = response.text.strip()
        
        if text_resp.startswith("```json"):
            text_resp = text_resp[7:]
        if text_resp.startswith("```"):
            text_resp = text_resp[3:]
        if text_resp.endswith("```"):
            text_resp = text_resp[:-3]
            
        result = json.loads(text_resp.strip())
        JOBS[job_id] = {"status": "completed", "result": result}
        
    except json.JSONDecodeError as e:
        JOBS[job_id] = {"status": "error", "message": "AI가 반환한 데이터를 파싱할 수 없습니다."}
    except Exception as e:
        JOBS[job_id] = {"status": "error", "message": str(e)}

@app.route('/api/analyze/start', methods=['POST'])
def analyze_start():
    if not GEMINI_KEY:
        return jsonify({"error": "Google Gemini API 키가 설정되지 않았거나 만료되었습니다. 클라우드타입(Cloudtype) 설정 -> 환경변수에서 'GEMINI_API_KEY'를 추가한 후 재배포해주세요."}), 400

    data = request.json
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing"}
    
    thread = threading.Thread(target=run_analysis, args=(job_id, data))
    thread.start()
    
    return jsonify({"success": True, "job_id": job_id})

@app.route('/api/analyze/status/<job_id>', methods=['GET'])
def analyze_status(job_id):
    if job_id not in JOBS:
        return jsonify({"status": "error", "message": "존재하지 않는 작업입니다."}), 404
        
    job_info = JOBS[job_id]
    
    if job_info["status"] == "completed":
        result = job_info.get("result", {})
        # 메모리 정리를 위해 완료된 작업은 삭제
        del JOBS[job_id]
        return jsonify({"status": "completed", "result": result})
        
    elif job_info["status"] == "error":
        error_msg = job_info.get("message", "알 수 없는 오류")
        del JOBS[job_id]
        return jsonify({"status": "error", "message": error_msg})
        
    return jsonify({"status": "processing"})

@app.route('/api/supervisor/checklist', methods=['GET'])
def get_supervisor_checklist():
    try:
        file_path = os.path.join(os.path.dirname(__file__), 'supervisor_checklist.json')
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/analyze/other_review', methods=['POST'])
def api_other_review():
    try:
        data = request.json
        text_content = data.get('text', '')
        
        if not text_content:
            return jsonify({"success": False, "message": "검토할 내용이 제공되지 않았습니다."}), 400
            
        genai.configure(api_key=GEMINI_KEY)
        try:
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            pro_models = [m for m in available_models if 'pro' in m.lower() and 'vision' not in m.lower()]
            model_name = next((m for m in pro_models if '1.5' in m), pro_models[0]) if pro_models else (available_models[0] if available_models else 'gemini-1.5-pro-latest')
        except Exception:
            model_name = 'gemini-1.5-pro-latest'
        
        moleg_context = fetch_moleg_context(text_content, os.environ.get('MOLEG_API_KEY', ''))
        local_law_context = fetch_local_law_data(text_content, moleg_context)
        
        prompt = f"""당신은 대한민국 공무원들의 행정, 감사, 예산 업무를 지원하는 '다중 에이전트(법무/감사/재무 전문가)'입니다.
공무원이 다음 상황에 대한 검토를 요청했습니다.

[사용자 질문]
{text_content}

{moleg_context}

[로컬 법령 데이터베이스 (조문 본문 및 별표/서식)]
{local_law_context}

[특별 지시사항]
1. [법제처 API 실시간 RAG 검색 결과]와 [로컬 법령 데이터베이스]를 최우선으로 인용하십시오. 특히 별표(Attached Tables)에 대한 질문은 로컬 데이터베이스의 내용을 바탕으로 상세히 설명하십시오. RAG에 포함된 하이퍼링크를 그대로 사용하세요.
2. 법령 조문, 판례, 해석례를 인용할 때는 아래의 규칙을 완벽하게 준수하십시오.
  - ⚖️ 법령 조문 링크: 법률의 성격에 따라 URL 형식을 엄격히 구분하여 반드시 **제X조**까지 구체적으로 연결되도록 작성하십시오. (띄어쓰기는 그대로 유지합니다)
    - **법률, 시행령, 시행규칙**인 경우 (예: ~법, ~령, ~규칙): `[법령명 제X조](https://www.law.go.kr/법령/법령명/제X조)`
    - **고시, 훈령, 예규, 지침, 기준**인 경우 (예: ~고시, ~기준, ~지침): `[행정규칙명 제X조](https://www.law.go.kr/행정규칙/행정규칙명/제X조)`
3. 🔎 **[판례 검색] 오직 사설 판례 엔진(케이스노트)만 활용**:
  - 대법원 공식 포털은 AI 봇의 접근을 차단하므로, 내부 검색 도구를 사용하여 **오직 케이스노트(casenote.kr)** 사이트 내에서만(`site:casenote.kr 검색어`) 판례를 검색하십시오.
  - 🚨 **[검색 과정 노출 금지]**: 답변 작성 시 "구글 검색 도구를 통해 검색합니다", "검색 결과 ~ 찾기 어렵습니다" 같은 내부 검색 과정이나 구차한 변명, 부연 설명을 절대 출력하지 마십시오.
  - 🚨 **[가짜 판례 창작 절대 금지]**: 만약 케이스노트 검색 결과 딱 맞는 판례가 없다면, 절대 지식을 짜내서 판례를 창작하지 마십시오. 검색된 것이 없으면 군더더기 없이 딱 한 줄로 **"현재 쟁점과 관련된 대법원 판례를 찾을 수 없습니다."** 라고만 출력하십시오.
  - 🚨 **[링크 생성 규칙]**: 검색된 실제 판례가 있다면 링크는 무조건 **검색 결과 페이지**로 연결되도록 아래 포맷을 엄격히 지켜 작성하십시오.
    - 포맷: `[판례명(사건번호)](https://casenote.kr/search/?q=사건번호)`
    - 예시: `[대법원 2014. 11. 13. 선고 2014다87955 판결](https://casenote.kr/search/?q=2014다87955)`
4. 응답은 반드시 마크다운(Markdown) 포맷으로 다음 4단계 구조를 엄격히 지켜 작성하십시오.

### 1. 상황 요약 (Situation Summary)
- 
### 2. 핵심 쟁점 (Key Legal Issues)
- 
### 3. 관련 법령 및 핵심 판례 (Applicable Laws & Key Precedents)
- 법령은 [법제처 API 실시간 RAG 검색 결과] 및 [로컬 법령 데이터베이스]를 바탕으로 상세 설명. 
- 판례는 케이스노트 검색을 통해 발굴한 **실제 판례** 요점을 상세히 설명하고 출처 링크 첨부. (단, 검색 결과가 없으면 변명 없이 "관련 판례 없음"만 명시할 것.)
### 4. 공무원 행동 지침 및 결론 (Action Plan)
- 

[요청 내용]
{text_content}"""
        
        try:
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and 'vision' not in m.name.lower()]
            models_to_try = sorted(available_models, key=lambda x: (0 if '1.5-pro' in x else 1 if '2.5-pro' in x else 2 if 'pro' in x else 3 if '1.5-flash' in x else 4))
        except:
            models_to_try = ['models/gemini-1.5-pro', 'models/gemini-1.5-flash']
            
        response = None
        last_err = None
        for m in models_to_try:
            try:
                try:
                    model = genai.GenerativeModel(model_name=m, tools='google_search_retrieval')
                    response = model.generate_content(prompt)
                    break
                except Exception as tool_e:
                    print(f"Tool {m} fallback: {tool_e}")
                    model = genai.GenerativeModel(model_name=m)
                    response = model.generate_content(prompt)
                    break
            except Exception as e:
                last_err = e
                print(f"Model {m} failed: {e}")
                continue
                
        if not response:
            raise Exception(f"모든 AI 모델이 요청 한도 초과 또는 오류로 실패했습니다. 마지막 오류: {last_err}")
            
        return jsonify({"success": True, "result": response.text})
        
    except Exception as e:
        print(f"Other Review API Error: {e}")
        return jsonify({"success": False, "message": f"서버 오류: {str(e)}"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
