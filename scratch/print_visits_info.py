import json, sys

sys.stdout.reconfigure(encoding='utf-8')

with open('scratch/activities_inspection/endpoints_summary.json', encoding='utf-8') as f:
    d = json.load(f)

for k in ['GET https://weapharma.bricks-rep.com/api/v1/visits/settings', 'GET https://weapharma.bricks-rep.com/api/v1/visits/wf/states', 'POST https://weapharma.bricks-rep.com/api/v1/visits/templates/list', 'GET https://weapharma.bricks-rep.com/api/v1/visits/started']:
    if k in d:
        print('=== KEY:', k)
        print('status:', d[k].get('status'))
        sb = d[k].get('sample_body')
        print('sample_body:', json.dumps(sb, ensure_ascii=False, indent=2)[:1000])
