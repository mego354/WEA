import re, subprocess

with open('templates/components/customer_selection_modal.html', 'r', encoding='utf-8') as f:
    content = f.read()

scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
for i, s in enumerate(scripts):
    js_file = f'scratch/modal_script_{i}.js'
    with open(js_file, 'w', encoding='utf-8') as out:
        out.write(s)
    print(f'Script {i} written, length {len(s)}')
    try:
        res = subprocess.run(['node', '-c', js_file], capture_output=True, text=True)
        print('Node check return code:', res.returncode)
        if res.stdout:
            print('STDOUT:', res.stdout)
        if res.stderr:
            print('STDERR:', res.stderr)
    except Exception as e:
        print('Error running node:', e)
