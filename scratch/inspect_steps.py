import json

with open(r'C:\Users\mahmo\.gemini\antigravity-ide\brain\d4036e02-fa34-4745-9ca6-a19a342c0124\.system_generated\logs\transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        data = json.loads(line)
        print(f"Line {i}: step={data.get('step_index')}, type={data.get('type')}, source={data.get('source')}, content_len={len(str(data.get('content', '')))}")
