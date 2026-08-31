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
notifications.send_sms = lambda *a, **k: (True, 'stub')
# Four arguments, the same as the real function. This stub took three, and so
# did the caller in errors.py — so "exactly one email went out" passed for
# months while the alerter had never sent one in its life. A stub that is
# easier to call than the real thing tests the stub. See test_email_callers.py.
notifications.send_email = lambda to_email, to_name, subject, html, **k: (
    SENT.append((to_email, subject)), (True, 'stub'))[1]

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

print('\n\n✅ All error-reporting tests passed.\n')
