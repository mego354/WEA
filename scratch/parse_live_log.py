import json, sys

sys.stdout.reconfigure(encoding='utf-8')

with open('scratch/activities_inspection/live_network_log.json', encoding='utf-8') as f:
    d = json.load(f)

for item in d:
    url = item.get('url', '')
    if any(k in url for k in ['visits', 'planned', 'agreements', 'calls']):
        print(f"{item.get('method')} {url} -> {item.get('status')}")
        if item.get('post_data'):
            print('   POST_DATA:', item['post_data'][:300])
        if item.get('response'):
            resp = item['response']
            if isinstance(resp, dict):
                for k in resp:
                    val = resp[k]
                    if isinstance(val, list):
                        print(f"      {k}: list length {len(val)}")
                        if val and isinstance(val[0], dict):
                            print(f"         sample keys: {list(val[0].keys())}")
                    else:
                        print(f"      {k}: {str(val)[:200]}")
            else:
                print('   RESPONSE type:', type(resp))
