import requests
import json

reqData = {
    "address": "경남 남해군 상주면 양아리 799-2",
    "bcode": "4884032021",
    "san": "1",
    "bonbeon": "799",
    "bubeon": "2",
    "area": 100
}

res = requests.post('http://127.0.0.1:5000/api/verify_parcel', json=reqData)
print(res.status_code)
try:
    print(json.dumps(res.json(), indent=2, ensure_ascii=False))
except:
    print(res.text)
