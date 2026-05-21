import requests

# BJD code for 성주군 수륜면 수륜리: 4784033023
# (47: 경북, 840: 성주군, 330: 수륜면, 23: 수륜리) -> This is a guess. Let's find it.
# Actually we can use the VWorld search API to find the bcode.
def get_bcode(query):
    url = f"https://api.vworld.kr/req/search?service=search&request=search&version=2.0&size=10&page=1&query={query}&type=district&category=L4&format=json&errorformat=json&key=D3C0A259-B45A-3CE6-841D-62EFB103D3CB&domain=http://127.0.0.1"
    res = requests.get(url).json()
    items = res.get('response', {}).get('result', {}).get('items', [])
    for item in items:
        if '수륜리' in item['title']:
            return item['id']
    return None

bcode = get_bcode("수륜면 수륜리")
print("Bcode:", bcode)

if bcode:
    pnu = bcode + "100150002"
    print("PNU:", pnu)
    
    # Check Parcel
    url_parcel = f"https://api.vworld.kr/req/data?service=data&request=GetFeature&data=lp_pa_cbnd_bubun&key=D3C0A259-B45A-3CE6-841D-62EFB103D3CB&domain=http://127.0.0.1&attrFilter=pnu:=:{pnu}"
    res_parcel = requests.get(url_parcel).json()
    features = res_parcel.get('response', {}).get('result', {}).get('featureCollection', {}).get('features', [])
    if features:
        print("Parcel:", features[0]['properties'])
    else:
        print("Parcel not found")
        
    # Check Zoning
    url_zoning = f"http://api.vworld.kr/ned/data/getLandUseAttr?key=D3C0A259-B45A-3CE6-841D-62EFB103D3CB&domain=http://127.0.0.1&pnu={pnu}&format=json&numOfRows=50&pageNo=1"
    res_zoning = requests.get(url_zoning).json()
    fields = res_zoning.get('landUses', {}).get('field', [])
    zones = []
    for f in fields:
        z = f.get('prposAreaDstrcCodeNm')
        if z and z not in zones:
            zones.append(z)
    print("Zoning:", zones)
