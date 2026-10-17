import json, sys, urllib.request

sys.stdout.reconfigure(encoding='utf-8')

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

headers = {
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0'
}

# 1. Fetch visits list with full preloads
body_visits = {
    "pagination": {"offset": 0, "limit": 5},
    "preloads": {
        "contact": True,
        "template": True,
        "owner": True,
        "status_state": True,
        "approval_status_state": True,
        "samples": True,
        "expenses": True
    }
}
req = urllib.request.Request('https://weapharma.bricks-rep.com/api/v1/visits/list', data=json.dumps(body_visits).encode('utf-8'), headers=headers, method='POST')
try:
    with urllib.request.urlopen(req) as res:
        visits_data = json.loads(res.read().decode('utf-8'))
        with open('scratch/visits_sample_full.json', 'w', encoding='utf-8') as f:
            json.dump(visits_data, f, ensure_ascii=False, indent=2)
        print("Saved scratch/visits_sample_full.json (count:", len(visits_data.get('visits', [])), ")")
except Exception as e:
    print("Visits preload failed:", e)

# 2. Fetch plans list with full preloads
body_plans = {
    "pagination": {"limit": 5},
    "preloads": {
        "status_state": True,
        "plan_visits": True,
        "assignee": True
    }
}
req2 = urllib.request.Request('https://weapharma.bricks-rep.com/api/v1/visits/plans/list', data=json.dumps(body_plans).encode('utf-8'), headers=headers, method='POST')
try:
    with urllib.request.urlopen(req2) as res:
        plans_data = json.loads(res.read().decode('utf-8'))
        with open('scratch/plans_sample_full.json', 'w', encoding='utf-8') as f:
            json.dump(plans_data, f, ensure_ascii=False, indent=2)
        print("Saved scratch/plans_sample_full.json (count:", len(plans_data.get('plans', [])), ")")
except Exception as e:
    print("Plans preload failed:", e)
