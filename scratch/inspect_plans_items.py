import json, sys

sys.stdout.reconfigure(encoding='utf-8')

with open('scratch/plans_sample_full.json', encoding='utf-8') as f:
    p = json.load(f)

for i, plan in enumerate(p.get('plans', [])):
    print(f"Plan {i}: date={plan.get('date')}, assignee={plan.get('assignee', {}).get('name')}")
    for pv in plan.get('plan_visits', []):
        print("   item:", json.dumps(pv, ensure_ascii=False))
