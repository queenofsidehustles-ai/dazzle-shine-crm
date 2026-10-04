"""A company gets the plan it is paying for, not the one its schema forgot.

A hosted company's plan is sold, trialled and cancelled in the control plane
(public.organizations). The entitlement check read it from BusinessSetting in
the company's own schema instead, and no company has ever had that setting --
so every one of them resolved to Solo and ran with no texting, no reports, no
automations and 20 jobs a month, whatever they were paying.

It was visible the whole time and nobody was looking: the denials table had
rows reading feature=sms, plan=solo for a company on a Scale trial.

What is worth protecting here:

  * the control plane decides for a hosted company
  * a single-business install, which has no control plane, is untouched
  * a lapsed card still drops to Solo -- this must not become a way to get
    paid features for free
  * an unreadable control plane does not take the page down with it
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/plan.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from app import create_app
from extensions import db
import entitlements as E

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


def with_org(org):
    """Run as a company whose control-plane row says this."""
    E._org_plan = lambda: org
    E._clear_cache()
    return E.state()


real = E._org_plan
try:
    with app.app_context():
        db.create_all()

        print('1. The plan that was sold is the plan that applies')
        st = with_org({'plan': 'scale', 'status': 'trialing',
                       'trial_ends': datetime.utcnow() + timedelta(days=3)})
        check(st['effective_plan'] == 'scale',
              'a Scale trial is Scale, not the Solo its schema never recorded')
        check(E.plan_can(st['effective_plan'], 'sms'),
              'so it can send a text, which is the whole point')

        st = with_org({'plan': 'pro', 'status': 'active', 'trial_ends': None})
        check(st['effective_plan'] == 'pro', 'a paying Pro company is Pro')

        print('\n2. A lapsed card still drops to Solo')
        st = with_org({'plan': 'scale', 'status': 'past_due', 'trial_ends': None})
        check(st['effective_plan'] == 'solo',
              'past_due is Solo — this must not be a free route to paid features')
        st = with_org({'plan': 'scale', 'status': 'canceled', 'trial_ends': None})
        check(st['effective_plan'] == 'solo', 'and so is cancelled')

        print('\n3. Nothing to ask, nothing changes')
        from models import BusinessSetting
        BusinessSetting.set('plan', 'pro')
        BusinessSetting.set('plan_status', 'active')
        db.session.commit()
        st = with_org(None)
        check(st['effective_plan'] == 'pro',
              'a single-business install still reads its own settings')

        print('\n4. A control plane that cannot be read is not fatal')
        def boom():
            raise RuntimeError('no such table: organizations')
        E._org_plan = boom
        E._clear_cache()
        try:
            st = E.state()
            ok = st['effective_plan'] == 'pro'
        except Exception:
            ok = False
        check(ok, 'the page still renders on the settings it already had')
finally:
    E._org_plan = real

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
