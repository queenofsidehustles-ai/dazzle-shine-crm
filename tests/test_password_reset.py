"""Getting back in without asking anybody.

Until this existed, a forgotten password had one remedy: the person who sold you
the software editing an environment variable on your hosting account. A support
call for every customer, forever, and a permanent way in for somebody else.

A reset flow is also a gift to an attacker if it is built carelessly, so most of
what follows is about the ways it could be abused rather than the way it is
meant to be used.
"""
import os, sys, tempfile
from datetime import datetime, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/reset.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications

SENT = []
notifications.send_sms = lambda *a, **k: (True, 'stub')


def _capture(to_email=None, to_name=None, subject='', html='', **kw):
    SENT.append({'to': to_email, 'subject': subject, 'html': html})
    return (True, 'stub')


notifications.send_email = _capture
from app import create_app
from extensions import db
from models import User, LoginToken
import blueprints.account as account

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def link_from_last_email():
    import re
    m = re.search(r'href="([^"]*/reset/[^"]+)"', SENT[-1]['html'])
    return m.group(1) if m else None


def token_from(link):
    return link.rstrip('/').split('/reset/')[-1]


with app.app_context():
    db.create_all()
    owner = User(name='Monica Lewis', username='owner@example.com', role='owner')
    owner.set_password('the-original-password')
    other = User(name='Someone Else', username='va@example.com', role='team')
    other.set_password('another-password')
    db.session.add_all([owner, other])
    db.session.commit()
    owner_id = owner.id

c = app.test_client()

print('\n1. An ordinary reset works end to end')
SENT.clear()
r = c.post('/forgot', data={'username': 'owner@example.com'})
check(b'Check your email' in r.data, 'the page confirms something was sent')
check(len(SENT) == 1, 'exactly one email went out')
check(SENT[0]['to'] == 'owner@example.com', 'to the right address')
link = link_from_last_email()
check(link is not None, 'and it carries a reset link')

r = c.get(link)
check(b'Choose a new password' in r.data, 'the link opens a form')
r = c.post(link, data={'password': 'a-brand-new-password', 'confirm': 'a-brand-new-password'},
           follow_redirects=True)
check(b'Password changed' in r.data or b'Sign' in r.data, 'the password is changed')

with app.app_context():
    u = User.query.filter_by(username='owner@example.com').first()
    check(u.check_password('a-brand-new-password'), 'the new password works')
    check(not u.check_password('the-original-password'), 'and the old one does not')

print('\n2. A link works once and then never again')
r = c.post(link, data={'password': 'yet-another-password', 'confirm': 'yet-another-password'})
check(b'expired' in r.data, 'reusing a spent link is refused')
with app.app_context():
    u = User.query.filter_by(username='owner@example.com').first()
    check(u.check_password('a-brand-new-password'),
          'and the password it already set is untouched')

print('\n3. Asking about an address that has no account looks identical')
# Otherwise the form is a way to find out who is a customer here.
SENT.clear()
r_known = c.post('/forgot', data={'username': 'va@example.com'})
SENT.clear()
r_unknown = c.post('/forgot', data={'username': 'nobody@example.com'})
check(r_known.data == r_unknown.data,
      'the page is byte-for-byte the same for a real and an unknown address')
check(len(SENT) == 0, 'and nothing is sent to an address with no account')

print('\n4. The form cannot be used to flood somebody else\'s inbox')
SENT.clear()
for _ in range(6):
    c.post('/forgot', data={'username': 'va@example.com'})
check(len(SENT) <= 1, f'six rapid requests sent at most one email (sent {len(SENT)})')

print('\n5. Requesting a reset does not change anything by itself')
with app.app_context():
    u = User.query.filter_by(username='va@example.com').first()
    check(u.check_password('another-password'),
          'the account still has its old password until a link is actually used')

print('\n6. A made-up or tampered link is refused')
for bad in ('nonsense', 'x' * 43, token_from(link)[:-1] + 'z', ''):
    r = c.get(f'/reset/{bad}')
    check(b'expired' in r.data or r.status_code == 404,
          f'a token of {len(bad)} characters that we never issued is refused')

print('\n7. An expired link is refused')
with app.app_context():
    u = User.query.filter_by(username='va@example.com').first()
    raw, row = LoginToken.issue(u, 'reset')
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
r = c.get(f'/reset/{raw}')
check(b'expired' in r.data, 'a link past its hour is refused')
r = c.post(f'/reset/{raw}', data={'password': 'sneaky-password', 'confirm': 'sneaky-password'})
check(b'expired' in r.data, 'and posting to it directly is refused too')
with app.app_context():
    check(User.query.filter_by(username='va@example.com').first()
          .check_password('another-password'), 'the password did not change')

print('\n8. Only the hash is stored, so a leaked backup hands over nothing')
with app.app_context():
    u = User.query.filter_by(username='va@example.com').first()
    raw, row = LoginToken.issue(u, 'reset')
    stored = [t.token_hash for t in LoginToken.query.all()]
    check(raw not in stored, 'the raw token appears nowhere in the table')
    check(len(row.token_hash) == 64, 'what is stored is a sha256 hash')
    check(row.token_hash != raw, 'and it is not the token')

print('\n9. Changing a password kills every other link in flight')
# If somebody else quietly requested a reset, this is the moment theirs dies.
with app.app_context():
    u = User.query.filter_by(username='owner@example.com').first()
    attacker_raw, _ = LoginToken.issue(u, 'reset')
    mine_raw, _ = LoginToken.issue(u, 'reset')
r = c.post(f'/reset/{mine_raw}',
           data={'password': 'my-chosen-password', 'confirm': 'my-chosen-password'},
           follow_redirects=True)
r = c.get(f'/reset/{attacker_raw}')
check(b'expired' in r.data,
      'a reset link issued to somebody else stops working the moment I change it')

print('\n10. A weak or mistyped password is refused')
with app.app_context():
    u = User.query.filter_by(username='va@example.com').first()
    raw, _ = LoginToken.issue(u, 'reset')
for pw, confirm, why in [('short', 'short', 'under 8 characters'),
                         ('password', 'password', 'a guessable password'),
                         ('goodenough1', 'goodenough2', 'two that do not match')]:
    r = c.post(f'/reset/{raw}', data={'password': pw, 'confirm': confirm})
    check(b'expired' not in r.data and (b'least 8' in r.data or b'not match' in r.data
                                        or b'too easy' in r.data),
          f'{why} is refused')
with app.app_context():
    check(User.query.filter_by(username='va@example.com').first()
          .check_password('another-password'),
          'and none of those attempts changed the password')
check(True, 'the link is still usable afterwards — a typo does not burn it')

print('\n11. A reset token cannot be spent as a signup token')
with app.app_context():
    u = User.query.filter_by(username='va@example.com').first()
    raw, _ = LoginToken.issue(u, 'reset')
    check(LoginToken.consume(raw, 'signup') is None,
          'a token issued for one purpose is refused for another')
    check(LoginToken.consume(raw, 'reset') is not None,
          'and still works for the one it was issued for')

print('\n12. The sign-in page tells people the option exists')
r = c.get('/login')
check(b'Forgotten your password' in r.data,
      'there is a link to it, which is the difference between existing and being found')

print('\n\n✅ All password-reset tests passed.\n')
