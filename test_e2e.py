"""
End-to-end test for DQ Platform — runs against FastAPI on localhost.
Tests: Login, Dashboard, Catalog, Upload, Rules, Validation, Cleaning, Reports.
"""
import urllib.request
import json
import time
import sys

BASE = "http://localhost"
COOKIE = "dq_token=test"  # bypass auth for API-level tests

def api(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Content-Type": "application/json",
        "Cookie": COOKIE,
    })
    try:
        resp = urllib.request.urlopen(req, timeout=45)
        return resp.status, json.loads(resp.read().decode())
    except Exception as e:
        code = getattr(e, 'code', 0)
        body_text = ""
        if hasattr(e, 'read'):
            body_text = e.read().decode()[:300]
        return code, {"error": str(e), "body": body_text}

results = []

def test(name, passed, detail=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    results.append((name, passed))
    print(f"{status} | {name}" + (f" — {detail}" if detail else ""))

# ========================================================
# 1. DASHBOARD — GET /api/catalog and /api/rules for counts
# ========================================================
print("\n" + "="*60)
print("1. DASHBOARD")
print("="*60)

code, data = api("GET", "/api/catalog?limit=50")
test("Dashboard: GET /api/catalog", code == 200 and "items" in data, f"status={code}, catalogs={len(data.get('items',[]))}")

code, data = api("GET", "/api/rules?limit=50")
test("Dashboard: GET /api/rules", code == 200 and "items" in data, f"status={code}, rules={len(data.get('items',[]))}")

# ========================================================
# 2. CATALOG LIST
# ========================================================
print("\n" + "="*60)
print("2. CATALOG LIST")
print("="*60)

code, data = api("GET", "/api/catalog?limit=50")
catalogs = data.get("items", [])
test("Catalog: List catalogs", code == 200 and len(catalogs) > 0, f"{len(catalogs)} catalogs found")

# Use first catalog with a name
catalog_id = ""
catalog_name = ""
for c in catalogs:
    if c.get("name"):
        catalog_id = c["id"]
        catalog_name = c["name"]
        break

test("Catalog: Has valid catalog", bool(catalog_id), f"Using: {catalog_name} ({catalog_id[:8]}...)")

# ========================================================
# 3. CATALOG DETAIL (get one + tables)
# ========================================================
print("\n" + "="*60)
print("3. CATALOG DETAIL")
print("="*60)

code, data = api("GET", f"/api/catalog/{catalog_id}")
test("CatalogDetail: GET /api/catalog/{id}", code == 200 and data.get("name"), f"name={data.get('name')}")

code, data = api("GET", f"/api/catalog/{catalog_id}/tables")
tables = data.get("items", [])
test("CatalogDetail: GET tables", code == 200, f"{len(tables)} tables found")

table_id = ""
table_name = ""
if tables:
    table_id = tables[0].get("id", "")
    table_name = tables[0].get("name", "")
    columns = tables[0].get("columns", [])
    test("CatalogDetail: Table has columns", len(columns) > 0, f"table={table_name}, cols={len(columns)}")
else:
    test("CatalogDetail: Table has columns", False, "No tables in catalog")

# ========================================================
# 4. UPLOAD (create catalog + upload CSV)
# ========================================================
print("\n" + "="*60)
print("4. UPLOAD (simulated via API)")
print("="*60)

# Create a test catalog (prefixed so it's identifiable and auto-cleaned at the end)
code, data = api("POST", "/api/catalog", {"name": "_E2E_TEST_DELETE_ME", "description": "Auto test - safe to delete", "owner": "test"})
test("Upload: Create catalog", code == 200 and data.get("id"), f"id={data.get('id','')[:8]}")
test_catalog_id = data.get("id", "")

# We can't do multipart file upload via urllib easily, but we can verify the endpoint exists
# by confirming a 422 (missing file) instead of 404
try:
    req = urllib.request.Request(f"{BASE}/api/upload", data=b"", method="POST", headers={"Cookie": COOKIE})
    resp = urllib.request.urlopen(req, timeout=10)
    upload_code = resp.status
except Exception as e:
    upload_code = getattr(e, 'code', 0)

test("Upload: POST /api/upload endpoint exists", upload_code in [400, 422, 415], f"status={upload_code} (expected 4xx for missing file)")

# ========================================================
# 5. RULES — Interpret + Create + Generate Code
# ========================================================
print("\n" + "="*60)
print("5. RULES (NL → Interpret → Save → Generate Code)")
print("="*60)

# Interpret
code, data = api("POST", "/api/rules/interpret", {
    "naturalLanguage": "ABONO must be greater than zero",
    "scope": "column",
})
test("Rules: Interpret NL", code == 200 and data.get("structuredJson"), f"type={data.get('structuredJson',{}).get('type','')}")

# Create rule (scoped to the throwaway test catalog, NOT the user's real catalog)
code, data = api("POST", "/api/rules", {
    "naturalLanguage": "_E2E_TEST_DELETE_ME rule: ABONO must be greater than zero",
    "scope": "column",
    "catalogId": test_catalog_id,
    "tableId": "dummy",
    "columnId": "ABONO",
    "templateCategory": "range",
    "status": "active",
})
rule_id = data.get("id", "") or data.get("ruleId", "")
test("Rules: Create rule", code == 200 and bool(rule_id), f"ruleId={rule_id[:8] if rule_id else 'NONE'}")

# Generate code for rule
if rule_id:
    code, data = api("POST", f"/api/rules/{rule_id}/generate-code")
    has_code = bool(data.get("code") or data.get("script"))
    test("Rules: Generate Python code", code == 200 and has_code, f"code_length={len(data.get('code','') or data.get('script',''))}")
else:
    test("Rules: Generate Python code", False, "No rule ID")

# ========================================================
# 6. VALIDATION — Run against table
# ========================================================
print("\n" + "="*60)
print("6. VALIDATION (Run rules against table)")
print("="*60)

if catalog_id and table_id:
    code, data = api("POST", "/api/validations", {
        "catalogId": catalog_id,
        "tableId": table_id,
    })
    test("Validation: Run validation", code == 200 and data.get("success"), 
         f"score={data.get('overallScore')}%, rules={data.get('totalRules')}, rows={data.get('totalRows')}")
    
    rule_results = data.get("results", [])
    if rule_results:
        r = rule_results[0]
        test("Validation: Per-rule result", r.get("totalRows", 0) > 0, 
             f"rule='{r.get('ruleName','')[:30]}', score={r.get('score')}%")
    else:
        test("Validation: Per-rule result", False, "No rule results returned")
else:
    test("Validation: Run validation", False, "Missing catalog/table ID")

# ========================================================
# 7. CLEANING — Generate script + Execute
# ========================================================
print("\n" + "="*60)
print("7. CLEANING (Generate + Execute)")
print("="*60)

if catalog_id and table_id:
    # Generate cleaning script
    code, data = api("POST", "/api/cleaning/generate", {
        "catalogId": catalog_id,
        "tableId": table_id,
        "issues": "remove duplicate rows and trim string columns",
    })
    script = data.get("script", "")
    test("Cleaning: Generate script", code == 200 and len(script) > 20, f"script_length={len(script)}")

    # Execute the script
    if script:
        code, data = api("POST", "/api/cleaning/execute", {
            "catalogId": catalog_id,
            "tableId": table_id,
            "script": script,
        })
        test("Cleaning: Execute script", code == 200 and data.get("success"),
             f"original={data.get('originalRows')}, cleaned={data.get('cleanedRows')}, removed={data.get('removedRows')}")
    else:
        test("Cleaning: Execute script", False, "No script generated")
else:
    test("Cleaning: Generate script", False, "Missing catalog/table ID")
    test("Cleaning: Execute script", False, "Missing catalog/table ID")

# ========================================================
# 8. REPORTS — Generate report
# ========================================================
print("\n" + "="*60)
print("8. REPORTS (Generate AI report)")
print("="*60)

code, data = api("POST", "/api/reports/generate", {
    "catalogId": catalog_id,
})
report = data.get("report", "")
test("Reports: Generate report", code == 200 and len(report) > 50,
     f"report_length={len(report)}, catalog={data.get('catalogName')}")

# ========================================================
# CLEANUP - remove test artifacts so they don't pollute real data
# ========================================================
print("\n" + "="*60)
print("CLEANUP")
print("="*60)

try:
    import boto3
    from boto3.dynamodb.conditions import Attr
    ddb = boto3.resource('dynamodb', region_name='us-east-1')

    if rule_id:
        ddb.Table('dq-rules').delete_item(Key={'pk': f"RULE#{rule_id}", 'sk': 'METADATA'})
        print(f"  Deleted test rule: {rule_id[:8]}")

    if test_catalog_id:
        ddb.Table('dq-catalogs').delete_item(Key={'pk': f"CATALOG#{test_catalog_id}", 'sk': 'METADATA'})
        print(f"  Deleted test catalog: {test_catalog_id[:8]}")
except Exception as e:
    print(f"  Cleanup warning: {e}")

# ========================================================
# SUMMARY
# ========================================================
print("\n" + "="*60)
print("SUMMARY")
print("="*60)

passed = sum(1 for _, p in results if p)
total = len(results)
print(f"\n{passed}/{total} tests passed")

if passed == total:
    print("\n🎉 ALL TESTS PASSED — Platform is fully operational!")
else:
    failed = [(name, p) for name, p in results if not p]
    print(f"\n⚠️  {len(failed)} test(s) failed:")
    for name, _ in failed:
        print(f"   - {name}")

sys.exit(0 if passed == total else 1)
