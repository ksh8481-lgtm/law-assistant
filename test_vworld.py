import requests

key = "D3C0A259-B45A-3CE6-841D-62EFB103D3CB"
pnu = "4884031022202900001"
domain = "http://127.0.0.1"

# 연속지적도 테스트
url1 = f"https://api.vworld.kr/req/data?service=data&request=GetFeature&data=lp_pa_cbnd_bubun&key={key}&domain={domain}&attrFilter=pnu:=:{pnu}"
r1 = requests.get(url1).json()
print("연속지적도:", r1)

# 용도지역지구 테스트 (lp_uq_111)
url2 = f"https://api.vworld.kr/req/data?service=data&request=GetFeature&data=lp_uq_111&key={key}&domain={domain}&attrFilter=pnu:=:{pnu}"
r2 = requests.get(url2).json()
print("용도지역:", r2)
