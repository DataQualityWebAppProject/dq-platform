import urllib.request
import json

url = "http://localhost/api/validations"
data = json.dumps({
    "catalogId": "bba7cdcf-b8a4-4745-b4a3-295ff0456579",
    "tableId": "9f1da478-53f0-45bb-92e0-e83fb51c5ea2"
}).encode()

req = urllib.request.Request(url, data=data, headers={
    "Content-Type": "application/json",
    "Cookie": "dq_token=test"
})

try:
    resp = urllib.request.urlopen(req, timeout=30)
    print(f"Status: {resp.status}")
    body = resp.read().decode()
    print(body[:1000])
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode()[:500])
