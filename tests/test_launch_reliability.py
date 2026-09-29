"""Launch reliability: money keys, bulk sends, interview invites, leads, /version.

What each of these would cost if it regressed:
  * a company that never connected Stripe charging its customers -- and paying
    its cleaners -- through the platform's own Stripe account;
  * a 200-lead send outliving the web worker, killed half way with the page
    erroring for every company at once;
  * an applicant's interview invite looked up in no company at all, so it
    never goes out;
  * somebody who asks for early access twice vanishing instead of showing as
    the warmest lead on the list;
  * a deploy whose migration failed looking healthy from /version.

Against a real disposable Postgres, like the rest of the suite.
"""
import os
import secrets
import sys
import threading

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
os.environ['PRODUCT_RESEND_API_KEY'] = 're_test_not_real'
os.environ['PRODUCT_LEGAL_ADDRESS'] = '1 Test Street\nOrlando, FL 32801'
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_PLATFORM_ENV'
os.environ['STRIPE_PUBLISHABLE_KEY'] = 'pk_test_PLATFORM_ENV'
os.environ['STRIPE_WEBHOOK_SECRET'] = 'whsec_PLATFORM_ENV'
os.environ.pop('STRIPE_ENV_FALLBACK_TENANTS', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (
    SENT.append(a[0] if a else k.get('to_email') or k.get('to')), (True, 'stub'))[1]
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import control_plane
import integrations
import lead_outreach
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


TAG = secrets.token_hex(4)
A, B = f'rela{TAG}', f'relb{TAG}'
with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    for slug in (A, B):
        provisioning.provision(slug, f'Company {slug}', quiet=True)
    db.session.remove()

print('\n1. A company that never connected Stripe does not use the platform\'s keys')
with app.app_context():
    with tenancy.use_tenant(A):
        check(integrations.stripe_secret_key() == '' and integrations.source('stripe_secret_key') is None,
              'the secret key reads as not connected, not as the environment\'s')
        check(integrations.stripe_publishable_key() == '' and integrations.get('stripe_webhook_secret') == '',
              'and so do the publishable key and webhook secret')
    os.environ['STRIPE_ENV_FALLBACK_TENANTS'] = f' {B.upper()} , someone-else'
    with tenancy.use_tenant(B):
        check(integrations.stripe_secret_key() == 'sk_test_PLATFORM_ENV'
              and integrations.source('stripe_secret_key') == 'environment',
              'a company named in STRIPE_ENV_FALLBACK_TENANTS does use them')
    with tenancy.use_tenant(A):
        check(integrations.stripe_secret_key() == '', 'and naming one company does not open it to the others')
        integrations.set('stripe_secret_key', 'sk_test_OWN_KEY')
        check(integrations.stripe_secret_key() == 'sk_test_OWN_KEY'
              and integrations.source('stripe_secret_key') == 'settings',
              'a company\'s own saved key is used')
        integrations.set('stripe_secret_key', '')
    os.environ.pop('STRIPE_ENV_FALLBACK_TENANTS', None)
    with tenancy.use_tenant(A):
        os.environ['TWILIO_ACCOUNT_SID'] = 'AC_PLATFORM'
        check(integrations.twilio_account_sid() == 'AC_PLATFORM',
              'texting still falls back to the platform number, as designed')
        os.environ.pop('TWILIO_ACCOUNT_SID', None)
    check(integrations.stripe_secret_key() == 'sk_test_PLATFORM_ENV',
          'the product site itself (no company) is unchanged')
    base = os.environ.pop('BASE_DOMAIN')
    with tenancy.use_tenant(A):
        check(integrations.stripe_secret_key() == 'sk_test_PLATFORM_ENV',
              'and so is a single-business install, where the environment is the business')
    os.environ['BASE_DOMAIN'] = base
    db.session.remove()

print('\n2. A bulk send stops at 50 a click, and says how to send the rest')
check(lead_outreach.MAX_BULK == 50, 'the per-click limit is 50')
with app.app_context():
    for i in range(60):
        control_plane.add_lead(engine, name=f'Bulk {i}', email=f'bulk{i}-{TAG}@example.com',
                               source='console upload')
    leads = [l for l in control_plane.all_leads(engine) if TAG in (l['email'] or '')
             and l['email'].startswith('bulk')]
    SENT.clear()
    out = lead_outreach.send_many(engine, leads, 'email', 'Hi', 'Hello {first_name}', 'test')
check(out['sent'] == 50 and len(SENT) == 50, f'50 of 60 go out ({out["sent"]})')
check(any('press send again' in k and v == 10 for k, v in out['skipped'].items()),
      f'the other 10 are named as waiting for the next click ({out["skipped"]})')
with app.app_context():
    # As the console does on the next click: the same people ticked, read afresh.
    leads = [l for l in control_plane.all_leads(engine) if TAG in (l['email'] or '')
             and l['email'].startswith('bulk')]
    SENT.clear()
    out = lead_outreach.send_many(engine, leads, 'email', 'Hi', 'Hello {first_name}', 'test')
check(out['sent'] == 10, 'pressing send again reaches the ten who were left, and nobody twice')

print('\n3. An applicant\'s interview invite is sent from their company')
import blueprints.contractors as contractors
import blueprints.interviews as interviews
timers = []


class _Timer:
    def __init__(self, delay, fn, args=None):
        timers.append((fn, list(args or [])))

    def start(self):
        pass

    daemon = True


invited = []
real_timer = contractors.threading.Timer
contractors.threading.Timer = _Timer
real_invite = interviews.send_interview_invite_email
interviews.send_interview_invite_email = lambda a: invited.append(
    (a.email, tenancy.current_schema()))
c = app.test_client()
r = c.post('/contractors/apply', headers={'Host': f'{A}.akyehq.test'}, data={
    'name': 'Casey Cleaner', 'email': f'casey-{TAG}@example.com', 'phone': '5550101',
    'years_experience': '3-5 years', 'has_transportation': 'on',
    'background_check_consent': 'on', 'agrees_to_ic_terms': 'on'})
check(r.status_code == 200 and len(timers) == 1, 'a qualified applicant schedules the ten-minute invite')
if timers:
    fn, args = timers[0]
    # The timer runs on a brand-new thread, which starts with no company.
    t = threading.Thread(target=fn, args=args)
    t.start()
    t.join(30)
check(invited == [(f'casey-{TAG}@example.com', tenancy.schema_for(A))],
      f'and it is sent, from inside that applicant\'s company ({invited})')
contractors.threading.Timer = real_timer
interviews.send_interview_invite_email = real_invite

print('\n4. Asking twice is counted, and an upload repeating somebody is not')
E = f'twice-{TAG}@example.com'
with app.app_context():
    check(control_plane.add_lead(engine, count_repeat=True, name='Twice', email=E) is True,
          'the first ask is recorded')
    check(control_plane.add_lead(engine, count_repeat=True, name='Twice', email=E.upper()) is True,
          'asking again is recorded too (so the form does not report a failed write)')
    rows = [l for l in control_plane.all_leads(engine) if (l['email'] or '') == E]
    check(len(rows) == 1 and rows[0]['times_asked'] == 2 and rows[0]['last_asked_at'],
          'on the same one row, counted twice')
    check(control_plane.add_lead(engine, name='Twice', email=E, source='console upload') is False,
          'an uploaded list repeating them adds nothing')
    rows = [l for l in control_plane.all_leads(engine) if (l['email'] or '') == E]
    check(rows[0]['times_asked'] == 2, 'and does not count as asking')
    P = f'(555) 7{secrets.randbelow(90) + 10}-{secrets.randbelow(9000) + 1000}'
    check(control_plane.add_lead(engine, name='Phone', phone=P, source='console upload') is True
          and control_plane.add_lead(engine, name='Phone', phone=''.join(ch for ch in P if ch.isdigit()),
                                     source='console upload') is False,
          'a phone number matches however it is punctuated')
    import console_data
    grouped = {l['email']: l['times'] for l in console_data.dedupe_leads(control_plane.all_leads(engine))
               if l.get('email')}
check(grouped.get(E) == 2, 'the console shows them as "asked 2×"')

print('\n5. /version says whether the database is on this build\'s schema')
r = c.get('/version', headers={'Host': 'akyehq.test'})
data = r.get_json()
check(data.get('migrations') == 'ok', f'migrations: {data.get("migrations")}')
import migrate
real_inspect = migrate.inspect_db
migrate.inspect_db = lambda *a, **k: (True, '0017_prospect_sequences', '0018_deposit_method')
data = c.get('/version', headers={'Host': 'akyehq.test'}).get_json()
migrate.inspect_db = real_inspect
check(data.get('migrations') == 'behind' and 'migration did not finish' in (data.get('problem') or ''),
      'and says so plainly when a startup migration did not finish')

print('\n6. The web server runs several workers with room for a slow request')
import runpy
conf = runpy.run_path(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'gunicorn.conf.py'))
check(conf['workers'] >= 2 and conf['timeout'] >= 60 and conf['worker_class'] == 'sync',
      f'{conf["workers"]} sync workers, {conf["timeout"]}s timeout')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Own keys only, 50 a click, invites from the right company, repeat asks counted.')
