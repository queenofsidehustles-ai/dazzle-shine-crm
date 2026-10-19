"""Fixes from the rogue-code and loose-ends review (2026-10-16).

What each of these would cost if it regressed:
  * MailerLite: every company's website quote requests -- names and email
    addresses -- added to one mailing list, the one MAILERLITE_API_KEY names;
  * the cleaner's accept / decline link: a link for job #N at one company
    opened job #N at every other, outlived a reassignment, and was answered by
    whatever opened it -- a mail scanner included, whose "decline" unassigns
    the cleaner;
  * scheduled jobs: two company jobs took their key in the URL and ran with
    no company address, and every key was compared with !=;
  * "back to where you were" redirects that a next field could point at
    another site;
  * feedback screenshots: any company's owner could read any other company's
    by id, and a "screenshot" could be an SVG that runs script;
  * `python app.py` serving the Werkzeug debugger to the network.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import base64
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_review_fixes')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
os.environ['REMINDER_API_KEY'] = 'cron-key'
os.environ['MAILERLITE_API_KEY'] = 'ml-test-not-real'

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append(('email', a, k)) or (True, 'stub'))
notifications.send_sms = lambda *a, **k: (SENT.append(('sms', a, k)) or (True, 'stub'))
OUTBOUND = []


class _Resp:
    status_code = 200
    ok = True
    text = '{}'

    def json(self):
        return {}


# Nothing leaves the machine: every HTTP call notifications makes is recorded.
notifications.http_requests.post = lambda url, *a, **k: (OUTBOUND.append(url) or _Resp())

from app import create_app
from extensions import db
import automations
import control_plane
import provisioning
import scheduler
import security
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


A, B = 'reviewa', 'reviewb'
HOST_A, HOST_B = f'http://{A}.akye.test', f'http://{B}.akye.test'
for slug, name in ((A, 'Review A Cleaning'), (B, 'Review B Cleaning')):
    with app.app_context():
        provisioning.provision(slug, name, quiet=True)
        db.session.remove()
    fresh_postgres.set_company_plan(slug, 'scale')
owner_a = fresh_postgres.owner_client(app, A, 'akye.test')
owner_b = fresh_postgres.owner_client(app, B, 'akye.test')

print('\n1. MailerLite gets no company\'s leads')
OUTBOUND.clear()
r = app.test_client().post('/api/quote', base_url=HOST_A, json={
    'name': 'Lena Lead', 'email': 'lena@example.com', 'service_type': 'standard',
    'bedrooms': 2, 'bathrooms': 1})
check(r.status_code == 201, f'a website quote request is taken ({r.status_code})')
check(not any('mailerlite' in u for u in OUTBOUND), 'and is not added to the MailerLite list')
with app.test_request_context('/', base_url=HOST_A):
    with tenancy.use_tenant(A):
        OUTBOUND.clear()
        notifications.add_to_mailerlite('x@example.com', 'X')
        check(not OUTBOUND, 'not from inside a company, called directly')
os.environ.pop('BASE_DOMAIN')
try:
    with app.test_request_context('/'):
        OUTBOUND.clear()
        notifications.add_to_mailerlite('own@example.com', 'Own Lead')
        check(any('mailerlite' in u for u in OUTBOUND),
              "a single-business install's own leads still go to its list")
finally:
    os.environ['BASE_DOMAIN'] = 'akye.test'

print('\n2. The cleaner\'s accept / decline link')
from datetime import date, timedelta
from models import Booking


def make_booking(slug, cleaner):
    with app.app_context(), tenancy.use_tenant(slug):
        b = Booking(name='Cora Customer', email=f'cora@{slug}.example', phone='5555550111',
                    service_type='standard', status='confirmed', assigned_cleaner=cleaner,
                    preferred_date=(date.today() + timedelta(days=2)).isoformat())
        db.session.add(b)
        db.session.commit()
        out = b.id
        db.session.remove()
    return out


def booking_state(slug, bid):
    with app.app_context(), tenancy.use_tenant(slug):
        b = db.session.get(Booking, bid)
        out = (b.assigned_cleaner, b.cleaner_response)
        db.session.remove()
    return out


def token_for(slug, bid):
    from blueprints.bookings import cleaner_response_token
    with app.test_request_context('/'), tenancy.use_tenant(slug):
        out = cleaner_response_token(db.session.get(Booking, bid))
        db.session.remove()
    return out


BA = make_booking(A, 'Casey Clean')
BB = make_booking(B, 'Casey Clean')
while BB < BA:            # the same id at both companies: the case that mattered
    BB = make_booking(B, 'Casey Clean')
while BA < BB:
    BA = make_booking(A, 'Casey Clean')
check(BA == BB, f'job #{BA} exists at both companies')
tok = token_for(A, BA)
check(len(tok) == 32 and tok != token_for(B, BB), "each company's token for job #N is its own")

anon = app.test_client()
url = f'/bookings/{BA}/cleaner-response'
r = anon.get(f'{url}?action=decline&token={tok}', base_url=HOST_A)
check(r.status_code == 200 and 'method="POST"' in r.get_data(as_text=True),
      'opening the decline link asks, with a button')
check(booking_state(A, BA) == ('Casey Clean', None), 'and opening it changes nothing (a mail scanner opens links)')
r = anon.post(url, base_url=HOST_B, data={'action': 'decline', 'token': tok})
check(r.status_code == 400, "company A's token is refused for job #N at company B")
check(booking_state(B, BB) == ('Casey Clean', None), 'and B\'s job is untouched')
import hashlib
legacy = hashlib.sha256(f"{BA}{os.environ['SECRET_KEY']}".encode()).hexdigest()[:16]
r = anon.post(url, base_url=HOST_A, data={'action': 'decline', 'token': legacy})
check(r.status_code == 400, 'the old id-only token is refused on the platform')
r = anon.post(url, base_url=HOST_A, data={'action': 'accept', 'token': tok})
check(r.status_code == 200 and booking_state(A, BA) == ('Casey Clean', 'accepted'),
      'pressing the button accepts the job')
with app.app_context(), tenancy.use_tenant(A):
    db.session.get(Booking, BA).assigned_cleaner = 'Robin Other'
    db.session.commit()
    db.session.remove()
r = anon.post(url, base_url=HOST_A, data={'action': 'decline', 'token': tok})
check(r.status_code == 400 and booking_state(A, BA)[0] == 'Robin Other',
      'once reassigned, the first cleaner\'s link cannot decline it for the new one')
new_tok = token_for(A, BA)
r = anon.post(url, base_url=HOST_A, data={'action': 'decline', 'token': new_tok})
check(r.status_code == 200 and booking_state(A, BA) == ('', 'declined'),
      "the new cleaner's own link declines it, and unassigns them")
r = anon.get(f'{url}?action=accept&token=nope', base_url=HOST_A)
check(r.status_code == 400, 'a made-up token is refused')

print('\n3. Scheduled jobs')
jobs = {f'/api/{k}' for k, *_ in automations.JOBS}
check(jobs <= security.CRON_PATHS, f'every company job is a company-only path ({sorted(jobs - security.CRON_PATHS)} missing)')
product_jobs = {f'/api/{k}' for k in scheduler.product_jobs_for()}
check(product_jobs <= security.PRODUCT_CRON_PATHS, 'every product job refuses a key in the URL too')
api_src = (ROOT / 'blueprints' / 'api.py').read_text()
check("api_key != expected" not in api_src and "request.args.get('api_key'" not in api_src,
      'no job compares its key with != or reads it from the URL')
# Twelve scheduled jobs and the endpoint backups and the scheduler report to.
check(api_src.count('if not _cron_key_ok():') == 13, 'all twelve jobs and the platform-run report use the one check')
check(api_src.count('def _cron_key_ok(') == 1, 'and there is only one such check, so a second cannot override it')
cl = app.test_client()
r = cl.post('/api/owner-digest?api_key=cron-key', base_url=HOST_A)
check(r.status_code == 403, f'owner-digest refuses its key in the URL ({r.status_code})')
r = cl.post('/api/owner-digest', base_url='http://akye.test', headers={'X-Api-Key': 'cron-key'})
check(r.status_code == 404, f'owner-digest does not run at the platform address ({r.status_code})')
r = cl.post('/api/rental-turnovers', base_url=HOST_A, headers={'X-Api-Key': 'wrong'})
check(r.status_code == 403, 'a wrong key is refused')
r = cl.post('/api/rental-turnovers', base_url=HOST_A, headers={'X-Api-Key': 'cron-key'})
check(r.status_code == 200, f'the right key, in the header, at a company address, runs ({r.status_code})')

print('\n4. Redirects stay on this site')
with app.test_request_context('/', base_url=HOST_A):
    lt = security.local_target
    check(lt('/bookings/?status=pending') == '/bookings/?status=pending', 'a path is kept')
    check(lt(f'{HOST_A}/bookings/7?x=1') == '/bookings/7?x=1', 'a full URL on this host becomes its path')
    for bad in ('//evil.example/x', '/\\evil.example', 'https://evil.example/', 'javascript:alert(1)',
                f'http://{B}.akye.test/x', '/x\r\nSet-Cookie: a=b'):
        check(lt(bad) is None, f'{bad!r} is refused')
    check(lt('https://evil.example/', '/fallback') == '/fallback', 'the next candidate is tried')
r = owner_a.post('/tips/dismiss', base_url=HOST_A, data={'key': 'whatever', 'next': '/\\evil.example/'})
loc = r.headers.get('Location', '')
check('evil.example' not in loc, f'a tip dismissal does not leave the site ({r.status_code} {loc})')
r = owner_a.post('/settings/brand/all', base_url=HOST_A, data={'next': '//evil.example/'})
loc = r.headers.get('Location', '')
check(r.status_code == 302 and 'evil.example' not in loc,
      f'nor does switching brand with a //host next ({loc})')

print('\n5. Feedback screenshots')
jpeg = 'data:image/jpeg;base64,' + base64.b64encode(b'\xff\xd8\xff' + b'a-private-screen' * 4).decode()
r = owner_a.post('/feedback', base_url=HOST_A, json={'body': 'It broke', 'shot': jpeg})
check(r.status_code == 200, f'feedback with a screenshot is taken ({r.status_code})')
engine = provisioning._engine()
from sqlalchemy import select
with engine.connect() as conn:
    fid = conn.execute(select(control_plane.feedback.c.id)
                       .where(control_plane.feedback.c.org_slug == A)
                       .order_by(control_plane.feedback.c.id.desc())).scalar()
r = owner_a.get(f'/feedback/{fid}/shot', base_url=HOST_A)
check(r.status_code == 200 and r.mimetype == 'image/jpeg', 'its own owner sees it')
r = owner_b.get(f'/feedback/{fid}/shot', base_url=HOST_B)
check(r.status_code == 404, "another company's owner gets nothing for it")
svg = 'data:image/svg+xml;base64,' + base64.b64encode(b'<svg onload="alert(1)"/>').decode()
r = owner_a.post('/feedback', base_url=HOST_A, json={'body': 'Look', 'shot': svg})
with engine.connect() as conn:
    row = conn.execute(select(control_plane.feedback.c.shot, control_plane.feedback.c.body)
                       .order_by(control_plane.feedback.c.id.desc())).first()
check(r.status_code == 200 and row.body == 'Look' and row.shot is None,
      'an SVG "screenshot": the words are kept, the picture is not')
with engine.begin() as conn:
    old = conn.execute(control_plane.feedback.insert().values(
        org_slug=A, body='old', shot=b'<svg/>', shot_type='image/svg+xml')).inserted_primary_key[0]
check(control_plane.feedback_shot(engine, old)[1] == 'application/octet-stream',
      'one already stored is never served as an image that runs script')
huge = 'data:image/jpeg;base64,' + 'A' * (4 * 1024 * 1024 + 8)
r = owner_a.post('/feedback', base_url=HOST_A, json={'body': 'Big', 'shot': huge})
check(r.status_code == 200, 'an oversized screenshot still lets the note through')

print('\n6. No debugger on the network')
main = (ROOT / 'app.py').read_text().split("if __name__ == '__main__':", 1)[1]
check("0.0.0.0" not in main and 'debug=True' not in main, '`python app.py` binds loopback, debugger off by default')
check('Redeploy trigger' not in (ROOT / 'app.py').read_text(), 'the stray redeploy comment is gone')

if failures:
    print(f'\n❌ {len(failures)} failed')
    sys.exit(1)
print('\n✅ all passed')
