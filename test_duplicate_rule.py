import urllib.request
import json

BASE = "http://localhost"
COOKIE = "dq_token=test"

def post(path, data):
    req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(data).encode(),
                                   method="POST", headers={"Content-Type": "application/json", "Cookie": COOKIE})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, json.loads(resp.read().decode())
    except Exception as e:
        code = getattr(e, 'code', 0)
        body = e.read().decode() if hasattr(e, 'read') else str(e)
        return code, json.loads(body) if body.startswith('{') else {"raw": body}

# Existing rule: "CANT BE NULL" on TDOC_DOCU in table ABONOS_FISA_202602, catalog bba7cdcf...
CATALOG_ID = "bba7cdcf-b8a4-4745-b4a3-295ff0456579"
TABLE_ID = "ABONOS_FISA_202602"
COLUMN_ID = "TDOC_DOCU"

print("=== Test 1: Exact duplicate text ===")
code, data = post("/api/rules", {
    "naturalLanguage": "CANT BE NULL",
    "scope": "column", "catalogId": CATALOG_ID, "tableId": TABLE_ID, "columnId": COLUMN_ID,
})
print(f"Status: {code}")
print(json.dumps(data, indent=2))

print("\n=== Test 2: Semantically equivalent (different wording) ===")
code, data = post("/api/rules", {
    "naturalLanguage": "this field should never be empty or missing",
    "scope": "column", "catalogId": CATALOG_ID, "tableId": TABLE_ID, "columnId": COLUMN_ID,
})
print(f"Status: {code}")
print(json.dumps(data, indent=2))

print("\n=== Test 3: Genuinely different rule (should succeed) ===")
code, data = post("/api/rules", {
    "naturalLanguage": f"_TEST_UNIQUE_{__import__('time').time()}: TDOC_DOCU must start with letter D",
    "scope": "column", "catalogId": CATALOG_ID, "tableId": TABLE_ID, "columnId": COLUMN_ID,
})
print(f"Status: {code}")
print(json.dumps(data, indent=2))

# Cleanup test 3 rule if created
if code == 200 and data.get("id"):
    import boto3
    ddb = boto3.resource('dynamodb', region_name='us-east-1')
    ddb.Table('dq-rules').delete_item(Key={'pk': f"RULE#{data['id']}", 'sk': 'METADATA'})
    print(f"\n(cleaned up test rule {data['id'][:8]})")
