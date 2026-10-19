import json, re

with open(r'C:\Users\mahmo\.gemini\antigravity-ide\brain\d4036e02-fa34-4745-9ca6-a19a342c0124\.system_generated\logs\transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('step_index') == 37:
            content = data.get('content', '')
            # Find the section between Step 20 and Step 38
            idx_start = content.find('### Step 20:')
            idx_end = content.find('### Step 38:')
            with open('scratch/sidebar_steps.txt', 'w', encoding='utf-8') as out:
                out.write(content[idx_start:idx_end])
            print('Written sidebar steps')
            break
