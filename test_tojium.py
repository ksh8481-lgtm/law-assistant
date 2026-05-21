import requests
import re

def test_tojium(pnu):
    url = f"https://www.eum.go.kr/web/ar/lu/luLandDetPopup.jsp?isNoScr=script&pnu={pnu}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=5)
        print("Status:", r.status_code)
        
        # Regex to find the contents of the td next to the th containing '지역지구등 지정여부'
        match = re.search(r'지역지구등 지정여부.*?<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
        if match:
            # Clean up HTML tags
            content = match.group(1)
            content = re.sub(r'<[^>]+>', ' ', content)
            content = re.sub(r'\s+', ' ', content).strip()
            print("지역지구:", content)
        else:
            print("Could not find zoning table.")
    except Exception as e:
        print("Exception:", e)

print("Testing Yeoksam-dong 825-1...")
test_tojium("1168010100108250001")
