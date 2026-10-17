import json, sys

sys.stdout.reconfigure(encoding='utf-8')

with open('scratch/activities_inspection/live_network_log.json', encoding='utf-8') as f:
    d = json.load(f)

for item in d:
    url = item.get('url', '')
    if 'visits/templates/list' in url and item.get('response'):
        templates = item['response'].get('templates', [])
        print(f"Total templates: {len(templates)}")
        for t in templates:
            print("-----------------------------------------")
            print("ID:", t.get('id'))
            print("Name:", t.get('name'))
            print("Display Name:", t.get('display_name'))
            print("Restrict contacts:", t.get('restrict_contacts'))
            q = t.get('questionnaire', {})
            print("Questionnaire:", q.get('display_name'))
            questions = q.get('questions', [])
            print(f"Questions ({len(questions)}):")
            for qn in questions:
                print(f"  - Order {qn.get('order')}: {qn.get('title')} (type: {qn.get('type')})")
