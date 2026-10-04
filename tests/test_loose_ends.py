"""Loose ends from the pre-launch sweep.

What each of these would cost if it regressed:
  * applicant videos uploading to a Cloudinary account hard-coded in the
    source instead of the one Akye configures -- or, with nothing configured,
    an applicant recording answers that can only fail to upload;
  * the sign-in and signup attempt tables growing by every attempt forever,
    when only the last day or so is ever read back.

Against a real disposable Postgres, like the rest of the suite.
"""
import os
import pathlib
import secrets
import sys
from datetime import datetime, timedelta

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
for k in ('CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_UPLOAD_PRESET'):
    os.environ.pop(k, None)
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import control_plane
import integrations
import provisioning
import security
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


TAG = secrets.token_hex(4)
SLUG = f'loose{TAG}'
HOST = {'Host': f'{SLUG}.akyehq.test'}
with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    provisioning.provision(SLUG, 'Loose Ends Cleaning', quiet=True)
    db.session.remove()

print('\n1. Interview videos go to the configured Cloudinary, never a built-in one')
check('dasgvqtyk' not in (ROOT / 'blueprints' / 'interviews.py').read_text(),
      'no Cloudinary account is written into the code')
token = secrets.token_urlsafe(16)
with app.app_context(), tenancy.use_tenant(SLUG):
    from models import ContractorApplication
    db.session.add(ContractorApplication(name='Casey Applicant', email=f'casey-{TAG}@example.com',
                                         interview_token=token, interview_status='sent'))
    db.session.commit()
    db.session.remove()
c = app.test_client()
r = c.get(f'/interview/{token}', headers=HOST)
body = r.get_data(as_text=True)
check(r.status_code == 200 and 'has not finished setting up video interviews' in body
      and 'api.cloudinary.com' not in body,
      'with nothing connected the applicant is told so, not handed a recorder that cannot upload')
with app.app_context(), tenancy.use_tenant(SLUG):
    status = ContractorApplication.query.filter_by(interview_token=token).first().interview_status
    db.session.remove()
check(status == 'sent', 'and the interview is not marked started')

os.environ['CLOUDINARY_CLOUD_NAME'] = 'platform-cloud'
body = c.get(f'/interview/{token}', headers=HOST).get_data(as_text=True)
check('"platform-cloud"' in body, 'the platform\'s cloud is used when the company has none')
with app.app_context(), tenancy.use_tenant(SLUG):
    integrations.set('cloudinary_cloud_name', 'company-own-cloud')
    db.session.remove()
body = c.get(f'/interview/{token}', headers=HOST).get_data(as_text=True)
# On hosted Akye job photos and interview videos are Akye's, like texting and
# email (test_platform_connections.py): a cloud a company saved is ignored.
check('"platform-cloud"' in body and '"company-own-cloud"' not in body,
      'and still Akye\'s, even if the company saved one of its own')
os.environ.pop('CLOUDINARY_CLOUD_NAME', None)

print('\n2. Sign-in attempts older than a month are cleared as new ones come in')
with app.app_context(), tenancy.use_tenant(SLUG):
    from models import LoginAttempt
    db.session.add(LoginAttempt(ip='10.9.9.9', username='old', ok=False,
                                created_at=datetime.utcnow() - timedelta(days=45)))
    db.session.add(LoginAttempt(ip='10.9.9.9', username='recent', ok=False,
                                created_at=datetime.utcnow() - timedelta(days=3)))
    db.session.commit()
    with app.test_request_context('/', environ_base={'REMOTE_ADDR': '10.9.9.9'}):
        security.record_login('someone', False)
    db.session.remove()
# Leaving a request clears the current company, so look again from inside it.
with app.app_context(), tenancy.use_tenant(SLUG):
    names = {a.username for a in LoginAttempt.query.filter_by(ip='10.9.9.9')}
    db.session.remove()
check('old' not in names, 'a 45-day-old attempt is gone')
check({'recent', 'someone'} <= names, f'the recent ones, and the new one, are kept ({sorted(names)})')

print('\n3. Signup attempts older than a week are cleared the same way')
with app.app_context():
    t = control_plane.signup_attempts
    ip_old, ip_new = f'10.8.{secrets.randbelow(250)}.1', f'10.8.{secrets.randbelow(250)}.2'
    with engine.begin() as conn:
        conn.execute(t.insert().values(ip=ip_old, created_at=datetime.utcnow() - timedelta(days=10)))
    control_plane.record_signup_attempt(engine, ip_new)
    with engine.connect() as conn:
        ips = {r.ip for r in conn.execute(t.select().where(t.c.ip.in_([ip_old, ip_new])))}
check(ip_old not in ips and ip_new in ips, 'a 10-day-old attempt is gone and the new one is kept')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Interview videos use the company\'s own connection; attempt tables stay small.')
