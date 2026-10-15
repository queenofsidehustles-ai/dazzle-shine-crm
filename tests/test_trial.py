"""Everything for 30 days, one clock, from signup.

A free plan nobody has seen the paid features from is a plan nobody upgrades
out of. You cannot miss the hiring pipeline if you never had it. So a new
company gets the top plan and steps down, rather than being asked to imagine
what it is not being shown.

The trial is 30 days from signup. It used to start only once somebody added a
cleaner and a customer, with a second 30-day window to do that, and the two
clocks needed two sentences everywhere. Now there is one number. Setting up is
a milestone (`activated_at`) that the emails and the Funnel watch, and it does
not start or move the trial.

Nothing is deleted when it ends. They drop to the free plan and everything
they entered is still there, including the features they can no longer use,
visible and locked, which is better ongoing pressure than any email.
"""
import os, sys, tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/tr.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

import billing

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


NOW = datetime.utcnow()


def org(**kw):
    base = {'slug': 'acme', 'status': 'active', 'created_at': NOW,
            'plan': 'scale', 'subscription_status': 'trialing',
            'trial_ends_at': NOW + timedelta(days=30), 'activated_at': None}
    base.update(kw)
    return base


print('\n1. A new company gets everything, not the free plan')
# The whole argument for a trial. Somebody who has only ever seen Solo has no
# idea what Pro is worth to them.
new = org()
check(billing.plan_for(new) == 'scale',
      f'a company on day one may use the top plan ({billing.plan_for(new)})')


print('\n2. The 30 days run from signup')
st = billing.trial_state(new)
check(st is not None, 'there is a trial in play')
check(st['phase'] == 'running', f"phase is {st['phase']}")
check(not st['activated'], 'they have not set up yet, and that is all it says')
check(29 <= st['days_left'] <= 30, f"30 days left ({st['days_left']})")
check(billing.TRIAL_DAYS == 30, 'and the length is the one constant')


print('\n3. Setting up does not move the end date')
before = org(created_at=NOW - timedelta(days=10), trial_ends_at=NOW + timedelta(days=20))
after = dict(before, activated_at=NOW)
check(billing.trial_state(before)['days_left'] == billing.trial_state(after)['days_left'],
      'the days left are the same before and after')
check(billing.trial_state(after)['activated'], 'but it is recorded as set up')
check(billing.plan_for(after) == 'scale', 'and everything stays on')


print('\n4. A trial with no end date is bounded from signup')
legacy = org(created_at=NOW - timedelta(days=5), trial_ends_at=None)
st = billing.trial_state(legacy)
check(24 <= st['days_left'] <= 25, f"30 days from signup, not forever ({st['days_left']})")


print('\n5. Somebody who never sets up runs out like anybody else')
idle = org(created_at=NOW - timedelta(days=31),
           trial_ends_at=NOW - timedelta(days=1))
st = billing.trial_state(idle)
check(st['expired'], 'the trial ended')
check(st['phase'] == 'over', f"phase is {st['phase']}")
check(billing.plan_for(idle) == 'solo',
      f'and they are on the free plan ({billing.plan_for(idle)})')


print('\n6. When it ends they keep working, on Solo')
done = org(activated_at=NOW - timedelta(days=20),
           trial_ends_at=NOW - timedelta(days=6))
check(billing.plan_for(done) == 'solo', 'dropped to free')
check(billing.trial_state(done)['expired'], 'and told so')
# Nothing here deletes anything. The point of dropping rather than locking out
# is that their data stays and the features stay visible.
check(billing.trial_state(done) is not None,
      'the banner still speaks to them rather than going silent')


print('\n7. A paying customer never sees a trial banner')
for status in ('active', 'past_due', 'canceled'):
    check(billing.trial_state(org(subscription_status=status)) is None,
          f'no trial state for a {status!r} subscription')


print('\n8. Missing information is never read as permission')
# A half-written row, or one edited by hand, must not grant the top plan.
check(billing.plan_for(org(trial_ends_at=None)) == 'solo',
      'a trial with no end date is not a trial')
check(billing.plan_for(None) == 'solo', 'and no company at all is the free plan')
check(billing.plan_for(org(status='suspended')) == 'solo',
      'a suspended company gets nothing regardless of what it paid')


print('\n9. The banner is on every page of a company CRM')
from app import create_app
app = create_app()
c = app.test_client()
with c.session_transaction() as sess:
    sess['logged_in'] = True
    sess['role'] = 'owner'
page = c.get('/').data.decode('utf8', 'replace')
# On a single-business install there is no control plane and no trial, and the
# banner must stay out of the way entirely.
check('trialbar' not in page,
      'a single-business instance shows no trial banner at all')


if failures:
    print(f'\n\n❌ {len(failures)} trial check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ One clock, thirty days, and it never stops early.\n')
