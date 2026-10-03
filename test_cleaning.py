import urllib.request
import json

# Test cleaning/generate
print("=== Test: Generate Cleaning Script ===")
url = "http://localhost/api/cleaning/generate"
data = json.dumps({
    "catalogId": "bba7cdcf-b8a4-4745-b4a3-295ff0456579",
    "tableId": "9f1da478-53f0-45bb-92e0-e83fb51c5ea2",
    "issues": "remove rows where ABONO is negative"
}).encode()

req = urllib.request.Request(url, data=data, headers={
    "Content-Type": "application/json",
    "Cookie": "dq_token=test"
})

try:
    resp = urllib.request.urlopen(req, timeout=30)
    print(f"Status: {resp.status}")
    body = json.loads(resp.read().decode())
    print(f"Script preview: {body.get('script', '')[:300]}")
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode()[:300])

# Test reports/generate
print("\n=== Test: Generate Report ===")
url2 = "http://localhost/api/reports/generate"
data2 = json.dumps({
    "catalogId": "bba7cdcf-b8a4-4745-b4a3-295ff0456579"
}).encode()

req2 = urllib.request.Request(url2, data=data2, headers={
    "Content-Type": "application/json",
    "Cookie": "dq_token=test"
})

try:
    resp2 = urllib.request.urlopen(req2, timeout=30)
    print(f"Status: {resp2.status}")
    body2 = json.loads(resp2.read().decode())
    print(f"Report preview: {body2.get('report', '')[:400]}")
    print(f"Catalog: {body2.get('catalogName')}, Tables: {body2.get('tablesCount')}, Rules: {body2.get('rulesCount')}")
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode()[:300])
