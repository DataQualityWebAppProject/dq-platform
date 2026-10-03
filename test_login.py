import urllib.request
import json

req = urllib.request.Request(
    "http://localhost/auth/login",
    data=json.dumps({"username": "admindatos", "password": "DqAdmin2026!"}).encode(),
    method="POST",
    headers={"Content-Type": "application/json"},
)
try:
    resp = urllib.request.urlopen(req, timeout=15)
    print(f"Status: {resp.status}")
    print(resp.read().decode())
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode())
