import json

with open("scratch/activities_inspection/apis_collected.json", "r", encoding="utf-8") as f:
    apis = json.load(f)

endpoints = {}
for item in apis:
    url = item['url']
    method = item['method']
    status = item['status']
    key = f"{method} {url.split('?')[0]}"
    endpoints[key] = {
        "url": url,
        "status": status,
        "sample_body": item['body'] if isinstance(item['body'], (dict, list)) else str(item['body'])[:200]
    }

print("Collected Endpoints:")
for ep in sorted(endpoints.keys()):
    print(" -", ep)

with open("scratch/activities_inspection/endpoints_summary.json", "w", encoding="utf-8") as f:
    json.dump(endpoints, f, ensure_ascii=False, indent=2)
