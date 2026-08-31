"""Somewhere to raise your hand while the door is shut.

The first ten companies are onboarded by hand, so signups stay closed for
weeks — and the site is live and indexed the whole time. Before this, every
"Start free" button simply vanished when `SIGNUPS_OPEN=0`, which left a
visitor who had read the whole page and decided they wanted it with exactly
one option: spotting an email address in the footer. `/signup` returned 404.

Every one of those people was lost, and they are the most valuable visitors
the site will ever get: they arrived, they read it, and they wanted it.

The rules this holds:

  * shut door, different call to action — never no call to action
  * a form that loses somebody is worse than no form, so a lead is written
    down AND emailed, and a failed write does not sink the request
  * when the door opens, the page gets out of the way
  * nothing about this appears on a cleaning company's own CRM
"""
import os, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/ea.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['SIGNUPS_OPEN'] = '0'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (True, 'stub')
# The stub takes the SAME arguments as the real function. It used to take
# three, which is why nobody noticed the caller was passing three to a
# function that needs four: the stub accepted what production rejected, and
# the `except Exception: pass` around the call swallowed the difference.
# A stub that is easier to call than the real thing tests the stub.
notifications.send_email = lambda to_email, to_name, subject, html, **k: (
    SENT.append({'to': to_email, 'subject': subject, 'body': html}), (True, 'stub'))[1]

from app import create_app

app = create_app()
c = app.test_client()
PRODUCT = {'Host': 'akye.test'}
TENANT = {'Host': 'acme.akye.test'}

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


print('\n1. A shut door still has a way through it')
home = c.get('/', headers=PRODUCT).data.decode('utf8', 'replace')
check('/early-access' in home, 'the homepage offers early access')
check('href="/signup"' not in home,
      'and does not dangle a signup link that would 404')

pricing = c.get('/pricing', headers=PRODUCT).data.decode('utf8', 'replace')
check(pricing.count('/early-access') >= 3,
      f'every plan card has something to press ({pricing.count("/early-access")})')

# The most valuable position on the page.
check('Get early access' in home, 'the header button says what it does')


print('\n2. The form')
r = c.get('/early-access', headers=PRODUCT)
check(r.status_code == 200, f'it loads ({r.status_code})')
page = r.data.decode('utf8', 'replace')
for field in ('name', 'company', 'email', 'phone', 'cleaners', 'note'):
    check(f'name="{field}"' in page, f'asks for {field}')


print('\n3. It refuses what it cannot act on')
# Only two things are required. Every extra required field is somebody who
# gives up instead.
r = c.post('/early-access', headers=PRODUCT, data={'name': '', 'email': ''})
body = r.data.decode('utf8', 'replace')
check('Please tell us your name' in body, 'a missing name is refused')
check('We need an email' in body, 'so is a missing email')
r = c.post('/early-access', headers=PRODUCT,
           data={'name': 'Dana', 'email': 'not-an-email'})
check('We need an email' in r.data.decode('utf8', 'replace'),
      'and something that is not an email at all')

r = c.post('/early-access', headers=PRODUCT,
           data={'name': 'Dana Whitfield', 'email': 'dana@example.com'})
check('Thank you' in r.data.decode('utf8', 'replace'),
      'a name and an email alone are enough to get through')


print('\n4. Nobody is lost if the write fails')
# The control plane is a Postgres thing; on SQLite it is not there at all.
# That must not cost us the lead, because a person filling in a form is not
# the one who should pay for our storage failing.
SENT.clear()
r = c.post('/early-access', headers=PRODUCT, data={
    'name': 'Marcus Feld', 'company': 'Feld & Daughters Cleaning',
    'email': 'marcus@felds.example', 'phone': '407 555 0188',
    'cleaners': '6', 'note': 'Chasing people for timesheets every Friday.'})
check('Thank you' in r.data.decode('utf8', 'replace'),
      'the request still succeeds when the database will not take it')
check(len(SENT) == 1, f'and it is emailed instead ({len(SENT)} sent)')
if SENT:
    mail = SENT[0]
    check('support@' in (mail['to'] or ''), f'to support ({mail["to"]})')
    check('Feld & Daughters' in mail['subject'],
          'with the company in the subject, so it is findable later')
    for bit in ('Marcus Feld', 'marcus@felds.example', '407 555 0188',
                'timesheets'):
        check(bit in mail['body'], f'and {bit!r} in the body')
    check('NO — write failed' in mail['body'],
          'and it says plainly that the write failed, rather than implying '
          'the lead is safely filed somewhere it is not')


print('\n5. The confirmation says what happens next')
# "Thanks, we'll be in touch" with no timeframe is how a form becomes a black
# hole that somebody stops trusting a week later.
done = c.post('/early-access', headers=PRODUCT,
              data={'name': 'Dana', 'email': 'd@example.com'}
              ).data.decode('utf8', 'replace')
check('couple of days' in done, 'it gives a timeframe')
check('load your customers' in done or 'we load your' in done.lower(),
      'and says what onboarding actually involves')


print('\n6. When the door opens, this page gets out of the way')
import blueprints.signup as _signup
_orig = _signup.signups_open
try:
    _signup.signups_open = lambda: True
    r = c.get('/early-access', headers=PRODUCT)
    check(r.status_code in (301, 302), f'it redirects ({r.status_code})')
    check('/signup' in (r.headers.get('Location') or ''),
          f'to signup ({r.headers.get("Location")})')
finally:
    _signup.signups_open = _orig


print('\n7. None of it appears on a cleaning company\'s CRM')
# This is our funnel, not theirs. A customer's own CRM must never show it.
r = c.get('/early-access', headers=TENANT)
check(r.status_code == 404, f'/early-access is 404 on a company subdomain ({r.status_code})')


if failures:
    print(f'\n\n❌ {len(failures)} early-access check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Nobody who wants it is left with nowhere to say so.\n')
