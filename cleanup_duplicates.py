"""Remove duplicate catalogs, keep only unique names."""
import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('dq-catalogs')

response = table.scan(FilterExpression=Attr('sk').eq('METADATA'))
items = response.get('Items', [])

# Group by name (case-insensitive)
seen_names = {}
to_delete = []

for item in items:
    name = (item.get('name') or '').strip().lower()
    pk = item.get('pk', '')
    
    if not name:
        to_delete.append(pk)
        continue
    
    if name in seen_names:
        # Keep the first one, delete duplicates
        to_delete.append(pk)
    else:
        seen_names[name] = pk

print(f"Keeping {len(seen_names)} unique catalogs:")
for name, pk in seen_names.items():
    print(f"  {name} -> {pk}")

print(f"\nDeleting {len(to_delete)} duplicates:")
for pk in to_delete:
    print(f"  Deleting {pk}")
    table.delete_item(Key={'pk': pk, 'sk': 'METADATA'})

print("\nDone.")
