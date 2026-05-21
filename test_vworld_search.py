import requests
import time

key = "D3C0A259-B45A-3CE6-841D-62EFB103D3CB"

def test_search(query, category):
    start = time.time()
    url = f"https://api.vworld.kr/req/search?service=search&request=search&version=2.0&size=1000&page=1&query={query}&type=district&category={category}&format=json&errorformat=json&key={key}&domain=http://127.0.0.1"
    try:
        r = requests.get(url, timeout=5).json()
        print(f"[{category}] Query '{query}' -> Time: {time.time()-start:.2f}s")
        if r.get('response', {}).get('status') == 'OK':
            items = r['response']['result']['items']
            print("Count:", len(items))
            for i in range(min(3, len(items))):
                print(f"  {items[i]['title']} ({items[i]['id']})")
        else:
            print("Error:", r)
    except Exception as e:
        print("Exception:", e)

test_search("경상남도", "L2")
test_search("남해군", "L3")
test_search("창원시", "L3")
test_search("상주면", "L4")
