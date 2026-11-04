"""Tell another cleaning owner, and you both get a month free.

What could go wrong, and what this holds:

  * money -- a webhook delivered five times crediting five times; a free or
    trial invoice crediting anything; a second invoice crediting again; more
    than 12 free months; a refunded first invoice leaving a free month behind;
  * the wrong people -- an owner referring themselves (same mailbox, same
    phone), a test or demo company, a company a partner brought (the partner
    already earns on it), a made-up referrer;
  * failure -- Stripe being down must leave the reward waiting and retried,
    never lost and never credited twice;
  * the switch -- off means nothing is credited, and fails closed;
  * what the owner sees -- names and states only, the thank-you only where the
    free month is real, the nudge only for an owner with a paid job.

Runs against a real PostgreSQL: the control plane lives in the `public` schema.
"""
import os
import secrets
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def postgres_url():
    from sqlalchemy import create_engine, text
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      'postgresql://app_user:localtest@127.0.0.1:5432/postgres',
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres'):
        if not candidate:
            continue
        try:
            e = create_engine(candidate)
            with e.connect() as c:
                c.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n  ⚠️  SKIPPED: no PostgreSQL server found.')
    sys.exit(0)

from sqlalchemy import create_engine, text

DB = 'dsm_referrals_test'
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as conn:
    conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
    conn.execute(text(f'CREATE DATABASE {DB}'))
os.environ.update(DATABASE_URL=f'{PG.rsplit("/", 1)[0]}/{DB}', SECRET_KEY='ref-test',
                  BASE_DOMAIN='akyehq.test', SIGNUPS_OPEN='1')
for k in ('ADMIN_USER', 'ADMIN_PASS', 'CANONICAL_HOST', 'REFERRAL_REWARDS_OPEN'):
    os.environ.pop(k, None)

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')
from app import create_app
import billing
import control_plane
import platform_switches
import provisioning
import referrals

app = create_app()
TAG = secrets.token_hex(3)
CALLS = []
FAIL = {'on': False}


def fake_balance(customer, cents, description, key, metadata):
    if FAIL['on']:
        raise RuntimeError('Stripe is down')
    CALLS.append({'customer': customer, 'cents': cents, 'key': key})
    return {'id': f'cbtxn_{len(CALLS)}'}


referrals._balance_transaction = fake_balance

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)


def company(slug, email=None, phone=None, referred_by=None, mrr=None, **flags):
    with app.app_context():
        control_plane.create(engine, slug, slug.title(),
                             owner_email=email or f'{slug}@example.com',
                             owner_phone=phone)
        fields = dict(stripe_customer_id=f'cus_{slug}', subscription_status='active')
        if mrr:
            fields['mrr_cents'] = mrr
        control_plane.set_billing(engine, slug, **fields)
        with engine.begin() as conn:
            vals = dict(flags)
            if referred_by:
                vals['referred_by'] = referred_by
            if vals:
                sets = ', '.join(f'{k} = :{k}' for k in vals)
                conn.execute(text(f'update public.organizations set {sets} where slug = :s'),
                             dict(vals, s=slug))
    return slug


def paid(slug, inv, cents=7900, tax=0):
    return billing.apply_event({'type': 'invoice.paid', 'data': {'object': {
        'id': inv, 'customer': f'cus_{slug}', 'amount_paid': cents + tax,
        'total_excluding_tax': cents, 'tax': tax,
        'status_transitions': {'paid_at': int(datetime.utcnow().timestamp())}}}})


def rows(referred=None, referrer=None):
    q, args = 'select * from public.referral_rewards where true', {}
    if referred:
        q += ' and referred_slug = :a'; args['a'] = referred
    if referrer:
        q += ' and referrer_slug = :b'; args['b'] = referrer
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(q + ' order by id'), args).mappings()]


dana = company(f'dana{TAG}', mrr=9900)

print('\n1. The first paid invoice earns each side a month, once')
sam = company(f'sam{TAG}', referred_by=dana)
with app.app_context():
    ev = paid(sam, f'in_{TAG}_1')
    paid(sam, f'in_{TAG}_1')
    billing.apply_event({'type': 'invoice.payment_succeeded', 'data': {'object': {
        'id': f'in_{TAG}_1', 'customer': f'cus_{sam}', 'amount_paid': 7900,
        'total_excluding_tax': 7900, 'tax': 0}}})
r = rows(referred=sam)
check(len(r) == 2 and {x['side'] for x in r} == {'referrer', 'referred'},
      f'the same invoice delivered three ways earns one reward per side ({len(r)})')
by = {x['side']: x for x in r}
check(by['referred']['amount_cents'] == 7900, 'the new company gets its own first month')
check(by['referrer']['amount_cents'] == 9900, "the referrer gets a month of her own price")
check(all(x['status'] == 'applied' for x in r), 'both are credited')
check(len(CALLS) == 2, f'Stripe was asked exactly twice ({len(CALLS)})')
check(sorted(c['cents'] for c in CALLS) == [-9900, -7900] and
      {c['customer'] for c in CALLS} == {f'cus_{dana}', f'cus_{sam}'},
      'a credit (negative) on each company\'s own customer')
with app.app_context():
    paid(sam, f'in_{TAG}_2')
check(len(rows(referred=sam)) == 2 and len(CALLS) == 2, 'a second invoice earns nothing')

print('\n2. A free, discounted or taxed-only invoice earns nothing')
lee = company(f'lee{TAG}', referred_by=dana)
with app.app_context():
    paid(lee, f'in_{TAG}_lee0', cents=0)
check(rows(referred=lee) == [], 'a $0 invoice (trial, 100% code) earns nothing')
with app.app_context():
    paid(lee, f'in_{TAG}_lee1', cents=7900, tax=600)
check({x['side']: x['amount_cents'] for x in rows(referred=lee)}.get('referred') == 7900,
      'tax is not credited back')
check(len(CALLS) == 4, 'and the real invoice, when it comes, does')

print('\n3. Not for the wrong people')
before = len(CALLS)
me = company(f'me{TAG}', email=f'owner{TAG}@gmail.com', referred_by=f'twin{TAG}')
twin = company(f'twin{TAG}', email=f'o.wner{TAG}@gmail.com')
with app.app_context():
    paid(me, f'in_{TAG}_me')
r = rows(referred=me)
check(len(r) == 2 and all(x['status'] == 'blocked' and 'email' in x['reason'] for x in r),
      'the same mailbox (Gmail dots) is recorded as blocked, with why')
ph1 = company(f'ph1{TAG}', phone='+14075550100')
ph2 = company(f'ph2{TAG}', phone='+14075550100', referred_by=ph1)
with app.app_context():
    paid(ph2, f'in_{TAG}_ph')
check(all(x['status'] == 'blocked' and 'phone' in x['reason'] for x in rows(referred=ph2)),
      'and the same phone number')
tst = company(f'tst{TAG}', referred_by=dana, is_test=True)
dem = company(f'dem{TAG}', referred_by=dana, is_demo=True)
part = company(f'part{TAG}', referred_by=dana, affiliate_code='someone')
ghost = company(f'ghost{TAG}', referred_by=f'nobody{TAG}')
with app.app_context():
    for s in (tst, dem, part, ghost):
        paid(s, f'in_{TAG}_{s}')
check(all(rows(referred=s) == [] for s in (tst, dem, part, ghost)),
      'a test company, a demo, one a partner brought, and a made-up referrer earn nothing')
check(len(CALLS) == before, 'and no credit was given for any of them')

print('\n4. At most 12 free months')
cap = company(f'cap{TAG}', mrr=5000)
kids = [company(f'k{i}x{TAG}', referred_by=cap) for i in range(13)]
CALLS.clear()
with app.app_context():
    for i, k in enumerate(kids):
        paid(k, f'in_{TAG}_k{i}')
mine = rows(referrer=cap)
mine_r = [x for x in mine if x['side'] == 'referrer']
check(sum(1 for x in mine_r if x['status'] == 'applied') == 12, 'twelve months are credited')
check([x['status'] for x in mine_r][-1] == 'capped', 'the thirteenth is recorded as capped')
last = [x for x in mine if x['side'] == 'referred'][-1]
check(last['status'] == 'applied', 'but the thirteenth company still gets its own month')
check(len(CALLS) == 25, f'12 + 13 credits ({len(CALLS)})')

print('\n5. Stripe being down leaves it waiting, then it is credited once')
FAIL['on'] = True
bob = company(f'bob{TAG}', referred_by=dana)
CALLS.clear()
with app.app_context():
    ok, _ = paid(bob, f'in_{TAG}_bob')
check(ok, 'the payment itself is still recorded')
r = rows(referred=bob)
check(all(x['status'] == 'pending' and x['last_error'] for x in r),
      'both rewards wait, with the error written down')
FAIL['on'] = False
with app.app_context():
    paid(bob, f'in_{TAG}_bob2')
r = rows(referred=bob)
check(all(x['status'] == 'applied' for x in r) and len(CALLS) == 2,
      'the next payment credits them, once each')
with app.app_context():
    referrals.apply_pending(engine, bob)
check(len(CALLS) == 2, 'applying again credits nothing more')

print('\n6. A referrer still on a trial is credited on her first payment')
trial = company(f'trial{TAG}')
with engine.begin() as conn:
    conn.execute(text('update public.organizations set stripe_customer_id = null where slug = :s'),
                 {'s': trial})
amy = company(f'amy{TAG}', referred_by=trial)
CALLS.clear()
with app.app_context():
    paid(amy, f'in_{TAG}_amy')
r = {x['side']: x for x in rows(referred=amy)}
check(r['referred']['status'] == 'applied' and r['referrer']['status'] == 'pending',
      'the new company is credited, the referrer waits')
check(r['referrer']['amount_cents'] == 7900, 'and her credit falls back to the invoice amount')
with engine.begin() as conn:
    conn.execute(text('update public.organizations set stripe_customer_id = :c where slug = :s'),
                 {'c': f'cus_{trial}', 's': trial})
with app.app_context():
    paid(trial, f'in_{TAG}_trial')
check({x['status'] for x in rows(referrer=trial) if x['side'] == 'referrer'} == {'applied'},
      'her own first payment credits it')

print('\n7. A refund of the first invoice takes it back')
joe = company(f'joe{TAG}', referred_by=dana)
CALLS.clear()
with app.app_context():
    paid(joe, f'in_{TAG}_joe')
    billing.apply_event({'type': 'charge.refunded', 'data': {'object': {
        'invoice': f'in_{TAG}_joe', 'customer': f'cus_{joe}', 'refunded': True,
        'metadata': {'slug': joe}}}})
r = rows(referred=joe)
check(all(x['status'] == 'reversed' for x in r), 'both rewards are reversed')
check(sorted(c['cents'] for c in CALLS) == [-9900, -7900, 7900, 9900],
      'each credit that was given is matched by a charge back')
n = len(CALLS)
with app.app_context():
    referrals.reverse(engine, f'in_{TAG}_joe')
check(len(CALLS) == n, 'reversing twice takes back once')

print('\n8. The switch')
os.environ['REFERRAL_REWARDS_OPEN'] = '0'
platform_switches.clear_cache()
off = company(f'off{TAG}', referred_by=dana)
CALLS.clear()
with app.app_context():
    paid(off, f'in_{TAG}_off')
check(rows(referred=off) == [] and CALLS == [], 'closed from the environment: nothing earned, nothing credited')
os.environ.pop('REFERRAL_REWARDS_OPEN')
platform_switches.clear_cache()
with app.app_context():
    platform_switches.set_switch(engine, 'referral_rewards', False, 'test')
    paid(off, f'in_{TAG}_off2')
check(rows(referred=off) == [], 'turned off in the console: nothing earned')
with app.app_context():
    platform_switches.set_switch(engine, 'referral_rewards', True, 'test')
    paid(off, f'in_{TAG}_off3')
check(len(rows(referred=off)) == 2, 'and earned once it is back on (the first paid invoice has not been lost)')
check([s for s in platform_switches.states(engine) if s['key'] == 'referral_rewards'][0]['on'],
      'the console lists it')

print('\n9. What the owner sees')
with app.app_context():
    s = referrals.summary(engine, dana)
check(s['cap'] == 12 and s['signed_up'] >= 5 and s['months'] >= 3,
      f'counts of companies and months ({s["signed_up"]} signed up, {s["months"]} months)')
check(all(set(r) == {'name', 'state'} for r in s['rows']),
      'names and states only: never an address or a number')
with app.app_context():
    check(referrals.sender_name(engine, dana) == dana.title(), 'the sender is named on the signup page')
    check(referrals.sender_name(engine, tst) is None and referrals.sender_name(engine, 'nope') is None,
          'but not a test company or a made-up one')
c = app.test_client()
import attribution
resp = c.get(f'/r/{dana}', headers={'Host': 'akyehq.test'})
r = c.get('/signup', headers={'Host': 'akyehq.test'})
check(f'{dana.title()} sent you' in r.get_data(as_text=True),
      'a visitor who came through a link is told who sent them, and that it is a free month')
c2 = app.test_client()
r = c2.get('/signup', headers={'Host': 'akyehq.test'})
check('sent you' not in r.get_data(as_text=True), 'and nobody else is promised one')

print('\n10. The billing page and the dashboard nudge')
with app.app_context():
    provisioning.provision(f'shop{TAG}', 'Shop Co', owner_email=f'shop{TAG}@example.com', quiet=True)
H = {'Host': f'shop{TAG}.akyehq.test'}
import auth, tenancy
from extensions import db
from models import Booking, User
with app.app_context():
    with tenancy.use_tenant(f'shop{TAG}'):
        u = User(name='Owner', username='owner', role='owner', password_hash='x')
        db.session.add(u)
        db.session.commit()
        OWNER_ID = u.id
oc = app.test_client()
with oc.session_transaction(base_url=f'http://shop{TAG}.akyehq.test') as sess:
    sess.update(logged_in=True, role='owner', user_id=OWNER_ID, user_name='Owner',
                tenant_slug=f'shop{TAG}',
                auth_fingerprint=auth._auth_fingerprint('x'))
r = oc.get('/billing', base_url=f'http://shop{TAG}.akyehq.test')
html = r.get_data(as_text=True)
check(r.status_code == 200 and 'Give a month, get a month' in html
      and f'/r/shop{TAG}' in html and 'Text it' in html and 'Email it' in html,
      'Billing offers the link with Text, Email and Copy')
r = oc.get('/', base_url=f'http://shop{TAG}.akyehq.test', follow_redirects=True)
check('Know another cleaning owner' not in r.get_data(as_text=True),
      'the nudge waits until a job has been paid for')
with app.app_context():
    with tenancy.use_tenant(f'shop{TAG}'):
        db.session.add(Booking(service_type='deep', name='A Customer', email='a@x.test',
                               phone='4075550101', address='1 Main', price=100.0,
                               status='completed', preferred_date='2030-01-01',
                               preferred_time='9:00 AM', paid_at=datetime.utcnow()))
        db.session.commit()
r = oc.get('/', base_url=f'http://shop{TAG}.akyehq.test', follow_redirects=True)
check('Know another cleaning owner' in r.get_data(as_text=True), 'and appears after the first paid job')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print('   -', f)
    sys.exit(1)
print('✅ A month for both, once, within limits, and never lost or doubled.')
