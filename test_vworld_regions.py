import requests

key = "D3C0A259-B45A-3CE6-841D-62EFB103D3CB"
domain = "http://127.0.0.1"

def test_layer(layer, filter_param=None):
    url = f"https://api.vworld.kr/req/data?service=data&request=GetFeature&data={layer}&key={key}&domain={domain}&size=1000&geometry=false"
    if filter_param:
        url += f"&attrFilter={filter_param}"
    print(f"--- {layer} ---")
    try:
        r = requests.get(url, timeout=10).json()
        if r.get('response', {}).get('status') == 'OK':
            features = r['response']['result']['featureCollection']['features']
            print("Count:", len(features))
            if features:
                print("Sample:", features[0]['properties'])
        else:
            print("Error:", r)
    except Exception as e:
        print("Exception:", e)

test_layer("LT_C_ADSIGG_INFO", "sig_cd:like:48")
