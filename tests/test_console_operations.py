"""The console as an operator's desk: companies, health, and the few actions
that are safe to take from a browser.

Against a real disposable Postgres, with two real provisioned companies,
because the interesting failures are all at the schema boundary: reading one
company's errors and automations must never show another's, and the ids in
every company's tables start at 1.
"""
import os
import secrets
import sys
from datetime import datetime, timedelta

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_email = lambda to, *a, **k: (SENT.append(to) or (True, 'stub'))
notifications.send_sms = lambda *a, **k: (True, 'stub')

from sqlalchemy import text

from app import create_app
import automations
from extensions import db
import console_data
import control_plane
import provisioning
import tenancy
from models import CronRun, ErrorLog

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


print('\n1. The pure parts')
now = datetime(2026, 9, 24, 12)
check(console_data.extended_trial_end({'trial_ends_at': now + timedelta(days=3)}, 7, now)
      == now + timedelta(days=10), 'a running trial is extended from its end')
check(console_data.extended_trial_end({'trial_ends_at': now - timedelta(days=5)}, 7, now)
      == now + timedelta(days=7), 'a trial that already ran out is extended from today')
check(console_data.extended_trial_end({}, 14, now) == now + timedelta(days=14),
      'no end date at all counts from today')
leads = [{'id': 3, 'email': 'A@x.test '}, {'id': 2, 'email': 'b@x.test'},
         {'id': 1, 'email': 'a@x.test'}, {'id': 9, 'email': ''}]
d = console_data.dedupe_leads(leads)
check([(l['id'], l['times']) for l in d] == [(3, 2), (2, 1), (9, 1)],
      f'duplicate emails fold into the newest, counted ({[(l["id"], l["times"]) for l in d]})')

app = create_app()
TAG = secrets.token_hex(3)
A, B, C = f'e2eopsa{TAG}', f'e2eopsb{TAG}', f'e2eopsc{TAG}'
HELPER, MANAGER = f'helper-{TAG}@example.com', f'manager-{TAG}@example.com'
PASSWORD = 'a-real-console-password-1'
LEAD = f'lead-{TAG}@example.com'


def get(c, path, **kw):
    r = c.get(path, **kw)
    db.session.remove()
    return r


def post(c, path, data=None, **kw):
    r = c.post(path, data=data or {}, **kw)
    db.session.remove()
    return r


def signed_in(email):
    c = app.test_client()
    r = post(c, '/console/login', {'email': email, 'password': PASSWORD})
    assert r.status_code == 302, f'console login failed for {email}'
    return c


with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()
    provisioning.provision(A, f'Ops Alpha {TAG}', f'a-{TAG}@example.com', quiet=True)
    provisioning.provision(B, f'Ops Bravo {TAG}', f'b-{TAG}@example.com', quiet=True)
    control_plane.create(engine, C, f'Ops Charlie {TAG}', f'c-{TAG}@example.com')
    with engine.begin() as conn:
        # Charlie signed up 8 days ago and never started: the day-7 email is due.
        conn.execute(text('UPDATE public.organizations SET created_at = :t, '
                          "status = 'closed', closed_at = :t WHERE slug = :s"),
                     {'t': datetime.utcnow() - timedelta(days=8), 's': C})
    db.session.remove()

    # Each company's first error and first cron row both get id 1. Different
    # contents, so a cross-company mix-up cannot pass by accident.
    with tenancy.use_tenant(A):
        db.session.add(ErrorLog(fingerprint='fa', kind='AlphaError', message='alpha broke',
                                path='/alpha', count=3))
        # Every other job ran fine, as the scheduler makes them in production.
        for key, *_ in automations.JOBS:
            if key != 'reminders':
                db.session.add(CronRun(job=key, ok=True))
        db.session.add(CronRun(job='reminders', ok=False, detail='HTTP 403 from alpha'))
        db.session.commit()
    db.session.remove()
    with tenancy.use_tenant(B):
        for i in range(2):
            db.session.add(ErrorLog(fingerprint=f'fb{i}', kind='BravoError',
                                    message=f'bravo broke {i}', path='/bravo'))
        for key, *_ in automations.JOBS:
            db.session.add(CronRun(job=key, ok=True))
        db.session.commit()
    db.session.remove()

    control_plane.add_console_user(engine, HELPER, 'Helper', PASSWORD, role='helper')
    control_plane.add_console_user(engine, MANAGER, 'Manager', PASSWORD, role='manager')
    for _ in range(2):
        control_plane.add_lead(engine, name='=HYPERLINK("http://evil")', company='Lead Co',
                               email=LEAD, source='direct')
    db.session.remove()

    print('\n2. Signed out, none of it is reachable')
    anon = app.test_client()
    for path in (f'/console/companies/{A}', '/console/health', '/console/leads.csv'):
        r = get(anon, path, follow_redirects=False)
        check(r.status_code == 302 and 'login' in (r.headers.get('Location') or ''),
              f'{path} sends you to sign in')

    helper = signed_in(HELPER)
    manager = signed_in(MANAGER)

    print('\n3. The list says which company needs a look, per company')
    body = get(helper, '/console/companies').data.decode()
    row_a = body.split(f'Ops Alpha {TAG}')[1].split('</tr>')[0]
    row_b = body.split(f'Ops Bravo {TAG}')[1].split('</tr>')[0]
    check('1 error' in row_a and '1 automation' in row_a,
          f"Alpha: its one error and its failing reminders ({row_a[-160:]!r})")
    check('2 errors' in row_b and 'automation' not in row_b,
          'Bravo: its own two errors, and none of Alpha\'s automation trouble')
    check('>>Health</a>' not in body and '>Health</a>' in body, 'Health is in the navigation')
    check('asked 2×' in body, 'a lead who asked twice is one row, counted')

    print('\n4. The company page reads that company and nobody else')
    body = get(helper, f'/console/companies/{A}').data.decode()
    check('AlphaError' in body and 'BravoError' not in body,
          "Alpha's page shows Alpha's error, not Bravo's with the same id")
    check('HTTP 403 from alpha' in body, "and why its reminders are failing")
    body_b = get(helper, f'/console/companies/{B}').data.decode()
    check('BravoError' in body_b and 'AlphaError' not in body_b, "and Bravo's page the reverse")
    check(get(helper, '/console/companies/nobody-here', follow_redirects=False).status_code == 302,
          'an unknown company sends you back to the list')
    body_c = get(helper, f'/console/companies/{C}').data.decode()
    check('not read from here' in body_c, "a closed company's data is not read")

    print('\n5. A helper can look but not change anything')
    check('Only a manager or the owner can change a company' in body, 'no buttons for a helper')
    before = control_plane.find(engine, A)
    post(helper, f'/console/companies/{A}/trial', {'days': '7'})
    post(helper, f'/console/companies/{A}/suspend', {'reason': 'test'})
    after = control_plane.find(engine, A)
    check(after['trial_ends_at'] == before['trial_ends_at'] and after['status'] == 'active',
          'posting straight at the routes changes nothing')

    print('\n6. A manager can extend a trial, and it is recorded')
    r = post(manager, f'/console/companies/{A}/trial', {'days': '14'})
    after = control_plane.find(engine, A)
    expect = max(before['trial_ends_at'], datetime.utcnow()) + timedelta(days=14)
    check(abs((after['trial_ends_at'] - expect).total_seconds()) < 60,
          f"trial moved 14 days ({before['trial_ends_at']:%d %b} → {after['trial_ends_at']:%d %b})")
    post(manager, f'/console/companies/{A}/trial', {'days': '365'})
    check(control_plane.find(engine, A)['trial_ends_at'] == after['trial_ends_at'],
          'only the offered lengths are accepted')

    print('\n6b. Marking a test account: managers only, recorded, reversible')
    post(helper, f'/console/companies/{A}/test', {'on': '1'})
    check(not control_plane.find(engine, A).get('is_test'), 'a helper cannot mark one')
    post(manager, f'/console/companies/{A}/test', {'on': '1'})
    check(control_plane.find(engine, A).get('is_test') is True, 'a manager can')
    listing = get(helper, '/console/companies').data.decode()
    check('test account' in listing.split(f'Ops Alpha {TAG}')[1].split('</tr>')[0],
          'the company list says so')
    post(manager, f'/console/companies/{A}/test', {'on': '0'})
    check(control_plane.find(engine, A).get('is_test') is False, 'and it can be undone')
    with engine.connect() as conn:
        marks = [r[0] for r in conn.execute(text(
            "SELECT action FROM public.console_log WHERE actor = :a AND target = :t "
            "AND action LIKE 'marked as%' ORDER BY id"), {'a': MANAGER, 't': A})]
    check(marks == ['marked as test account', 'marked as a real company'],
          f'both changes are in the record ({marks})')

    print('\n7. Suspend needs a reason, locks the company out, and reactivates')
    post(manager, f'/console/companies/{B}/suspend', {'reason': ''})
    check(control_plane.find(engine, B)['status'] == 'active', 'no reason, no suspension')
    r = post(manager, f'/console/companies/{B}/suspend', {'reason': 'unpaid, called twice'},
             headers={'Origin': 'https://evil.example'})
    check(r.status_code == 403 and control_plane.find(engine, B)['status'] == 'active',
          'a cross-site submit is refused')
    post(manager, f'/console/companies/{B}/suspend', {'reason': 'unpaid, called twice'})
    check(control_plane.find(engine, B)['status'] == 'suspended', 'suspended with a reason')
    tenant = app.test_client()
    r = tenant.get('/login', headers={'Host': f'{B}.akyehq.test'})
    db.session.remove()
    check(r.status_code == 423, f'the company itself is now locked ({r.status_code})')
    post(manager, f'/console/companies/{A}/reactivate')
    check(control_plane.find(engine, A)['status'] == 'active',
          'reactivating an active company does nothing')
    post(manager, f'/console/companies/{B}/reactivate')
    check(control_plane.find(engine, B)['status'] == 'active', 'reactivated')
    with engine.connect() as conn:
        logged = [tuple(r) for r in conn.execute(text(
            'SELECT action, detail FROM public.console_log WHERE actor = :a AND target = :t '
            'ORDER BY id'), {'a': MANAGER, 't': B})]
    check(logged == [('suspended', 'unpaid, called twice'), ('reactivated', None)],
          f'the record shows who, what and why ({logged})')
    body_b = get(manager, f'/console/companies/{B}').data.decode()
    check('unpaid, called twice' in body_b, "and the company page shows it")

    print('\n8. The lead export cannot run a formula in a spreadsheet')
    csv_body = get(helper, '/console/leads.csv').data.decode()
    check('\'=HYPERLINK' in csv_body and ',=HYPERLINK' not in csv_body,
          'a name starting with = is exported as text')

    print('\n9. Health: every company at once, and the trial emails')
    body = get(helper, '/console/health').data.decode()
    alpha_row = body.split(f'Ops Alpha {TAG}')[1].split('</tr>')[0]
    check('failing' in alpha_row, "Alpha's failing reminders show in the matrix")
    check(f'Ops Charlie {TAG}' not in body.split('Trial emails due')[1].split('Closed, in retention')[0],
          'a closed company is never sent a trial email')
    check(f'Ops Charlie {TAG}' in body.split('Closed, in retention')[1],
          'it is listed as closed, with the date it can be purged')
    check('once a day at 22:00 UTC' in body,
          'the page says when they go out on their own')
    with engine.begin() as conn:
        conn.execute(text("UPDATE public.organizations SET status = 'active', closed_at = NULL "
                          'WHERE slug = :s'), {'s': C})
    body = get(helper, '/console/health').data.decode()
    charlie_row = body.split(f'Ops Charlie {TAG}')[1].split('</tr>')[0]
    check('could not read (no schema)' in charlie_row,
          'a company with no schema of its own is reported, never read from public')
    listing = get(helper, '/console/companies').data.decode()
    charlie_listed = listing.split(f'Ops Charlie {TAG}')[1].split('</tr>')[0]
    check('could not read' in charlie_listed and 'error' not in charlie_listed,
          "and the list does not show another schema's errors as Charlie's")
    due = body.split('Trial emails due')[1].split('Closed, in retention')[0]
    check(f'Ops Charlie {TAG}' in due and 'Not started (day 7)' in due,
          'reopened, Charlie is due the day-7 email')
    check('Send these' not in due, 'a helper gets no send button')
    SENT.clear()
    post(helper, '/console/health/trial-emails')
    check(SENT == [], 'and posting at it sends nothing')
    post(manager, '/console/health/trial-emails')
    check(f'c-{TAG}@example.com' in SENT, 'a manager sends it')
    check('start_7' in (control_plane.find(engine, C)['nudges_sent'] or ''),
          'recorded against the company')
    SENT.clear()
    post(manager, '/console/health/trial-emails')
    check(f'c-{TAG}@example.com' not in SENT, 'pressing again does not send it twice')
    r = post(manager, '/console/health/test-email', follow_redirects=True)
    check(r.status_code == 200, 'the test-email button answers, whatever the mail setup')

    for slug in (A, B):
        try:
            provisioning.drop_schema(engine, tenancy.schema_for(slug))
        except Exception as e:
            print(f'  ⚠️  cleanup of {slug}: {e}')
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM public.organizations WHERE slug LIKE 'e2eops%'"))
        conn.execute(text('DELETE FROM public.product_leads WHERE email = :e'), {'e': LEAD})
        for who in (HELPER, MANAGER):
            conn.execute(text('DELETE FROM public.console_log WHERE actor = :e'), {'e': who})
            conn.execute(text('DELETE FROM public.console_users WHERE email = :e'), {'e': who})

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ The console reads every company safely, and only managers change them.')
