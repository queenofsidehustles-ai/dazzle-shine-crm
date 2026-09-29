"""Launch hardening: response headers, console two-factor, signup limits.

What would make each of these dangerous:
  * a login or payment page that another site can frame and click-jack, or a
    booking embed that stops working because the fix framed out everything;
  * a console login -- which sees every company -- that a phished password
    alone opens, or whose six-digit code can be guessed without a lockout;
  * a signup form a script can use to create thousands of company schemas.

Against a real disposable Postgres, like the rest of the console suite.
"""
import os
import secrets
import sys
import time

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
os.environ['SIGNUPS_OPEN'] = '1'
os.environ.pop('CONSOLE_REQUIRE_2FA', None)
os.environ.pop('SIGNUP_LIMITS', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import control_plane
import provisioning
import totp

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


TAG = secrets.token_hex(4)
PRODUCT = {'Host': 'akyehq.test'}
PW = 'a-real-console-password-1'

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()


def client(ip=None):
    c = app.test_client()
    c.environ_base['REMOTE_ADDR'] = ip or f'10.{secrets.randbelow(250)}.{secrets.randbelow(250)}.{secrets.randbelow(250)}'
    return c


print('\n1. Every page refuses to be framed, except the booking embed')
c = client()
r = c.get('/', headers=PRODUCT)
check(r.headers.get('X-Frame-Options') == 'SAMEORIGIN'
      and "frame-ancestors 'self'" in (r.headers.get('Content-Security-Policy') or ''),
      'the home page cannot be framed by another site')
check(r.headers.get('X-Content-Type-Options') == 'nosniff'
      and r.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin',
      'and carries nosniff and an origin-only referrer policy')
r = c.get('/console/login', headers=PRODUCT)
check(r.headers.get('X-Frame-Options') == 'SAMEORIGIN', 'nor can the console sign-in')
check('Strict-Transport-Security' not in r.headers,
      'HSTS is not sent off production (it would pin http://localhost)')
os.environ['RAILWAY_ENVIRONMENT'] = 'production'
r = c.get('/console/login', headers=PRODUCT, base_url='https://akyehq.test')
os.environ.pop('RAILWAY_ENVIRONMENT', None)
check((r.headers.get('Strict-Transport-Security') or '').startswith('max-age=31536000'),
      'and is sent on production over HTTPS')

slug = f'hdr{TAG}'
with app.app_context():
    provisioning.provision(slug, 'Header Cleaning', quiet=True)
    db.session.remove()
TENANT = {'Host': f'{slug}.akyehq.test'}
r = c.get('/book?embed=1', headers=TENANT)
check(r.status_code == 200 and 'X-Frame-Options' not in r.headers
      and 'frame-ancestors' not in (r.headers.get('Content-Security-Policy') or ''),
      'the booking embed can still be shown inside a company\'s own website')
r = c.get('/book', headers=TENANT)
check(r.headers.get('X-Frame-Options') == 'SAMEORIGIN',
      'but the same page without ?embed=1 is not frameable')

print('\n2. The console makes every login set up two-factor, in production')
MGR = f'mgr-{TAG}@example.com'
with app.app_context():
    control_plane.add_console_user(engine, MGR, 'Manager', PW, role='manager')
os.environ['CONSOLE_REQUIRE_2FA'] = '1'
m = client()
r = m.post('/console/login', data={'email': MGR, 'password': PW}, headers=PRODUCT)
r = m.get('/console/companies', headers=PRODUCT)
check(r.status_code == 302 and '/console/security' in r.headers['Location'],
      'a password-only login is sent to set up two-factor before anything else')
r = m.post('/console/security/start', headers=PRODUCT)
body = r.get_data(as_text=True)
check('otpauth://' in body and 'Turn it on' in body, 'setup shows an authenticator link')
with app.app_context():
    secret = control_plane.console_user(engine, MGR)['totp_secret']
r = m.post('/console/security/confirm', data={'code': '000000'}, headers=PRODUCT)
check('did not match' in r.get_data(as_text=True), 'a wrong code does not switch it on')
code = totp._code_at(secret, int(time.time()) // 30)
r = m.post('/console/security/confirm', data={'code': code}, headers=PRODUCT)
body = r.get_data(as_text=True)
check('Save these backup codes' in body, 'the right code switches it on and shows backup codes once')
backup = body.split('columns:2">')[1].split('</div>\n  </div>')[0]
backup_code = backup.split('<div>')[1].split('</div>')[0].strip()
r = m.get('/console/companies', headers=PRODUCT)
check(r.status_code == 200, 'and the console opens')

print('\n3. Signing in then takes the password and a code')
m2 = client()
r = m2.post('/console/login', data={'email': MGR, 'password': PW}, headers=PRODUCT)
check(r.status_code == 302 and r.headers['Location'].endswith('/console/login/code'),
      'the right password alone asks for a code')
r = m2.get('/console/companies', headers=PRODUCT)
check(r.status_code == 302 and '/console/login' in r.headers['Location'],
      'and opens nothing until it is given')
r = m2.post('/console/login/code', data={'code': '123456'}, headers=PRODUCT)
check('did not match' in r.get_data(as_text=True), 'a wrong code is refused')
code = totp._code_at(secret, int(time.time()) // 30)
r = m2.post('/console/login/code', data={'code': code}, headers=PRODUCT)
check(r.status_code == 302 and m2.get('/console/companies', headers=PRODUCT).status_code == 200,
      'the right code signs in')

m3 = client()
m3.post('/console/login', data={'email': MGR, 'password': PW}, headers=PRODUCT)
r = m3.post('/console/login/code', data={'code': backup_code}, headers=PRODUCT)
check(r.status_code == 302 and m3.get('/console/companies', headers=PRODUCT).status_code == 200,
      'a backup code signs in once')
m4 = client()
m4.post('/console/login', data={'email': MGR, 'password': PW}, headers=PRODUCT)
r = m4.post('/console/login/code', data={'code': backup_code}, headers=PRODUCT)
check('did not match' in r.get_data(as_text=True), 'and not a second time')

m5 = client()
m5.post('/console/login', data={'email': MGR, 'password': PW}, headers=PRODUCT)
for _ in range(control_plane.LOCK_AFTER):
    r = m5.post('/console/login/code', data={'code': '000001'}, headers=PRODUCT)
check(r.status_code == 302 and '/console/login' in r.headers['Location'],
      f'{control_plane.LOCK_AFTER} wrong codes lock the account like wrong passwords')
m6 = client()
r = m6.post('/console/login', data={'email': MGR, 'password': PW}, headers=PRODUCT,
            follow_redirects=True)
check('Too many tries' in r.get_data(as_text=True), 'and even the right password waits')
os.environ.pop('CONSOLE_REQUIRE_2FA', None)

print('\n4. Signup refuses bots and floods')
os.environ['SIGNUP_LIMITS'] = '1'


def signup(c, slug, **extra):
    data = {'business': f'Biz {slug}', 'slug': slug, 'name': 'Owner',
            'email': f'{slug}@example.com', 'password': 'a-perfectly-fine-password',
            'terms_accepted': '1'}
    data.update(extra)
    return c.post('/signup', data=data, headers=PRODUCT)


def exists(slug):
    with app.app_context():
        return control_plane.find(engine, slug) is not None


s = client()
r = signup(s, f'bot{TAG}', website='http://spam.example')
check(r.status_code == 200 and not exists(f'bot{TAG}'),
      'a filled-in hidden field creates nothing')
ip = f'10.200.{secrets.randbelow(250)}.{secrets.randbelow(250)}'
made = []
for i in range(4):
    slug_i = f'ip{i}{TAG}'
    r = signup(client(ip), slug_i)
    made.append(exists(slug_i))
check(made == [True, True, True, False],
      f'three companies a day from one address, then no more ({made})')
check('as many new companies as we can open from one place' in r.get_data(as_text=True),
      'and it says why')

with app.app_context():
    from datetime import datetime, timedelta
    today = control_plane.orgs_created_since(engine, datetime.utcnow() - timedelta(days=1))
os.environ['SIGNUP_DAILY_CAP'] = str(today)
r = signup(client(), f'cap{TAG}')
check(not exists(f'cap{TAG}') and 'as many new accounts as we can today' in r.get_data(as_text=True),
      'past the daily ceiling nobody new is let in')
os.environ.pop('SIGNUP_DAILY_CAP', None)
os.environ.pop('SIGNUP_LIMITS', None)
r = signup(client(ip), f'dev{TAG}')
check(exists(f'dev{TAG}'), 'and off production the limits do not apply')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Frames refused but for the embed, console behind two factors, signup rate limited.')
