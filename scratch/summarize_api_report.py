import json

with open('scratch/api_details_readable.json', encoding='utf-8') as f:
    d = json.load(f)

lines = []
for k, v in d.items():
    lines.append(f"==================================================")
    lines.append(f"ENDPOINT: {k}")
    if isinstance(v, dict):
        lines.append(f"Keys: {list(v.keys())}")
        if 'status' in v:
            lines.append(f"Status: {v.get('status')}")
        if 'error' in v:
            lines.append(f"Error: {v.get('error')}")
        if 'data' in v:
            lines.append(f"Data type: {type(v['data']).__name__}")
            lines.append(f"Data content: {json.dumps(v['data'], ensure_ascii=False, indent=2)[:500]}")
        if 'results' in v:
            lines.append(f"Results len: {len(v['results'])}")
            if v['results']:
                lines.append(f"First result keys: {list(v['results'][0].keys()) if isinstance(v['results'][0], dict) else type(v['results'][0])}")
                lines.append(f"First result: {json.dumps(v['results'][0], ensure_ascii=False, indent=2)[:500]}")
    elif isinstance(v, list):
        lines.append(f"List len: {len(v)}")
        if v and isinstance(v[0], dict):
            lines.append(f"First item keys: {list(v[0].keys())}")
            lines.append(f"First item: {json.dumps(v[0], ensure_ascii=False, indent=2)[:500]}")

with open('scratch/api_summary_report.txt', 'w', encoding='utf-8') as out:
    out.write('\n'.join(lines))

print("Wrote scratch/api_summary_report.txt")
