import json, urllib.request

with open('scratch/auth_state.json') as f:
    auth = json.load(f)

# Find jwt token in cookies or localStorage
token = None
for cookie in auth.get('cookies', []):
    if cookie.get('name') in ['token', 'jwt', 'auth']:
        token = cookie.get('value')
for origin in auth.get('origins', []):
    for item in origin.get('localStorage', []):
        if 'token' in item.get('name', '').lower() or 'jwt' in item.get('name', '').lower() or 'auth' in item.get('name', '').lower():
            val = item.get('value')
            if val and len(val) > 20:
                token = val.strip('"')

print("Found token prefix:", token[:20] if token else "None")

headers = {
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0'
}

endpoints_to_try = [
    ('POST', 'https://weapharma.bricks-rep.com/api/v1/visits/list', {"pagination": {"offset": 0, "limit": 10}}),
    ('POST', 'https://weapharma.bricks-rep.com/api/v1/visits/search', {}),
    ('GET', 'https://weapharma.bricks-rep.com/api/v1/visits', None),
    ('GET', 'https://weapharma.bricks-rep.com/api/v1/visits/history', None),
    ('GET', 'https://weapharma.bricks-rep.com/api/v1/visits/all', None),
    ('POST', 'https://weapharma.bricks-rep.com/api/v1/visits/plans/list', {"pagination": {"limit": 10}, "filters": {}}),
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
                    if v:
                        print(f"      sample: {list(v[0].keys()) if isinstance(v[0], dict) else v[0]}")
    except Exception as e:
        print(f"FAILED {method} {url} -> {e}")
