"""The trial is thirty days from signup, and everything reads it the same way.

It used to be two clocks: a fortnight that began when a company added a
cleaner and a customer, inside a month to make that start. The reasoning was
sound; the shape was not. It could not be said in one sentence, the rule the
code ran was not the rule the emails described, and it made an owner with no
customers invent one before her trial would begin.

What this holds:
- Thirty days from signup, whatever the company does.
- Nobody loses days to the change: a trial already running to a later date
  keeps that date.
- The banner and the entitlements read the same rule. Those two disagreeing
  is how somebody is told they have days left while already on the free plan.
"""
import os, sys
from datetime import datetime, timedelta
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import billing

NOW = datetime(2026, 10, 18, 12, 0, 0)
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def org(days_old, **kw):
    created = NOW - timedelta(days=days_old)
    row = {'slug': 'c', 'subscription_status': 'trialing', 'plan': 'scale',
           'created_at': created, 'trial_ends_at': None, 'activated_at': None}
    row.update(kw)
    return row


print('\n1. Thirty days from signup, used or not')
check(billing.TRIAL_DAYS == 30, 'the trial is thirty days')
fresh = billing.trial_state(org(0), NOW)
check(fresh['days_left'] == 30, 'a company that signed up today has thirty days')
check(fresh['phase'] == 'running', 'and it is already running')
check(fresh['started'] is True, 'there is no "not started" any more')

idle = billing.trial_state(org(10), NOW)
check(idle['days_left'] == 20, 'ten days in, twenty left, having done nothing')
busy = billing.trial_state(org(10, activated_at=NOW - timedelta(days=2)), NOW)
check(busy['days_left'] == 20, 'and exactly the same for one that got going')
check(busy['activated'] is True and idle['activated'] is False,
      'whether they got it working is still recorded')

print('\n2. Nobody loses days they already had')
late = org(20, activated_at=NOW - timedelta(days=1),
           trial_ends_at=NOW + timedelta(days=13))
check(billing.trial_state(late, NOW)['days_left'] == 13,
      'an old trial running past signup-plus-thirty keeps its date')
extended = org(5, trial_ends_at=NOW + timedelta(days=90))
check(billing.trial_state(extended, NOW)['days_left'] == 90,
      'and so does one somebody extended by hand')
short = org(5, trial_ends_at=NOW + timedelta(days=2))
check(billing.trial_state(short, NOW)['days_left'] == 25,
      'an earlier stored date never shortens the thirty days')

print('\n3. Over is over')
done = billing.trial_state(org(31), NOW)
check(done['expired'] is True and done['phase'] == 'over', 'day 31 is finished')
check(done['days_left'] == 0, 'and does not count backwards')

print('\n4. The banner and the entitlements agree')
check(billing.plan_for(org(10)) == 'scale', 'a running trial has its plan')
check(billing.plan_for(org(40)) == 'solo', 'a finished one is on the free plan')
mid = org(20, trial_ends_at=NOW - timedelta(days=5))
state = billing.trial_state(mid, NOW)
check(state['expired'] is False and billing.plan_for(mid) == 'scale',
      'a stale stored date does not strand somebody between the two')

print('\n5. Missing information is not permission')
check(billing.plan_for({'subscription_status': 'trialing', 'plan': 'scale'}) == 'solo',
      'a row with no dates at all gets the free plan, not the top one')

if failures:
    print(f'\n❌ {len(failures)} trial check(s) failed')
    sys.exit(1)
print('\n✅ One clock, thirty days, read the same way everywhere.')
