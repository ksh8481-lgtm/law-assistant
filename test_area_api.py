import requests

key = "D3C0A259-B45A-3CE6-841D-62EFB103D3CB"
pnu = "4784033042100150002"  # 수륜리 15-2 (Area should be 3838, Jimok 답)

endpoints = [
    "getLandCharacteristics", # 토지특성정보
    "getLandLedger",          # 토지임야대장
    "getLandInfo",
    "getLandUseAttr"          # Reference (works)
]

for ep in endpoints:
    url = f"http://api.vworld.kr/ned/data/{ep}?key={key}&domain=http://127.0.0.1&pnu={pnu}&format=json"
    try:
        res = requests.get(url, timeout=5)
        print(f"[{ep}] Status: {res.status_code}")
        if res.status_code == 200:
            print("Response:", res.text[:200])
    except Exception as e:
        print(f"[{ep}] Error: {e}")
