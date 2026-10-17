import json

with open('scratch/activities_inspection/direct_api_audit.json', encoding='utf-8') as f:
    d = json.load(f)

summary = {}
for k, v in d.items():
    summary[k] = v

with open('scratch/api_details_readable.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print("Saved api_details_readable.json successfully")
