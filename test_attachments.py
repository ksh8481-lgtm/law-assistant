import requests
import xml.etree.ElementTree as ET
import urllib.parse
res = requests.get('https://www.law.go.kr/DRF/lawService.do?OC=ksh8481&target=law&MST=281245&type=XML')
root = ET.fromstring(res.content)
links = [t.text for t in root.findall('.//별표서식파일링크')]
for link in links[:3]:
    h = requests.get('https://www.law.go.kr' + link, stream=True)
    print(urllib.parse.unquote(h.headers.get('Content-Disposition', '')))
