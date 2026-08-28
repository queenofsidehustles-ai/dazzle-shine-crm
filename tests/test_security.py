"""The locks: throttled logins, hardened cookies, and forms posted from
somewhere else being refused.

The thing these tests are really guarding is the second failure mode. It is
easy to write a lock that keeps everybody out, including the owner at 6am with
thirty jobs booked. So roughly half of what follows checks that ordinary use
still works.
"""
import os, sys, tempfile
from datetime import datetime, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/sec.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ADMIN_USER'] = 'owner'
os.environ['ADMIN_PASS'] = 'correct-horse-battery'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import LoginAttempt, ErrorLog
import security

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def clear_attempts():
    with app.app_context():
        LoginAttempt.query.delete()
        db.session.commit()


print('\n1. The cookie settings are decisions, not defaults')
check(app.config['SESSION_COOKIE_HTTPONLY'] is True,
      'the session cookie is hidden from JavaScript')
check(app.config['SESSION_COOKIE_SAMESITE'] == 'Lax',
      'the session cookie is not sent on a cross-site POST')
check(app.config['PERMANENT_SESSION_LIFETIME'] == timedelta(days=14),
      'sessions expire after 14 days rather than never')
check(app.config['SESSION_COOKIE_SECURE'] is False,
      'HTTPS-only is off locally, or nobody could log in to test anything')
os.environ['RAILWAY_ENVIRONMENT'] = 'production'
os.environ.pop('FLASK_ENV')
check(security._is_production() is True, 'and on Railway it is switched on')
os.environ.pop('RAILWAY_ENVIRONMENT')
os.environ['FLASK_ENV'] = 'development'

print('\n2. An ordinary sign-in still works')
clear_attempts()
c = app.test_client()
r = c.post('/login', data={'username': 'owner', 'password': 'correct-horse-battery'},
           follow_redirects=False)
check(r.status_code in (301, 302), 'correct credentials sign in')
with app.app_context():
    check(LoginAttempt.query.filter_by(ok=True).count() == 1, 'the success is recorded')

print('\n3. Guessing gets slow, and stays slow for the guesser')
clear_attempts()
c = app.test_client()
for i in range(security.MAX_FAILED_LOGINS):
    c.post('/login', data={'username': 'owner', 'password': f'wrong-{i}'})
with app.app_context():
    check(LoginAttempt.query.filter_by(ok=False).count() == security.MAX_FAILED_LOGINS,
          f'{security.MAX_FAILED_LOGINS} failures are recorded')
r = c.post('/login', data={'username': 'owner', 'password': 'wrong-again'})
check(b'Too many failed sign-ins' in r.data, 'the 11th attempt is refused')

print('\n4. And the refusal survives the right password — that is the point')
r = c.post('/login', data={'username': 'owner', 'password': 'correct-horse-battery'})
check(b'Too many failed sign-ins' in r.data,
      'a locked-out address cannot log in even with the correct password')
check(b'Dashboard' not in r.data, 'and is not let through to anything')

print('\n5. The block expires — nobody is locked out permanently')
with app.app_context():
    old = datetime.utcnow() - timedelta(minutes=20)
    for a in LoginAttempt.query.all():
        a.created_at = old
    db.session.commit()
c = app.test_client()
r = c.post('/login', data={'username': 'owner', 'password': 'correct-horse-battery'},
           follow_redirects=False)
check(r.status_code in (301, 302),
      'after the window passes the owner can sign in again')

print('\n6. The lock is on the address, not the account')
# Locking the account would let a stranger shut the owner out of her own
# business by typing her username wrong ten times.
clear_attempts()
attacker = app.test_client()
for i in range(security.MAX_FAILED_LOGINS + 2):
    attacker.post('/login', data={'username': 'owner', 'password': f'x{i}'},
                  environ_base={'REMOTE_ADDR': '203.0.113.9'})
r = attacker.post('/login', data={'username': 'owner', 'password': 'correct-horse-battery'},
                  environ_base={'REMOTE_ADDR': '203.0.113.9'})
check(b'Too many failed sign-ins' in r.data, 'the attacking address is blocked')

owner = app.test_client()
r = owner.post('/login', data={'username': 'owner', 'password': 'correct-horse-battery'},
               environ_base={'REMOTE_ADDR': '198.51.100.4'}, follow_redirects=False)
check(r.status_code in (301, 302),
      'while the owner, elsewhere, signs in perfectly normally')

print('\n7. A forwarded address cannot be forged to dodge the throttle')
with app.test_request_context('/', headers={'X-Forwarded-For': '1.2.3.4, 5.6.7.8'}):
    check(security.client_ip() == '1.2.3.4',
          'only the first entry in X-Forwarded-For is trusted')

print('\n8. Forms posted from another website are refused')
clear_attempts()
c = app.test_client()
c.post('/login', data={'username': 'owner', 'password': 'correct-horse-battery'})
r = c.post('/settings/business', data={'business_name': 'Hacked Co'},
           headers={'Origin': 'https://evil.example.com'})
check(r.status_code == 403, 'a POST claiming to come from another site is refused')
r = c.post('/settings/business', data={'business_name': 'Hacked Co'},
           headers={'Referer': 'https://evil.example.com/attack'})
check(r.status_code == 403, 'the same check applies to Referer')

print('\n9. Ordinary submissions from the CRM itself are not')
r = c.post('/settings/business', data={'business_name': 'Test Co'},
           headers={'Origin': 'http://localhost'})
check(r.status_code != 403, 'a form posted from this site goes through')
r = c.post('/settings/business', data={'business_name': 'Test Co'})
check(r.status_code != 403,
      'and so does one with no Origin at all — privacy tools strip it')

print('\n10. Machines that legitimately post from elsewhere are exempt')
# Stripe's webhook and Twilio's inbound texts arrive from another origin by
# definition. Both carry their own proof; neither can carry ours.
r = c.post('/api/stripe-webhook', data='{}',
           headers={'Origin': 'https://stripe.com'})
check(r.status_code != 403, 'the Stripe webhook is not origin-checked')
r = c.post('/messages/incoming', data={'From': '+14075551212', 'Body': 'hi'},
           headers={'Origin': 'https://api.twilio.com'})
check(r.status_code != 403, 'nor is an inbound text from Twilio')

print('\n11. A refused submission is written down')
with app.app_context():
    blocked = ErrorLog.query.filter_by(kind='blocked').first()
    check(blocked is not None, 'the block is recorded so a pattern is visible')
    check('evil.example.com' in (blocked.message or ''), 'along with where it claimed to be from')

print('\n12. A throttle that cannot read its table does not lock anyone out')
import models


class BrokenTable:
    @property
    def query(self):
        raise RuntimeError('database unreachable')


with app.test_request_context('/login', environ_base={'REMOTE_ADDR': '10.0.0.1'}):
    real = models.LoginAttempt
    models.LoginAttempt = BrokenTable()
    try:
        blocked, mins = security.login_blocked()
    finally:
        models.LoginAttempt = real
check(blocked is False, 'a broken throttle fails open, not closed')
check(mins == 0, 'and reports no wait, so the owner is not told to sit and wait')

print('\n\n✅ All security tests passed.\n')
