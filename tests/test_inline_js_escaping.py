"""A name typed into a public form cannot become script in the owner's admin.

The "Are you sure?" buttons wrote names straight into inline JavaScript:

    onsubmit="return confirm('Delete {{ a.name }}?')"

Autoescaping turns ' into &#39;, but in an attribute the browser decodes that
back to ' before the script runs. So an applicant called x'+(code)+' ran
`code` in the owner's session the moment they clicked Delete -- and a signup
email address carrying the same did it in the platform console. Values in
those places now go through the `js` filter (security.js_string).

This checks three things:
  * the filter itself: what it writes is the same string once JavaScript
    (here, JSON) reads it, and holds no character that can end a string, an
    attribute or a script;
  * every template: each {{ value }} inside an on*="..." handler is either
    |js inside a quoted string or |int / |float -- so a handler added later
    the old way fails here;
  * real pages: an applicant and a booking with a hostile name, rendered for
    their owner, carry it only as escaped text.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import html
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_inline_js_escaping')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

import security

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


HOSTILE = "x'+(document.title='PWNED')+'"

print('\n1. The filter')
for value in (HOSTILE, 'Bob\'s "Best" <b>&amp;</b>', 'ends with a backslash \\', 'line\nbreak sep',
              '${x} `tick`', 'é 😀', '</script><script>alert(1)</script>', ''):
    out = str(security.js_string(value))
    check(json.loads('"' + out + '"') == value, f'{value!r} reads back unchanged')
    check(not set(out) & set('\'"`<>&\\\n\r()[]{};=+$') - {'\\'} and
          all(out[i + 1] == 'u' for i, ch in enumerate(out) if ch == '\\'),
          f'{value!r} is written with nothing that can end a string, attribute or script')
check(str(security.js_string(None)) == '', 'None is an empty string')
check(str(security.js_string(42)) == '42', 'a number is its digits')

print('\n2. Every inline handler in every template')
ATTR = re.compile(r'''\son[a-z]+\s*=\s*(?:"([^"]*)"|'([^']*)')''', re.S)
PART = re.compile(r'(\{\{.*?\}\}|\{%.*?%\})', re.S)
offenders = []
handlers = 0
for path in sorted((ROOT / 'templates').rglob('*.html')):
    source = path.read_text()
    for m in ATTR.finditer(source):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        line = source.count('\n', 0, m.start()) + 1
        quote = None      # which JavaScript string we are inside, if any
        for part in PART.split(body):
            if part.startswith('{%'):
                continue
            if part.startswith('{{'):
                handlers += 1
                expr = part[2:-2].strip()
                if re.search(r'\|\s*(int|float)$', expr):
                    continue
                if expr.endswith('|js') and quote:
                    continue
                offenders.append(f'{path.relative_to(ROOT)}:{line}: {part}'
                                 + ('' if expr.endswith('|js') else ' (not |js)')
                                 + ('' if quote else ' (outside a quoted string)'))
                continue
            # The browser decodes the attribute before JavaScript reads it.
            text = html.unescape(part)
            i = 0
            while i < len(text):
                ch = text[i]
                if quote and ch == '\\':
                    i += 2
                    continue
                if quote is None and ch in '\'"`':
                    quote = ch
                elif ch == quote:
                    quote = None
                i += 1
check(handlers > 50, f'found the inline handlers that carry a value ({handlers})')
for o in offenders:
    print('     ', o)
check(not offenders, 'each value in a handler is |js inside a quoted string, or |int / |float')

print('\n3. Hostile names, rendered for their owner')
from datetime import date, timedelta
from app import create_app
from extensions import db
import provisioning
import tenancy

app = create_app()
SLUG = 'jsesc'
HOST = f'http://{SLUG}.akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Escaping Cleaning', quiet=True)
    db.session.remove()
fresh_postgres.set_company_plan(SLUG, 'scale')
owner = fresh_postgres.owner_client(app, SLUG, 'akye.test')

with app.app_context(), tenancy.use_tenant(SLUG):
    from models import Booking, ContractorApplication
    a = ContractorApplication(name=HOSTILE, email='hostile@example.com')
    b = Booking(name=HOSTILE, email='hostile-booking@example.com', phone='5555550100',
                service_type='standard', status='pending',
                preferred_date=(date.today() + timedelta(days=3)).isoformat())
    db.session.add_all([a, b])
    db.session.commit()
    app_id, booking_id = a.id, b.id
    db.session.remove()


def handler_scripts(page):
    """The JavaScript of each inline handler, as the browser hands it over."""
    return [html.unescape(m.group(1) if m.group(1) is not None else m.group(2))
            for m in ATTR.finditer(page)]


for url, what in (('/contractors/applications', 'the applications list'),
                  (f'/contractors/applications/{app_id}', "the applicant's page"),
                  ('/bookings/', 'the bookings list'),
                  (f'/bookings/{booking_id}', "the booking's page")):
    r = owner.get(url, base_url=HOST)
    page = r.get_data(as_text=True)
    scripts = handler_scripts(page)
    check(r.status_code == 200, f'{what} renders ({r.status_code})')
    check(any(str(security.js_string(HOSTILE)) in s for s in scripts),
          f'{what}: the name reaches its handlers, escaped')
    check(not any("'+(document.title=" in s for s in scripts),
          f'{what}: no handler carries it as code')

if failures:
    print(f'\n❌ {len(failures)} failed')
    sys.exit(1)
print('\n✅ all passed')
