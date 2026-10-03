"""Remove pre-existing duplicate rules that existed before the uniqueness check was added."""
import boto3
from boto3.dynamodb.conditions import Attr

ddb = boto3.resource('dynamodb', region_name='us-east-1')
rules_table = ddb.Table('dq-rules')

resp = rules_table.scan(FilterExpression=Attr('sk').eq('METADATA'))
items = resp.get('Items', [])
print("Current rules:")
for r in items:
    print(f"  {r.get('id','')[:8]} | col={r.get('columnId','')} | {r.get('naturalLanguage','')}")

# Known duplicate: "not null allowed" (a12e5b40) and "CANT BE NULL" (1716039d) on TDOC_DOCU
# Keep "CANT BE NULL" since it scored correctly (100%, consistent with no nulls in sample data)
DUPLICATE_ID_TO_REMOVE = "a12e5b40-4431-41b6-97bc-19e9ef97fe57"

for r in items:
    if r.get('id') == DUPLICATE_ID_TO_REMOVE:
        rules_table.delete_item(Key={'pk': f"RULE#{r['id']}", 'sk': 'METADATA'})
        print(f"\nDeleted duplicate: {r['id'][:8]} | {r.get('naturalLanguage','')}")
