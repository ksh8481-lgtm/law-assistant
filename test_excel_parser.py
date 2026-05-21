import re
import requests

key = "D3C0A259-B45A-3CE6-841D-62EFB103D3CB"

addresses = [
    "경북 성주군 수륜면 수륜리 15-2",
    "상주면 양아리 산 290-1",
    "서울특별시 강남구 역삼동 825-1"
]

def parse_address(full_addr):
    # Regex to extract 산, 본번, 부번
    # Matches: (산)? (number)-(number) or (number)
    match = re.search(r'(산)?\s*(\d+)(?:-(\d+))?\s*$', full_addr)
    if match:
        san_str = match.group(1)
        bonbeon = match.group(2)
        bubeon = match.group(3) if match.group(3) else "0"
        san = "2" if san_str else "1"
        
        # Address part is everything before the match
        addr_part = full_addr[:match.start()].strip()
        return addr_part, san, bonbeon, bubeon
    return full_addr, "1", "", "0"

def get_bcode(full_addr):
    # Use VWorld Search API (type=address)
    url = f"https://api.vworld.kr/req/search?service=search&request=search&version=2.0&size=10&page=1&query={full_addr}&type=address&category=parcel&format=json&errorformat=json&key={key}&domain=http://127.0.0.1"
    try:
        res = requests.get(url, timeout=5).json()
        items = res.get('response', {}).get('result', {}).get('items', [])
        if items:
            # Address search usually returns parcel object with 'bjdcd' or 'parcel'
            return items[0].get('address', {}).get('bldnmdc', '') + " / PNU: " + items[0].get('id', '')
    except Exception as e:
        return str(e)
    return None

for addr in addresses:
    bcode = get_bcode(addr)
    print(f"[{addr}] -> BCODE/PNU: {bcode}")
