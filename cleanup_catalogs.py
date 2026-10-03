"""Clean up empty/null catalogs from DynamoDB and verify table registrations."""
import boto3
from boto3.dynamodb.conditions import Key, Attr

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('dq-catalogs')

# Scan all items
response = table.scan()
items = response.get('Items', [])
print(f"Total items in dq-catalogs: {len(items)}")

catalogs = [i for i in items if i.get('sk') == 'METADATA']
tables = [i for i in items if i.get('sk', '').startswith('TABLE#')]

print(f"\nCatalogs (METADATA): {len(catalogs)}")
for cat in catalogs:
    name = cat.get('name', '<NULL>')
    owner = cat.get('owner', '<NULL>')
    pk = cat.get('pk', '')
    print(f"  {pk} | name={name} | owner={owner}")
    if not name or name == 'None' or name == '<NULL>':
        table.delete_item(Key={'pk': pk, 'sk': 'METADATA'})
        print(f"    -> DELETED (empty name)")

print(f"\nTables (TABLE#*): {len(tables)}")
for t in tables:
    pk = t.get('pk', '')
    sk = t.get('sk', '')
    fname = t.get('fileName', t.get('name', '<unknown>'))
    cols = len(t.get('columns', []))
    print(f"  {pk} | {sk} | file={fname} | columns={cols}")

print("\nDone.")
