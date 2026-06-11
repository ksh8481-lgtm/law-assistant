import os
import requests
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
import io
import re

API_KEY = "ksh8481"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'laws')

def extract_text_from_hwpx(hwpx_bytes):
    texts = []
    try:
        with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as z:
            for name in z.namelist():
                if name.startswith('Contents/section'):
                    xml_data = z.read(name)
                    # Strip namespaces for easier parsing
                    xml_str = xml_data.decode('utf-8', errors='ignore')
                    xml_str = re.sub(r'\sxmlns="[^"]+"', '', xml_str, count=1)
                    # Also strip hp: namespace prefixes
                    xml_str = re.sub(r'hp:', '', xml_str)
                    
                    root = ET.fromstring(xml_str)
                    
                    for p in root.iter('p'):
                        p_texts = []
                        for t in p.iter('t'):
                            if t.text:
                                p_texts.append(t.text)
                        if p_texts:
                            texts.append(''.join(p_texts))
    except Exception as e:
        print(f"Failed to parse HWPX: {e}")
        
    return '\n\n'.join(texts)

def process_hwpx_law(law_name):
    print(f"Fetching HWPX for: {law_name}")
    q = urllib.parse.quote(law_name)
    res = requests.get(f'https://www.law.go.kr/DRF/lawSearch.do?OC={API_KEY}&target=admrul&type=XML&query={q}')
    root = ET.fromstring(res.content)
    
    mst_id = None
    if root.find('.//admrul/행정규칙일련번호') is not None:
        mst_id = root.find('.//admrul/행정규칙일련번호').text
        
    if not mst_id:
        print("Not found.")
        return
        
    res2 = requests.get(f'https://www.law.go.kr/DRF/lawService.do?OC={API_KEY}&target=admrul&ID={mst_id}&type=XML')
    root2 = ET.fromstring(res2.content)
    
    hwpx_link = None
    for f in root2.findall('.//첨부파일'):
        names = f.findall('첨부파일명')
        links = f.findall('첨부파일링크')
        for n, l in zip(names, links):
            if n.text and (n.text.strip().endswith('.hwpx') or n.text.strip().endswith('.hwp')):
                hwpx_link = l.text.strip()
                break
        if hwpx_link: break
            
    if not hwpx_link:
        print("No HWPX attachment found.")
        return
        
    print(f"Downloading {hwpx_link}...")
    req = requests.get(hwpx_link, headers={'User-Agent': 'Mozilla/5.0'})
    
    print("Extracting text...")
    text_content = extract_text_from_hwpx(req.content)
    
    md_content = f"# {law_name}\n\n"
    md_content += "## 본문 및 별표 (첨부파일 추출본)\n\n"
    md_content += text_content
    
    safe_filename = law_name.replace(" ", "_").replace("/", "_") + ".md"
    file_path = os.path.join(OUTPUT_DIR, safe_filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print(f"Saved {safe_filename} ({len(md_content)} chars)")

if __name__ == '__main__':
    items = [
        '지방자치단체 입찰 및 계약집행기준',
        '지방자치단체 입찰시 낙찰자 결정기준',
        '재해영향평가등의 협의 실무지침'
    ]
    for item in items:
        process_hwpx_law(item)
