"""A flash message is the colour it is trying to be.

akye.css styles `.flash.success` and `.flash.error` -- compound classes. Two
shells emitted `class="flash flash-success"` instead, which matches neither,
so every confirmation and every refusal in the console and the admin rendered
as plain text. Nothing broke; the page just stopped saying whether the thing
worked, which is the only job a flash has.

What this holds:
- No template emits the prefixed class the stylesheet does not define.
- The categories actually flashed are ones the stylesheet knows how to colour.
"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


css = read('static', 'akye.css')
styled = set(re.findall(r'\.flash\.([a-z]+)\s*\{', css))

print('\n1. The stylesheet colours success and error')
check({'success', 'error'} <= styled, f'akye.css defines: {sorted(styled)}')

print('\n2. No template uses a class the stylesheet does not define')
bad = []
for folder, _dirs, names in os.walk(os.path.join(ROOT, 'templates')):
    for name in names:
        if not name.endswith('.html'):
            continue
        path = os.path.join(folder, name)
        with open(path) as f:
            body = f.read()
        if re.search(r'class="flash flash-', body):
            bad.append(os.path.relpath(path, ROOT))
check(not bad, f'no template emits "flash flash-<category>"{": " + ", ".join(bad) if bad else ""}')

print('\n3. The shells pass the category through bare, so the CSS matches')
for shell in ('templates/console/_shell.html', 'templates/base_admin.html'):
    check('class="flash {{ category }}"' in read(*shell.split('/')),
          f'{shell} emits the bare category')

if failures:
    print(f'\n❌ {len(failures)} flash style check(s) failed')
    sys.exit(1)
print('\n✅ Flash messages carry a class the stylesheet colours.')
