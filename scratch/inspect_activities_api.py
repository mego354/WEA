import json
import os
import sys
import urllib.request
import urllib.error

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Read JWT from auth_state.json
with open("scratch/auth_state.json", "r", encoding="utf-8") as f:
    state = json.load(f)

jwt_token = None
for origin in state.get("origins", []):
    for item in origin.get("localStorage", []):
        if item.get("name") == "CapacitorStorage.token":
            val = json.loads(item["value"])
            jwt_token = val.get("jwt")
            break

if not jwt_token:
    print("Could not find JWT in auth_state.json!")
    sys.exit(1)

print("Found JWT Token:", jwt_token[:25] + "...")

headers = {
    "Authorization": f"Bearer {jwt_token}",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

endpoints_to_test = [
    # Visits
    "/api/v1/visits?offset=0&limit=10",
    "/api/v1/visits/count",
    "/api/v1/visits/settings",
    "/api/v1/visits/wf/states",
    "/api/v1/visits/templates/list",
    "/api/v1/visits/expenses/types",
    "/api/v1/ui-preferences/visits-listing",
    "/api/v1/filters/view/visits-listing",
    # Planned Visits / Planning
    "/api/v1/visits/planning?offset=0&limit=10",
    "/api/v1/visits/planning/count",
    "/api/v1/planned-visits?offset=0&limit=10",
    "/api/v1/ui-preferences/planned-visits-listing",
    "/api/v1/filters/view/planned-visits-listing",
    # Agreements
    "/api/v1/agreements?offset=0&limit=10",
    "/api/v1/agreements/count",
    "/api/v1/agreements/types",
    "/api/v1/agreements/wf/states",
    "/api/v1/ui-preferences/agreements-listing",
    "/api/v1/filters/view/agreements-listing",
    # Calls
    "/api/v1/calls?offset=0&limit=10",
    "/api/v1/calls/count",
    "/api/v1/calls/templates/list",
    "/api/v1/ui-preferences/calls-listing",
    "/api/v1/filters/view/calls-listing",
    # Users / Reps for activities assignment
    "/api/v1/users?offset=0&limit=50",
    # Contacts list for activities
    "/api/v1/contacts?offset=0&limit=5",
]

api_results = {}

for ep in endpoints_to_test:
    url = f"https://weapharma.bricks-rep.com{ep}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            api_results[ep] = {
                "status": resp.status,
                "data": data
            }
            count_str = ""
            if isinstance(data, dict):
                if "count" in data: count_str = f" (count: {data['count']})"
                elif "results" in data: count_str = f" (results: {len(data['results'])})"
                elif "items" in data: count_str = f" (items: {len(data['items'])})"
            elif isinstance(data, list):
                count_str = f" (list len: {len(data)})"
            print(f"  ✓ GET {ep:<50} -> HTTP 200{count_str}")
    except urllib.error.HTTPError as e:
        print(f"  ✗ GET {ep:<50} -> HTTP {e.code}")
        api_results[ep] = {"status": e.code, "error": str(e)}
    except Exception as e:
        print(f"  ! GET {ep:<50} -> {e}")
        api_results[ep] = {"error": str(e)}

os.makedirs("scratch/activities_inspection", exist_ok=True)
with open("scratch/activities_inspection/direct_api_audit.json", "w", encoding="utf-8") as f:
    json.dump(api_results, f, ensure_ascii=False, indent=2)

print("\nSaved all API responses to scratch/activities_inspection/direct_api_audit.json")
