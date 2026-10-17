import json

with open("scratch/activities_inspection/direct_api_audit.json", "r", encoding="utf-8") as f:
    data = json.load(f)

agreements_data = data.get("/api/v1/agreements?offset=0&limit=10", {}).get("data", {})
with open("scratch/activities_inspection/agreements_sample.json", "w", encoding="utf-8") as f:
    json.dump(agreements_data, f, ensure_ascii=False, indent=2)

print("Dumped agreements sample to scratch/activities_inspection/agreements_sample.json")
if isinstance(agreements_data, dict):
    print("Keys in agreements data:", list(agreements_data.keys()))
    if "results" in agreements_data and agreements_data["results"]:
        print("First agreement keys:", list(agreements_data["results"][0].keys()))
elif isinstance(agreements_data, list) and agreements_data:
    print("First agreement keys:", list(agreements_data[0].keys()))
