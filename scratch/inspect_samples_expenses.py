import json

with open('scratch/visits_sample_full.json', encoding='utf-8') as f:
    v = json.load(f)

for i, visit in enumerate(v.get('visits', [])):
    print(f"Visit {i}: {visit.get('serial_num')}")
    print("  samples:", visit.get('samples'))
    print("  expenses:", visit.get('expenses'))
    print("  doubled:", visit.get('doubled'))
    print("  mode:", visit.get('mode'))
    print("  is_successful:", visit.get('is_successful'))
    print("  status:", visit.get('status'))
