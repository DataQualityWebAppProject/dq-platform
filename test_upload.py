import requests, boto3, json

cognito = boto3.client('cognito-idp', region_name='us-east-1')
auth = cognito.admin_initiate_auth(
    UserPoolId='us-east-1_8KvqRmGSN', ClientId='4q5odh7hskaevkpphb4p8jgl3j',
    AuthFlow='ADMIN_USER_PASSWORD_AUTH',
    AuthParameters={'USERNAME': 'admindatos', 'PASSWORD': 'DqAdmin2026!'}
)
token = auth['AuthenticationResult']['IdToken']
h = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
API = 'https://86iruyzin2.execute-api.us-east-1.amazonaws.com'

# Get existing catalog
r = requests.get(f'{API}/catalog', headers=h)
catalogs = r.json().get('items', [])
print(f'Catalogs: {len(catalogs)}')

if catalogs:
    cid = catalogs[0]['id']
    cname = catalogs[0]['name']
    print(f'Using catalog: {cid} ({cname})')
    
    # Try upload initiation
    r2 = requests.post(f'{API}/catalog/{cid}/upload', headers=h, json={
        'fileName': 'test_banking_data.csv',
        'fileSize': 1024,
        'fileType': 'csv'
    })
    print(f'Upload init status: {r2.status_code}')
    print(f'Response: {r2.text[:400]}')
else:
    print('No catalogs found - create one first')
