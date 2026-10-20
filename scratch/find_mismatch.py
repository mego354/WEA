with open('scratch/modal_script_0.js', 'r', encoding='utf-8') as f:
    text = f.read()

in_single = False
in_double = False
in_backtick = False
brace_depth = 0

lines = text.splitlines()
for line_idx, line in enumerate(lines):
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '\\' and (in_single or in_double or in_backtick):
            i += 2
            continue
        if ch == "'" and not in_double and not in_backtick:
            in_single = not in_single
        elif ch == '"' and not in_single and not in_backtick:
            in_double = not in_double
        elif ch == '`' and not in_single and not in_double:
            in_backtick = not in_backtick
        elif not in_single and not in_double and not in_backtick:
            if ch == '{':
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
        i += 1
    if line_idx in range(220, 275) or line_idx >= len(lines) - 5:
        safe_line = line[:60].encode('ascii', 'replace').decode('ascii')
        print(f"Line {line_idx+1}: depth={brace_depth} | {safe_line}")

print("Final depth:", brace_depth)
