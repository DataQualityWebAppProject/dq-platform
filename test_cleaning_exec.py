import urllib.request
import json

BASE = "http://localhost"
COOKIE = "dq_token=test"

# First generate a script
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
print(f"Generated script:\n{script}\n")

# Now execute
url2 = f"{BASE}/api/cleaning/execute"
data2 = json.dumps({
    "catalogId": "bba7cdcf-b8a4-4745-b4a3-295ff0456579",
    "tableId": "9f1da478-53f0-45bb-92e0-e83fb51c5ea2",
    "script": script,
}).encode()

req2 = urllib.request.Request(url2, data=data2, method="POST", headers={
    "Content-Type": "application/json",
    "Cookie": COOKIE,
})
try:
    resp2 = urllib.request.urlopen(req2, timeout=30)
    print(f"Status: {resp2.status}")
    print(resp2.read().decode()[:500])
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode()[:500])
