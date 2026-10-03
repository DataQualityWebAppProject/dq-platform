import urllib.request
import json

# Test 1: Interpret rule
print("=== Test 1: Interpret Rule ===")
url = "http://localhost/api/rules/interpret"
data = json.dumps({
    "naturalLanguage": "ABONO must be greater than 0",
    "scope": "column"
}).encode()

req = urllib.request.Request(url, data=data, headers={
    "Content-Type": "application/json",
    "Cookie": "dq_token=test"
})

try:
    resp = urllib.request.urlopen(req, timeout=30)
    print(f"Status: {resp.status}")
    body = json.loads(resp.read().decode())
    print(json.dumps(body, indent=2)[:500])
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode()[:300])

# Test 2: Generate code
print("\n=== Test 2: Generate Code ===")
url2 = "http://localhost/api/generate-code"
data2 = json.dumps({
    "naturalLanguage": "ABONO must be greater than 0",
    "columnId": "ABONO"
}).encode()

req2 = urllib.request.Request(url2, data=data2, headers={
    "Content-Type": "application/json",
    "Cookie": "dq_token=test"
})

try:
    resp2 = urllib.request.urlopen(req2, timeout=30)
    print(f"Status: {resp2.status}")
    body2 = json.loads(resp2.read().decode())
    print(json.dumps(body2, indent=2)[:800])
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode()[:300])
