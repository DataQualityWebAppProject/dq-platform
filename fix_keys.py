"""Fix PK/SK → pk/sk in all handler files."""
import os

root = r"c:\Users\ELVIA\Desktop\202601\TP1\APPWEB\services"
count = 0

for dirpath, dirnames, filenames in os.walk(root):
    for fname in filenames:
        if not fname.endswith(".py"):
            continue
        filepath = os.path.join(dirpath, fname)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Replace "PK" with "pk" and "SK" with "sk" (only as dict keys)
        new_content = content.replace('"PK"', '"pk"').replace('"SK"', '"sk"')
        
        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            count += 1
            print(f"  Fixed: {filepath}")

print(f"\nTotal files fixed: {count}")
