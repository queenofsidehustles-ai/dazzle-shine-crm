"""Console → New Leads: emailing and texting prospects once they are uploaded.

What would make this dangerous or embarrassing:
  * an email with no way to unsubscribe, or no postal address (CAN-SPAM);
  * emailing somebody who unsubscribed, or texting somebody who replied STOP;
  * a text that does not say who it is from or how to stop;
  * Akye's pitch going out from a cleaning company's number -- the platform
    TWILIO_* keys are theirs, the console must use PRODUCT_TWILIO_* only;
  * texting at 6am or 10pm somewhere in the US;
  * a group send hitting the same person twice in a week;
  * anybody forging a STOP/START webhook, or a helper sending at all;
  * {first_name} arriving in someone's inbox as "{first_name}".

Against a real disposable Postgres, like the rest of the console suite.
"""
import os
import secrets
import sys
from datetime import datetime, timedelta

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
os.environ['PRODUCT_LEGAL_ADDRESS'] = '1 Test Street\nOrlando, FL'
os.environ['PRODUCT_LEGAL_ENTITY'] = 'Test Entity LLC'
# The platform's keys -- a cleaning company's fallback. Must never be used here.
os.environ['TWILIO_ACCOUNT_SID'] = 'AC_platform_never_use'
os.environ['TWILIO_AUTH_TOKEN'] = 'platform_token_never_use'
os.environ['TWILIO_PHONE'] = '+15550000000'
for k in ('PRODUCT_TWILIO_ACCOUNT_SID', 'PRODUCT_TWILIO_AUTH_TOKEN', 'PRODUCT_TWILIO_PHONE'):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io

EMAILS = []
import notifications
notifications.send_email = lambda to, name, subject, html, **k: (
    EMAILS.append({'to': to, 'subject': subject, 'html': html, **k}), (True, 'stub'))[1]

TEXTS = []
import twilio.rest


class FakeTwilio:
    def __init__(self, sid, token):
        self.sid, self.token = sid, token
        self.messages = self

    def create(self, body, from_, to):
        TEXTS.append({'sid': self.sid, 'body': body, 'from': from_, 'to': to})
        return type('M', (), {'sid': 'SM' + secrets.token_hex(4)})()


twilio.rest.Client = FakeTwilio

from sqlalchemy import text

from app import create_app
from extensions import db
import control_plane
import lead_outreach
import provisioning

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


TAG = secrets.token_hex(4)
MANAGER = f'mgr-{TAG}@example.com'
HELPER = f'helper-{TAG}@example.com'
PW = 'a-real-console-password-1'
PRODUCT = 'http://akyehq.test'
A_EMAIL, B_EMAIL = f'ann-{TAG}@example.com', f'bob-{TAG}@example.com'
A_PHONE = f'(555) 010-{secrets.randbelow(9000) + 1000}'
C_PHONE = f'555-020-{secrets.randbelow(9000) + 1000}'

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    control_plane.add_console_user(engine, MANAGER, 'Manager', PW, role='manager')
    control_plane.add_console_user(engine, HELPER, 'Helper', PW, role='helper')
    db.session.remove()

c = app.test_client()
c.post('/console/login', data={'email': MANAGER, 'password': PW})
c.post('/console/leads/upload', data={'file': (io.BytesIO((
    'name,company,email,phone\n'
    f'Ann Able,Able Cleaning,{A_EMAIL},{A_PHONE}\n'
    f'Bob Baker,,{B_EMAIL},\n'
    f'Cara Cole,Cole Maids,,{C_PHONE}\n').encode()), 'leads.csv')},
    content_type='multipart/form-data')
with app.app_context():
    leads = {l['email'] or l['phone']: l for l in control_plane.all_leads(engine)
             if TAG in (l['email'] or '') or l['phone'] in (A_PHONE, C_PHONE)}
ann, bob, cara = leads[A_EMAIL], leads[B_EMAIL], leads[C_PHONE]


def lead(id_):
    with app.app_context():
        return control_plane.lead_by_id(engine, id_)


print('\n1. The page offers a compose box and a tick per lead')
page = c.get('/console/leads').get_data(as_text=True)
check('Message the ticked leads' in page and f'value="{ann["id"]}"' in page,
      'a compose box and a checkbox for each lead')
check('PRODUCT_TWILIO_ACCOUNT_SID' in page, 'and it says texting is not set up yet')

print('\n2. An email is filled in, can be unsubscribed from, and names who sent it')
EMAILS.clear()
r = c.post('/console/leads/send', data={
    'channel': 'email', 'lead_id': [ann['id'], bob['id'], cara['id']],
    'subject': 'Hi {first_name}', 'body': 'Hello {first_name} at {company}. {signup_link}'},
    follow_redirects=True)
body = r.get_data(as_text=True)
check(len(EMAILS) == 2 and {e['to'] for e in EMAILS} == {A_EMAIL, B_EMAIL},
      'the two leads with an email get one; the phone-only lead is skipped')
check('Skipped 1: no email address' in body, 'and the page says why one was skipped')
e = next(x for x in EMAILS if x['to'] == A_EMAIL)
check(e['subject'] == 'Hi Ann' and 'Hello Ann at Able Cleaning.' in e['html'],
      'placeholders are filled in')
check('{first_name}' not in next(x for x in EMAILS if x['to'] == B_EMAIL)['html']
      and 'your business' in next(x for x in EMAILS if x['to'] == B_EMAIL)['html'],
      'and a lead with no company still reads naturally')
check('/leads/unsubscribe/' in e['html'] and '1 Test Street' in e['html']
      and 'Test Entity LLC' in e['html'], 'it carries an unsubscribe link and the postal address')
check('www.akyehq.test/signup?' in e['html'],
      'the signup link is on the www host, not the bare domain that only answers "/"')
check(lead(ann['id'])['last_emailed_at'] is not None, 'the lead is stamped as emailed')
with app.app_context():
    hist = control_plane.lead_messages(engine)
check(any(m['lead_id'] == ann['id'] and m['channel'] == 'email' and m['ok'] for m in hist),
      'and it is in the outreach history')

print('\n3. A group send does not email the same person twice in a week')
EMAILS.clear()
r = c.post('/console/leads/send', data={'channel': 'email', 'lead_id': [ann['id'], bob['id']],
                                        'subject': 'Again', 'body': 'Again'}, follow_redirects=True)
check(EMAILS == [] and 'emailed in the last 7 days' in r.get_data(as_text=True),
      'both are skipped, and the page says so')

print('\n4. One click unsubscribes, and that address is never emailed again')
token = e['html'].split('/leads/unsubscribe/')[1].split('"')[0]
r = c.get(f'/leads/unsubscribe/{token}', base_url=PRODUCT)
check(r.status_code == 200 and "unsubscribed" in r.get_data(as_text=True), 'the link works')
check(lead(ann['id'])['unsubscribed_at'] is not None, 'the lead is marked unsubscribed')
check(c.get('/leads/unsubscribe/not-a-token', base_url=PRODUCT).status_code == 404,
      'a made-up token is refused')
check(c.get(f'/leads/unsubscribe/{token}', base_url='http://acme.akyehq.test').status_code == 404,
      'and the link only works on the product site')
EMAILS.clear()
r = c.post('/console/leads/send', data={'channel': 'email', 'lead_id': [ann['id']],
                                        'subject': 's', 'body': 'b'}, follow_redirects=True)
check(EMAILS == [] and 'unsubscribed' in r.get_data(as_text=True), 'a direct send is refused')
c.post(f'/console/leads/{ann["id"]}/invite')
check(EMAILS == [], 'and so is the standard invite')

print('\n5. Texts never use a cleaning company\'s number')
r = c.post('/console/leads/send', data={'channel': 'sms', 'lead_id': [cara['id']],
                                        'body': 'Hi {first_name}'}, follow_redirects=True)
check(TEXTS == [], 'with only the platform TWILIO_* keys set, nothing is sent')
os.environ.update(PRODUCT_TWILIO_ACCOUNT_SID='AC_product', PRODUCT_TWILIO_AUTH_TOKEN='product_token',
                  PRODUCT_TWILIO_PHONE='+15557770000')

print('\n6. Texts only go out 11am-8pm Eastern')
check(lead_outreach.quiet_hours(datetime(2026, 9, 28, 14, 0)) is not None, '10am Eastern: not yet')
check(lead_outreach.quiet_hours(datetime(2026, 9, 28, 16, 0)) is None, 'noon Eastern: fine')
check(lead_outreach.quiet_hours(datetime(2026, 9, 29, 1, 0)) is not None, '9pm Eastern: too late')
real_quiet = lead_outreach.quiet_hours
lead_outreach.quiet_hours = lambda now_utc=None: 'closed for the test'
r = c.post('/console/leads/send', data={'channel': 'sms', 'lead_id': [cara['id']], 'body': 'Hi'},
           follow_redirects=True)
check(TEXTS == [] and 'closed for the test' in r.get_data(as_text=True),
      'outside the window nothing is sent, and the page says why')
lead_outreach.quiet_hours = lambda now_utc=None: None

print('\n7. A text says who it is from and how to stop, from the product number')
r = c.post('/console/leads/send', data={'channel': 'sms', 'lead_id': [cara['id'], bob['id']],
                                        'body': 'Hi {first_name}, try us'}, follow_redirects=True)
check(len(TEXTS) == 1, 'the lead with a phone gets one; the one without is skipped')
t = TEXTS[0]
check(t['sid'] == 'AC_product' and t['from'] == '+15557770000', 'sent on the product account and number')
check(t['to'].startswith('+1') and t['to'][-4:] == C_PHONE[-4:], 'to the lead\'s number, in E.164')
check('Hi Cara, try us' in t['body'] and t['body'].startswith('Akye') and 'Reply STOP' in t['body'],
      'filled in, and names the sender and how to stop')
check(lead(cara['id'])['last_texted_at'] is not None, 'the lead is stamped as texted')

print('\n8. STOP and START come back through a signed webhook')
from twilio.request_validator import RequestValidator
url = f'{PRODUCT}/leads/sms-reply'


def reply(body, sign=True):
    form = {'Body': body, 'From': '+1' + ''.join(ch for ch in C_PHONE if ch.isdigit())}
    sig = RequestValidator('product_token').compute_signature(url, form) if sign else ''
    return c.post('/leads/sms-reply', base_url=PRODUCT, data=form,
                  headers={'X-Twilio-Signature': sig} if sign else {})


check(reply('STOP', sign=False).status_code == 403, 'an unsigned request is refused')
check(reply('STOP').status_code == 200 and lead(cara['id'])['sms_opted_out_at'] is not None,
      'a signed STOP marks the lead')
TEXTS.clear()
r = c.post('/console/leads/send', data={'channel': 'sms', 'lead_id': [cara['id']], 'body': 'Hi'},
           follow_redirects=True)
check(TEXTS == [] and 'replied STOP' in r.get_data(as_text=True), 'and nothing is texted to them again')
check(reply('START').status_code == 200 and lead(cara['id'])['sms_opted_out_at'] is None,
      'START clears it')
lead_outreach.quiet_hours = real_quiet

print('\n9. A helper can read the list but cannot send')
h = app.test_client()
h.post('/console/login', data={'email': HELPER, 'password': PW})
page = h.get('/console/leads').get_data(as_text=True)
check('Message the ticked leads' not in page, 'no compose box for a helper')
EMAILS.clear()
h.post('/console/leads/send', data={'channel': 'email', 'lead_id': [bob['id']],
                                    'subject': 's', 'body': 'b'})
check(EMAILS == [], 'and a direct POST sends nothing')

print('\n10. Every send is on the console record')
with app.app_context():
    acts = {x['action'] for x in control_plane.console_log_all(engine) if x['actor'] == MANAGER}
check({'sent emails', 'sent texts'} <= acts, f'emails and texts both logged ({sorted(acts)})')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Console outreach: filled in, unsubscribable, STOP-respecting, from the product only.')
