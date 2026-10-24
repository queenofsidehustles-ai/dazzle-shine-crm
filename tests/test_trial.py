"""Everything for thirty days, from the day they sign up.

A free plan nobody has seen the paid features from is a plan nobody upgrades
out of. You cannot miss the hiring pipeline if you never had it. So a new
company gets the top plan and steps down, rather than being asked to imagine
what it is not being shown.

One clock: thirty days from signup. It was two -- a fortnight that began when
a company added a cleaner and a customer, inside a month to make that start.
The reasoning was good and the shape was not. It could not be said in a
sentence; the rule the code ran was not the rule anything described (this file
and billing.py both said "the first job assigned", while what actually started
it was a cleaner and a customer); and it made a brand-new owner invent a
customer she did not have before her trial would begin.

Nobody lost days to the change. Where an older trial already ran to a later
date, that date stands.

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


print('\n2. The thirty days are already running')
st = billing.trial_state(new)
check(st is not None, 'there is a trial in play')
check(st['phase'] == 'running', f"phase is {st['phase']}")
check(st['started'], 'there is no waiting to begin any more')
check(29 <= st['days_left'] <= 30,
      f"thirty days from signup ({st['days_left']} days)")


print('\n3. Using it does not change the clock')
# It used to start it, which is why "add a customer" was a required setup
# step for somebody who had no customers.
busy = org(activated_at=NOW)
st = billing.trial_state(busy)
check(29 <= st['days_left'] <= 30,
      f"a company that got going has exactly the same days ({st['days_left']})")
check(st['activated'], 'but whether they got going is still recorded')
check(billing.trial_state(new)['activated'] is False, 'and distinguishes the two')
check(billing.plan_for(busy) == 'scale', 'still everything while it runs')


print('\n4. Nobody loses days they already had')
# A trial written under the old rule can run past signup-plus-thirty, and so
# can one somebody extended by hand. Either way the later date stands.
late = org(created_at=NOW - timedelta(days=29),
           activated_at=NOW - timedelta(days=1),
           trial_ends_at=NOW + timedelta(days=13))
st = billing.trial_state(late)
check(st['phase'] == 'running', 'their trial is running')
check(12 <= st['days_left'] <= 13,
      f'keeping the later date, not cut to one day ({st["days_left"]})')
short = org(created_at=NOW - timedelta(days=5),
            trial_ends_at=NOW + timedelta(days=2))
check(24 <= billing.trial_state(short)['days_left'] <= 25,
      'and an earlier stored date never shortens the thirty')


print('\n5. Thirty days is thirty days, used or not')
idle = org(created_at=NOW - timedelta(days=31),
           trial_ends_at=NOW - timedelta(days=1))
st = billing.trial_state(idle)
check(st['expired'], 'day 31 is over')
check(st['phase'] == 'over', f"phase is {st['phase']}")
check(billing.plan_for(idle) == 'solo',
      f'and they are on the free plan ({billing.plan_for(idle)})')


print('\n5b. The banner and the entitlements never disagree')
# They read different things once -- trial_state computed a date and plan_for
# went straight to the stored column -- so a company could be told it had
# days left while already locked onto the free plan.
stale = org(created_at=NOW - timedelta(days=10),
            trial_ends_at=NOW - timedelta(days=3))
check(billing.trial_state(stale)['expired'] is False
      and billing.plan_for(stale) == 'scale',
      'a stale stored date strands nobody between the two')


print('\n6. When it ends they keep working, on Solo')
done = org(created_at=NOW - timedelta(days=36),
           activated_at=NOW - timedelta(days=30),
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
check(billing.plan_for({'status': 'active', 'plan': 'scale',
                        'subscription_status': 'trialing'}) == 'solo',
      'a row with no signup date and no end date is not a trial')
check(billing.plan_for(None) == 'solo', 'and no company at all is the free plan')
check(billing.plan_for(org(status='suspended')) == 'solo',
      'a suspended company gets nothing regardless of what it paid')


print('\n9. The banner is on every page of a company CRM')
from app import create_app
app = create_app()
# Billing and Business Settings read entitlements' state, not trial_state():
# it must use the same end. A row stored before the one-clock rule can hold an
# earlier trial_ends_at, and Billing said "not on a trial" beside a banner
# that was still counting down.
import entitlements
early = {'slug': 'early', 'status': 'active', 'subscription_status': 'trialing',
         'plan': 'scale', 'created_at': NOW - timedelta(days=10),
         'trial_ends_at': NOW - timedelta(days=1), 'activated_at': None}
_was = billing.current_org
billing.current_org = lambda: early
try:
    with app.app_context():
        st = entitlements._load_state()
finally:
    billing.current_org = _was
check(st['on_trial'] and st['trial_ends_at'] == billing.trial_ends(early),
      'Billing reads the same trial end as the banner: 30 days from signup, not the old column')
check(st['trial_days_left'] == billing.trial_state(early, NOW)['days_left'],
      f"and the same days left ({st['trial_days_left']})")

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
print('\n\n✅ One clock, thirty days, and nobody loses a day to it.\n')
