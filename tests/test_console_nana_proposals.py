"""Whether Nana's offers are landing, seen across every company at once.

Every proposal Nana makes — mark a job finished, send outreach, turn on the
morning digest — is written down per tenant, under that tenant's own schema
(see proposals.py, models.AssistantProposal). That is correct for safety and
useless for the question "is anyone actually using this": answering it used
to mean somebody holding the production database URL and writing a query by
hand, one capability at a time.

console.nana_proposals() is the standing answer. Proven here against a real
disposable Postgres (schema-per-tenant needs actual schemas — SQLite cannot
do this), with two tenants that must never see each other's rows.
"""
import os
import secrets
import sys
from datetime import datetime, timedelta

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import control_plane
import provisioning
import tenancy
from models import AssistantProposal

app = create_app()
SLUG_A = 'e2enanaa' + secrets.token_hex(4)
SLUG_B = 'e2enanab' + secrets.token_hex(4)
CONSOLE_EMAIL = f'console-{secrets.token_hex(4)}@example.com'
CONSOLE_PASSWORD = 'a-real-console-password-1'

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def get(client, path, **kw):
    r = client.get(path, **kw)
    db.session.remove()
    return r


def post(client, path, data=None, **kw):
    r = client.post(path, data=data or {}, **kw)
    db.session.remove()
    return r


with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()

    provisioning.provision(SLUG_A, 'E2E Nana Co A', 'ownera@example.com', quiet=True)
    provisioning.provision(SLUG_B, 'E2E Nana Co B', 'ownerb@example.com', quiet=True)
    db.session.remove()

    # Company A: two people asked for the digest, one of them pressed it.
    # Company B: one job-finish offer, never pressed. Deliberately different
    # actions and different press rates, so the aggregation can't pass by
    # accident — a bug that summed everything into one bucket or that
    # counted "offered" as "pressed" would still look right on identical data.
    with tenancy.use_tenant(SLUG_A):
        db.session.add(AssistantProposal(
            token=secrets.token_urlsafe(16), action='enable_owner_digest',
            summary='Turn on the morning digest?', asked_by='owner',
            created_at=datetime.utcnow() - timedelta(hours=2),
            used_at=datetime.utcnow() - timedelta(hours=2), outcome='done: turned on'))
        db.session.add(AssistantProposal(
            token=secrets.token_urlsafe(16), action='enable_owner_digest',
            summary='Turn on the morning digest?', asked_by='owner',
            created_at=datetime.utcnow() - timedelta(hours=1)))
        db.session.commit()
    db.session.remove()

    with tenancy.use_tenant(SLUG_B):
        db.session.add(AssistantProposal(
            token=secrets.token_urlsafe(16), action='complete_booking',
            summary='Mark Rita Vance finished?', asked_by='owner',
            created_at=datetime.utcnow()))
        db.session.commit()
    db.session.remove()

    control_plane.add_console_user(engine, CONSOLE_EMAIL, 'Console Tester',
                                   CONSOLE_PASSWORD, role='owner')
    db.session.remove()

    c = app.test_client()

    print('\n1. Signed out, the page is not reachable')
    r = get(c, '/console/nana', follow_redirects=False)
    check(r.status_code == 302 and 'login' in (r.headers.get('Location') or ''),
          'redirected to the console login, same as every other console page')

    print('\n2. Signed in, it sees across both companies at once')
    r = post(c, '/console/login',
            data={'email': CONSOLE_EMAIL, 'password': CONSOLE_PASSWORD},
            follow_redirects=False)
    check(r.status_code == 302, 'console login succeeds')

    r = get(c, '/console/nana')
    check(r.status_code == 200, 'the page loads')
    body = r.data.decode()
    check('E2E Nana Co A' in body and 'E2E Nana Co B' in body,
          'both companies show up on one page, without either holding the URL')
    check('enable_owner_digest' in body and 'complete_booking' in body,
          'both actions are represented, not just the one this test happened to add first')

    print('\n3. The counts are the real ones, not a coincidence')
    # Real aggregation, checked against the exact rows seeded above — 2
    # offered / 1 pressed for the digest, 1 offered / 0 pressed for
    # complete_booking. Anything that summed both actions together, or
    # conflated "written down" with "pressed", fails a check here.
    check('<td>enable_owner_digest</td>' in body, 'the digest action is its own row')
    digest_row = body.split('<td>enable_owner_digest</td>')[1].split('</tr>')[0]
    check('<td>2</td>' in digest_row, f'offered twice, correctly ({digest_row!r})')
    check('<td>1</td>' in digest_row, f'and pressed once ({digest_row!r})')
    check('50%' in digest_row, f'a 50% adoption rate, computed rather than eyeballed ({digest_row!r})')

    booking_row = body.split('<td>complete_booking</td>')[1].split('</tr>')[0]
    check('<td>0</td>' in booking_row, f'never pressed, correctly zero ({booking_row!r})')
    check('0%' in booking_row, f'0% adoption, not left blank or wrong ({booking_row!r})')

    print('\n4. Newest first, like everything else in this console')
    a_pos = body.find('E2E Nana Co B')   # created last, in the feed section
    b_pos = body.find('E2E Nana Co A')
    check(0 <= a_pos < b_pos, 'the most recently offered row leads the feed')

    print('\n5. A schema that will not read does not take the page down')
    # Simulates a company mid-provisioning or with a stale slug in the
    # control plane -- the one company's failure must not blank the rest.
    control_plane.create(engine, 'e2enana-ghost' + secrets.token_hex(3),
                         'Ghost Co', 'ghost@example.com')
    db.session.remove()
    r = get(c, '/console/nana')
    check(r.status_code == 200,
          'a company with no real schema behind it does not break the page')
    check('E2E Nana Co A' in r.data.decode(),
          'and the companies that do have data are still shown')

    # Cleanup: real schemas against a disposable database — left behind,
    # a re-run collides on slug uniqueness in the control plane.
    from sqlalchemy import text
    for slug in (SLUG_A, SLUG_B):
        try:
            provisioning.drop_schema(engine, tenancy.schema_for(slug))
        except Exception as e:
            print(f'  ⚠️  schema cleanup of {slug!r} left something behind: {e}')
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM public.organizations WHERE slug LIKE 'e2enana%'"))
        conn.execute(text('DELETE FROM public.console_users WHERE email = :e'),
                    {'e': CONSOLE_EMAIL})

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ What Nana has offered, and whether anybody pressed it, in one place — '
      'across every company, without a database URL.')
