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



@app.route('/api/supervisor/checklist', methods=['GET', 'POST'])
def get_supervisor_checklist():
    try:
        file_path = os.path.join(os.path.dirname(__file__), 'supervisor_db.json')
        with open(file_path, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
            
        if request.method == 'POST' and request.json:
            project_data = request.json
            if project_data.get('description') or project_data.get('budget'):
                if GEMINI_KEY:
                    genai.configure(api_key=GEMINI_KEY)
                    try:
                        model = genai.GenerativeModel('models/gemini-2.5-flash')
                    except:
                        model = genai.GenerativeModel('models/gemini-2.0-flash')
                    
                    prompt = f"""
당신은 현장 공사감독관을 위한 맞춤형 체크리스트 필터링 AI입니다.
아래 [사업 개요]를 꼼꼼히 읽고, 이어지는 [전체 체크리스트 DB]의 항목(task) 중에서 이 공사에 **해당하지 않거나 불필요한 항목의 task_id**를 추출하세요.

[사업 개요]
- 사업명: {project_data.get('projectName', '')}
- 예산: {project_data.get('budget', 0)}억 원
- 면적: {project_data.get('totalArea', 0)}㎡
- 주요 사업 내용: {project_data.get('description', '')}

[판단 기준 예시]
1. 건설사업관리(감리) 항목: "직접 감독" 공사이거나 소규모 공사인 경우 감리가 없을 수 있습니다. 단, 사업 내용에 명확히 없다고 하지 않으면 일단 둡니다.
2. 지하안전평가: 지하 10m 이상 굴착이나 흙막이가 명시되지 않은 단순 지상/포장 공사면 제외.
3. 건축허가/건축물 사용승인: 건축물이 포함되지 않은 순수 토목(도로, 공원, 하천 정비 등)이면 제외.
4. 특정 공사 규모에 미달: 100억 이상일 때만 하는 VE(설계경제성검토) 등. 예산이 기준 미달이면 제외.
(그 외에도 공사 내용과 전혀 무관한 항목은 과감히 제외하여 실무자의 피로도를 낮추세요.)

[전체 체크리스트 DB]
{json.dumps(db_data, ensure_ascii=False)}

응답은 오직 제외할 항목의 task_id들만 순수한 JSON 배열 포맷(예: ["TSK_STG_PRE_001", "TSK_STG_CON_005"])으로 반환하세요. 마크다운(` ``` `) 없이 배열만 반환하세요.
제외할 항목이 없으면 빈 배열 []을 반환하세요.
"""
                    try:
                        response = model.generate_content(prompt)
                        resp_text = response.text.strip()
                        if resp_text.startswith("```json"): resp_text = resp_text[7:]
                        if resp_text.startswith("```"): resp_text = resp_text[3:]
                        if resp_text.endswith("```"): resp_text = resp_text[:-3]
                        
                        excluded_tasks = json.loads(resp_text.strip())
                        if isinstance(excluded_tasks, list):
                            for stage in db_data.get("project_stages", []):
                                original_checklists = stage.get("checklists", [])
                                stage["checklists"] = [task for task in original_checklists if task.get("task_id") not in excluded_tasks]
                    except Exception as e:
                        print("AI filtering error:", e)
                        pass

        return jsonify({"success": True, "data": db_data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/report')
def report():
    return render_template('report.html')

@app.route('/other_review')
def other_review():
    return render_template('other_review.html')

@app.route('/duty_list')
def duty_list():
    return render_template('duty_list.html')

@app.route('/api/search_law_list', methods=['POST'])
def search_law_list():
    try:
        data = request.get_json(silent=True) or {}
        keyword = data.get('keyword', '')
        if isinstance(keyword, str):
            keyword = keyword.strip()
            
        if not keyword:
            return jsonify({"success": False, "message": "검색어를 입력해주세요."})
        
        search_res = requests.get(f"https://www.law.go.kr/DRF/lawSearch.do?OC={LAW_KEY}&target=law&type=XML&query={urllib.parse.quote(keyword)}", timeout=5)
        root = ET.fromstring(search_res.text)
        laws = []
        for law in root.findall('law'):
            laws.append({
                'lsi_seq': law.findtext('법령일련번호'),
                'law_name': law.findtext('법령명한글')
            })
        return jsonify({"success": True, "data": laws})
    except Exception as e:
        print("Law List Search Error:", e)
        return jsonify({"success": False, "message": f"법령 목록 검색 오류: {str(e)}"})


LAW_TEXT_CACHE = {}

@app.route('/api/search_duties_chunk', methods=['POST'])
def search_duties_chunk():
    try:
        data = request.get_json(silent=True) or {}
        lsi_seq = data.get('lsi_seq', '')
        exact_law_name = data.get('law_name', '')
        chunk_index = int(data.get('chunk_index', 0))
        
        if isinstance(lsi_seq, str): lsi_seq = lsi_seq.strip()
        if isinstance(exact_law_name, str): exact_law_name = exact_law_name.strip()
        
        if not lsi_seq or not exact_law_name:
            return jsonify({"success": False, "message": "법령일련번호 또는 법률명이 누락되었습니다."})
        
        # 1. Fetch XML (with memory cache to prevent rate limits)
        global LAW_TEXT_CACHE
        full_text = LAW_TEXT_CACHE.get(lsi_seq)
        
        if not full_text:
            doc_res = requests.get(f"https://www.law.go.kr/DRF/lawService.do?OC={LAW_KEY}&target=law&type=XML&MST={lsi_seq}", timeout=10)
            doc_root = ET.fromstring(doc_res.text)
            
            articles = doc_root.findall('.//조문단위')
            full_text = ""
            for art in articles:
                art_title = art.findtext('조문내용') or ""
                full_text += art_title + "\\n"
                for hang in art.findall('.//항내용'):
                    full_text += hang.text + "\\n"
                for ho in art.findall('.//호내용'):
                    full_text += ho.text + "\\n"
            
            LAW_TEXT_CACHE[lsi_seq] = full_text
                
        # 2. Split into chunks (1,500 chars per chunk to ensure < 40s even with detailed JSON)
        CHUNK_SIZE = 1500
        chunks = [full_text[i:i+CHUNK_SIZE] for i in range(0, len(full_text), CHUNK_SIZE)]
        if not chunks:
            chunks = [""]
            
        if chunk_index >= len(chunks):
            return jsonify({"success": True, "data": {"duties": [], "has_more": False, "total_chunks": len(chunks)}})
            
        current_chunk = chunks[chunk_index]
            
        if not GEMINI_KEY:
            return jsonify({"success": False, "message": "Gemini API 키가 설정되지 않았습니다."})
            
        genai.configure(api_key=GEMINI_KEY)
        model_name = 'models/gemini-2.5-flash'
        model = genai.GenerativeModel(model_name)
        
        # 4. Prompt without 7-item limit but allowing detailed output
        prompt = f"""
다음은 '{exact_law_name}' 법령의 일부 조문입니다 (파트 {chunk_index + 1}/{len(chunks)}):
{current_chunk}

이 법령 내용 중에서 '행정/건설 관리기관, 사업주, 지자체 등이 의무적으로 이행해야 하는 사항'(예: 정기 안전점검, 교육 실시, 계획 수립, 결과 통보 등)만 모두 추출하세요.
(발견되는 모든 의무사항을 남김없이 전부 추출하되, 각 의무의 내용을 충분히 구체적이고 상세하게 설명하세요.)
결과는 오직 아래의 순수 JSON 배열 포맷으로만 반환하세요(마크다운 없이). 의무사항이 없으면 빈 배열 []을 반환하세요.
[
  {{
    "article": "제O조",
    "duty_title": "핵심 의무 제목",
    "description": "구체적인 의무 내용을 상세하게 서술 (이행해야 할 대상, 조건, 방법 등을 포함)",
    "frequency": "수시 / 연 1회 등 기한",
    "target": "의무 이행 주체"
  }}
]
"""
        response = model.generate_content(prompt)
        resp_text = response.text.strip()
        if resp_text.startswith("```json"): resp_text = resp_text[7:]
        if resp_text.startswith("```"): resp_text = resp_text[3:]
        if resp_text.endswith("```"): resp_text = resp_text[:-3]
        
        try:
            duties = json.loads(resp_text.strip())
        except json.JSONDecodeError:
            print("JSON Decode Error. Raw resp:", resp_text)
            duties = []
            
        result_data = {
            "law_name": exact_law_name,
            "duties": duties,
            "has_more": chunk_index < len(chunks) - 1,
            "total_chunks": len(chunks)
        }
        
        return jsonify({"success": True, "data": result_data})
        
    except Exception as e:
        print("Chunked Duty Search Error:", e)
        return jsonify({"success": False, "message": f"서버 오류: {str(e)}"})

@app.route('/api/search_duties', methods=['POST'])
def search_duties():
    try:
        data = request.get_json(silent=True) or {}
        lsi_seq = data.get('lsi_seq', '')
        exact_law_name = data.get('law_name', '')
        if isinstance(lsi_seq, str): lsi_seq = lsi_seq.strip()
        if isinstance(exact_law_name, str): exact_law_name = exact_law_name.strip()
        
        if not lsi_seq or not exact_law_name:
            return jsonify({"success": False, "message": "법령일련번호 또는 법률명이 누락되었습니다."})
        
        doc_res = requests.get(f"https://www.law.go.kr/DRF/lawService.do?OC={LAW_KEY}&target=law&type=XML&MST={lsi_seq}", timeout=10)
        doc_root = ET.fromstring(doc_res.text)
        
        articles = doc_root.findall('.//조문단위')
        full_text = ""
        for art in articles:
            art_title = art.findtext('조문내용') or ""
            full_text += art_title + "\n"
            for hang in art.findall('.//항내용'):
                full_text += hang.text + "\n"
            for ho in art.findall('.//호내용'):
                full_text += ho.text + "\n"
                
        if len(full_text) > 8000:
            full_text = full_text[:8000]
            
        if not GEMINI_KEY:
            return jsonify({"success": False, "message": "Gemini API 키가 설정되지 않았습니다."})
            
        genai.configure(api_key=GEMINI_KEY)
        model_name = 'models/gemini-2.5-flash'
    
        model = genai.GenerativeModel(model_name)
        prompt = f"""
다음은 '{exact_law_name}' 법령의 일부 조문입니다:
{full_text}

이 법령 내용 중에서 '행정/건설 관리기관, 사업주, 지자체 등이 의무적으로 이행해야 하는 사항'(예: 정기 안전점검, 교육 실시, 계획 수립, 결과 통보 등)만 추출하세요.
(응답 시간 최적화를 위해 가장 중요하고 핵심적인 의무 사항 최대 7개까지만 추출하세요.)
결과는 오직 아래의 순수 JSON 배열 포맷으로만 반환하세요(마크다운 없이). 의무사항이 없으면 빈 배열 []을 반환하세요.
[
  {{
    "article": "제O조",
    "duty_title": "핵심 의무 제목",
    "description": "구체적인 의무 내용 요약",
    "frequency": "수시 / 연 1회 등 기한",
    "target": "의무 이행 주체"
  }}
]
"""
        response = model.generate_content(prompt)
        resp_text = response.text.strip()
        if resp_text.startswith("```json"): resp_text = resp_text[7:]
        if resp_text.startswith("```"): resp_text = resp_text[3:]
        if resp_text.endswith("```"): resp_text = resp_text[:-3]
        
        duties = json.loads(resp_text.strip())
        
        result_data = {
            "law_name": exact_law_name,
            "duties": duties
        }
        
        return jsonify({"success": True, "data": result_data})
        
    except Exception as e:
        print("Duty Search Error:", e)
        return jsonify({"success": False, "message": f"서버 오류: {str(e)}"})

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
        import xml.etree.ElementTree as ET
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

def download_law_to_db(law_name, law_key, md_path):
    import os
    import xml.etree.ElementTree as ET
    import urllib.parse
    import requests
    try:
        url = f'https://www.law.go.kr/DRF/lawSearch.do?OC={law_key}&target=law&type=XML&query={urllib.parse.quote(law_name)}'
        res = requests.get(url, timeout=5)
        root = ET.fromstring(res.text)
        law = root.find('.//law')
        if law is None:
            return False
        lsi_seq = law.find('법령일련번호').text
        
        doc_url = f'https://www.law.go.kr/DRF/lawService.do?OC={law_key}&target=law&type=XML&MST={lsi_seq}'
        doc_res = requests.get(doc_url, timeout=10)
        doc_root = ET.fromstring(doc_res.text)
        
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f'# {law_name}\n\n')
            for art in doc_root.findall('.//조문단위'):
                num = art.findtext('조문번호')
                title = art.findtext('조문제목')
                body = art.findtext('조문내용')
                title_str = f'({title})' if title else ''
                f.write(f'### 제{num}조 {title_str}\n{body}\n\n')
                
                for hang in art.findall('.//항'):
                    hang_body = hang.findtext('항내용')
                    if hang_body: f.write(f'{hang_body}\n')
                    for ho in hang.findall('.//호'):
                        ho_body = ho.findtext('호내용')
                        if ho_body: f.write(f'  {ho_body}\n')
                    for mok in hang.findall('.//목'):
                        mok_body = mok.findtext('목내용')
                        if mok_body: f.write(f'    {mok_body}\n')
                f.write('\n')
        return True
    except Exception as e:
        print(f"Auto-download failed for {law_name}: {e}")
        return False

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
            models_to_try = ['models/gemini-2.5-flash', 'models/gemini-2.0-flash', 'models/gemini-1.5-flash']
            
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
            count = 0
            for law in law_root.findall('.//law'):
                name = law.find('법령명한글')
                if name is not None and name.text:
                    law_name = name.text
                    link = f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}"
                    laws.append(f"[{law_name}]({link})")
                    
                    # Auto-download top 1 missing law
                    if count < 1:
                        clean_name = law_name.replace(" ", "").replace("·", "").replace("ㆍ", "")
                        md_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'laws', f"{clean_name}.md")
                        if not os.path.exists(md_path):
                            print(f"Auto-downloading missing law: {law_name}")
                            download_law_to_db(law_name, law_key, md_path)
                        count += 1
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
        for preferred in ['models/gemini-2.5-flash', 'models/gemini-2.0-flash', 'models/gemini-1.5-flash']:
            if preferred in available_models:
                model_name = preferred
                break
        if not model_name and available_models:
            model_name = available_models[0]
        if not model_name:
            raise Exception(f"텍스트 생성을 지원하는 모델이 없습니다. (검색된 모델: {available_models})")

        model = genai.GenerativeModel(model_name)
        search_model = None
        try:
            search_model = genai.GenerativeModel(model_name, tools='google_search_retrieval')
        except Exception:
            pass
        
        project_name = data.get('projectName', '이름 없음')
        project_type = data.get('projectType', '복합공사')
        budget = data.get('budget', 0)
        budget_nat = data.get('budgetNational', 0)
        budget_prov = data.get('budgetProvincial', 0)
        budget_mun = data.get('budgetMunicipal', 0)
        total_area = data.get('totalArea', 0)
        public_water_area = data.get('publicWaterArea', 0)
        description = data.get('description', '설명 없음')
        parcels = data.get('parcels', [])

        if not parcels and public_water_area <= 0:
            raise Exception("검증된 편입 필지 또는 공유수면 면적이 없습니다.")

        parcel_str_list = []
        all_zonings = set()
        for p in parcels:
            parcel_str_list.append(f"- {p['address']} (면적: {p['area']}㎡) | 지역지구: {p['zoning']}")
            for z in p['zoning'].split(', '):
                all_zonings.add(z)
                
        parcel_str = "\n".join(parcel_str_list)
        if not parcel_str:
            parcel_str = "지번이 부여된 육상 필지 편입 없음"
            
        zoning_context = ", ".join(list(all_zonings))
        
        public_water_instruction = ""
        if public_water_area > 0:
            public_water_instruction = f"""
        [특수 조건: 해상 및 공유수면 공사]
        본 사업 구역에는 지번이 존재하지 않는 바다/하천 등 **공유수면 면적 {public_water_area}㎡**가 포함되어 있습니다.
        따라서 토지이음 규제 내역에 나타나지 않더라도, 해상 공사 및 공유수면 점용과 관련된 다음 법률 및 절차를 반드시 최우선으로 검토하고 각 단계(Phase)에 포함하십시오:
        - 「공유수면 관리 및 매립에 관한 법률」 (점용·사용 허가, 실시계획 승인)
        - 「해양환경관리법」 (해역이용협의 등)
        - 「해양조사와 해양정보 활용에 관한 법률」 등 해상 인허가 관련 필수 법령
"""
        
        law_context = fetch_law_data(LAW_KEY, "국토의 계획 및 이용에 관한 법률")
        # 모든 DB 변수 추출
        all_rule_vars = get_all_variables()
        vars_instruction = ", ".join(all_rule_vars)
        
        # --- 에이전트 1: 파라미터 추출기 (Extractor Agent) ---
        extractor_prompt = f"""
        당신은 건설공사 내역 분석 에이전트입니다.
        아래 [사업 개요] 및 [편입필지 지역지구] 정보를 바탕으로 JSON 데이터를 추출하세요.
        응답은 순수 JSON 형식만 반환하세요 (마크다운 백틱 제외).
        
        [사업 개요] 사업명: {project_name}, 공종: {project_type}, 총 사업비: {budget}억, 면적: {total_area}㎡, 주요 내용: {description}
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

        # 국토계획법 등 기본 정보 패치
        law_context = fetch_law_data(LAW_KEY, "국토의 계획 및 이용에 관한 법률")

        prompt = f"""
        당신은 대한민국 시설직 공무원을 돕는 최고 수준의 법규 검토 AI 전문가입니다.
        
        🚨 [절대 누락 금지: 무결점 감사 대비 모드] 🚨
        사용자는 공무원이며, 단 하나의 법적 절차, 인허가, 현장 감독 사항이라도 누락될 경우 심각한 징계나 감사 지적을 받게 됩니다.
        따라서 사업 규모나 내용에 비추어 볼 때 단 1%의 가능성이라도 있는 법정 의무사항이나 인허가는 **절대로 생략하지 말고 모두 빠짐없이 도출**하십시오. 당신은 공무원의 완벽한 업무 처리를 보장하는 최후의 안전망입니다.
        
        아래 [사업 개요]와 토지대장에서 실시간으로 조회한 [편입필지 지역지구] 정보를 바탕으로 분석하세요.

        [사업 개요]
        - 사업명: {project_name}
        - 주요 사업 분류 (공종): {project_type}
        - 총 사업비: {budget}억 원
        - 검증된 총 사업 면적: {total_area}㎡
        - 주요 사업 내용: {description}
        
        [편입 필지 및 지역지구 현황] (매우 중요)
        {parcel_str}
        {public_water_instruction}
        
        ※ 핵심 검토 요건: 이 사업은 [{zoning_context}] 구역을 포함하고 있습니다. 이 용도지역에 따른 행위 제한 및 필수 인허가를 반드시 찾아내어 적으세요.
        {scale_permits_str}
        [법제처 제공 현행법 컨텍스트]
        {law_context}

        **[법령 조항 번호 명시 (매우 중요)]**
        1. 당신이 도출한 필수 법적 절차에 대해, **정확한 조항 번호(예: 제8조, 제10조 제1항 등)를 반드시 기재**하십시오.
        2. 제공된 텍스트(컨텍스트)에 법률 조문이 충분하지 않더라도, **구글 검색 도구(Google Search Retrieval)를 적극 활용하여 대한민국 법제처(law.go.kr) 등 공식 사이트의 최신 법령을 실시간으로 검색**하십시오.
        3. 🚨 **[현행법령 확인 의무]**: 검색 시 반드시 연혁법령이나 폐지된 법률이 아닌 **"현행법령(현재 시행 중인 법률)"**인지 확인해야 합니다. 만약 옛날 블로그 글이나 구법(폐지된 법)의 조항이라면 절대 사용하지 말고, 현행 법제처 기준으로 재확인하십시오.
        4. 조항 번호를 기재할 때는 절대 "컨텍스트에 없어서~"와 같은 변명이나 사과문, 해명글을 적지 마십시오. 전문적인 보고서 문체만을 유지하세요.

        **[전문가 수준의 심층 연관 분석 프레임워크 (Deep Reasoning Framework)]**
        당신은 단순 정보 검색기가 아니라 최상급 건설 행정 전문가입니다. 아래 3단계 사고 프레임워크를 반드시 거쳐 결과를 도출하십시오.
        
        [1단계: 사업 본질 분해 (Project Deconstruction)]
        제시된 사업 개요(예산, 면적, 공사내용)를 분석하여 해당 사업이 어떤 특성(예: 하천 공사, 산지 전용, 시특법상 1·2·3종 시설물 등)을 갖는지 스스로 규정하십시오.
        
        [2단계: 법적 트리거 탐색 (Legal Trigger Search)]
        분해된 사업 특성을 바탕으로, 당신의 내부 지식(Pre-trained Knowledge)을 총동원하여 '이 조건일 때 발동하는(Trigger) 법적 의무'가 무엇인지 샅샅이 탐색하십시오. 
        특히 「건설기술 진흥법」, 「산업안전보건법」, 「환경영향평가법」 등 대한민국 건설공사 핵심 법령에 따른 안전/환경/품질 관리 의무를 절대 누락하지 마십시오.
        
        [3단계: 생애주기별 역산 (Lifecycle Reverse-Engineering)]
        시공 단계의 의무만 찾지 마십시오. 도출된 의무를 이행하기 위해 기획이나 설계 단계에서 미리 준비해야 하는 행정 절차(예: 설계단계 건설사업관리, 타당성조사, 각종 영향평가, 심의 등)를 역산하여 도출하고 적절한 phase에 배치하십시오.

        **[추가 지시사항: 공종에 따른 엄격한 필터링 및 추측 금지]**
        이 사업은 '{project_type}'입니다.
        - [절대 금지 사항] '토목공사이더라도 건축물이 포함될 경우를 대비하여'와 같은 추측성 판단을 절대 하지 마십시오.
        - 입력된 공종이 '토목공사'라면 사업 현장에 100% 토목 시설물만 존재한다고 확정 지으십시오. 건축법, 건축서비스산업진흥법 등 건축 관련 법령은 단 1%도 도출해서는 안 됩니다.
        - 조경공사 역시 건축 관련 규제는 철저히 배제하고 산지/공원 위주로 도출하십시오.
        - 복합공사라면 모든 가능성을 열어두고 종합적으로 검토하세요.

        [요청 사항]
        보고서에 쓸 수 있도록 전문적인 용어로 답변하되, 응답은 반드시 아래 JSON 형식(마크다운 백틱 없이 순수 JSON만)으로 반환하세요.
        URL 링크 엉킴을 방지하기 위해, 관련 법령은 절대로 HTML 태그를 쓰지 말고 "law_name"(정확한 법령명 띄어쓰기 준수)과 "article"(조항 번호)로 정확히 분리하여 작성해 주세요.
        - 타당성 조사, 기본계획, 투자심사 등 구상/기획 단계에 해당하는 항목은 'planning' 배열에 작성하세요.
        - 건축허가, 도로점용허가 등 인허가 항목은 'permits' 배열에 별도로 분리하여 작성하세요.
        - 대금 지급(선금, 기성금, 준공금 등)과 관련된 절차가 여러 단계에 걸쳐 중복될 경우, 하나로 통합하여 '공사 대금 청구 및 지급' 등의 단일 항목으로 병합하세요.
        {{
            "permits": [
                {{
                    "name": "건축허가",
                    "law_name": "건축법",
                    "article": "제11조",
                    "reason": "해당 사업은 계획관리지역 내 새로운 건축물을 축조하는 사업이므로 건축허가가 필요함."
                }}
            ],
            "phases": {{
                "planning": [
                    {{"task": "타당성 조사 및 투자심사", "law_name": "지방재정법", "article": "제37조", "desc": "신규 투자사업에 대한 예산 편성 전 타당성 조사 및 투자심사 의뢰"}}
                ],
                "design": [
                    {{"task": "설계안전성검토 의뢰", "law_name": "건설기술 진흥법", "article": "제62조", "desc": "가설구조물 및 굴착 공사에 따른 설계안전성 사전 검토 (대상 여부 확인 필요)"}}
                ],
                "construction": [
                    {{"task": "안전관리계획서 제출", "law_name": "건설기술 진흥법", "article": "제62조", "desc": "착공 전 인허가 기관에 안전관리계획서 제출 및 승인"}}
                ],
                "completion": [
                    {{"task": "준공검사 신청", "law_name": "건설기술 진흥법", "article": "제39조", "desc": "공사 완료 후 발주청에 준공검사원 제출"}}
                ],
                "maintenance": [
                    {{"task": "하자보수 점검", "law_name": "건설산업기본법", "article": "제28조", "desc": "하자담보책임기간 내 정기 점검 실시"}}
                ]
            }}
        }}
        """
        
        try:
            if search_model:
                response = search_model.generate_content(prompt)
            else:
                response = model.generate_content(prompt)
        except Exception as e:
            print(f"Search retrieval failed, falling back to standard: {e}")
            response = model.generate_content(prompt)
            
        text_resp = response.text.strip()
        
        if text_resp.startswith("```json"):
            text_resp = text_resp[7:]
        if text_resp.startswith("```"):
            text_resp = text_resp[3:]
        if text_resp.endswith("```"):
            text_resp = text_resp[:-3]
            
        result = json.loads(text_resp.strip())
        
        # 100% Guaranteed Link Injection
        base_dir = os.path.dirname(os.path.abspath(__file__))
        law_urls_path = os.path.join(base_dir, 'data', 'law_urls.json')
        law_urls_dict = {}
        if os.path.exists(law_urls_path):
            with open(law_urls_path, 'r', encoding='utf-8') as f:
                law_urls_dict = json.load(f)
                
        import urllib.parse
        import requests
        import xml.etree.ElementTree as ET
        import concurrent.futures

        def resolve_url(item):
            if 'law_name' not in item or not item['law_name']:
                return
            law_name = item['law_name'].strip()
            
            if law_name in law_urls_dict:
                item['law_url'] = law_urls_dict[law_name]
                return
                
            try:
                res_law = requests.get(f"https://www.law.go.kr/DRF/lawSearch.do?OC={LAW_KEY}&target=law&type=XML&query={urllib.parse.quote(law_name)}", timeout=3)
                root_law = ET.fromstring(res_law.text)
                if int(root_law.findtext('totalCnt', '0')) > 0:
                    item['law_url'] = f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}"
                    return
            except: pass
            
            try:
                res_adm = requests.get(f"https://www.law.go.kr/DRF/lawSearch.do?OC={LAW_KEY}&target=admrul&type=XML&query={urllib.parse.quote(law_name)}", timeout=3)
                root_adm = ET.fromstring(res_adm.text)
                if int(root_adm.findtext('totalCnt', '0')) > 0:
                    item['law_url'] = f"https://www.law.go.kr/행정규칙/{urllib.parse.quote(law_name)}"
                    return
            except: pass
            
            is_admrul = law_name.endswith('지침') or law_name.endswith('기준') or law_name.endswith('고시') or law_name.endswith('규정')
            base = 'https://www.law.go.kr/LSW/admRulSc.do?query=' if is_admrul else 'https://www.law.go.kr/LSW/lsSc.do?query='
            item['law_url'] = base + urllib.parse.quote(law_name)
            
        items_to_resolve = []
        if 'permits' in result:
            items_to_resolve.extend(result['permits'])
        if 'phases' in result:
            for phase_items in result['phases'].values():
                items_to_resolve.extend(phase_items)
                
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            executor.map(resolve_url, items_to_resolve)
                
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



import tempfile
import werkzeug.utils

@app.route('/api/analyze/other_review', methods=['POST'])
def api_other_review():
    try:
        if request.content_type and 'multipart/form-data' in request.content_type:
            text_content = request.form.get('text', '')
            file_obj = request.files.get('file')
        else:
            data = request.json or {}
            text_content = data.get('text', '')
            file_obj = None
            
        if not text_content and not file_obj:
            return jsonify({"success": False, "message": "검토할 내용이나 파일이 제공되지 않았습니다."}), 400
            
        genai.configure(api_key=GEMINI_KEY)
        
        uploaded_file = None
        file_text = ""
        if file_obj and file_obj.filename:
            filename = werkzeug.utils.secure_filename(file_obj.filename)
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, filename)
            file_obj.save(temp_path)
            
            try:
                uploaded_file = genai.upload_file(path=temp_path, display_name=filename)
            except Exception as e:
                print(f"genai.upload_file failed: {e}. Falling back to local extraction.")
                try:
                    import fitz
                    doc = fitz.open(temp_path)
                    for page in doc:
                        file_text += page.get_text() + "\n"
                except Exception:
                    try:
                        with open(temp_path, 'r', encoding='utf-8') as f:
                            file_text = f.read()
                    except:
                        pass
                
                if file_text:
                    text_content += f"\n\n[첨부 문서 내용]\n{file_text[:30000]}"
                    
            os.remove(temp_path)
            
        try:
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and 'vision' not in m.name.lower()]
            models_to_try = sorted(available_models, key=lambda x: (0 if '1.5-pro' in x else 1 if '2.5-pro' in x else 2 if 'pro' in x else 3 if '1.5-flash' in x else 4))
        except:
            models_to_try = ['models/gemini-2.5-flash', 'models/gemini-2.0-flash', 'models/gemini-1.5-flash']
            
        moleg_context = fetch_moleg_context(text_content, os.environ.get('MOLEG_API_KEY', ''))
        local_law_context = fetch_local_law_data(text_content, moleg_context)
        
        raw_text = text_content.strip()
        has_file = bool(file_text or uploaded_file)
        dummy_phrases = ["이네용", "이거", "이거 분석해줘", "분석해줘", "검토해줘"]
        has_text = bool(raw_text and raw_text not in dummy_phrases and len(raw_text) > 5)

        if has_file and has_text:
            mode_instruction = "🚨 **[분석 모드: 질의 + 첨부문서]** 사용자가 특정 질문/지시사항과 함께 문서를 첨부했습니다. 첨부된 문서를 꼼꼼히 분석하되, 반드시 **사용자가 입력한 [요청 내용]을 최우선으로 반영하여 실행/답변**하십시오. 필요시 아래 4단계 구조를 적절히 활용하여 보충하십시오."
        elif has_file and not has_text:
            mode_instruction = "🚨 **[분석 모드: 문서 단독 분석]** 사용자가 특별한 질문 없이 문서만 첨부했습니다. 절대로 '질문이 부족하다'고 핑계대지 마시고, 첨부된 문서 자체를 심층 분석하여 스스로 핵심 쟁점을 도출해낸 뒤 **무조건 아래 4단계 구조의 종합 법리 검토 보고서를 작성**하십시오."
        else:
            mode_instruction = "🚨 **[분석 모드: 일반 질의응답]** 사용자가 첨부문서 없이 일반적인 질문이나 지시를 내렸습니다. [요청 내용]을 분석하여 정확한 법리적 답변 및 지시된 포맷으로 제공하십시오. 가급적 아래 4단계 구조를 따르되, 단순한 질문이나 특정 지시가 있다면 그 지시에 맞게 유연하게 답변하십시오."
        
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
  - 구글 검색 도구를 사용할 때 반드시 `site:casenote.kr 검색어` 형식으로 검색어에 케이스노트 도메인을 강제하여 실제 존재하는 판례만 찾으십시오.
  - 🚨 **[가짜 판례 창작 절대 금지]**: 케이스노트에서 검색되지 않은 사건번호나 판례를 AI가 임의로 창작(할루시네이션)하면 절대 안 됩니다! 검색 결과가 없으면 "현재 쟁점과 관련된 대법원 판례를 찾을 수 없습니다."라고만 출력하십시오.
  - 🚨 **[링크 생성 규칙]**: 검색된 실제 판례가 있다면 링크는 무조건 **검색 결과 페이지**로 연결되도록 아래 포맷을 엄격히 지켜 작성하십시오.
    - 포맷: `[판례명(사건번호)](https://casenote.kr/search/?q=사건번호)`
    - 예시: `[대법원 2014. 11. 13. 선고 2014다87955 판결](https://casenote.kr/search/?q=2014다87955)`
4. 응답 구조 및 모드:
  {mode_instruction}
5. 🚨 **[할루시네이션(환각) 원천 차단]**: 만약 사용자가 질의한 특정 법률의 원문이 [로컬 법령 데이터베이스]에 제공되지 않았다면, **절대로 조항 번호(예: 제X조)나 구체적 내용을 스스로 창작하거나 유추해서 적지 마십시오!** 이 경우 일반적인 법리와 절차만 설명하고, 반드시 "해당 법률의 원문 데이터가 로컬 DB에 없어 정확한 조항 번호는 법제처(law.go.kr)를 직접 참조하시기 바랍니다."라고 명시하십시오.

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
        
        contents_payload = [prompt]
        if uploaded_file:
            contents_payload.append(uploaded_file)
            
        response = None
        last_err = None
        for m in models_to_try:
            try:
                try:
                    model = genai.GenerativeModel(model_name=m, tools='google_search_retrieval')
                    response = model.generate_content(contents_payload)
                    break
                except Exception as tool_e:
                    print(f"Tool {m} fallback: {tool_e}")
                    model = genai.GenerativeModel(model_name=m)
                    response = model.generate_content(contents_payload)
                    break
            except Exception as e:
                last_err = e
                print(f"Model {m} failed: {e}")
                continue
                
        if not response:
            raise Exception(f"모든 AI 모델이 요청 한도 초과 또는 오류로 실패했습니다. 마지막 오류: {last_err}")
            
        file_name = uploaded_file.name if uploaded_file else ""
        return jsonify({
            "success": True, 
            "result": response.text, 
            "file_name": file_name, 
            "initial_context": prompt
        })
        
    except Exception as e:
        print(f"Other Review API Error: {e}")
        return jsonify({"success": False, "message": f"서버 오류: {str(e)}"})


@app.route('/api/chat/duty_list', methods=['POST'])
def api_chat_duty_list():
    try:
        data = request.json
        chat_history = data.get('chat_history', [])
        new_message = data.get('new_message', '')
        law_name = data.get('law_name', '')
        
        if not new_message:
            return jsonify({"success": False, "message": "질문이 제공되지 않았습니다."}), 400
            
        genai.configure(api_key=GEMINI_KEY)
        
        contents_payload = []
        initial_context = f"사용자가 '{law_name}' 법률과 그에 따른 법적 의무 사항에 대해 질문하고 있습니다. 친절하고 정확하게 법률 상담원처럼 답변해주세요."
        contents_payload.append({"role": "user", "parts": [initial_context]})
        
        for msg in chat_history:
            contents_payload.append({
                "role": msg["role"],
                "parts": [msg["text"]]
            })
            
        contents_payload.append({
            "role": "user",
            "parts": [new_message]
        })
        
        model_name = 'models/gemini-2.5-flash'
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(contents_payload)
            
        return jsonify({"success": True, "result": response.text})
        
    except Exception as e:
        print(f"Duty List Chat API Error: {e}")
        return jsonify({"success": False, "message": f"서버 오류: {str(e)}"})

@app.route('/api/chat/other_review', methods=['POST'])
def api_chat_other_review():
    try:
        data = request.json
        chat_history = data.get('chat_history', [])
        new_message = data.get('new_message', '')
        file_name = data.get('file_name', '')
        initial_context = data.get('initial_context', '')
        
        if not new_message:
            return jsonify({"success": False, "message": "질문이 제공되지 않았습니다."}), 400
            
        genai.configure(api_key=GEMINI_KEY)
        
        contents_payload = []
        first_user_parts = [initial_context]
        if file_name:
            try:
                file_obj = genai.get_file(file_name)
                first_user_parts.append(file_obj)
            except Exception as e:
                print(f"File retrieval failed: {e}")
                
        contents_payload.append({"role": "user", "parts": first_user_parts})
        
        for msg in chat_history:
            contents_payload.append({
                "role": msg["role"],
                "parts": [msg["text"]]
            })
            
        contents_payload.append({
            "role": "user",
            "parts": [new_message]
        })
        
        try:
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and 'vision' not in m.name.lower()]
            models_to_try = sorted(available_models, key=lambda x: (0 if '1.5-pro' in x else 1 if '2.5-pro' in x else 2 if 'pro' in x else 3 if '1.5-flash' in x else 4))
        except:
            models_to_try = ['models/gemini-2.5-flash', 'models/gemini-2.0-flash', 'models/gemini-1.5-flash']
            
        response = None
        last_err = None
        for m in models_to_try:
            try:
                model = genai.GenerativeModel(model_name=m)
                response = model.generate_content(contents_payload)
                break
            except Exception as e:
                last_err = e
                continue
                
        if not response:
            raise Exception(f"채팅 응답 생성 실패: {last_err}")
            
        return jsonify({"success": True, "result": response.text})
        
    except Exception as e:
        print(f"Chat Review API Error: {e}")
        return jsonify({"success": False, "message": f"서버 오류: {str(e)}"})

@app.route('/api/chat/report', methods=['POST'])
def api_chat_report():
    try:
        data = request.json
        chat_history = data.get('chat_history', [])
        new_message = data.get('new_message', '')
        report_data = data.get('report_data', {})
        
        if not new_message:
            return jsonify({"success": False, "message": "질문이 제공되지 않았습니다."}), 400
            
        genai.configure(api_key=GEMINI_KEY)
        
        initial_context = f"""
        당신은 건설사업의 [AI 법규 검토 종합 보고서]에 대해 설명해주는 AI 챗봇입니다.
        아래는 당신이 조금 전 분석하여 생성한 보고서의 원본 데이터(JSON)입니다.
        사용자가 이 보고서의 내용에 대해 질문하면, 아래 데이터를 바탕으로 친절하고 전문적으로 답변해 주세요.
        없는 내용을 꾸며내지 마시고, 데이터에 있는 법적 근거와 현장 상황을 연결하여 설명해 주십시오.

        [보고서 데이터]:
        {json.dumps(report_data, ensure_ascii=False, indent=2)}
        """
        
        contents_payload = []
        contents_payload.append({"role": "user", "parts": [initial_context]})
        
        for msg in chat_history:
            contents_payload.append({
                "role": msg["role"],
                "parts": [msg["text"]]
            })
            
        contents_payload.append({
            "role": "user",
            "parts": [new_message]
        })
        
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        model_name = None
        for preferred in ['models/gemini-2.5-flash', 'models/gemini-2.0-flash', 'models/gemini-1.5-flash']:
            if preferred in available_models:
                model_name = preferred
                break
                
        # If no preferred model is found, just pick the very first available one
        if not model_name and available_models:
            model_name = available_models[0]
        elif not model_name:
            model_name = 'models/gemini-2.5-flash'  # Final fallback if list is empty
            
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(contents_payload)
        
        return jsonify({
            "success": True,
            "result": response.text
        })
        
    except Exception as e:
        print(f"Report Chat API Error: {e}")
        return jsonify({"success": False, "message": f"서버 오류: {str(e)}"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
