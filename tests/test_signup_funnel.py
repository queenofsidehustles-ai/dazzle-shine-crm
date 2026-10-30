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
            'trial_ends_at': created + timedelta(days=billing.TRIAL_DAYS),
            'activated_at': None, 'nudges_sent': None}
    base.update(kw)
    return base


def running(days_in, **kw):
    """Got it working `days_in` days ago. The clock still runs from signup."""
    return org(days_old=days_in + 2,
               activated_at=NOW - timedelta(days=days_in), **kw)


def ending_soon(days_old=28, **kw):
    """Nearly out of its thirty days, and it did get going."""
    return org(days_old=days_old,
               activated_at=NOW - timedelta(days=days_old - 8), **kw)


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
check(tn.due(ending_soon(28, nudges_sent='activated,day2'), next_step=step) == 'ending',
      'and never in competition with "3 days left"')
subj, html = tn.compose(running(9), 'feature', step)
check('Share your booking page' in html and '/settings/booking-page' in html,
      'it names the step and links to it')

print('\n5. A week after it lapses, once, and only for somebody who used it')
lapsed = dict(running(22), created_at=NOW - timedelta(days=38),
              trial_ends_at=NOW - timedelta(days=8),
              nudges_sent='activated,day2,ending,ended')
check(tn.due(lapsed) == 'winback', 'a week on — here is what you would get back')
check(tn.due(dict(lapsed, nudges_sent=lapsed['nudges_sent'] + ',winback')) is None,
      'and only once')
check(tn.due(dict(lapsed, activated_at=None)) is None,
      'never to a trial that lapsed without being started')
check(tn.due(dict(lapsed, created_at=NOW - timedelta(days=200),
                  trial_ends_at=NOW - timedelta(days=90))) is None,
      'never to one that lapsed months ago')

print('\n6. Never to the people the rules already protect')
for label, o in (('paying', org(days_old=1, subscription_status='active')),
                 ('test account', org(days_old=1, is_test=True)),
                 ('demo company', org(days_old=1, is_demo=True)),
                 ('opted out', org(days_old=1, nudges_opted_out=True)),
                 ('suspended', org(days_old=1, status='suspended'))):
    check(tn.due(o) is None, f'{label}: nothing')

print('\n6b. Gone quiet: set up and stopped coming back, or never started')
away = lambda d: NOW - timedelta(days=d)          # noqa: E731
quiet = running(10, nudges_sent='activated,day2,feature', owner_active_at=away(8))
check(tn.due(quiet) == 'quiet', 'on a trial, set up, away 8 days: did the week get away?')
check(tn.due(dict(quiet, owner_active_at=away(3))) is None, 'not after a few days away')
check(tn.due(dict(quiet, owner_active_at=away(20))) is None,
      'not once they are long gone: the window ends')
check(tn.due(dict(quiet, owner_active_at=None)) is None,
      'never on a guess: no recorded activity is not "away"')
check(tn.due(dict(quiet, nudges_sent='activated,day2,feature,quiet')) is None, 'and only once')
check(tn.due(dict(quiet, activated_at=None, created_at=NOW - timedelta(days=12),
                  nudges_sent='day1,day2,day4,day5,start_7')) != 'quiet',
      'never to somebody who never set up (they get the getting-started notes)')
check(tn.due(dict(quiet, subscription_status='active')) is None, 'never to a paying customer')
both = dict(quiet, nudges_sent='activated,day2')
step = {'key': 'job', 'title': 'Book a job'}
check(tn.due(both, next_step=step) == 'quiet', 'quiet and feature both due: quiet first')
check(tn.due(both, next_step=step, skip={'quiet'}) == 'feature',
      'but with quiet switched off, feature still goes (it is not swallowed)')
check(tn.due(both, next_step=step, skip=set(tn.ALL)) is None,
      'and with everything switched off, nothing')

free = dict(running(30), created_at=NOW - timedelta(days=60),
            trial_ends_at=NOW - timedelta(days=30),
            nudges_sent='activated,day2,ending,ended,winback', owner_active_at=away(20))
check(tn.due(free) == 'free_quiet', 'free plan, set up, away 20 days: need a hand?')
check(tn.due(dict(free, owner_active_at=away(10))) is None, 'not after 10 days away')
check(tn.due(dict(free, owner_active_at=away(45))) is None, 'not after a month and a half')
check(tn.due(dict(free, owner_active_at=None)) is None, 'and not without recorded activity')
check(tn.due(dict(free, nudges_sent=free['nudges_sent'] + ',free_quiet')) is None, 'only once')

never = org(days_old=46, trial_ends_at=NOW - timedelta(days=16),
            nudges_sent='day1,day2,day4,day5,start_7,start_21,ending,ended')
check(tn.due(never) == 'free_start', 'free plan, never set up, 16 days on: still here')
check(tn.due(dict(never, created_at=NOW - timedelta(days=120),
                  trial_ends_at=NOW - timedelta(days=90))) is None,
      'never to a trial that ended months ago')
check(tn.due(dict(never, trial_ends_at=NOW - timedelta(days=5))) is None, 'nor in its first week')
check(tn.due(dict(never, nudges_sent=never['nudges_sent'] + ',free_start')) is None, 'only once')
for label, o in (('test account', dict(free, is_test=True)), ('demo', dict(free, is_demo=True)),
                 ('opted out', dict(free, nudges_opted_out=True)),
                 ('suspended', dict(free, status='suspended'))):
    check(tn.due(o) is None, f'{label}: no gone-quiet note either')
check(tn.due(dict(free, nudge_last_at=NOW - timedelta(hours=2))) is None,
      'and still one email a day')

print('\n7. Every new email reads right')
for kind in ('day1', 'day2', 'day4', 'day5', 'activated', 'feature',
             'first_booking', 'winback', 'quiet', 'free_quiet', 'free_start'):
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

print('\n10b. The number they typed is kept, to ring and not to text')
import lead_outreach
control_plane.add_lead(engine, source='early_access', email='early@x.test', phone='+14075550166')
r = client.post('/signup/started', json={'email': 'dana@sparkle.test', 'name': 'Dana',
                                         'business': 'Sparkle', 'phone': '(407) 555-0188'},
                headers=PRODUCT)
rows = leads_for('dana@sparkle.test')
check(r.status_code == 204 and len(rows) == 1,
      'typed after the email, it goes on the same row: still one person')
check(rows[0]['phone'] == '+14075550188', 'kept as +1XXXXXXXXXX, however it was typed')
check(lead_outreach.sms_block(rows[0]) == 'left the signup form without asking for a text',
      'it cannot be texted from the leads page: they were told somebody would call, and have not asked for a text')
check(rows[0]['do_not_text_at'] is None and control_plane.number_text_block(engine, '+14075550188') is None,
      'but that is not a do-not-text mark, which is durable: when they finish and ask, the welcome text can go')
client.post('/signup/started', json={'email': 'dana@sparkle.test', 'phone': '555'}, headers=PRODUCT)
check(leads_for('dana@sparkle.test')[0]['phone'] == '+14075550188',
      'half a number is ignored, not kept over a good one')
client.post('/signup/started', json={'email': 'dana@sparkle.test', 'phone': '407 555 0199'}, headers=PRODUCT)
check(leads_for('dana@sparkle.test')[0]['phone'] == '+14075550199', 'a corrected number replaces it')
client.post('/signup/started', json={'email': 'new@sparkle.test', 'phone': '4075550142'}, headers=PRODUCT)
fresh = leads_for('new@sparkle.test')
check(len(fresh) == 1 and fresh[0]['phone'] == '+14075550142',
      'a number typed with the email (a browser that filled both) is kept the same way')
client.post('/signup/started', json={'email': 'bot2@spam.test', 'phone': '4075550143', 'website': 'x'},
            headers=PRODUCT)
check(not leads_for('bot2@spam.test'), 'a bot leaves nothing, number included')
client.post('/signup/started', json={'email': 'nonumber@sparkle.test'}, headers=PRODUCT)
check(leads_for('nonumber@sparkle.test')[0]['phone'] is None, 'no number, no number')
client.post('/signup/started', json={'email': 'early@x.test', 'phone': '4075550166'}, headers=PRODUCT)
early = leads_for('early@x.test')[0]
check(early['source'] == 'early_access' and early['do_not_text_at'] is None
      and lead_outreach.sms_block(early) is None,
      'somebody already on the list as an early-access request is not changed by it: still textable by the rules they came in under')

print('\n10c. Finishing clears the half-finished row by address or by number, and never a refusal')
control_plane.add_lead(engine, source='abandoned_signup', email='pat@old.test', phone='+14075550177')
control_plane.add_lead(engine, source='abandoned_signup', email='other@x.test', phone='+14075550155')
control_plane.add_lead(engine, source='abandoned_signup', email='stop@old.test', phone='+14075550133')
control_plane.set_leads_sms_opt_out(engine, '+14075550133')
control_plane.add_lead(engine, source='abandoned_signup', email='dnt@old.test', phone='+14075550122',
                       do_not_text=True)
gone = control_plane.clear_abandoned_signup(engine, 'pat@new.test', '(407) 555-0177')
check(gone == 1 and not leads_for('pat@old.test'),
      'finishing with a different address but the same number clears the row')
control_plane.clear_abandoned_signup(engine, 'nobody@x.test', '407-555-0166')
check(leads_for('early@x.test') and leads_for('other@x.test'),
      'an early-access request on the same number, and somebody else\'s half-finished signup, are left alone')
control_plane.clear_abandoned_signup(engine, 'stop@old.test', '+14075550133')
check(leads_for('stop@old.test') and control_plane.number_text_block(engine, '+14075550133') == 'replied STOP',
      'a row that holds a STOP reply is kept, so the number stays opted out')
control_plane.clear_abandoned_signup(engine, 'dnt@old.test', '+14075550122')
check(leads_for('dnt@old.test') and control_plane.number_text_block(engine, '+14075550122') == 'marked do not text',
      'and so is one staff marked do-not-text')
# These rows were for this section only: a later one counts who the nurture run emails.
with engine.begin() as conn:
    conn.execute(text("DELETE FROM public.product_leads WHERE email IN "
                      "('new@sparkle.test', 'nonumber@sparkle.test', 'other@x.test', 'early@x.test', "
                      "'stop@old.test', 'dnt@old.test')"))

print('\n11. Finishing signup sends the address, the code, and clears the lead')
SENT.clear()
r = client.post('/signup', data={
    'business': 'Sparkle Cleaning', 'slug': 'sparkle', 'name': 'Dana Reed',
    'email': 'dana@sparkle.test', 'password': 'a-perfectly-fine-password',
    'terms_accepted': '1', 'zip_code': '32801', 'phone': '4075550123'}, headers=PRODUCT)
check(r.status_code == 302, 'signup still goes straight into the account')
token = r.headers['Location'].split('/welcome/')[1]
check(not leads_for('dana@sparkle.test'), 'and they are no longer a half-finished signup')
welcome = [m for m in SENT if m['to'] == 'dana@sparkle.test']
code = email_confirm.code('sparkle', 'dana@sparkle.test')
check(len(welcome) == 1, 'one email to them, not a welcome and a separate confirm')
check(welcome and code in welcome[0]['html'] and 'sparkle.rollcall.test' in welcome[0]['html'],
      'it carries their address and their code')
check(welcome and 'Your thirty days start today' in ' '.join(welcome[0]['html'].split()),
      'and the trial rule the code actually uses: thirty days from signup')
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

print('\n14. The moment they get it working, a note — once')
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
got = [m for m in SENT if 'that is it working' in m['subject'].lower()]
check(len(got) == 1, 'the "that is it working" email, sent when it happened')
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
