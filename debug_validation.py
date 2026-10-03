import urllib.request
import json

BASE = "http://localhost"
COOKIE = "dq_token=test"

req = urllib.request.Request(f"{BASE}/api/validations",
    data=json.dumps({"catalogId": "bba7cdcf-b8a4-4745-b4a3-295ff0456579", "tableId": "9f1da478-53f0-45bb-92e0-e83fb51c5ea2"}).encode(),
    method="POST", headers={"Content-Type": "application/json", "Cookie": COOKIE})
resp = urllib.request.urlopen(req, timeout=30)
data = json.loads(resp.read().decode())
print(json.dumps(data, indent=2))
