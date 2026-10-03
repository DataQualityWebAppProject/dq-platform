"""Test API Gateway end-to-end with real Cognito token."""
import boto3
import json
import requests

# Get token
cognito = boto3.client('cognito-idp', region_name='us-east-1')
auth = cognito.admin_initiate_auth(
    UserPoolId='us-east-1_8KvqRmGSN',
    ClientId='4q5odh7hskaevkpphb4p8jgl3j',
    AuthFlow='ADMIN_USER_PASSWORD_AUTH',
    AuthParameters={'USERNAME': 'admindatos', 'PASSWORD': 'DqAdmin2026!'}
)
token = auth['AuthenticationResult']['IdToken']
print(f"Token obtained: {token[:50]}...")

API = "https://86iruyzin2.execute-api.us-east-1.amazonaws.com"
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Test 1: List catalogs
print("\n--- Test 1: GET /catalog ---")
r = requests.get(f"{API}/catalog", headers=headers)
print(f"Status: {r.status_code}")
print(f"Body: {r.text[:200]}")

# Test 2: Create catalog
print("\n--- Test 2: POST /catalog ---")
r = requests.post(f"{API}/catalog", headers=headers, json={
    "name": "Test Banking Data",
    "description": "Customer transaction data for quality testing",
    "owner": "admindatos"
})
print(f"Status: {r.status_code}")
print(f"Body: {r.text[:300]}")

# Test 3: Interpret rule via NL
print("\n--- Test 3: POST /rules/interpret ---")
r = requests.post(f"{API}/rules/interpret", headers=headers, json={
    "naturalLanguage": "The balance field cannot have null values for deposit products",
    "scope": "catalog",
    "catalogId": "test-catalog-1"
})
print(f"Status: {r.status_code}")
print(f"Body: {r.text[:500]}")

# Test 4: List rules
print("\n--- Test 4: GET /rules ---")
r = requests.get(f"{API}/rules", headers=headers)
print(f"Status: {r.status_code}")
print(f"Body: {r.text[:200]}")
