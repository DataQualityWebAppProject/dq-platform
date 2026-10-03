import boto3
from boto3.dynamodb.conditions import Attr
ddb = boto3.resource('dynamodb', region_name='us-east-1')
t = ddb.Table('dq-rules')
resp = t.scan(FilterExpression=Attr('sk').eq('METADATA'))
items = resp.get('Items', [])
print(f"Total rules: {len(items)}")
for item in items:
    print(f"  {item.get('id','')[:8]} | {item.get('naturalLanguage','')} | col={item.get('columnId','')}")
