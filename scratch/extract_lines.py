import json, re

with open(r'C:\Users\mahmo\.gemini\antigravity-ide\brain\d4036e02-fa34-4745-9ca6-a19a342c0124\.system_generated\logs\transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('step_index') == 37:
            content = data.get('content', '')
            lines = [l for l in content.split('\n') if 'settings' in l.lower() or 'إعدادات' in l or 'مستخدم' in l or 'صلاحيات' in l]
            with open('scratch/settings_lines.txt', 'w', encoding='utf-8') as out:
                for l in lines[:200]:
                    out.write(l + '\n')
            print(f'Wrote {len(lines)} lines')
            break
