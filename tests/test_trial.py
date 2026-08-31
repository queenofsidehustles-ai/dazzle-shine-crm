"""Everything for a fortnight — but the fortnight starts when they begin.

A free plan nobody has seen the paid features from is a plan nobody upgrades
out of. You cannot miss the hiring pipeline if you never had it. So a new
company gets the top plan and steps down, rather than being asked to imagine
what it is not being shown.

Two clocks, because one is not honest:

  * **14 days from the first job assigned.** A fortnight measured from signup
    is a trial a busy company can lose without ever having used the product —
    and then they are owed an apology and a manual extension, which is a
    conversation worth designing out.

  * **30 days from signup to make that start.** Without it the first clock
    never runs for somebody who signs up and does nothing, and a trial that
    waits indefinitely gives nobody a reason to begin. This was the owner's
    objection to the activation clock, and it was the right one.

Nothing is deleted when it ends. They drop to the free plan and everything
they entered is still there — including the features they can no longer use,
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


print('\n2. The 14 days have not started yet')
st = billing.trial_state(new)
check(st is not None, 'there is a trial in play')
check(st['phase'] == 'not_started', f"phase is {st['phase']}")
check(not st['started'], 'and it says so')
check(29 <= st['days_left'] <= 30,
      f"the countdown is the 30-day window to begin ({st['days_left']} days)")


print('\n3. Assigning a job starts the real clock')
started = org(activated_at=NOW, trial_ends_at=NOW + timedelta(days=14))
st = billing.trial_state(started)
check(st['phase'] == 'running', f"phase is {st['phase']}")
check(13 <= st['days_left'] <= 14, f"14 days from that moment ({st['days_left']})")
check(billing.plan_for(started) == 'scale', 'still everything while it runs')


print('\n4. Somebody who starts late still gets their full fortnight')
# They engaged on day 29. Cutting them off on day 30 would punish exactly the
# person the second clock exists to be fair to.
late = org(created_at=NOW - timedelta(days=29),
           activated_at=NOW,
           trial_ends_at=NOW + timedelta(days=14))
st = billing.trial_state(late)
check(st['phase'] == 'running', 'their trial is running')
check(13 <= st['days_left'] <= 14,
      f'with the whole fortnight, not one day ({st["days_left"]})')


print('\n5. Somebody who never starts runs out anyway')
# The owner's objection to the activation clock: without a cap it is a trial
# that waits forever, and nobody hurries for something that waits forever.
idle = org(created_at=NOW - timedelta(days=31),
           trial_ends_at=NOW - timedelta(days=1))
st = billing.trial_state(idle)
check(st['expired'], 'the window to begin closed')
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
print('\n\n✅ Two clocks, and neither of them stops.\n')
