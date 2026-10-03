"""End-to-end test of the FastAPI server on EC2."""
import requests

BASE = "http://44.223.82.117"
s = requests.Session()

# Test 1: Login
print("=== Test 1: Login ===")
r = s.post(f"{BASE}/auth/login", json={"username": "admindatos", "password": "DqAdmin2026!"})
print(f"  Status: {r.status_code}")
print(f"  Body: {r.text[:100]}")
has_cookie = "dq_token" in s.cookies.get_dict()
print(f"  Cookie set: {has_cookie}")

# Test 2: Get user info
print("\n=== Test 2: /auth/me ===")
r = s.get(f"{BASE}/auth/me")
print(f"  Status: {r.status_code}")
print(f"  Body: {r.text[:200]}")

# Test 3: List catalogs via proxy
print("\n=== Test 3: GET /api/catalog ===")
r = s.get(f"{BASE}/api/catalog")
print(f"  Status: {r.status_code}")
print(f"  Body: {r.text[:200]}")

# Test 4: Interpret rule via proxy (uses Nova Lite)
print("\n=== Test 4: POST /api/rules/interpret (Nova Lite AI) ===")
r = s.post(f"{BASE}/api/rules/interpret", json={
    "naturalLanguage": "email must not be null and must contain @",
    "scope": "catalog",
    "catalogId": "test-1"
})
print(f"  Status: {r.status_code}")
print(f"  Body: {r.text[:400]}")

# Summary
print("\n=== SUMMARY ===")
tests = [
    ("Login", has_cookie),
    ("Auth/me", "authenticated" in s.get(f"{BASE}/auth/me").text),
    ("Catalog list", s.get(f"{BASE}/api/catalog").status_code == 200),
    ("Rule interpret (AI)", s.post(f"{BASE}/api/rules/interpret", json={"naturalLanguage":"test","scope":"catalog","catalogId":"x"}).status_code == 200),
]
for name, passed in tests:
    print(f"  {'PASS' if passed else 'FAIL'} - {name}")
