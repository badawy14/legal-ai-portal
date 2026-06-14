content = open('static/index.html', 'r', encoding='utf-8').read()
lines = content.split('\n')
print('Total lines:', len(lines))
for i, line in enumerate(lines):
    if 'id="tab-' in line:
        print(f"  Line {i+1}: {line.strip()}")
