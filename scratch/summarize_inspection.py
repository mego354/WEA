import json
import sys

# Ensure UTF-8 output
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open('scratch/excel_inspection.json', encoding='utf-8') as f:
    data = json.load(f)

for fname, finfo in data.items():
    print('=' * 80)
    print(f"FILE: {fname} (Size: {finfo['size_bytes']:,} bytes)")
    for sname, sinfo in finfo['sheets'].items():
        print(f"  SHEET: {sname} | Rows: {sinfo['total_rows']:,}")
        print(f"  COLUMNS ({len(sinfo['columns'])}): {sinfo['columns']}")
        print("  SAMPLE ROW 1:")
        if sinfo['sample']:
            for col, val in zip(sinfo['columns'], sinfo['sample'][0]):
                print(f"    - {col}: {val}")
        print("-" * 50)
