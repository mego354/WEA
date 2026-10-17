import json

with open("scratch/activities_inspection/direct_api_audit.json", "r", encoding="utf-8") as f:
    data = json.load(f)

def show_obj(name, obj):
    print(f"\n==================== {name} ====================")
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:3000])

if "/api/v1/ui-preferences/visits-listing" in data:
    show_obj("Visits Listing UI Preferences", data["/api/v1/ui-preferences/visits-listing"]["data"])

if "/api/v1/ui-preferences/planned-visits-listing" in data:
    show_obj("Planned Visits Listing UI Preferences", data["/api/v1/ui-preferences/planned-visits-listing"]["data"])

if "/api/v1/ui-preferences/agreements-listing" in data:
    show_obj("Agreements Listing UI Preferences", data["/api/v1/ui-preferences/agreements-listing"]["data"])

if "/api/v1/agreements/types" in data:
    show_obj("Agreements Types", data["/api/v1/agreements/types"]["data"])

if "/api/v1/agreements/wf/states" in data:
    show_obj("Agreements Workflow States", data["/api/v1/agreements/wf/states"]["data"])

if "/api/v1/agreements?offset=0&limit=10" in data:
    show_obj("Agreements Sample Records", data["/api/v1/agreements?offset=0&limit=10"]["data"])
