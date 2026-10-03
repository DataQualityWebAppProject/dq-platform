import urllib.request
import json

BASE = "http://localhost"
COOKIE = "dq_token=test"

url = f"{BASE}/api/cleaning/generate"
data = json.dumps({
    "catalogId": "bba7cdcf-b8a4-4745-b4a3-295ff0456579",
    "tableId": "9f1da478-53f0-45bb-92e0-e83fb51c5ea2",
    "issues": "remove duplicate rows and trim string columns",
}).encode()

req = urllib.request.Request(url, data=data, method="POST", headers={
    "Content-Type": "application/json",
    "Cookie": COOKIE,
})
resp = urllib.request.urlopen(req, timeout=30)
gen_data = json.loads(resp.read().decode())
script = gen_data.get("script", "")
print(f"=== SCRIPT ===\n{script}\n")
