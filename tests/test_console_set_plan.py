"""Console → a company's plan, written where the application actually reads it.

Two records answer "what has this company bought". The control-plane row is
what billing and Stripe believe. `BusinessSetting('plan')`, inside the
company's own schema, is what entitlements._load_state reads when it decides
whether to show Quotes, Invoices, Reports or Payroll.

Nothing wrote the second one. A company whose schema never got that row falls
back to DEFAULT_PLAN -- solo, whose feature set is empty -- no matter how
healthy the billing row looks beside it. That is a paying customer staring at a
product with most of it missing, and no screen anywhere to put it right.

Against a real disposable Postgres: the control plane lives in `public` and the
company's settings live in its own schema, which is the whole point here and
something SQLite cannot represent.
"""
import os
import secrets
import sys

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
import entitlements

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


TAG = secrets.token_hex(4)
SLUG = f'plantest{TAG}'
BOSS = f'console-{TAG}@example.com'
HELPER = f'helper-{TAG}@example.com'
PW = 'a-real-console-password-1'

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()
    control_plane.add_console_user(engine, BOSS, 'Console Manager', PW, role='manager')
    control_plane.add_console_user(engine, HELPER, 'Console Helper', PW, role='helper')
    db.session.remove()

    provisioning.provision(SLUG, 'Plan Test Cleaning', owner_email=f'owner-{TAG}@example.com',
                           quiet=True)
    db.session.remove()

    def tenant_plan():
        """What the application itself would enforce for this company."""
        db.session.remove()
        try:
            with tenancy.use_tenant(SLUG):
                return entitlements.state()['effective_plan']
        finally:
            db.session.remove()

    print('\n1. The gap this exists to close')
    start = tenant_plan()
    check(start == 'solo',
          f'a fresh company enforces solo in its own schema (got {start})')
    check(not entitlements.plan_can(start, 'commercial'),
          'so Quotes is locked, whatever the billing row says')

    c = app.test_client()

    print('\n2. A helper may read but not change a plan')
    c.post('/console/login', data={'email': HELPER, 'password': PW})
    r = c.post(f'/console/companies/{SLUG}/plan', data={'plan': 'scale'},
               follow_redirects=True)
    check(r.status_code == 200, 'the attempt is handled, not crashed')
    check(tenant_plan() == 'solo', 'and the plan did not move')
    c.get('/console/logout')

    print('\n3. A manager puts them on Scale, free of charge')
    c.post('/console/login', data={'email': BOSS, 'password': PW})
    r = c.post(f'/console/companies/{SLUG}/plan',
               data={'plan': 'scale', 'free': '1'}, follow_redirects=True)
    check(r.status_code == 200, 'the form is accepted')
    check(tenant_plan() == 'scale',
          'the company now enforces Scale in its own schema — the half nothing wrote before')

    print('\n4. Which is the point: the locked features unlock')
    db.session.remove()
    try:
        with tenancy.use_tenant(SLUG):
            st = entitlements.state()
            can_commercial = entitlements.can('commercial')
            can_invoices = entitlements.can('invoices')
            grand = st['grandfathered']
    finally:
        db.session.remove()
    check(can_commercial, 'Quotes and commercial accounts are available')
    check(can_invoices, 'so is invoicing')
    check(grand, 'and they are marked as carried free of charge')

    print('\n5. Both records agree, so billing cannot contradict the app')
    org = control_plane.find(engine, SLUG)
    check(org['plan'] == 'scale', 'the control-plane row says scale too')
    check(bool(org['grandfathered']), 'and that it is free')
    check((org['subscription_status'] or '').lower() == 'active',
          'with an active subscription status rather than a dangling trial')

    print('\n6. It is written down who did it')
    log = [r for r in control_plane.console_log_all(engine) if r.get('target') == SLUG]
    entry = next((r for r in log if 'plan' in (r.get('action') or '')), None)
    check(entry is not None, 'the change is in the console log')
    check(entry and entry.get('actor') == BOSS, 'against the manager who made it')
    check(entry and 'free of charge' in (entry.get('detail') or ''),
          'recording that it was granted, not sold')

    print('\n7. Guards')
    r = c.post(f'/console/companies/{SLUG}/plan', data={'plan': 'enterprise'},
               follow_redirects=True)
    check(tenant_plan() == 'scale', 'a plan that does not exist is refused')
    r = c.post(f'/console/companies/not-a-company-{TAG}/plan',
               data={'plan': 'pro'}, follow_redirects=True)
    check(r.status_code == 200, 'an unknown company is handled rather than crashing')

    print('\n8. And it can be taken back down')
    c.post(f'/console/companies/{SLUG}/plan', data={'plan': 'pro'}, follow_redirects=True)
    check(tenant_plan() == 'pro', 'dropping them to Pro takes effect')
    db.session.remove()
    try:
        with tenancy.use_tenant(SLUG):
            check(not entitlements.can('commercial'),
                  'and Quotes locks again, because Pro does not include it')
    finally:
        db.session.remove()

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 A plan set in the console is a plan the application honours.')
