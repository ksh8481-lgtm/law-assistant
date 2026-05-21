import requests

try:
    # Test local API for sigungu with parent_code = 48 (Gyeongnam)
    url = "http://127.0.0.1:5000/api/regions/sigungu?vworldKey=D3C0A259-B45A-3CE6-841D-62EFB103D3CB&parentCode=48"
    r = requests.get(url)
    print("Status:", r.status_code)
    print("Response:", r.text)
except Exception as e:
    print("Exception:", e)
