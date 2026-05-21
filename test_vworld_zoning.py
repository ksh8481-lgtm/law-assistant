import requests

key = "D3C0A259-B45A-3CE6-841D-62EFB103D3CB"
domain = "http://127.0.0.1"
pnu = "4884031022202900001" # 상주면 양아리 산 290-1

def test_parcel_layer():
    url = f"https://api.vworld.kr/req/data?service=data&request=GetFeature&data=lp_pa_cbnd_bubun&key={key}&domain={domain}&attrFilter=pnu:=:{pnu}"
    try:
        r = requests.get(url, timeout=5).json()
        if r.get('response', {}).get('status') == 'OK':
            features = r['response']['result']['featureCollection']['features']
            print(f"Count: {len(features)}")
            for f in features:
                print("  ->", f['properties'])
        else:
            print(f"Error: {r}")
    except Exception as e:
        print(f"Exception: {e}")

test_parcel_layer()
