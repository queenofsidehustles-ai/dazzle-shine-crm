"""Plans: what a business may do, and what it keeps when it stops paying.

The two failures worth writing a test for are asymmetric. Letting a free
business use a paid feature costs money. Locking a paying business out of one
they bought, or making a downgrade eat records they entered, costs the customer
— so most of what follows is about the second kind.
"""
import os, sys, tempfile
from datetime import datetime, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/plans.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import BusinessSetting, Staff, Booking, EntitlementDenial
import entitlements as ent
import navigation

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def set_plan(plan, status='active', trial_ends=None):
    BusinessSetting.set('plan', plan)
    BusinessSetting.set('plan_status', status)
    BusinessSetting.set('trial_ends_at', trial_ends.isoformat() if trial_ends else '')
    db.session.commit()
    ent._clear_cache()


with app.app_context():
    db.create_all()

    print('\n1. A deployment with no plan set is on the free plan, not locked out')
    BusinessSetting.set('plan', '')
    db.session.commit()
    check(ent.effective_plan() == 'solo', 'no plan configured falls back to Solo')
    check(ent.can('sms') is False, 'Solo cannot send SMS')
    check(ent.limit('clients') is None, 'Solo never caps clients — their business, not ours')

    print('\n2. Features unlock upward, and the top plan gets everything')
    set_plan('solo')
    check(not ent.can('hiring'), 'Solo cannot use the hiring funnel')
    check(not ent.can('payroll'), 'Solo cannot use payroll')
    set_plan('pro')
    check(ent.can('hiring'), 'Pro can use the hiring funnel')
    check(ent.can('payroll') and ent.can('sms'), 'Pro gets crew pay and texting')
    check(not ent.can('commercial'), 'Pro does not get commercial accounts')
    set_plan('scale')
    check(ent.can('commercial'), 'Scale gets commercial accounts')
    for f in ent.FEATURE_LABELS:
        check_all = ent.can(f)
        assert check_all, f'FAILED: Scale should include {f}'
    print('  ✅ Scale includes every named feature')

    print('\n3. The core loop is free — this is the whole freemium bet')
    set_plan('solo')
    for endpoint in ('bookings.index', 'bookings.calendar', 'bookings.clients',
                     'workorders.templates', 'messages.inbox', 'contractors.team'):
        check(navigation.feature_for(endpoint) is None,
              f'{endpoint} is on the free plan')

    print('\n4. A trial is a real Pro trial, not a decorated free plan')
    set_plan('solo', trial_ends=datetime.utcnow() + timedelta(days=7))
    check(ent.effective_plan() == 'pro', 'a live trial grants Pro')
    check(ent.state()['on_trial'] and ent.state()['trial_days_left'] > 0,
          'the trial reports days remaining')
    check(ent.limit('field_workers') == 10, 'trial gets the Pro worker limit')
    set_plan('solo', trial_ends=datetime.utcnow() - timedelta(days=1))
    check(ent.effective_plan() == 'solo', 'an expired trial falls back to Solo')

    print('\n5. An unpaid card drops the plan — it does not lock the app')
    set_plan('pro', status='past_due')
    check(ent.effective_plan() == 'solo', 'past_due drops to Solo')
    check(ent.state()['plan'] == 'pro', 'what they bought is still recorded')
    # A trial only ever applies to a business that has not bought anything. By
    # the time Stripe reports 'canceled' the paid period has already run out —
    # cancelling sets cancel_at_period_end and the status stays active until
    # then. So a signup trial date still sitting in the row must not hand Pro
    # back to somebody who cancelled.
    set_plan('pro', status='canceled', trial_ends=datetime.utcnow() + timedelta(days=3))
    check(ent.effective_plan() == 'solo', 'a stale trial date does not resurrect a cancelled plan')

    print('\n6. Limits count real records, and block the next one — not the last one')
    set_plan('solo')
    for i in range(2):
        db.session.add(Staff(name=f'Cleaner {i}', is_active=True))
    db.session.commit()
    check(ent.usage('field_workers') == 2, 'two active cleaners are counted')
    check(ent.at_limit('field_workers'), 'Solo is at its 2-cleaner limit')
    ok, msg = ent.check_limit('field_workers')
    check(not ok and 'Pro' in msg and '99' in msg,
          f'the refusal names the plan and the price: {msg!r}')

    set_plan('pro')
    check(not ent.at_limit('field_workers'), 'Pro is not at the limit with 2 cleaners')
    ok, _ = ent.check_limit('field_workers')
    check(ok, 'Pro may add a third cleaner')

    print('\n7. Downgrading never destroys what they already entered')
    set_plan('solo')
    check(Staff.query.filter_by(is_active=True).count() == 2,
          'both cleaners survive the downgrade to a 2-cleaner plan')
    for i in range(3):
        db.session.add(Staff(name=f'Extra {i}', is_active=True))
    db.session.commit()
    check(Staff.query.filter_by(is_active=True).count() == 5,
          'five cleaners exist after a downgrade from a bigger plan')
    check(ent.at_limit('field_workers'), 'the sixth is blocked')
    check(ent.remaining('field_workers') == 0, 'remaining bottoms out at zero, never negative')

    print('\n8. Jobs are counted per calendar month')
    set_plan('solo')
    before = ent.usage('jobs_per_month')
    db.session.add(Booking(service_type='standard', name='Test', status='pending'))
    db.session.commit()
    check(ent.usage('jobs_per_month') == before + 1, 'a new booking counts against the month')
    check(ent.limit('jobs_per_month') == 20, 'Solo allows 20 jobs a month')
    set_plan('scale')
    check(ent.limit('jobs_per_month') is None, 'Scale is unlimited')

    print('\n9. The menu marks locked pages instead of hiding them')
    set_plan('solo')
    nav = navigation.sidebar('owner', ent.can)
    flat = [i for s in nav for i in s['items']]
    hiring = next((i for i in flat if i['endpoint'] == 'contractors.applications'), None)
    check(hiring is not None, 'Hiring is still in the menu on the free plan')
    check(hiring['locked'], 'Hiring is marked locked on the free plan')
    bookings = next(i for i in flat if i['endpoint'] == 'bookings.index')
    check(not bookings['locked'], 'Bookings is not locked')
    set_plan('scale')
    nav = navigation.sidebar('owner', ent.can)
    flat = [i for s in nav for i in s['items']]
    check(not any(i['locked'] for i in flat), 'nothing is locked on Scale')

    print('\n10. Role still removes pages — a permission is not an upsell')
    nav = navigation.sidebar('team', ent.can)
    flat = [i for s in nav for i in s['items']]
    check(not any(i['endpoint'] == 'money.pnl' for i in flat),
          'a team member does not see the money section at all')

    print('\n11. Every gated endpoint is a real route, and every feature has a label')
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    missing = sorted(e for e in navigation.MIN_PLAN if e not in endpoints)
    check(not missing, f'no gate points at a route that does not exist ({missing})')
    unlabelled = sorted(f for f in navigation.MIN_PLAN.values() if f not in ent.FEATURE_LABELS)
    check(not unlabelled, f'every gated feature has a human name ({unlabelled})')
    ungranted = sorted(
        f for f in navigation.MIN_PLAN.values()
        if not any(c['features'] and f in c['features'] for c in ent.PLANS.values())
        and ent.plan_for_feature(f) == 'scale'
    )
    print(f'  ✅ features reachable only on Scale: {ungranted}')

    print('\n12. Hitting a wall is recorded')
    EntitlementDenial.query.delete()
    db.session.commit()
    set_plan('solo')
    ent.record_denial('hiring', path='/contractors/applications')
    rows = EntitlementDenial.query.all()
    check(len(rows) == 1, 'the denial was written')
    check(rows[0].feature == 'hiring' and rows[0].plan == 'solo',
          'it records what they wanted and what they were on')

    print('\n13. A broken plan lookup does not take a page down')
    BusinessSetting.set('plan', 'enterprise-deluxe')
    db.session.commit()
    ent._clear_cache()
    check(ent.effective_plan() == 'solo', 'an unknown plan name falls back to Solo')
    check(ent.usage('nonexistent_thing') == 0, 'an unknown usage counter returns 0, not an error')

# --- Established instances must not wake up on the free plan -----------------
# Run separately: this needs a database that looks like a real business at the
# moment create_app() boots, which is not the state the tests above leave.
import subprocess, textwrap
print('\n14. An existing business is grandfathered, a fresh one is not')
script = textwrap.dedent('''
    import os, sys, tempfile
    TMP = tempfile.mkdtemp()
    os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/gf.db'
    os.environ['SECRET_KEY'] = 'test'
    sys.path.insert(0, %r)
    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    notifications.send_email = lambda *a, **k: (True, 'stub')
    from app import create_app
    from extensions import db
    from models import Booking, BusinessSetting
    app = create_app()
    with app.app_context():
        assert BusinessSetting.get('plan') == 'solo', 'fresh instance should be Solo'
        # Now make it look like a business with history and re-boot.
        for i in range(6):
            db.session.add(Booking(service_type='standard', name=f'J{i}', status='completed'))
        BusinessSetting.set('plan', '')
        db.session.commit()
    app2 = create_app()
    with app2.app_context():
        assert BusinessSetting.get('plan') == 'scale', 'established instance should be grandfathered'
        assert BusinessSetting.get('grandfathered') == '1', 'and marked as such'
    print('OK')
''') % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
r = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
assert 'OK' in r.stdout, f'FAILED:\n{r.stdout}\n{r.stderr}'
print('  ✅ a fresh deployment starts on Solo')
print('  ✅ a deployment with real history is grandfathered onto the full plan')
print('\n\n✅ All plan tests passed.\n')
