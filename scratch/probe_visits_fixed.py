import json, urllib.request

with open('scratch/auth_state.json') as f:
    auth = json.load(f)

token = None
for origin in auth.get('origins', []):
    for item in origin.get('localStorage', []):
        if 'token' in item.get('name', '').lower() or 'jwt' in item.get('name', '').lower() or 'auth' in item.get('name', '').lower():
            val = item.get('value', '')
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict) and 'jwt' in parsed:
                    token = parsed['jwt']
                    break
            except:
                pass

print("Token:", token[:25] if token else "None")

headers = {
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0'
}

endpoints_to_try = [
    ('POST', 'https://weapharma.bricks-rep.com/api/v1/visits/plans/list', {"pagination": {"limit": 10}, "filters": {}}),
    ('GET', 'https://weapharma.bricks-rep.com/api/v1/visits/history?offset=0&limit=10', None),
    ('GET', 'https://weapharma.bricks-rep.com/api/v1/visits/all?offset=0&limit=10', None),
    ('POST', 'https://weapharma.bricks-rep.com/api/v1/visits/list', {"pagination": {"offset": 0, "limit": 10}}),
]

for method, url, body in endpoints_to_try:
    try:
        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as res:
            res_data = json.loads(res.read().decode('utf-8'))
            print(f"SUCCESS {method} {url} -> {res.status}")
            print("  Keys:", list(res_data.keys()))
            for k in res_data:
                v = res_data[k]
                if isinstance(v, list):
                    print(f"    {k} (len {len(v)})")
                    if v and isinstance(v[0], dict):
                        print(f"      sample keys: {list(v[0].keys())}")
    except Exception as e:
        print(f"FAILED {method} {url} -> {e}")
