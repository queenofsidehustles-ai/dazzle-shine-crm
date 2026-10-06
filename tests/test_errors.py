"""Error reporting: does a broken page tell anyone, and does it shut up
afterwards.

Two failure modes, opposite to each other. A reporter that stays quiet is
useless. A reporter that emails on every one of four hundred hits gets filtered
into a folder and is then also useless. Most of this is about the second.
"""
import os, sys, tempfile
from datetime import datetime, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/err.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications

SENT = []
MAIL = []
notifications.send_sms = lambda *a, **k: (True, 'stub')
# Four arguments, the same as the real function. This stub took three, and so
# did the caller in errors.py — so "exactly one email went out" passed for
# months while the alerter had never sent one in its life. A stub that is
# easier to call than the real thing tests the stub. See test_email_callers.py.
notifications.send_email = lambda to_email, to_name, subject, html, **k: (
    SENT.append((to_email, subject)),
    MAIL.append({'to': to_email, 'subject': subject, 'html': html, **k}),
    (True, 'stub'))[2]

from app import create_app
from extensions import db
from models import ErrorLog, BusinessSetting
import errors

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


# Routes that break in specific ways, added for the test only.
@app.route('/_boom')
def _boom():
    raise ValueError('the thing went wrong')


@app.route('/_boom2')
def _boom2():
    raise KeyError('a different thing')


# One route per scenario below. The fingerprint is (endpoint, exception), so
# reusing a path would land inside the 24-hour cooldown and send nothing —
# the test would then pass by measuring silence.
for _name in ('product', 'noowner', 'single', 'mailfail'):
    def _mk(n):
        def _view():
            raise RuntimeError(f'broke in {n}')
        _view.__name__ = f'_boom_{n}'
        return _view
    app.route(f'/_boom_{_name}')(_mk(_name))


with app.app_context():
    BusinessSetting.set('email', 'owner@example.com')
    BusinessSetting.set('business_name', 'Test Cleaning')
    db.session.commit()

c = app.test_client()

print('\n1. A broken page is recorded, and the visitor is not shown the wreckage')
r = c.get('/_boom')
check(r.status_code == 500, 'the request fails with a 500')
check(b'ValueError' not in r.data and b'Traceback' not in r.data,
      'no exception name or stack trace reaches the browser')
check(b'went wrong on our end' in r.data, 'a plain apology is shown instead')
with app.app_context():
    row = ErrorLog.query.filter_by(kind='ValueError').first()
    check(row is not None, 'the fault is written down')
    check(row.path == '/_boom' and row.method == 'GET', 'with where it happened')
    check('the thing went wrong' in (row.message or ''), 'and what went wrong')
    check('ValueError' in (row.traceback or ''), 'and a traceback for the developer')

print('\n2. The owner is emailed the first time')
check(len(SENT) == 1, 'exactly one email went out')
check('owner@example.com' == SENT[0][0], 'to the owner')
check('Test Cleaning' in SENT[0][1] and 'ValueError' in SENT[0][1],
      'naming the business and the fault')

print('\n3. The same fault forty more times is one row and no more email')
for _ in range(40):
    c.get('/_boom')
with app.app_context():
    rows = ErrorLog.query.filter_by(kind='ValueError').all()
    check(len(rows) == 1, '41 crashes are still one row')
    check(rows[0].count == 41, 'counted 41 times')
check(len(SENT) == 1, 'and still exactly one email — no alert storm')

print('\n4. A different fault is a different row, and does get an email')
c.get('/_boom2')
with app.app_context():
    check(ErrorLog.query.count() == 2, 'a second distinct fault is its own row')
check(len(SENT) == 2, 'and is emailed, because it is genuinely new')

print('\n5. A fault still happening tomorrow gets one reminder, not a flood')
with app.app_context():
    row = ErrorLog.query.filter_by(kind='ValueError').first()
    row.alerted_at = datetime.utcnow() - timedelta(hours=25)
    db.session.commit()
c.get('/_boom')
check(len(SENT) == 3, 'after 24 hours a persisting fault is raised once more')
c.get('/_boom')
c.get('/_boom')
check(len(SENT) == 3, 'and then goes quiet again')

print('\n6. Bad URLs are not incidents')
before = len(SENT)
with app.app_context():
    n = ErrorLog.query.count()
c.get('/this-page-does-not-exist')
c.post('/_boom')                      # 405, wrong method
with app.app_context():
    check(ErrorLog.query.count() == n, 'a 404 and a 405 are not recorded as faults')
check(len(SENT) == before, 'and nobody is emailed about them')

print('\n7. Nothing sensitive is kept')
c.get('/_boom')
with app.app_context():
    row = ErrorLog.query.filter_by(kind='ValueError').first()
    blob = f'{row.message}{row.path}{row.traceback}'.lower()
    for secret in ('password', 'cookie', 'session=', 'secret_key', 'sk_live'):
        check(secret not in blob, f'no {secret} in the stored report')

print('\n8. Ticking a fault off works, and is undone if it comes back')
with app.app_context():
    row = ErrorLog.query.filter_by(kind='ValueError').first()
    row.resolved = True
    db.session.commit()
    rid = row.id
c.get('/_boom')
with app.app_context():
    check(ErrorLog.query.get(rid).resolved is False,
          'a fault that happens again reopens itself')

print('\n9. Two crashes on the same line group; the same line via another page does not')
with app.app_context():
    try:
        raise ValueError('x')
    except ValueError as e:
        a = errors.fingerprint('bookings.index', e)
        b = errors.fingerprint('bookings.index', e)
        c2 = errors.fingerprint('leads.index', e)
    check(a == b, 'the same fault on the same page fingerprints the same')
    check(a != c2, 'the same fault on a different page is a different fingerprint')

print('\n10. Reporting a fault can never cause one')
with app.app_context():
    import models as m
    real = m.ErrorLog
    class Broken:
        @staticmethod
        def record(*a, **k):
            raise RuntimeError('database unreachable')
    m.ErrorLog = Broken
    try:
        r = c.get('/_boom')
        check(r.status_code == 500,
              'a crash while recording a crash still returns a clean 500')
    finally:
        m.ErrorLog = real

print('\n11. On the hosted product, we are told as well as the customer')
# A fault in one company's CRM is usually a fault in everybody's. Without this
# copy the only person who knows the software is broken is the customer it
# broke for, and the most likely thing they do is say nothing and stop using
# it. During a beta that is the entire signal.
import product as _product
import tenancy as _tenancy

os.environ['BASE_DOMAIN'] = 'akyehq.com'
_tenancy._current.set('tenant_brightside')
with app.app_context():
    BusinessSetting.set('email', 'dana@brightside.example')
    db.session.commit()

MAIL.clear(); SENT.clear()
c.get('/_boom_product')
check(len(MAIL) == 2, f'two emails go out, not one ({len(MAIL)})')

owner = [m for m in MAIL if 'brightside.example' in m['to']]
ours = [m for m in MAIL if 'akyehq.com' in m['to']]
check(len(owner) == 1, 'one to the owner of the CRM it happened in')
check(len(ours) == 1, 'one to whoever runs the product')

if ours:
    o = ours[0]
    check('support@akyehq.com' == o['to'], f"to support ({o['to']})")
    check('Test Cleaning' in o['subject'],
          'naming which company it happened to — the whole point of the copy')
    check('/_boom_product' in o['subject'] or '/_boom_product' in o['html'],
          'and which page')
    check('Traceback' in o['html'] and 'RuntimeError' in o['html'],
          'with a traceback, because we are the ones who have to fix it')
    check(o.get('from_name') == 'Akye',
          f"sent as the product ({o.get('from_name')})")
    check(o.get('reply_to') == 'support@akyehq.com',
          'and a reply goes somewhere a person reads')

if owner:
    check('Traceback' not in owner[0]['html'],
          'the owner is not sent a stack trace — it is not their job')
    check('Settings' in owner[0]['html'],
          'she is pointed at her own Errors page instead')


print('\n11b. The copy says which company, by address as well as by name')
# Two customers can call themselves Sparkle Cleaning. The subdomain cannot,
# and it is also the thing you click to go and look. Checked directly because
# a test-client request has no real host to resolve a company from — in
# production `_alert` runs inside the request, where it has been set.
_tenancy._current.set('tenant_brightside')
slug, url = errors._which_company()
check(slug == 'brightside', f'the company is identified ({slug})')
check(url == 'https://brightside.akyehq.com', f'with a link to it ({url})')

_tenancy._current.set('public')
check(errors._which_company() == (None, None),
      'and on a single-business install the question does not arise')


print('\n12. No owner address does not also cost us our copy')
# The old code returned early when it could not find an owner address, before
# either email had been sent. In practice `owner_email()` falls back to the
# from-address so it rarely comes back empty — but "rarely" is the wrong
# safety margin for the thing that tells you the product is broken, and the
# two sends are independent now.
import branding as _branding
_real_owner = _branding.owner_email
_branding.owner_email = lambda: ''
MAIL.clear()
c.get('/_boom_noowner')
check(len(MAIL) == 1, f'one email still goes out ({len(MAIL)})')
check(MAIL and 'akyehq.com' in MAIL[0]['to'], 'and it reaches the product')
check(MAIL and 'no owner email' in MAIL[0]['html'],
      'and says plainly that the customer was not told')
_branding.owner_email = _real_owner


print('\n13. A single business is not emailed about itself twice')
# On a deployment that is one cleaning company, there is no "product" to tell.
# The owner is the only person there is, and a second copy addressed to a
# support inbox that does not exist would be noise at best.
os.environ['BASE_DOMAIN'] = ''
_tenancy._current.set('public')
with app.app_context():
    BusinessSetting.set('email', 'owner@example.com')
    db.session.commit()
MAIL.clear()
c.get('/_boom_single')
check(len(MAIL) == 1, f'exactly one email ({len(MAIL)})')
check(MAIL and MAIL[0]['to'] == 'owner@example.com', 'to the owner, and only her')


print('\n14. The alert still cannot raise')
# Both sends are independent and both are wrapped. A mail outage must not turn
# a 500 into a 500 plus a second crash inside the crash reporter.
os.environ['BASE_DOMAIN'] = 'akyehq.com'
_saved = notifications.send_email
notifications.send_email = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('mail down'))
try:
    r = c.get('/_boom_mailfail')
    check(r.status_code == 500, 'a total mail failure still returns a clean 500')
finally:
    notifications.send_email = _saved

os.environ['BASE_DOMAIN'] = ''
_tenancy._current.set('public')

print('\n\n✅ All error-reporting tests passed.\n')
