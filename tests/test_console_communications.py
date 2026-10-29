"""Console → Communications: every automated email, in one place.

What it guards:

  * every email the product sends an owner is written down, and shows on the
    page and on that company's own console page
  * a switch turned off stops that email -- in the daily run, in the moment
    emails, and for leads -- without marking it sent
  * only a manager or the owner can flip a switch, and the welcome email
    cannot be switched off
  * a signup invite sent by hand stops the automatic lead emails
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
URL = fresh_postgres.url('akye_comms_test')
os.environ.update(DATABASE_URL=URL, SECRET_KEY='comms-test',
                  BASE_DOMAIN='rollcall.test', SIGNUPS_OPEN='1',
                  SIGNUP_LIMITS='0', FLASK_ENV='development')
os.environ.pop('ADMIN_USER', None)
os.environ.pop('ADMIN_PASS', None)

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to_email, to_name, subject, html, **k: (
    SENT.append({'to': to_email, 'subject': subject}), (True, 'stub'))[1]

from sqlalchemy import text

from app import create_app
import communications
import control_plane
import lead_nurture
import provisioning
import trial_nudges as tn

app = create_app()
engine = provisioning._engine()
NOW = datetime.utcnow()

print('\n1. The catalog matches what the senders can send')
keys = {k for k, *_ in communications.CATALOG}
check(set(tn.ALL) <= keys, 'every owner email is listed')
check({f'nurture_{i}' for i in range(1, len(lead_nurture.SCHEDULE) + 1)} <= keys,
      'every lead email is listed')
check('welcome' in communications.ALWAYS_ON, 'the welcome email is always on')
with app.app_context():
    for key in keys:
        subject, html = communications.sample_preview(key)
        check(bool(subject) and len(html) > 100, f'{key}: has a preview')

print('\n2. A signup is written down')
c = app.test_client()
c.post('/signup', data={'business': 'Sparkle Cleaning', 'slug': 'sparkle',
                        'name': 'Dana Reed', 'email': 'dana@sparkle.test',
                        'password': 'a-perfectly-fine-password',
                        'terms_accepted': '1', 'zip_code': '32801',
                        'phone': '4075550123'}, headers={'Host': 'rollcall.test'})
logged = control_plane.product_messages_for(engine, slug='sparkle')
check([m['kind'] for m in logged] == ['welcome'] and logged[0]['ok'],
      'the welcome email is recorded against the company')

print('\n3. The daily run records what it sends, and respects switches')
with engine.begin() as conn:
    conn.execute(text("UPDATE public.organizations SET created_at = :c WHERE slug='sparkle'"),
                 {'c': NOW - timedelta(days=1, hours=2)})
control_plane.set_switch(engine, 'day1', False, 'test')
SENT.clear()
out = tn.run(engine)
check(out['switched_off'] == 1 and not SENT, 'day 1 switched off: nothing sent')
check('day1' not in (control_plane.find(engine, 'sparkle').get('nudges_sent') or ''),
      'and not marked as sent, so it can still go')
control_plane.set_switch(engine, 'day1', True, 'test')
out = tn.run(engine)
check(out['day1'] == 1 and SENT, 'switched back on: it goes')
kinds = [m['kind'] for m in control_plane.product_messages_for(engine, slug='sparkle')]
check(kinds[0] == 'day1', 'and is recorded')

print('\n4. The master switch holds everything to owners')
control_plane.set_switch(engine, communications.ALL_OWNER, False, 'test')
ok, why = tn.send_event('sparkle', 'first_booking', engine)
check(not ok and 'switched off' in why, 'a moment email waits while all owner emails are off')
control_plane.set_switch(engine, communications.ALL_OWNER, True, 'test')
ok, why = tn.send_event('sparkle', 'first_booking', engine)
check(ok, 'and goes once they are back on')
check(control_plane.product_messages_for(engine, slug='sparkle')[0]['sent_by'] == 'event',
      'recorded as sent by the event')

print('\n5. Lead emails: switches, and a hand-sent invite stops them')
control_plane.add_lead(engine, email='lee@halfway.test', name='Lee',
                       source='abandoned_signup')
control_plane.add_lead(engine, email='ivy@invited.test', name='Ivy',
                       source='abandoned_signup')
with engine.begin() as conn:
    conn.execute(text("UPDATE public.product_leads SET created_at = :c"),
                 {'c': NOW - timedelta(days=1, hours=2)})
    conn.execute(text("UPDATE public.product_leads SET invited_at = :c "
                      "WHERE email = 'ivy@invited.test'"), {'c': NOW})
control_plane.set_switch(engine, communications.ALL_LEAD, False, 'test')
SENT.clear()
out = lead_nurture.run(engine)
check(not SENT and out['switched_off'] == 1, 'all lead emails off: nothing sent')
control_plane.set_switch(engine, communications.ALL_LEAD, True, 'test')
out = lead_nurture.run(engine)
check([m['to'] for m in SENT] == ['lee@halfway.test'],
      'back on: only the lead nobody invited by hand is emailed')

print('\n6. The console page')
TAG = 'comms'
control_plane.add_console_user(engine, f'mgr-{TAG}@example.com', 'Manager',
                               'a-real-console-password-1', role='manager')
control_plane.add_console_user(engine, f'help-{TAG}@example.com', 'Helper',
                               'a-real-console-password-1', role='helper')
m = app.test_client()
m.post('/console/login', data={'email': f'mgr-{TAG}@example.com',
                               'password': 'a-real-console-password-1'})
page = m.get('/console/communications').data.decode()
check('Communications' in page and 'Every automated email' in page, 'the page opens')
check('Get the schedule out of your head' in page and 'Last one from us' in page,
      'it lists owner and lead emails')
check('dana@sparkle.test' in page, 'recent sends show who they went to')
found = m.get('/console/communications?q=dana@sparkle.test').data.decode()
check('Everything sent to' in found and 'Welcome' in found,
      'searching an address shows that person\'s emails')
check(m.get('/console/communications/preview/day2').status_code == 200,
      'an email can be previewed')
comp = m.get('/console/companies/sparkle').data.decode()
check('Emails we have sent them' in comp and 'Get the schedule out of your head' in comp,
      "the company's own page lists its emails")

m.post('/console/communications/switch', data={'key': 'day4', 'on': '0'})
check(control_plane.switches(engine).get('day4') is False, 'a manager can switch an email off')
m.post('/console/communications/switch', data={'key': 'welcome', 'on': '0'})
check('welcome' not in control_plane.switches(engine), 'but not the welcome email')
h = app.test_client()
h.post('/console/login', data={'email': f'help-{TAG}@example.com',
                               'password': 'a-real-console-password-1'})
h.post('/console/communications/switch', data={'key': 'day4', 'on': '1'})
check(control_plane.switches(engine).get('day4') is False, 'a helper cannot change switches')
check(any(r['action'] == 'email switched off' for r in control_plane.console_log_all(engine)),
      'switching is written in the console record')

engine.dispose()
if failures:
    print(f'\n\n❌ {len(failures)} communications check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Every email to owners and leads, in one place, under one set of switches.\n')
