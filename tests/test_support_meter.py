"""Who needs support, and the emails that reach the ones drifting away.

  * console_data.support_meter: a label and its reasons from what the console
    already reads, described rather than built
  * the owner's use is recorded as they use it (auth.note_activity), at most
    hourly, because a self-renewing session leaves last_login months old
  * Console -> Companies shows the label, and "Needs support" filters to it
  * the three "gone quiet" emails ship switched off, and the daily run holds
    them until somebody turns them on

Against a real disposable Postgres, with real provisioned companies.
"""
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


import fresh_postgres
URL = fresh_postgres.url('akye_support_meter_test')
os.environ.update(DATABASE_URL=URL, SECRET_KEY='support-meter-test',
                  BASE_DOMAIN='akye.test', FLASK_ENV='development')

import notifications
SENT = []
notifications.send_email = lambda to, *a, **k: (SENT.append(to), (True, 'stub'))[1]
notifications.send_sms = lambda *a, **k: (True, 'stub')

import communications
import console_data as cd
import trial_nudges as tn

NOW = datetime.utcnow()
ago = lambda days: NOW - timedelta(days=days)     # noqa: E731
SNAP = {'ok': True, 'owner_last_login': None, 'bookings_30d': 4, 'clients': 3,
        'users': 2, 'open_errors': 0, 'jobs_broken': 0}


def company(**kw):
    base = {'slug': 'sparkle', 'status': 'active', 'created_at': ago(40),
            'activated_at': ago(35), 'owner_active_at': ago(1),
            'subscription_status': 'active'}
    base.update(kw)
    return base


def meter(org, snap=None, trial=None):
    return cd.support_meter(org, dict(SNAP, **(snap or {})), trial, NOW)


print('\n1. The meter, described')
check(meter(company())['level'] == 'ok', 'set up, in this week, jobs booked: healthy')
m = meter(company(created_at=ago(1), activated_at=None, owner_active_at=None,
                  subscription_status='trialing'))
check(m['level'] == 'new', 'signed up yesterday: new, the first-week emails have it')
m = meter(company(created_at=ago(6), activated_at=None, subscription_status='trialing'))
check(m['level'] == 'help' and 'Not set up after 6 days' in m['reasons'][0],
      f'six days and no cleaner and customer: needs help ({m["reasons"][:1]})')
m = meter(company(owner_active_at=ago(9)))
check(m['level'] == 'watch' and any('9 days' in r for r in m['reasons']),
      'owner away 9 days: watch')
m = meter(company(owner_active_at=ago(20)))
check(m['level'] == 'help' and m['reasons'][0].startswith('Paying, but the owner'),
      'a paying owner away 20 days: needs help, and says they are paying')
m = meter(company(owner_active_at=ago(30)), {'owner_last_login': ago(2)})
check(m['level'] == 'ok', 'a recent password sign-in counts too: the later of the two')
m = meter(company(owner_active_at=None, created_at=ago(20)), {'owner_last_login': None})
check(m['level'] == 'help' and 'not been seen' in ' '.join(m['reasons']),
      'never seen using it: needs help')
m = meter(company(), {'bookings_30d': 0})
check(m['level'] == 'watch' and 'no jobs booked or done in 30 days' in m['reasons'][0],
      'set up but no jobs in a month: watch')
check(meter(company(), {'bookings_30d': 0, 'completed_30d': 6})['level'] == 'ok',
      'a recurring schedule made months ago, visits still being done: healthy')
m = meter(company(), {'open_errors': 3, 'jobs_broken': 1})
check(m['level'] == 'watch' and m['reasons'] == ['3 errors open', '1 automation not running'],
      'errors and a stalled automation: watch, each named')
fresh = [{'state': 'never'}] * 7
check(meter(company(created_at=ago(0), activated_at=None, owner_active_at=NOW,
                    subscription_status='trialing'), {'jobs': fresh})['level'] == 'new',
      "a company's first day: automations that have not run yet are not a problem")
check('7 automations not running' in meter(company(), {'jobs': fresh})['reasons'],
      'but after a few days, never having run is')
check('1 automation not running' in meter(company(created_at=ago(1)),
                                          {'jobs': [{'state': 'failing'}]})['reasons'],
      'and one failing counts from the start')
check('Payment past due' in meter(company(subscription_status='past_due'))['reasons'],
      'a payment past due is named')
trial = {'phase': 'running', 'days_left': 4}
m = meter(company(created_at=ago(26), activated_at=None, subscription_status='trialing'),
          trial=trial)
check(any('Trial ends in 4 days' in r for r in m['reasons']), 'a trial ending unused says so')
check(meter(company(is_test=True))['level'] == 'none', 'a test account is not supported')
check(meter(company(is_demo=True))['level'] == 'none', 'nor the demo')
check(meter(company(status='suspended'))['level'] == 'none', 'nor a suspended company')
check(cd.support_meter(company(), {'ok': False}, None, NOW)['level'] == 'watch',
      "a company whose data will not read is worth a look, not a crash")

print('\n2. New emails ship switched off')
for key in ('quiet', 'free_quiet', 'free_start'):
    check(key in communications.LABELS, f'{key}: on the Communications page')
    check(not communications.is_on(key, {}), f'{key}: off until somebody turns it on')
    check(communications.is_on(key, {key: True}), f'{key}: on once switched on')
    check(not communications.is_on(key, {key: True, 'owner_all': False}),
          f'{key}: and still held by the "all owner emails" switch')
check(communications.is_on('day1', {}), 'an email from before keeps its old default: on')
check(communications.state('quiet', {}) is False and communications.state('day1', {}) is True,
      'and the page shows each as it is')
for key in ('quiet', 'free_quiet', 'free_start'):
    subject, html = communications.sample_preview(key)
    check(subject.startswith('Sparkle Cleaning') and 'sparkle.' in html,
          f'{key}: the console preview renders ({subject})')

print('\n3. The words')
o = company(name='Brightside Cleaning', slug='brightside', owner_email='dana@b.test',
            subscription_status='trialing', trial_ends_at=NOW + timedelta(days=9),
            created_at=ago(21))
for key in ('quiet', 'free_quiet', 'free_start'):
    subject, html = tn.compose(o, key)
    words = (subject + html).lower()
    check('brightside' in subject.lower() and 'brightside.akye.test' in html
          and '/billing' in html, f'{key}: names them, their own address, how to stop')
    check(not any(w in words for w in ("you'll love", 'game-changer', 'act now',
                                       'last chance', 'hours a week')),
          f'{key}: no invented urgency or numbers')
_, free_start = tn.compose(o, 'free_start')
check('20 jobs a month' in free_start and 'up to 3 cleaners' in free_start,
      'free_start promises only what the free plan has')
_, free_quiet = tn.compose(o, 'free_quiet')
check('texting' not in free_quiet.lower() and 'reminders' not in free_quiet.lower(),
      'free_quiet offers no paid feature')

print('\n4. Against a real database')
from app import create_app
from extensions import db
import auth
import control_plane
import provisioning

app = create_app()
with app.app_context():
    provisioning.provision('meterone', 'Meter One Cleaning', 'one@meter.test', quiet=True)
    provisioning.provision('metertwo', 'Meter Two Cleaning', 'two@meter.test', quiet=True)
    db.session.remove()
engine = provisioning._engine()


def tidy():
    with app.app_context():
        db.session.remove()


check(control_plane.find(engine, 'meterone').get('owner_active_at') is None,
      'a new company has no recorded activity yet')

owner = fresh_postgres.owner_client(app, 'meterone', 'akye.test')
r = owner.get('/', base_url='http://meterone.akye.test')
tidy()
row = control_plane.find(engine, 'meterone')
check(r.status_code == 200 and row.get('owner_active_at') and row.get('active_at'),
      f'the owner opening a page records them ({r.status_code})')
first = row['owner_active_at']
owner.get('/', base_url='http://meterone.akye.test')
tidy()
check(control_plane.find(engine, 'meterone')['owner_active_at'] == first,
      'and not again on the next page: at most hourly')
with owner.session_transaction(base_url='http://meterone.akye.test') as sess:
    sess['active_mark'] = 0
owner.get('/', base_url='http://meterone.akye.test')
tidy()
check(control_plane.find(engine, 'meterone')['owner_active_at'] > first,
      'an hour later, it moves')
check(control_plane.find(engine, 'metertwo').get('owner_active_at') is None,
      "and one company's use is never written to another's")

real_mark = control_plane.mark_active
control_plane.mark_active = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('db down'))
try:
    with owner.session_transaction(base_url='http://meterone.akye.test') as sess:
        sess['active_mark'] = 0
    r = owner.get('/', base_url='http://meterone.akye.test')
    tidy()
    check(r.status_code == 200, 'a page still loads when the timestamp cannot be written')
finally:
    control_plane.mark_active = real_mark

print('\n5. Console -> Companies')
PASSWORD = 'a-real-console-password-1'
control_plane.add_console_user(engine, 'manager@meter.test', 'Manager', PASSWORD, role='manager')
control_plane.set_billing(engine, 'metertwo', subscription_status='active')
with engine.begin() as conn:
    from sqlalchemy import update
    conn.execute(update(control_plane.organizations)
                 .where(control_plane.organizations.c.slug == 'metertwo')
                 .values(created_at=ago(30), activated_at=ago(28), owner_active_at=ago(21)))
console = app.test_client()
r = console.post('/console/login', data={'email': 'manager@meter.test', 'password': PASSWORD})
tidy()
page = console.get('/console/companies').get_data(as_text=True)
tidy()
check('Support' in page and 'Needs help' in page and 'Needs support' in page,
      'every row has a support label, and the filter is there')
check('Paying, but the owner has not been in for 21 days' in page,
      'a paying company gone quiet is called out for a personal note')
needs = console.get('/console/companies?needs=1').get_data(as_text=True)
tidy()
check('Meter Two Cleaning' in needs and 'Needing support' in needs,
      'Needs support lists the company that needs it')
check('Meter One Cleaning' not in needs, 'and not the one in use today')
detail = console.get('/console/companies/metertwo').get_data(as_text=True)
tidy()
check('Needs help' in detail and 'has not been in for 21 days' in detail,
      "the company's own page says why")

print('\n6. The daily run holds them until they are switched on')
with engine.begin() as conn:
    conn.execute(update(control_plane.organizations)
                 .where(control_plane.organizations.c.slug == 'meterone')
                 .values(subscription_status='trialing', created_at=ago(11),
                         trial_ends_at=NOW + timedelta(days=19), activated_at=ago(9),
                         owner_active_at=ago(8), nudges_sent='activated'))
with app.app_context():                 # as the /api/trial-nudges request has
    step = tn.next_step('meterone')
    out = tn.run(engine, dry_run=True)
    db.session.remove()
check(step and tn.due(control_plane.find(engine, 'meterone'), NOW, next_step=step) == 'quiet',
      f'Meter One, set up 9 days ago and away 8: quiet is first in line ({step and step["title"]})')
check(('meterone', 'feature', 'one@meter.test') in out['plan'],
      f'quiet is switched off, so the feature note still goes instead '
      f'({[p for p in out["plan"] if p[0] == "meterone"]})')
with engine.begin() as conn:
    conn.execute(update(control_plane.organizations)
                 .where(control_plane.organizations.c.slug == 'metertwo')
                 .values(subscription_status='trialing', trial_ends_at=ago(25),
                         nudges_sent='activated,day2,ending,ended,winback'))
out = tn.run(engine, dry_run=True)
check(not any(slug == 'metertwo' for slug, *_ in out['plan']) and out['switched_off'] >= 1,
      f'free_quiet is due for Meter Two but held by its switch ({out["switched_off"]} held)')
control_plane.set_switch(engine, 'free_quiet', True, 'test')
out = tn.run(engine, dry_run=True)
check(('metertwo', 'free_quiet', 'two@meter.test') in out['plan'],
      'switched on, it is in the plan')
SENT.clear()
out = tn.run(engine)
check('two@meter.test' in SENT and 'free_quiet' in
      control_plane.find(engine, 'metertwo')['nudges_sent'],
      'and the real run sends it once and writes it down')
SENT.clear()
tn.run(engine)
check('two@meter.test' not in SENT, 'never twice')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for m in failures:
        print(f'   - {m}')
    sys.exit(1)
print('\n✅ The console says who needs support, and the quiet ones are written to, once.')
