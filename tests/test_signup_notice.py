"""Somebody signing up is the most important thing that happens here.

It used to happen in silence. A row appeared in a table nobody was watching,
and that was all. Somebody could sign up at eleven at night, hit something
broken in their first ten minutes, and be gone before anyone knew they had
arrived — which during a beta is the whole thing you are paying attention for.

So one email, to whoever runs the product, the moment a company is created.

It is also the honest end-to-end test of the product's email: the same key,
the same from-address, the same code path as a trial reminder. If this
arrives, they all will — which is worth more than a command that proves a
laptop can send.

The rule that matters most here is what it must not do. By the time this runs,
a company exists: a schema, a database, a password somebody chose. Failing to
send a notification cannot be allowed to undo any of that, or to show a new
customer an error about our email when nothing of theirs has gone wrong.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/sn.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
os.environ['BASE_DOMAIN'] = 'akyehq.com'
os.environ['PRODUCT_RESEND_API_KEY'] = 're_product_key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications

SENT = []
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to_email, to_name, subject, html, **k: (
    SENT.append({'to': to_email, 'subject': subject, 'html': html, **k}),
    (True, 'stub'))[1]

import blueprints.signup as signup
import product

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


FORM = {'business': 'Brightside Cleaning', 'slug': 'brightside',
        'name': 'Dana Whitfield', 'email': 'dana@brightside.example'}


print('\n1. A signup is reported')
SENT.clear()
signup._tell_us('brightside', FORM, 'akyehq.com')
check(len(SENT) == 1, f'one email goes out ({len(SENT)})')

if SENT:
    m = SENT[0]
    check(m['to'] == 'support@akyehq.com', f"to support ({m['to']})")
    check('Brightside Cleaning' in m['subject'],
          'naming the company in the subject, so the inbox is scannable')
    for bit in ('Dana Whitfield', 'dana@brightside.example'):
        check(bit in m['html'], f'and {bit!r} in the body')
    check('https://brightside.akyehq.com' in m['html'],
          'with a link straight into their CRM')


print('\n2. It goes out as the product, on the product\'s key')
# Same reasoning as every other product email: the identity and the key must
# not be borrowed from whichever company the process last looked at.
if SENT:
    m = SENT[0]
    check(m.get('from_name') == 'Akye', f"from Akye ({m.get('from_name')})")
    check(m.get('api_key') == 're_product_key', 'on our own key')
    check(m.get('reply_to') == 'dana@brightside.example',
          f"and a reply goes to them ({m.get('reply_to')}) — the useful thing "
          f"to do with a new signup is answer it")


print('\n3. A failed send never costs somebody their account')
# By now the company exists: a schema, a database, a password they chose.
# Nothing about our email may undo that or put an error in front of them.
_saved = notifications.send_email
notifications.send_email = lambda *a, **k: (_ for _ in ()).throw(
    RuntimeError('mail is down'))
try:
    signup._tell_us('brightside', FORM, 'akyehq.com')
    check(True, 'a total mail failure does not raise')
except Exception as e:
    check(False, f'it raised: {type(e).__name__}: {e}')
finally:
    notifications.send_email = _saved


print('\n4. A single-business install never sends this')
# There is no product to notify, and no support address to notify it at.
os.environ['BASE_DOMAIN'] = ''
SENT.clear()
signup._tell_us('brightside', FORM, 'localhost:5000')
check(len(SENT) == 0, 'nothing is sent where there is no product')
os.environ['BASE_DOMAIN'] = 'akyehq.com'


print('\n5. It is wired into the signup route, not just written')
# The failure this guards against is a helper that exists, is tested, and is
# called from nowhere.
import inspect
src = inspect.getsource(signup.signup)
check('_tell_us(' in src, 'signup() calls it')
check(src.index('_create_everything') < src.index('_tell_us('),
      'after the company is actually created, not before')
check(src.index('_tell_us(') < src.index('return redirect('),
      'and before the customer is sent on their way')


if failures:
    print(f'\n\n❌ {len(failures)} signup-notice check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Nobody arrives unnoticed.\n')
