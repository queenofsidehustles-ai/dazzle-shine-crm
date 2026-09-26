"""Our email is ours. Theirs is theirs.

The product sends two kinds of email that a cleaning company never does: a
trial reminder, and the alert that says a customer's CRM just broke. Both were
going out through `notifications.send_email` with no key of their own — and
that function reads the key from `integrations`, which reads the settings of
whichever company the current request belongs to.

So a crash inside a customer's CRM would have emailed us about it **through
that customer's Resend account**. Billed to them. Sitting in their sending
logs, addressed to a company they have never heard of. And failing outright
for any customer who had not connected an email account yet — which is most of
them on the day they sign up, and the day they sign up is when a crash is most
likely.

Nothing about that is visible from either end. The customer sees an odd line
in a log they do not read. We see no alert, and no alert looks exactly like no
crash.

The rules here:

  * product email goes out on the product's key, from the product's address,
    signed with the product's name — never borrowed from whichever tenant the
    process happened to be looking at
  * a cleaning company's own mail is untouched by all of this, because that
    path is how they reach their actual customers
  * and when the product cannot send at all, it says so somewhere a person
    will see, rather than failing quietly. An email nobody notices missing is
    the whole failure mode.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/pm.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications

# Capture what would have gone to the provider, including the key it would
# have gone out on — which is the whole point of this file.
CALLS = []
_real_post = None


def _fake_post(url, headers=None, json=None, timeout=None, **kw):
    CALLS.append({'auth': (headers or {}).get('Authorization', ''),
                  'from': (json or {}).get('from', ''),
                  'to': (json or {}).get('to', []),
                  'subject': (json or {}).get('subject', '')})

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {'id': 'test-message-id'}
    return R


notifications.http_requests.post = _fake_post
notifications.send_sms = lambda *a, **k: (True, 'stub')

import integrations
import product

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


CUSTOMER_KEY = 're_the_customers_own_key'
OUR_KEY = 're_the_products_own_key'

# What a cleaning company has saved in its own Settings → Connections.
integrations.resend_api_key = lambda: CUSTOMER_KEY


print('\n1. The product knows its own identity, separately from any customer')
os.environ['BASE_DOMAIN'] = 'akyehq.com'
os.environ['PRODUCT_RESEND_API_KEY'] = OUR_KEY
os.environ.pop('PRODUCT_FROM_EMAIL', None)
os.environ.pop('PRODUCT_SUPPORT_EMAIL', None)

check(product.support_email() == 'support@akyehq.com',
      f'support address ({product.support_email()})')
check(product.from_email() == 'support@akyehq.com',
      f'from address, defaulting to it ({product.from_email()})')
check(product.resend_api_key() == OUR_KEY, 'and its own key')
check(product.resend_api_key() != CUSTOMER_KEY,
      'which is not the key the customer saved')


print('\n2. A trial reminder goes out on our key, not the customer\'s')
import trial_nudges as tn
from datetime import datetime, timedelta

NOW = datetime.utcnow()
org = {'slug': 'brightside', 'name': 'Brightside Cleaning',
       'owner_email': 'dana@brightside.example', 'status': 'active',
       'created_at': NOW - timedelta(days=8), 'plan': 'scale',
       'subscription_status': 'trialing',
       'trial_ends_at': NOW + timedelta(days=22),
       'activated_at': None, 'nudges_sent': None}

CALLS.clear()
ok, detail = tn._send(org, 'start_7')
check(ok, f'it sends ({detail})')
check(len(CALLS) == 1, 'once')
if CALLS:
    c = CALLS[0]
    check(OUR_KEY in c['auth'], 'on the product\'s key')
    check(CUSTOMER_KEY not in c['auth'],
          'and never on the key the cleaning company saved')
    check('support@akyehq.com' in c['from'], f"from us ({c['from']})")
    check('Akye' in c['from'], 'signed as the product')


print('\n3. So does a crash alert')
# The one that matters most. This fires from inside a customer's request, so
# it is the most likely of the two to pick up their key by accident.
import errors
from app import create_app
from extensions import db
from models import BusinessSetting

app = create_app()


@app.route('/_crash_mail')
def _crash_mail():
    raise RuntimeError('for the mail test')


with app.app_context():
    db.create_all()
    BusinessSetting.set('email', 'dana@brightside.example')
    BusinessSetting.set('business_name', 'Brightside Cleaning')
    db.session.commit()

CALLS.clear()
app.test_client().get('/_crash_mail')
ours = [c for c in CALLS if 'akyehq.com' in (c['to'] or [''])[0]]
theirs = [c for c in CALLS if 'brightside.example' in (c['to'] or [''])[0]]
check(len(ours) == 1, f'the product is told ({len(ours)})')
check(len(theirs) == 1, f'and so is the owner ({len(theirs)})')
if ours:
    check(OUR_KEY in ours[0]['auth'],
          'our copy goes out on our key')
    check(CUSTOMER_KEY not in ours[0]['auth'],
          'and is not billed to the customer whose CRM broke')
if theirs:
    check(CUSTOMER_KEY in theirs[0]['auth'],
          "the owner's own copy still goes out on her key, as it always did")


print('\n4. A cleaning company\'s own mail is untouched')
# This is the path that reaches their actual customers. Nothing above may
# have changed it.
CALLS.clear()
notifications.send_email('client@example.com', 'A Client',
                         'Your booking is confirmed', '<p>See you Tuesday.</p>')
check(len(CALLS) == 1, 'a normal email still sends')
if CALLS:
    check(CUSTOMER_KEY in CALLS[0]['auth'],
          'on the company\'s own key, exactly as before')


print('\n5. When it is not set up, it says so')
# The failure this is really guarding against is silence. Nobody notices an
# email that never arrived, and the crash alert is the one thing whose entire
# job is to be noticed.
os.environ.pop('PRODUCT_RESEND_API_KEY', None)
saved_env = os.environ.pop('RESEND_API_KEY', None)
st = product.mail_status()
check(st['applies'], 'on the hosted product, product mail applies')
check(st['problem'] and 'key' in st['problem'].lower(),
      f'a missing key is reported: {st["problem"]}')
check(not st['key'], 'and the status says plainly that there is no key')

# And it reaches a screen she can open on a phone.
v = app.test_client().get('/version').get_json()
check(v.get('product_mail') == 'not configured',
      f"/version says so ({v.get('product_mail')})")
check('key' in (v.get('product_mail_problem') or '').lower(),
      'and explains what is missing')
# A missing database is more urgent and takes the headline. That must not be
# a way for the mail fault to disappear — setting a deployment up is exactly
# when both are broken at once.
check(v.get('product_mail_problem') and v.get('problem'),
      'two faults at once are both reported, not just the louder one')

os.environ['PRODUCT_RESEND_API_KEY'] = OUR_KEY
check(product.mail_status()['problem'] is None,
      'once the key is set, no problem is reported')
v = app.test_client().get('/version').get_json()
check(v.get('product_mail') == 'ok', f"and /version agrees ({v.get('product_mail')})")


print('\n6. A support address behind a forward is a fine answer')
# She has a Gmail inbox and a domain that will forward to it. Those are two
# different questions: where a person writes to us, and what address the
# provider will let us send FROM. Conflating them is why this is two settings.
os.environ['PRODUCT_SUPPORT_EMAIL'] = 'monica@example-gmail.test'
os.environ['PRODUCT_FROM_EMAIL'] = 'alerts@akyehq.com'
check(product.support_email() == 'monica@example-gmail.test',
      'support can be any inbox she actually reads')
check(product.from_email() == 'alerts@akyehq.com',
      'while the from-address stays on the verified domain')
check(product.mail_status()['problem'] is None, 'and that is a valid setup')

CALLS.clear()
tn._send(org, 'start_7')
if CALLS:
    check('alerts@akyehq.com' in CALLS[0]['from'],
          'mail is sent from the verified domain')


print('\n7. A single-business install has none of this')
os.environ['BASE_DOMAIN'] = ''
st = product.mail_status()
check(not st['applies'], 'product mail does not apply')
check(st['problem'] is None, 'and nothing is reported as broken')
v = app.test_client().get('/version').get_json()
check('product_mail' not in v, '/version does not mention it at all')


if failures:
    print(f'\n\n❌ {len(failures)} product-mail check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Our email is ours. Theirs is theirs.\n')
