import json, re

with open(r'C:\Users\mahmo\.gemini\antigravity-ide\brain\d4036e02-fa34-4745-9ca6-a19a342c0124\.system_generated\logs\transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('step_index') == 37:
            content = data.get('content', '')
            matches = set(re.findall(r'/settings/[a-zA-Z0-9_\-\/]+', content))
            with open('scratch/all_settings_urls.txt', 'w', encoding='utf-8') as out:
                for m in sorted(matches):
                    out.write(m + '\n')
            print('Extracted URLs:', len(matches))
            break
