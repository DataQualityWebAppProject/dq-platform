import boto3
from boto3.dynamodb.conditions import Attr

ddb = boto3.resource('dynamodb', region_name='us-east-1')
rules_table = ddb.Table('dq-rules')
catalogs_table = ddb.Table('dq-catalogs')

# List all rules
resp = rules_table.scan(FilterExpression=Attr('sk').eq('METADATA'))
items = resp.get('Items', [])
print(f"Total rules: {len(items)}")

# Keep only the 3 original user rules (identified by natural language text)
KEEP_TEXTS = {" not null allowed", "cant cointain a number grater than 2000", "CANT BE NULL"}

deleted = 0
for item in items:
    nl = item.get('naturalLanguage', '')
    rule_id = item.get('id', '')
    if nl not in KEEP_TEXTS:
        rules_table.delete_item(Key={'pk': f"RULE#{rule_id}", 'sk': 'METADATA'})
        print(f"  Deleted: {rule_id[:8]} | {nl}")
        deleted += 1

print(f"\nDeleted {deleted} test rules, kept {len(items) - deleted}")

# Also clean up test catalogs (name = "E2E Test Catalog")
cat_resp = catalogs_table.scan(FilterExpression=Attr('sk').eq('METADATA'))
cat_items = cat_resp.get('Items', [])
cat_deleted = 0
for item in cat_items:
    name = item.get('name', '')
    cat_id = item.get('id', '')
    if name == "E2E Test Catalog":
        catalogs_table.delete_item(Key={'pk': f"CATALOG#{cat_id}", 'sk': 'METADATA'})
        print(f"  Deleted catalog: {cat_id[:8]} | {name}")
        cat_deleted += 1

print(f"Deleted {cat_deleted} test catalogs")
