import requests
import urllib.parse

key = "D3C0A259-B45A-3CE6-841D-62EFB103D3CB"
pnu = "1168010100108250001"

# Try Data.go.kr standard endpoint structure but on vworld domain
url1 = f"http://api.vworld.kr/ned/data/getLandUseAttr?key={key}&domain=http://127.0.0.1&pnu={pnu}&format=json&numOfRows=10&pageNo=1"

# Try VWorld standard format
url2 = f"http://api.vworld.kr/req/data?service=data&request=GetFeature&data=LT_C_UQ111&key={key}&domain=http://127.0.0.1&attrFilter=pnu:=:{pnu}"

print("URL1:", url1)
try:
    r1 = requests.get(url1, timeout=5)
    print("Status 1:", r1.status_code)
    print("Response 1:", r1.text[:200])
except Exception as e:
    print("Error 1:", e)
