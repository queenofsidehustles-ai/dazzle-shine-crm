"""A deployment with no owner login configured used to accept admin/changeme.

On one hand-configured server that was untidy. Once the same code runs a second
company's business it is a guessable way into their customer list, their pricing
and their payment settings — so an unconfigured deployment now has no built-in
login at all.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/auth.db'
os.environ['SECRET_KEY'] = 'test'
for stale in ('ADMIN_USER', 'ADMIN_PASS'):
    os.environ.pop(stale, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda **k: (True, 'ok')

from app import create_app
from extensions import db
from models import User
import auth

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

app = create_app()
with app.app_context():
    db.create_all()

    print('\n1. A fresh instance with nothing configured lets nobody in')
    check(not auth.env_login_configured(), 'no built-in login is considered configured')
    for user, pw in [('admin', 'changeme'), ('admin', 'admin'), ('admin', 'password'),
                     ('admin', '123456'), ('admin', '')]:
        ok, _ = auth.authenticate(user, pw)
        check(not ok, f'{user}/{pw or "(blank)"} is refused')

    print('\n2. And the login page says why, rather than leaving someone guessing')
    c = app.test_client()
    page = c.get('/login').get_data(as_text=True)
    check('no owner login yet' in page, 'the page explains the instance is not set up')
    check('ADMIN_USER' in page, 'and names what to set')

    print('\n3. A weak password is refused even if it IS set')
    os.environ['ADMIN_USER'] = 'owner'
    os.environ['ADMIN_PASS'] = 'changeme'
    check(not auth.env_login_configured(), 'changeme does not count as configured')
    ok, _ = auth.authenticate('owner', 'changeme')
    check(not ok, 'and it cannot be used to log in')

    print('\n4. A real password works')
    os.environ['ADMIN_PASS'] = 'a-genuinely-chosen-password'
    check(auth.env_login_configured(), 'the instance is now configured')
    ok, info = auth.authenticate('owner', 'a-genuinely-chosen-password')
    check(ok and info['role'] == 'owner', 'the owner can sign in')
    ok, _ = auth.authenticate('owner', 'wrong')
    check(not ok, 'a wrong password still fails')
    ok, _ = auth.authenticate('admin', 'changeme')
    check(not ok, 'and the old default is gone for good')

    print('\n5. Real user accounts are unaffected')
    u = User(name='Ade Bello', username='ade', role='owner', active=True)
    u.set_password('their-own-password')
    db.session.add(u); db.session.commit()
    ok, info = auth.authenticate('ade', 'their-own-password')
    check(ok and info['name'] == 'Ade Bello', 'a real account signs in')
    ok, _ = auth.authenticate('ade', 'their-own-password!')
    check(not ok, 'with the wrong password refused')
    check(User.query.get(u.id).password_hash != 'their-own-password',
          'and the password is stored hashed, never in the clear')

    print('\n6. An account holder can still get in when the env login is removed')
    os.environ.pop('ADMIN_USER', None)
    os.environ.pop('ADMIN_PASS', None)
    check(not auth.env_login_configured(), 'the built-in login is gone')
    ok, _ = auth.authenticate('ade', 'their-own-password')
    check(ok, 'but their own account still works — so the owner is never locked out')
    page = c.get('/login').get_data(as_text=True)
    check('no owner login yet' not in page,
          'and the setup warning is hidden once real accounts exist')

print('\n🎉 No deployment is reachable with a password nobody chose.')
