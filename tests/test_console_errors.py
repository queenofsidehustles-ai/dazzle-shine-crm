"""The console's open errors: only real ones, and sortable from the console.

What kept three "errors" on Dazzle & Shine's row for over a week:
  * Nana's answer check counted a numbered-list marker ("3) Send interview
    links...") as a figure that had to come from the books, so every answer
    written as a list failed it -- and each one was logged as an error even
    when she corrected herself;
  * a refused cross-site form post, which is the guard working, was counted
    as an error by the console although the owner's own page leaves it out;
  * only the owner could mark anything sorted, from her own Errors page.
Plus the pricing engine raising on a half bathroom ("2.5") for any caller
that did not round it first.

Against a real disposable Postgres, like the rest of the console suite.
"""
import os
import secrets
import sys

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
os.environ.pop('CONSOLE_REQUIRE_2FA', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import agent
import assistant
import console_data
import control_plane
import provisioning
import tenancy
from models import ErrorLog
from pricing import calculate_job

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


print('\n1. A numbered list is not a list of figures')
src = ['You have 4 applicants waiting.']
check(agent._figures_ok('3) Send interview links from the Hiring page for promising candidates.', src),
      '"3) Send interview links..." passes')
check(agent._figures_ok('1. Call them today.\n2. Send the links.\n3. Book the best two.', src),
      'nor does a "1. 2. 3." list trip it')
check(agent._figures_ok('- Follow up with all 4 applicants.', src), 'a bullet is not a figure either')
check(not agent._figures_ok('3) You made $9,900 this month.', src),
      'but a made-up figure inside a list item is still caught')
check(not agent._figures_ok('5.5% of your jobs ran late.', src)
      and not agent._figures_ok('7 jobs are unassigned.', src),
      'and a sentence that starts with a real figure is still checked')

print('\n2. A caught-and-corrected answer is not logged as an error')
recorded = []
real_record = assistant._record
assistant._record = lambda detail: recorded.append(detail)
out = agent._finish('You made $9,900.', src, 'how am I doing?', None,
                    retry=lambda bad: 'You have 4 applicants waiting.')
check('4 applicants' in out['say'] and recorded == [],
      f'she corrected it, the owner got an answer, nothing was logged ({recorded})')
out = agent._finish('You made $9,900.', src, 'how am I doing?', None,
                    retry=lambda bad: 'You made $9,900.')
check(len(recorded) == 1 and 'not corrected' in recorded[0],
      'only an answer she could not fix is logged, once')
assistant._record = real_record

print('\n3. Half a bathroom prices instead of raising')
r = calculate_job('standard', 3, '2.5')
check(r['client_price'] == calculate_job('standard', 3, 2)['client_price'],
      '"2.5" bathrooms prices as 2, as the public calculator already did')
check(calculate_job('standard', '3.0', 2.0)['client_price'] > 0, 'and "3.0" bedrooms works too')
for bad in ('abc', 'inf', 'nan'):
    try:
        calculate_job('standard', 3, bad)
        raised = None
    except Exception as e:
        raised = type(e).__name__
    check(raised == 'ValueError', f'a room count of {bad!r} is a ValueError, as callers expect ({raised})')

print('\n4. The console counts real errors only, and can mark them sorted')
app = create_app()
TAG = secrets.token_hex(3)
SLUG = f'errs{TAG}'
MANAGER, HELPER = f'mgr-{TAG}@example.com', f'helper-{TAG}@example.com'
PW = 'a-real-console-password-1'
with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    provisioning.provision(SLUG, 'Errors Cleaning', quiet=True)
    control_plane.add_console_user(engine, MANAGER, 'Manager', PW, role='manager')
    control_plane.add_console_user(engine, HELPER, 'Helper', PW, role='helper')
    with tenancy.use_tenant(SLUG):
        ErrorLog.record('RuntimeError', 'Nana: something', path='/ask')
        ErrorLog.record('ValueError', "invalid literal for int() with base 10: '2.5'",
                        path='/api/calculate')
        for _ in range(2):        # one row, two attempts
            ErrorLog.record('blocked', 'Cross-site form submission refused (Origin: https://evil.example.com)',
                            path='/settings/business')
        db.session.remove()
    snap = console_data.snapshot(SLUG)
check(snap['open_errors'] == 2 and snap['blocked'] == 2,
      f'two real errors; the two refused attempts are counted apart ({snap["open_errors"]}, {snap["blocked"]})')
check(all(e['kind'] != 'blocked' for e in snap['errors']), 'and is not in the error list')

PRODUCT = {'Host': 'akyehq.test'}


def current():
    with app.app_context():
        return console_data.snapshot(SLUG)


h = app.test_client()
h.post('/console/login', data={'email': HELPER, 'password': PW}, headers=PRODUCT)
first = snap['errors'][0]
r = h.post(f'/console/companies/{SLUG}/errors/resolve', data={'error_id': first['id']},
           headers=PRODUCT)
check(current()['open_errors'] == 2, 'a helper cannot mark them sorted')

m = app.test_client()
m.post('/console/login', data={'email': MANAGER, 'password': PW}, headers=PRODUCT)
page = m.get(f'/console/companies/{SLUG}', headers=PRODUCT).get_data(as_text=True)
check('Mark sorted' in page and 'Mark all sorted' in page and 'not counted as errors' in page,
      'a manager sees the buttons, and the refused form explained')
m.post(f'/console/companies/{SLUG}/errors/resolve', data={'error_id': first['id']}, headers=PRODUCT)
snap = current()
check(snap['open_errors'] == 1 and first['id'] not in [e['id'] for e in snap['errors']],
      'one can be marked sorted')
m.post(f'/console/companies/{SLUG}/errors/resolve', headers=PRODUCT)
check(current()['open_errors'] == 0, 'or all of them at once')
with app.app_context():
    log = [r for r in control_plane.console_log_all(engine) if r.get('target') == SLUG]
check(any(r.get('action') == 'resolved errors' for r in log), 'and it is in the console history')

with app.app_context(), tenancy.use_tenant(SLUG):
    ErrorLog.record('RuntimeError', 'Nana: something', path='/ask')
    db.session.remove()
check(current()['open_errors'] == 1, 'one that happens again comes straight back')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Lists are not figures, half baths price, and the console can sort real errors.')
