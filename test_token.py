import boto3, json, base64
cognito = boto3.client('cognito-idp', region_name='us-east-1')
auth = cognito.admin_initiate_auth(
    UserPoolId='us-east-1_8KvqRmGSN',
    ClientId='4q5odh7hskaevkpphb4p8jgl3j',
    AuthFlow='ADMIN_USER_PASSWORD_AUTH',
    AuthParameters={'USERNAME': 'admindatos', 'PASSWORD': 'DqAdmin2026!'}
)
token = auth['AuthenticationResult']['IdToken']
# Decode payload (middle part)
payload = token.split('.')[1]
payload += '=' * (4 - len(payload) % 4)
claims = json.loads(base64.b64decode(payload))
print("JWT Claims:")
print(json.dumps(claims, indent=2))
print(f"\ncognito:groups = {claims.get('cognito:groups')}")
print(f"type = {type(claims.get('cognito:groups'))}")
