"""Paying for the product, and what happens when the payment fails.

Two things here are worth more than the rest.

**A browser redirect must not upgrade anybody.** Stripe sends the customer back
to a success URL after checkout, and that URL is a link like any other — it can
be opened, shared, bookmarked or typed. If arriving there changed the plan, the
plan could be changed by visiting a page.

**A failed card must not take a business off its own schedule.** Dropping to the
free plan is right. Locking the owner out of her own bookings over an expired
card, or deleting anything, is how a customer never comes back — and it would be
holding her data hostage over $99.
"""
import os, sys, subprocess
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


import billing

print('\n1. Which plan a company may actually use')
now = datetime.utcnow()
soon, past = now + timedelta(days=5), now - timedelta(days=1)
for org, want, why in [
    (None, 'solo', 'no company at all'),
    ({'plan': 'pro', 'subscription_status': 'active'}, 'pro', 'a paid-up subscription'),
    ({'plan': 'scale', 'subscription_status': 'active'}, 'scale', 'the top plan'),
    ({'plan': 'pro', 'subscription_status': 'trialing', 'trial_ends_at': soon},
     'pro', 'a trial still running'),
    ({'plan': 'pro', 'subscription_status': 'trialing', 'trial_ends_at': past},
     'solo', 'a trial that has ended'),
    ({'plan': 'pro', 'subscription_status': 'past_due'}, 'solo', 'a failed payment'),
    ({'plan': 'pro', 'subscription_status': 'canceled'}, 'solo', 'a cancellation'),
    ({'plan': 'pro', 'subscription_status': 'unpaid'}, 'solo', 'an unpaid subscription'),
    ({'plan': 'scale', 'subscription_status': 'active', 'status': 'suspended'},
     'solo', 'a company we have suspended'),
]:
    got = billing.plan_for(org)
    check(got == want, f'{why} → {got}')

print('\n2. An unknown or nonsense status falls back to free, never to locked')
for status in ('incomplete', 'incomplete_expired', 'paused', '', None, 'nonsense'):
    check(billing.plan_for({'plan': 'scale', 'subscription_status': status}) == 'solo',
          f'status {status!r} → solo')

print('\n3. Events state facts, so processing one twice changes nothing')
# Stripe retries until it gets a 200 and will happily deliver the same event
# again. Nothing in apply_event increments, adds or toggles.
import inspect as _inspect
src = _inspect.getsource(billing.apply_event)
for danger in ('+=', '-=', 'append(', 'increment'):
    check(danger not in src,
          f'no {danger!r} anywhere in the event handler')

print('\n4. The success page cannot change anything')
import blueprints.billing_routes as routes
ret = _inspect.getsource(routes.checkout_return)
for danger in ('set_billing', 'plan=', 'subscription_status', 'control_plane'):
    check(danger not in ret,
          f'the return page does not touch {danger!r}')
check('render_template' in ret, 'it only renders a page')

hook = _inspect.getsource(routes.stripe_webhook)
check('construct_event' in hook, 'the webhook verifies the signature')
check(hook.index('construct_event') < hook.index('apply_event'),
      'and does so BEFORE acting on anything in the payload')

print('\n5. A webhook with no signature, or a wrong one, is refused')


def postgres_url():
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres'):
        if not candidate:
            continue
        try:
            from sqlalchemy import create_engine, text
            e = create_engine(candidate)
            with e.connect() as c:
                c.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n' + '=' * 70)
    print('  ⚠️  SKIPPED: the rest needs PostgreSQL and found no server.')
    print('=' * 70 + '\n')
    sys.exit(0)

DB = 'dsm_billing_test'
TEST_URL = f'{PG.rsplit("/", 1)[0]}/{DB}'
from sqlalchemy import create_engine, text
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as c:
    c.execute(text(f'DROP DATABASE IF EXISTS {DB}'))
    c.execute(text(f'CREATE DATABASE {DB}'))

env = dict(os.environ, DATABASE_URL=TEST_URL, SECRET_KEY='test',
           BASE_DOMAIN='rollcall.test', SIGNUPS_OPEN='1',
           STRIPE_PLATFORM_SECRET_KEY='sk_test_fake',
           STRIPE_PLATFORM_WEBHOOK_SECRET='whsec_fake',
           STRIPE_PRICE_PRO='price_pro', STRIPE_PRICE_SCALE='price_scale')
env.pop('ADMIN_USER', None)
env.pop('ADMIN_PASS', None)

STUB = '''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
'''


def run(code, label, extra_env=None):
    e = dict(env, **(extra_env or {}))
    r = subprocess.run([sys.executable, '-c', code], capture_output=True,
                       text=True, cwd=ROOT, env=e)
    if 'OK' not in r.stdout:
        raise AssertionError(f'{label}:\n{r.stdout}\n{r.stderr}')
    return r.stdout


out = run(STUB + '''
from app import create_app
app = create_app()
c = app.test_client()
H = {"Host": "rollcall.test"}
print("NO SIG:", c.post("/api/stripe/webhook", data=b"{}", headers=H).status_code)
print("BAD SIG:", c.post("/api/stripe/webhook", data=b'{"type":"x"}',
      headers=dict(H, **{"Stripe-Signature": "t=1,v1=deadbeef"})).status_code)
print("OK")
''', 'webhook signature')
check('NO SIG: 400' in out, 'an unsigned payload is refused')
check('BAD SIG: 400' in out, 'and so is one with a forged signature')

print('\n6. A company subscribes, and only the webhook changes what it gets')
run(STUB + '''
import provisioning
provisioning.provision("acme", "Acme Cleaning", "owner@acme.test", quiet=True)
print("OK")
''', 'provision')

out = run(STUB + '''
import control_plane, billing, provisioning
eng = provisioning._engine()
org = control_plane.find(eng, "acme")
print("START PLAN:", billing.plan_for(org), org["subscription_status"])

# Exactly what Stripe sends when a subscription starts.
ok, detail = billing.apply_event({
    "type": "customer.subscription.created",
    "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "active",
        "metadata": {"slug": "acme", "plan": "pro"},
        "current_period_end": 1800000000,
    }}})
org = control_plane.find(eng, "acme")
print("AFTER:", ok, billing.plan_for(org), org["stripe_subscription_id"])

# The same event again, four more times.
for _ in range(4):
    billing.apply_event({
        "type": "customer.subscription.created",
        "data": {"object": {
            "id": "sub_1", "customer": "cus_1", "status": "active",
            "metadata": {"slug": "acme", "plan": "pro"},
            "current_period_end": 1800000000,
        }}})
org = control_plane.find(eng, "acme")
print("AFTER 5x:", billing.plan_for(org), org["plan"], org["subscription_status"])
print("OK")
''', 'subscription created')
check('START PLAN: solo trialing' in out, 'a new company starts on the free plan')
check('AFTER: True pro sub_1' in out, 'a subscription event moves it to Pro')
check('AFTER 5x: pro pro active' in out,
      'and the same event five times leaves it in exactly the same place')

print('\n7. A failed payment drops the plan and keeps every record')
out = run(STUB + '''
import control_plane, billing, provisioning, tenancy
from app import create_app
from extensions import db
from models import Client, Booking
eng = provisioning._engine()
app = create_app()
with app.app_context():
    with tenancy.use_tenant("acme"):
        db.session.add_all([Client(name="Mrs Johnson", email="j@x.test"),
                            Booking(service_type="deep", name="Thursday", price=280.0)])
        db.session.commit()

billing.apply_event({"type": "invoice.payment_failed",
                     "data": {"object": {"customer": "cus_1"}}})
org = control_plane.find(eng, "acme")
print("PLAN NOW:", billing.plan_for(org), "STATUS:", org["subscription_status"])
print("STILL PAYING FOR:", org["plan"])
with app.app_context():
    with tenancy.use_tenant("acme"):
        print("CLIENTS:", Client.query.count(), "JOBS:", Booking.query.count())
        print("JOB NAME:", Booking.query.first().name)
print("OK")
''', 'payment failed')
check('PLAN NOW: solo STATUS: past_due' in out, 'a failed payment drops them to free')
check('STILL PAYING FOR: pro' in out, 'while what they bought is still recorded')
check('CLIENTS: 1 JOBS: 1' in out, 'and every customer and job is still there')
check('JOB NAME: Thursday' in out, 'unchanged')

print('\n8. Paying again puts it straight back')
out = run(STUB + '''
import control_plane, billing, provisioning
eng = provisioning._engine()
billing.apply_event({"type": "invoice.paid",
                     "data": {"object": {"customer": "cus_1"}}})
org = control_plane.find(eng, "acme")
print("RESTORED:", billing.plan_for(org), org["subscription_status"])
print("OK")
''', 'paid again')
check('RESTORED: pro active' in out, 'the plan comes back without anybody re-entering anything')

print('\n9. Cancelling keeps the data')
out = run(STUB + '''
import control_plane, billing, provisioning, tenancy
from app import create_app
from models import Client
eng = provisioning._engine()
billing.apply_event({"type": "customer.subscription.deleted",
                     "data": {"object": {"id": "sub_1", "customer": "cus_1",
                                         "status": "canceled",
                                         "metadata": {"slug": "acme"}}}})
org = control_plane.find(eng, "acme")
print("AFTER CANCEL:", billing.plan_for(org), org["subscription_status"])
app = create_app()
with app.app_context():
    with tenancy.use_tenant("acme"):
        print("CLIENTS STILL THERE:", Client.query.count())
print("OK")
''', 'cancelled')
check('AFTER CANCEL: solo canceled' in out, 'cancelling drops them to free')
check('CLIENTS STILL THERE: 1' in out,
      'and does not delete a single customer — their data is theirs')

print('\n10. An event for a company we do not know is acknowledged, not obeyed')
out = run(STUB + '''
import billing
ok, detail = billing.apply_event({
    "type": "customer.subscription.updated",
    "data": {"object": {"id": "sub_x", "customer": "cus_nobody",
                        "status": "active", "metadata": {"slug": "not-a-company"}}}})
print("HANDLED:", ok)
print("DETAIL:", detail)
print("OK")
''', 'unknown company')
check('HANDLED: False' in out, 'nothing is changed for a company that does not exist')
check('no company for' in out, 'and it says so rather than failing silently')

print('\n11. What a company pays cannot be edited from inside its own CRM')
# The subscription lives in the control plane, not in the company's schema, so
# nothing the business can reach through its own software can change it.
out = run(STUB + '''
import provisioning, extensions
from sqlalchemy import inspect as si
eng = provisioning._engine()
with eng.connect() as c:
    acme = set(si(c).get_table_names(schema="tenant_acme"))
print("ORGS INSIDE ACME:", "organizations" in acme)
print("BILLING IN MODELS:", any("subscription" in t for t in extensions.db.metadata.tables))
print("OK")
''', 'control plane isolation')
check('ORGS INSIDE ACME: False' in out,
      'the subscription record is not inside the company schema')
check('BILLING IN MODELS: False' in out,
      'and no billing table is part of what a company gets a copy of')

with admin.connect() as c:
    c.execute(text(f'DROP DATABASE IF EXISTS {DB}'))

print('\n\n✅ All billing tests passed.\n')
