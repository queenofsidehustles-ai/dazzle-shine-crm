"""Cards a person can drag into their own order: the markup the script needs.

The behaviour itself (drag between columns, arrow keys, remembered after a
reload, an order saved by the old client-page code still honoured) was
checked in a real browser. What can silently break it later is the markup:
a card that loses its key, two cards sharing one, or a page that stops
loading the script. A duplicated key would make a saved order move the wrong
card, so that is the check that matters most.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def read(path):
    return open(os.path.join(ROOT, path)).read()


print('\n1. Every admin page loads the script, once')
base = read('templates/base_admin.html')
check(base.count("filename='card-reorder.js'") == 1, 'base_admin loads static/card-reorder.js')
check(os.path.exists(os.path.join(ROOT, 'static', 'card-reorder.js')), 'and the file exists')

for page, key, cols in (('templates/admin/booking_detail.html', 'bookingDetailCardOrder',
                         ['left', 'right']),
                        ('templates/admin/client_detail.html', 'clientDetailCardOrder',
                         ['main'])):
    print(f'\n2. {page}')
    src = read(page)
    check(f'data-reorder="{key}"' in src, f'is a reorder area saved under {key}')
    for col in cols:
        check(f'data-reorder-col="{col}"' in src, f'with a "{col}" column')
    keys = re.findall(r'data-card-key="([^"]+)"', src)
    check(len(keys) >= len(cols) and len(keys) == len(set(keys)),
          f'{len(keys)} cards, every key different ({keys})')

client = read('templates/admin/client_detail.html')
check('<script>\n// Drag-to-reorder' not in client,
      'the client page no longer carries its own copy of the script')

js = read('static/card-reorder.js')
check('Array.isArray(saved)' in js,
      'an order saved by the old single-list format is still read')
check("'ArrowUp'" in js and "'ArrowLeft'" in js, 'cards can be moved with the keyboard')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Cards can be moved, and every page that allows it is marked up to.')
