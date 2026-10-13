"""From a Meta click to a company that is actually using it.

The signup funnel added in October 2026, walked end to end on a real
PostgreSQL, with every email caught instead of sent:

  * somebody who leaves the form half-way is still written down, and taken
    off the list again when they finish
  * the welcome email carries a code that proves the address is right; the
    emailed link asks before it confirms; a mistyped address can be fixed
  * the first week has its own short run of emails, the two moments that
    matter get a note when they happen, and never more than one a day
  * somebody who came close and did not sign up gets four useful emails,
    and nobody from an uploaded list ever does
"""
import os
import re
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
URL = fresh_postgres.url('akye_funnel_test')
os.environ.update(DATABASE_URL=URL, SECRET_KEY='funnel-test',
                  BASE_DOMAIN='rollcall.test', SIGNUPS_OPEN='1',
                  SIGNUP_LIMITS='0', FLASK_ENV='development')
os.environ.pop('ADMIN_USER', None)
os.environ.pop('ADMIN_PASS', None)

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to_email, to_name, subject, html, **k: (
    SENT.append({'to': to_email, 'subject': subject, 'html': html,
                 'from': k.get('from_email')}), (True, 'stub'))[1]

import billing
import email_confirm
import lead_nurture
import trial_nudges as tn

NOW = datetime.utcnow()


def org(days_old=0, **kw):
    created = NOW - timedelta(days=days_old)
    base = {'slug': 'brightside', 'name': 'Brightside Cleaning',
            'owner_email': 'dana@brightside.example', 'status': 'active',
            'created_at': created, 'plan': 'scale',
            'subscription_status': 'trialing',
            'trial_ends_at': created + timedelta(days=billing.START_WITHIN_DAYS),
            'activated_at': None, 'nudges_sent': None}
    base.update(kw)
    return base


def running(days_in, **kw):
    began = NOW - timedelta(days=days_in)
    return org(days_old=days_in + 2, activated_at=began,
               trial_ends_at=began + timedelta(days=billing.TRIAL_DAYS), **kw)


print('\n1. The first week is no longer silent')
check(tn.due(org(days_old=0)) is None, 'signup day — the welcome email is enough')
check(tn.due(org(days_old=1)) == 'day1', 'day 1 — two things, two minutes')
check(tn.due(org(days_old=2, nudges_sent='day1')) == 'day2',
      'day 2 — your booking page is already live')
check(tn.due(org(days_old=2)) == 'day1',
      'a missed day sends yesterday\'s note first, not both')
check(tn.due(org(days_old=4, nudges_sent='day1,day2')) == 'day4',
      'day 4 — where people get stuck')
check(tn.due(org(days_old=5, nudges_sent='day1,day2,day4')) == 'day5',
      'day 5 — bring your list over')
check(tn.due(org(days_old=7, nudges_sent='day1,day2,day4,day5')) == 'start_7',
      'day 7 — the existing nudge carries on as before')
check(tn.due(org(days_old=3, nudges_sent='day1,day2')) is None,
      'a quiet day in between')

print('\n2. Each not-activated note stops the moment they act')
check(tn.due(running(0, created_at=NOW - timedelta(days=1))) == 'activated',
      'activated today — the "now switched on" note, not "two things"')
o = running(0, created_at=NOW - timedelta(days=1), nudges_sent='activated')
check(tn.due(o) is None, 'and never "add a cleaner" to somebody who has')
check(tn.due(running(1, nudges_sent='activated')) == 'day2',
      'the booking page note still goes to everybody')
check(tn.due(running(5, nudges_sent='activated,day2')) is None,
      'day 5 of a running trial — nothing about importing a list')

print('\n3. One email a day, whatever sent the last one')
just = NOW - timedelta(hours=3)
check(tn.due(org(days_old=1, nudge_last_at=just)) is None,
      'three hours after any email, nothing else today')
check(tn.due(org(days_old=1, nudge_last_at=NOW - timedelta(hours=23))) == 'day1',
      'the next morning, the day\'s note goes')

print('\n4. A week into the trial, one thing they have not tried')
step = {'title': 'Share your booking page', 'why': 'w', 'cta': 'Go',
        'link': '/settings/booking-page'}
check(tn.due(running(9, nudges_sent='activated,day2'), next_step=step) == 'feature',
      'day 9 with a step undone — the feature note')
check(tn.due(running(9, nudges_sent='activated,day2')) is None,
      'with nothing undone, nothing')
check(tn.due(running(11, nudges_sent='activated,day2'), next_step=step) == 'ending',
      'and never in competition with "3 days left"')
subj, html = tn.compose(running(9), 'feature', step)
check('Share your booking page' in html and '/settings/booking-page' in html,
      'it names the step and links to it')

print('\n5. A week after it lapses, once, and only for somebody who used it')
lapsed = dict(running(22), trial_ends_at=NOW - timedelta(days=8),
              nudges_sent='activated,day2,ending,ended')
check(tn.due(lapsed) == 'winback', 'a week on — here is what you would get back')
check(tn.due(dict(lapsed, nudges_sent=lapsed['nudges_sent'] + ',winback')) is None,
      'and only once')
check(tn.due(dict(lapsed, activated_at=None)) is None,
      'never to a trial that lapsed without being started')
check(tn.due(dict(lapsed, trial_ends_at=NOW - timedelta(days=90))) is None,
      'never to one that lapsed months ago')

print('\n6. Never to the people the rules already protect')
for label, o in (('paying', org(days_old=1, subscription_status='active')),
                 ('test account', org(days_old=1, is_test=True)),
                 ('demo company', org(days_old=1, is_demo=True)),
                 ('opted out', org(days_old=1, nudges_opted_out=True)),
                 ('suspended', org(days_old=1, status='suspended'))):
    check(tn.due(o) is None, f'{label}: nothing')

print('\n7. Every new email reads right')
for kind in ('day1', 'day2', 'day4', 'day5', 'activated', 'feature',
             'first_booking', 'winback'):
    subj, html = tn.compose(running(1), kind, step)
    check('Brightside' in subj and 'brightside.rollcall.test' in html
          and '/billing' in html,
          f'{kind}: names them, links to their own address, says how to stop')
_s, h = tn.compose(org(days_old=1), 'day2')
check('brightside.rollcall.test/book' in h, 'day 2 shows their real booking link')
_s, h = tn.compose(running(0), 'activated')
check('add one cleaner' not in h.lower(), 'the activated note does not ask for what they did')

print('\n8. The confirm code')
c1 = email_confirm.code('brightside', 'dana@brightside.example')
check(re.fullmatch(r'\d{6}', c1) is not None, 'six digits')
check(c1 == email_confirm.code('brightside', ' Dana@Brightside.example '),
      'the same code for the same address, however it is typed')
check(c1 != email_confirm.code('brightside', 'dana@brightsde.example'),
      'a corrected address gets a different code')
check(email_confirm.code_matches('brightside', 'dana@brightside.example',
                                 c1[:3] + ' ' + c1[3:]),
      'a code typed with a space still matches')
check(not email_confirm.code_matches('brightside', 'dana@brightside.example', '000000')
      or c1 == '000000', 'a wrong code does not')
tok = email_confirm.token('brightside', 'dana@brightside.example')
check(email_confirm.read_token(tok) == ('brightside', 'dana@brightside.example'),
      'the link names the company and the address')
check(email_confirm.read_token(tok + 'x') == (None, None), 'a tampered link names nothing')
check(not email_confirm.pending({'owner_email': 'x@y.z'}),
      'a company from before this existed is never asked to confirm')

print('\n9. The nurture sequence, described')
lead = {'id': 1, 'email': 'sam@sparkle.example', 'name': 'Sam Reed',
        'company': 'Sparkle', 'source': 'abandoned_signup',
        'created_at': NOW - timedelta(days=1)}
check(lead_nurture.due_step(lead, now=NOW) == 1, 'day 1 — email 1')
check(lead_nurture.due_step(dict(lead, created_at=NOW), now=NOW) is None,
      'not on the same day they left')
check(lead_nurture.due_step(dict(lead, source='console upload'), now=NOW) is None,
      'never anybody from an uploaded list')
check(lead_nurture.due_step(lead, owners={'sam@sparkle.example'}, now=NOW) is None,
      'never somebody who has since opened an account')
check(lead_nurture.due_step(dict(lead, unsubscribed_at=NOW), now=NOW) is None,
      'never somebody who unsubscribed')
check(lead_nurture.due_step(dict(lead, contacted_at=NOW), now=NOW) is None,
      'never somebody a person is already talking to')
check(lead_nurture.due_step(dict(lead, created_at=NOW - timedelta(days=60)),
                            now=NOW) is None,
      'never the start of the sequence for somebody who asked months ago')
check(lead_nurture.due_step(dict(lead, nurture_step=1,
                                 created_at=NOW - timedelta(days=4),
                                 nurture_last_at=NOW - timedelta(days=3)),
                            now=NOW) == 2, 'day 4 — email 2')
check(lead_nurture.due_step(dict(lead, nurture_step=1,
                                 created_at=NOW - timedelta(days=4),
                                 nurture_last_at=NOW - timedelta(hours=20)),
                            now=NOW) is None, 'never two within two days')
check(lead_nurture.due_step(dict(lead, nurture_step=4,
                                 created_at=NOW - timedelta(days=30)),
                            now=NOW) is None, 'and after four, nothing')
s1, b1 = lead_nurture.compose(lead, 1)
check('You started setting up Sparkle' in b1, 'email 1 offers to finish for somebody who left')
s1b, b1b = lead_nurture.compose(dict(lead, source='direct'), 1)
check('You started' not in b1b, 'and does not for an early-access request')
for n in range(1, 5):
    _s, b = lead_nurture.compose(lead, n)
    check(lead_nurture.signup_link() in b, f'email {n} carries the free signup link')


# ───────────────────────────── on a real database ──────────────────────────
from app import create_app
import control_plane
import provisioning
import tenancy
from sqlalchemy import text

app = create_app()
client = app.test_client()
PRODUCT = {'Host': 'rollcall.test'}
COMPANY = {'Host': 'sparkle.rollcall.test'}
engine = provisioning._engine()


def leads_for(email):
    return [l for l in control_plane.all_leads(engine)
            if (l.get('email') or '') == email]


print('\n10. Leaving the form half-way still leaves a name behind')
r = client.post('/signup/started', json={'email': 'Dana@Sparkle.test',
                                         'name': 'Dana', 'business': 'Sparkle'},
                headers=PRODUCT)
check(r.status_code == 204, 'the form gets nothing back to act on')
rows = leads_for('dana@sparkle.test')
check(len(rows) == 1 and rows[0]['source'] == 'abandoned_signup',
      'one lead, tagged as a half-finished signup')
client.post('/signup/started', json={'email': 'dana@sparkle.test'}, headers=PRODUCT)
check(len(leads_for('dana@sparkle.test')) == 1, 'tabbing out twice is still one person')
client.post('/signup/started', json={'email': 'not-an-email'}, headers=PRODUCT)
client.post('/signup/started', json={'email': 'bot@spam.test', 'website': 'x'},
            headers=PRODUCT)
check(not leads_for('not-an-email') and not leads_for('bot@spam.test'),
      'nothing written for a bad address or a bot')

print('\n11. Finishing signup sends the address, the code, and clears the lead')
SENT.clear()
r = client.post('/signup', data={
    'business': 'Sparkle Cleaning', 'slug': 'sparkle', 'name': 'Dana Reed',
    'email': 'dana@sparkle.test', 'password': 'a-perfectly-fine-password',
    'terms_accepted': '1'}, headers=PRODUCT)
check(r.status_code == 302, 'signup still goes straight into the account')
token = r.headers['Location'].split('/welcome/')[1]
check(not leads_for('dana@sparkle.test'), 'and they are no longer a half-finished signup')
welcome = [m for m in SENT if m['to'] == 'dana@sparkle.test']
code = email_confirm.code('sparkle', 'dana@sparkle.test')
check(len(welcome) == 1, 'one email to them, not a welcome and a separate confirm')
check(welcome and code in welcome[0]['html'] and 'sparkle.rollcall.test' in welcome[0]['html'],
      'it carries their address and their code')
check(welcome and 'add one cleaner and one customer' in ' '.join(welcome[0]['html'].split()),
      'and the trial rule the code actually uses')
link = re.search(r'href="(https?://sparkle\.rollcall\.test/confirm-email/[^"]+)"',
                 welcome[0]['html']) if welcome else None
check(link is not None, 'and a link to the "is this you?" page on their own address')
o = control_plane.find(engine, 'sparkle')
check(o.get('email_confirm_sent_at') and not o.get('email_confirmed_at'),
      'the company is waiting on a confirmation')

client.get(f'/welcome/{token}', headers=COMPANY)
page = client.get('/', headers=COMPANY, follow_redirects=True).data.decode()
check('Confirm your email' in page, 'the dashboard asks, softly')

print('\n12. The emailed link asks before it confirms')
path = link.group(1).split('rollcall.test', 1)[1]
anon = app.test_client()
r = anon.get(path, headers=COMPANY)
check(r.status_code == 200 and b'Yes, this is me' in r.data,
      'opening it shows a button and nothing more')
check(not control_plane.find(engine, 'sparkle').get('email_confirmed_at'),
      'so a mail scanner opening it confirms nothing')
r = anon.post(path, headers=COMPANY)
check(r.status_code == 200 and control_plane.find(engine, 'sparkle').get('email_confirmed_at'),
      'pressing the button confirms it')
page = client.get('/', headers=COMPANY, follow_redirects=True).data.decode()
check('Confirm your email' not in page, 'and the banner goes')
r = anon.get(path.replace('/confirm-email/', '/confirm-email/x'), headers=COMPANY)
check(r.status_code == 400, 'a damaged link says it is out of date')

print('\n13. A mistyped address can be fixed, and the old link stops working')
control_plane.set_email_state(engine, 'sparkle', email_confirmed_at=None)
r = client.post('/confirm-email/change', headers=COMPANY, data={
    'email': 'dana.reed@sparkle.test', 'password': 'wrong'})
check(control_plane.find(engine, 'sparkle')['owner_email'] == 'dana@sparkle.test',
      'the wrong password changes nothing')
SENT.clear()
client.post('/confirm-email/change', headers=COMPANY, data={
    'email': 'dana.reed@sparkle.test', 'password': 'a-perfectly-fine-password'})
o = control_plane.find(engine, 'sparkle')
check(o['owner_email'] == 'dana.reed@sparkle.test', 'the right password updates the company')
with app.app_context(), tenancy.use_tenant('sparkle'):
    from models import User, BusinessSetting
    owner = User.query.filter_by(role='owner').first()
    check(owner.username == 'dana.reed@sparkle.test', 'and the address they sign in with')
    check(BusinessSetting.get('email') == 'dana.reed@sparkle.test',
          'and the business contact email')
check(any(m['to'] == 'dana.reed@sparkle.test' for m in SENT),
      'a fresh code goes to the new address')
check(anon.get(path, headers=COMPANY).status_code == 400,
      'the old link no longer confirms anything')
new_code = email_confirm.code('sparkle', 'dana.reed@sparkle.test')
client.post('/confirm-email', headers=COMPANY, data={'code': code})
check(not control_plane.find(engine, 'sparkle').get('email_confirmed_at'),
      'nor does the old code')
client.post('/confirm-email', headers=COMPANY, data={'code': new_code})
check(control_plane.find(engine, 'sparkle').get('email_confirmed_at'),
      'the new code does')

print('\n14. The moment the 14 days start, a note — once')
SENT.clear()
with app.app_context(), tenancy.use_tenant('sparkle'):
    from extensions import db
    from models import Staff, Client
    db.session.add(Staff(name='Kim', phone='5550100', is_active=True))
    db.session.add(Client(name='Pat Customer', email='pat@example.test'))
    db.session.commit()
    db.session.remove()
client.get('/', headers=COMPANY, follow_redirects=True)
client.get('/', headers=COMPANY, follow_redirects=True)
got = [m for m in SENT if 'just started' in m['subject']]
check(len(got) == 1, 'the "your 14 days just started" email, sent when it happened')
check('activated' in (control_plane.find(engine, 'sparkle').get('nudges_sent') or ''),
      'and recorded, so it is never sent again')

print('\n15. The first booking through their own page, once')
SENT.clear()
ok, why = tn.send_event('sparkle', 'first_booking', engine)
check(ok, 'somebody booked you — sent')
ok, why = tn.send_event('sparkle', 'first_booking', engine)
check(not ok and why == 'already sent', 'the second booking sends nothing')
check(not tn.send_event('sparkle', 'day1', engine)[0], 'only real events can be sent this way')

print('\n16. And the daily run waits for tomorrow')
SENT.clear()
out = tn.run(engine)
check(not [p for p in out.get('plan', []) if p[0] == 'sparkle'],
      'a company emailed today gets nothing else today')

print('\n17. The nurture run, against the real table')
control_plane.add_lead(engine, email='left@halfway.test', name='Lee',
                       company='Halfway Co', source='abandoned_signup')
control_plane.add_lead(engine, email='cold@list.test', name='Cole',
                       source='console upload')
control_plane.add_lead(engine, email='dana.reed@sparkle.test', name='Dana',
                       source='direct')
with engine.begin() as conn:
    conn.execute(text("UPDATE public.product_leads SET created_at = :c"),
                 {'c': NOW - timedelta(days=1, hours=1)})
SENT.clear()
out = lead_nurture.run(engine)
to = sorted(m['to'] for m in SENT)
check(to == ['left@halfway.test'], 'only the half-finished signup is emailed')
check(SENT and 'Unsubscribe' in SENT[0]['html'], 'with an unsubscribe link')
SENT.clear()
lead_nurture.run(engine)
check(not SENT, 'running it again the same day sends nothing')

engine.dispose()

if failures:
    print(f'\n\n❌ {len(failures)} funnel check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ From a click to a company that is using it, nobody falls through.\n')
