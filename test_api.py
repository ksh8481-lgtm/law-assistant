import requests, urllib.parse
VWORLD_KEY = 'D3C0A259-B45A-3CE6-841D-62EFB103D3CB'
addr = urllib.parse.quote("서울특별시 강남구 역삼동 123-4")
url_search = f'https://api.vworld.kr/req/search?service=search&request=search&version=2.0&size=10&page=1&query={addr}&type=address&category=parcel&key={VWORLD_KEY}&domain=http://127.0.0.1&format=json&callback=test'
res = requests.get(url_search).text
print('Search:', res[:200])

pnu = '1168010100101230004'
url_zoning = f'https://api.vworld.kr/ned/data/getLandUseAttr?key={VWORLD_KEY}&domain=http://127.0.0.1&pnu={pnu}&numOfRows=50&pageNo=1&format=json&callback=test'
print('Zoning:', requests.get(url_zoning).text[:200])
