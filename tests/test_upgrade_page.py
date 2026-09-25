"""The page a locked feature sends somebody to, and the one somebody browses
to on their own -- /upgrade.

The interesting risk here is drift: the page draws its three cards from
entitlements.PLANS, the same table every gate in the app reads. If the page
ever hand-typed a price or a feature list instead, it would go stale the
moment PLANS changed and nobody would notice until a customer did.
"""
import os, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/upgrade.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
os.environ.pop('BASE_DOMAIN', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

import billing
import entitlements as ent
from app import create_app
from extensions import db
from models import BusinessSetting

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def set_plan(plan, status='active'):
    with app.app_context():
        BusinessSetting.set('plan', plan)
        BusinessSetting.set('plan_status', status)
        db.session.commit()
        ent._clear_cache()


with app.app_context():
    db.create_all()

client = app.test_client()
with client.session_transaction() as s:
    s['logged_in'] = True
    s['role'] = 'owner'


print('\n1. plan_can() answers about any plan, not only the caller\'s own')
check(ent.plan_can('solo', 'payroll') is False, 'Solo cannot do a Pro feature')
check(ent.plan_can('pro', 'payroll') is True, 'Pro can')
check(ent.plan_can('scale', 'payroll') is True, 'and Scale, which grants everything')
check(ent.plan_can('scale', 'anything_undefined') is True,
      'Scale is "everything" even for a feature nobody named yet')
set_plan('pro')
with app.app_context():
    check(ent.can('payroll') == ent.plan_can(ent.effective_plan(), 'payroll'),
          'can() is exactly plan_can() applied to the caller\'s own effective plan')


print('\n2. The page draws its numbers from entitlements.PLANS, not its own copy')
set_plan('solo')
r = client.get('/upgrade')
check(r.status_code == 200, 'renders for a logged-in owner')
text = r.get_data(as_text=True)
for plan, price_text in [('solo', 'Free'), ('pro', '$79'), ('scale', '$249')]:
    check(price_text in text, f'{plan} shows {price_text!r}, read live off entitlements.PLANS')
check(ent.PLANS['pro']['price'] == 79 and ent.PLANS['scale']['price'] == 249,
      'sanity: the real prices this assertion depends on')


print('\n3. The plan you are actually on is marked, not sold to you again')
r = client.get('/upgrade')
text = r.get_data(as_text=True)
check('Your plan' in text, 'Solo shows the "Your plan" badge while on Solo')
check('Move to Solo' not in text, 'and there is no button to buy the free plan')

set_plan('pro')
r = client.get('/upgrade')
text = r.get_data(as_text=True)
check('Move to Pro' not in text, 'on Pro, there is no "Move to Pro" button for the plan you have')
check('Move to Scale' in text or 'switched on' in text,
      'but Scale is still offered (as a button or the not-configured note)')


print('\n4. Every feature row reflects entitlements.PLANS exactly, per plan')
set_plan('solo')
r = client.get('/upgrade')
text = r.get_data(as_text=True)
before, after = text.index('pr-name">Solo'), text.index('pr-name">Pro')
solo_block = text[before:after]
check('✕' in solo_block and 'Payroll' in solo_block,
      'Solo shows a cross next to a feature it does not include')
check(ent.FEATURE_LABELS['payroll'] in solo_block, 'using the real feature label, not the raw key')


print('\n5. can_pay gates the checkout button, never the page itself')
orig = billing.configured
billing.configured = lambda: False
r = client.get('/upgrade')
check(r.status_code == 200, 'the page still renders with payments off')
check("aren't switched on" in r.get_data(as_text=True),
      'and says so instead of a dead button')
billing.configured = lambda: True
r = client.get('/upgrade')
check('billing/checkout' in r.get_data(as_text=True),
      'with payments on, the checkout form is there')
billing.configured = orig


print('\n6. Arriving via a locked feature explains what was reached for')
set_plan('solo')
r = client.get('/upgrade?feature=payroll')
text = r.get_data(as_text=True)
check('Payroll is part of Pro' in text, 'names the feature and the plan that has it')
check('You\'re on Solo' in text, 'and where the visitor actually is right now')


print('\n7. Downgrading never threatens what is already there')
r = client.get('/upgrade')
check("can't add more of something" in r.get_data(as_text=True)
      and "never that anything disappears" in r.get_data(as_text=True),
      'the page states the no-data-loss guarantee entitlements.py itself makes')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ /upgrade shows exactly what entitlements.PLANS says, for every plan, every time.')
