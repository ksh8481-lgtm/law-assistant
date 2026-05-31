import os
import json
import requests
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import google.generativeai as genai
import random
# dotenv removed

import base64
import threading
import uuid
from rule_engine import get_scale_based_permits

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
        
        # 룰 엔진을 통한 기계적 필수 인허가 목록 추출
        scale_permits = get_scale_based_permits(budget, budget_nat, total_area)
        scale_permits_str = ""
        if scale_permits:
            scale_permits_str = "\n".join([f"        - {p}" for p in scale_permits])
            scale_permits_str = f"\n        **[시스템 자동 판별: 규모 기반 필수 인허가]**\n        서버의 룰 엔진이 면적과 사업비 규정을 바탕으로 도출한 절대 누락되어서는 안 될 목록입니다. 보고서 작성 시 반드시 포함하고 관련 근거 조항을 설명하세요:\n{scale_permits_str}\n"

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

        **[추가 검토 체크리스트 (지역지구 및 목적 기반)]**
        다음 항목들을 추가로 판단하여 보고서에 반영하십시오:
        1. **매장유산 보호 및 조사에 관한 법률**: 문화재 지표조사 대상 여부 파악
        2. **도시교통정비 촉진법**: 교통영향평가 대상 여부
        3. **국토의 계획 및 이용에 관한 법률**: 개발행위허가 및 도시계획위원회 심의 대상 여부
        4. **산지관리법 / 농지법**: 산지전용허가, 농지전용허가 대상 여부 (산지/농지 포함 시)

        [요청 사항]
        보고서에 쓸 수 있도록 전문적인 용어로 답변하되, 응답은 반드시 아래 JSON 형식(마크다운 백틱 없이 순수 JSON만)으로 반환하세요.
        "permits" 항목 작성 시 관련 법령에는 국가법령정보센터 검색 링크(https://www.law.go.kr/LSW/lsSc.do?query=법령명)를 HTML <a> 태그로 작성해 주세요.
        {{
            "risks": ["보전산지 편입으로 인한 행위제한 검토 요망", "수질보전특별대책지역에 따른 오수처리계획 수립 필수"],
            "permits": ["건축허가 (<a href='https://www.law.go.kr/LSW/lsSc.do?query=건축법' target='_blank'>건축법 제11조</a>)", "산지전용허가 (<a href='https://www.law.go.kr/LSW/lsSc.do?query=산지관리법' target='_blank'>산지관리법 제14조</a>)"]
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
