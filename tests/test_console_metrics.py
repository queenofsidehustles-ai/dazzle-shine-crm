"""Console → metrics.json: the tenant census, for something that is not a person.

The figures were all on screen already, behind a session and a TOTP prompt and
spread over /companies and /funnel. Nothing that was not a human with a browser
could read them, so an operator report worked the customer count out of the
source tree -- a number inferred from code describing intent instead of taken
from the database holding fact.

What is proved here:

  * the credential bar is the console's own, not a weaker one. In particular a
    signed-in account without two-factor cannot read through this endpoint
    what console_required would not let it read on a page;
  * a missing key does not mean an open door;
  * test companies are counted apart from real ones, because twelve tenants is
    not twelve customers;
  * how balances are collected is reported, since the hourly charge job runs
    for everybody and charges only those who chose `auto` -- "the timetable
    fires" and "the timetable collects" being different facts;
  * a company whose schema will not read is called unreadable rather than
    reported as a company with no clients, which looks identical in a chart.

Against a real disposable Postgres: the control plane is in `public` and each
company's settings are in its own schema, which is the whole point and
something SQLite cannot represent.
"""
import json
import os
import secrets
import sys

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
# Off by default so the body of this test does not need a phone; the two-factor
# bar is then turned on explicitly in the one section that is about it.
os.environ['CONSOLE_REQUIRE_2FA'] = '0'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import automations
import control_plane
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


TAG = secrets.token_hex(4)
REAL = f'metricsreal{TAG}'
TEST = f'metricstest{TAG}'
BOSS = f'console-{TAG}@example.com'
PW = 'a-real-console-password-1'
KEY = secrets.token_hex(16)

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()
    control_plane.add_console_user(engine, BOSS, 'Console Manager', PW,
                                   role='manager')
    db.session.remove()

    provisioning.provision(REAL, 'Real Cleaning Co',
                           owner_email=f'owner-{TAG}@example.com', quiet=True)
    provisioning.provision(TEST, 'Test Cleaning Co',
                           owner_email=f'tester-{TAG}@example.com', quiet=True)
    db.session.remove()
    control_plane.set_test_account(engine, TEST, True)
    db.session.remove()

    # The real company asks for balances to be charged; nobody else does.
    with tenancy.use_tenant(REAL):
        automations.set_balance_mode('auto')
        db.session.commit()
    db.session.remove()

    c = app.test_client()
    URL = '/console/metrics.json'

    def body(resp):
        return json.loads(resp.data.decode())

    def mine(data, slug):
        return next((x for x in data['companies'] if x['slug'] == slug), None)

    print('\n1. No credential is not a credential')
    os.environ.pop('METRICS_API_KEY', None)
    r = c.get(URL)
    check(r.status_code == 403, 'signed out and keyless is refused')
    check(body(r).get('ok') is False, 'and says so in JSON, not an HTML redirect')

    print('\n2. An unset key does not mean an open door')
    r = c.get(URL, headers={'X-Api-Key': KEY})
    check(r.status_code == 403,
          'a key offered when none is configured is still refused')

    print('\n3. A configured key, right and wrong')
    os.environ['METRICS_API_KEY'] = KEY
    r = c.get(URL, headers={'X-Api-Key': 'not-the-key'})
    check(r.status_code == 403, 'the wrong key is refused')
    r = c.get(URL, headers={'X-Api-Key': KEY})
    check(r.status_code == 200, 'the right key is let in')
    r2 = c.get(f'{URL}?api_key={KEY}')
    check(r2.status_code == 200, 'and so is the same key as a query parameter')
    data = body(r)
    check(data.get('ok') is True, 'the document says it is complete')

    print('\n4. It says which code answered')
    check(bool(data['build'].get('channel')),
          'the release channel is on the document, so two weeks can be compared')

    print('\n5. Twelve tenants is not twelve customers')
    real, test = mine(data, REAL), mine(data, TEST)
    check(real is not None and test is not None, 'both companies are listed')
    check(real['is_test'] is False and test['is_test'] is True,
          'and one of them is marked as a test account')
    check(data['tenants']['test'] >= 1, 'test accounts are counted')
    check(data['tenants']['real'] == data['tenants']['total'] - data['tenants']['test']
          - sum(1 for x in data['companies'] if x['is_demo'] and not x['is_test']),
          'and counted out of the real total rather than into it')

    print('\n6. Whether the charge job would actually collect')
    check(real['balance_mode'] == 'auto',
          'the company that opted in is reported as auto')
    check(test['balance_mode'] == automations.BALANCE_DEFAULT,
          f"and one that did not is reported as {automations.BALANCE_DEFAULT}, "
          f"not as auto")
    check(data['balance_collection']['auto'] >= 1,
          'the roll-up counts who would be charged')
    check(data['balance_collection']['of_real'] == data['tenants']['real'],
          'against the number of real companies, so the gap is visible')

    print('\n7. A real company reads')
    check(real['readable'] is True, 'its schema was read')
    check(real['clients'] == 0 and real['bookings_30d'] == 0,
          'and a fresh company honestly has nothing in it')
    check(real['why_unreadable'] is None, 'with no unreadable reason attached')

    print('\n8. An unreadable company is not a company with no customers')
    control_plane.create(engine, f'noschema{TAG}', 'No Schema Co')
    db.session.remove()
    r = c.get(URL, headers={'X-Api-Key': KEY})
    orphan = mine(body(r), f'noschema{TAG}')
    check(orphan is not None, 'a company with no schema still appears')
    check(orphan['readable'] is False, 'marked unreadable')
    check(orphan['clients'] is None,
          'with no client count at all, rather than a zero that reads as fact')
    check(body(r)['tenants']['unreadable'] >= 1, 'and counted as such')

    print('\n9. A console session reads it too')
    os.environ.pop('METRICS_API_KEY', None)
    c.post('/console/login', data={'email': BOSS, 'password': PW})
    r = c.get(URL)
    check(r.status_code == 200, 'a signed-in console account is let in')

    print('\n10. But not past the second factor')
    os.environ['CONSOLE_REQUIRE_2FA'] = '1'
    r = c.get(URL)
    check(r.status_code == 403,
          'an account without TOTP is refused, as console_required would refuse it')
    os.environ['CONSOLE_REQUIRE_2FA'] = '0'
    check(c.get(URL).status_code == 200, 'and let back in when it is not required')
    c.get('/console/logout')

    print('\n11. Reading it changes nothing')
    before = control_plane.find(engine, REAL)
    os.environ['METRICS_API_KEY'] = KEY
    c.get(URL, headers={'X-Api-Key': KEY})
    db.session.remove()
    after = control_plane.find(engine, REAL)
    check(before['plan'] == after['plan']
          and before['subscription_status'] == after['subscription_status'],
          'the company is exactly as it was before the report ran')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 The customer count comes from the database, behind the console\'s own bar.')
