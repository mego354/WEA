import json, re

with open(r'C:\Users\mahmo\.gemini\antigravity-ide\brain\d4036e02-fa34-4745-9ca6-a19a342c0124\.system_generated\logs\transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('step_index') == 37:
            content = data.get('content', '')
            # find all occurrences of /settings/ with surrounding text or labels
            items = re.findall(r'(<[^>]*href=[^>]*settings[^>]*>.*?<[^>]*>)', content, re.DOTALL)
            print(f'Found {len(items)} HTML items')
            with open('scratch/settings_sidebar_dom.txt', 'w', encoding='utf-8') as out:
                for item in items[:100]:
                    out.write(item + '\n---\n')
            break
