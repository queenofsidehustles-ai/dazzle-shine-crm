"""Console → New Leads: marking leads "do not text".

What would make this dangerous:
  * a number checked against the Do Not Call list and uploaded "do not text"
    getting a text anyway -- by a group send, a single send, or because it was
    already on the list from an earlier upload;
  * the person's own START reply undoing a mark somebody here made for a
    different reason;
  * the mark stopping email as well, when email is what the list is for;
  * a helper changing it.

Against a real disposable Postgres, like the rest of the console suite.
"""
import io
import os
import secrets
import sys

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
os.environ['PRODUCT_LEGAL_ADDRESS'] = '1 Test Street\nOrlando, FL 32801'
os.environ['PRODUCT_RESEND_API_KEY'] = 're_test_not_real'
os.environ.update(PRODUCT_TWILIO_ACCOUNT_SID='AC_product', PRODUCT_TWILIO_AUTH_TOKEN='product_token',
                  PRODUCT_TWILIO_PHONE='+15557770000')
os.environ.pop('CONSOLE_REQUIRE_2FA', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EMAILS = []
import notifications
notifications.send_email = lambda to, name, subject, html, **k: (
    EMAILS.append(to), (True, 'stub'))[1]

TEXTS = []
import twilio.rest


class FakeTwilio:
    def __init__(self, sid, token):
        self.messages = self

    def create(self, body, from_, to):
        TEXTS.append(to)
        return type('M', (), {'sid': 'SM' + secrets.token_hex(4)})()


twilio.rest.Client = FakeTwilio

from app import create_app
from extensions import db
import control_plane
import lead_outreach
import provisioning

lead_outreach.quiet_hours = lambda now_utc=None: None
app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


TAG = secrets.token_hex(4)
MANAGER, HELPER = f'mgr-{TAG}@example.com', f'helper-{TAG}@example.com'
PW = 'a-real-console-password-1'


def phone():
    return f'555-3{secrets.randbelow(90) + 10}-{secrets.randbelow(9000) + 1000}'


with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    control_plane.add_console_user(engine, MANAGER, 'Manager', PW, role='manager')
    control_plane.add_console_user(engine, HELPER, 'Helper', PW, role='helper')
    db.session.remove()

c = app.test_client()
c.post('/console/login', data={'email': MANAGER, 'password': PW})


def upload(client, csv_text, whole_file=False):
    data = {'file': (io.BytesIO(csv_text.encode()), 'leads.csv')}
    if whole_file:
        data['do_not_text'] = '1'
    return client.post('/console/leads/upload', data=data,
                       content_type='multipart/form-data', follow_redirects=True)


def by_email(email):
    with app.app_context():
        return next(l for l in control_plane.all_leads(engine) if l['email'] == email)


def send(channel, *leads):
    return c.post('/console/leads/send', data={
        'channel': channel, 'lead_id': [l['id'] for l in leads],
        'subject': 'Hi', 'body': 'Hi {first_name}'}, follow_redirects=True)


print('\n1. The upload form offers the box, and a ticked box marks the whole file')
page = c.get('/console/leads').get_data(as_text=True)
check('name="do_not_text"' in page and 'Do not text anyone in this file' in page,
      'the upload form has a "do not text" box')
A, B = f'ann-{TAG}@example.com', f'bob-{TAG}@example.com'
r = upload(c, f'name,email,phone\nAnn,{A},{phone()}\nBob,{B},{phone()}\n', whole_file=True)
body = r.get_data(as_text=True)
check('Added 2 leads' in body and 'Marked 2 as do not text' in body,
      'both are added and the page says they are marked')
ann, bob = by_email(A), by_email(B)
check(ann['do_not_text_at'] and bob['do_not_text_at'], 'both rows carry the mark')

print('\n2. Marked leads are emailed but never texted')
TEXTS.clear()
r = send('sms', ann, bob)
check(TEXTS == [] and 'marked do not text' in r.get_data(as_text=True),
      'a group text skips them, and says why')
r = send('sms', ann)
check(TEXTS == [], 'and so does a text to just one of them')
EMAILS.clear()
send('email', ann, bob)
check(sorted(EMAILS) == sorted([A, B]), 'email still reaches them')
page = c.get('/console/leads').get_data(as_text=True)
check('do not text</span>' in page and 'Allow texts' in page,
      'the list shows the mark and a button to lift it')

print('\n3. A column marks single rows')
C, D, E = (f'{n}-{TAG}@example.com' for n in ('cara', 'dan', 'eve'))
r = upload(c, f'Name,Email,Phone,DNC\nCara,{C},{phone()},yes\nDan,{D},{phone()},no\n'
              f'Eve,{E},{phone()},\n')
check('Added 3 leads' in r.get_data(as_text=True) and 'Marked 1 as do not text' in r.get_data(as_text=True),
      'three added, one marked')
check(by_email(C)['do_not_text_at'] and not by_email(D)['do_not_text_at']
      and not by_email(E)['do_not_text_at'], '"yes" marks the row; "no" and blank do not')

print('\n4. Re-uploading somebody already on the list still marks them')
r = upload(c, f'name,email\nDan again,{D.upper()}\n', whole_file=True)
body = r.get_data(as_text=True)
check('Added 0 leads' in body and 'already on the list' in body,
      'no second row, and the page says why')
check(by_email(D)['do_not_text_at'], 'but the existing row is now marked do not text')

print('\n5. The mark is set and lifted per lead, and START does not lift it')
eve = by_email(E)
c.post(f'/console/leads/{eve["id"]}/do-not-text', data={'on': '1'})
check(by_email(E)['do_not_text_at'], '"Do not text" marks one lead')
with app.app_context():
    control_plane.set_leads_sms_opt_out(engine, eve['phone'], opted_out=False)
check(by_email(E)['do_not_text_at'], 'a START reply from that number does not undo it')
c.post(f'/console/leads/{eve["id"]}/do-not-text', data={'on': '0'})
check(not by_email(E)['do_not_text_at'], '"Allow texts" lifts it')
TEXTS.clear()
send('sms', by_email(E))
check(len(TEXTS) == 1, 'and the lead can be texted again')

print('\n6. A helper cannot change it')
h = app.test_client()
h.post('/console/login', data={'email': HELPER, 'password': PW})
r = h.post(f'/console/leads/{eve["id"]}/do-not-text', data={'on': '1'})
check(r.status_code == 302 and not by_email(E)['do_not_text_at'], 'the request is refused')
r = upload(h, f'name,email\nZed,zed-{TAG}@example.com\n', whole_file=True)
with app.app_context():
    check(not any(l['email'] == f'zed-{TAG}@example.com' for l in control_plane.all_leads(engine)),
          'and so is an upload')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Do-not-text leads are emailed, never texted, and only the console lifts the mark.')
