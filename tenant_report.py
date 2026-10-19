"""Who is on the platform, read from the control plane itself.

The number of company schemas is not the number of customers: the demo and
test companies have schemas too, and a closed company keeps one through its
retention window. This counts the organizations rows the product itself
decides by -- status, billing and the test/demo flags -- with the same
definitions the console uses (funnel.py), and says what each one means.

  real         not marked demo or test in the console
  active       status 'active' (suspended, closing and closed are not)
  paying       Stripe last said 'active' (subscription_status), never a guess
  trialing     Stripe last said 'trialing', or no subscription yet
  grandfathered a founding customer (app._grandfather_established_business);
               counted as real, shown on its own line
  archived     hidden from the console's default list; nothing else changes

Windows are fixed lengths back from the moment it runs, in UTC (timestamps in
the control plane are UTC), so the same run gives the same answer whatever the
reader's timezone. Slugs and counts only: no names, emails or amounts.

Pure: takes rows, returns numbers. certify.py does the reading.
"""
from datetime import timedelta

WINDOWS = (('last_24h', timedelta(hours=24)), ('last_7d', timedelta(days=7)))

# Each a timestamp the product already writes when the thing happens.
EVENTS = (('signed_up', 'created_at'), ('activated', 'activated_at'),
          ('started_paying', 'paid_since'), ('canceled', 'canceled_at'),
          ('suspended', 'suspended_at'), ('closed', 'closed_at'),
          ('archived', 'archived_at'))

STATUSES = ('active', 'suspended', 'closing', 'closed')
BILLING = ('active', 'trialing', 'past_due', 'canceled')


def kind(org):
    if org.get('is_demo'):
        return 'demo'
    return 'test' if org.get('is_test') else 'real'


def _billing(org):
    status = (org.get('subscription_status') or '').lower()
    if status == 'active':
        return 'paying'
    if status in ('', 'trialing'):
        return 'trialing'
    return status if status in BILLING else 'other'


def compute(orgs, now):
    real = [o for o in orgs if kind(o) == 'real']
    open_ = [o for o in real if o.get('status') not in ('closing', 'closed')]
    out = {
        'as_of': now.isoformat() + 'Z',
        'registered': len(orgs),
        'by_kind': {k: sorted(o['slug'] for o in orgs if kind(o) == k)
                    for k in ('real', 'test', 'demo')},
        'real': {
            'status': {s: sorted(o['slug'] for o in real if o.get('status') == s)
                       for s in STATUSES},
            # Billing of the companies still open: a closed company's last
            # Stripe status says nothing about today.
            'billing': {b: sorted(o['slug'] for o in open_ if _billing(o) == b)
                        for b in ('paying', 'trialing', 'past_due', 'canceled', 'other')},
            'grandfathered': sorted(o['slug'] for o in real if o.get('grandfathered')),
            'archived': sorted(o['slug'] for o in real if o.get('archived_at')),
        },
        'windows': {},
    }
    other = [o['slug'] for o in real if o.get('status') not in STATUSES]
    if other:
        out['real']['status']['other'] = sorted(other)
    for name, span in WINDOWS:
        since = now - span
        out['windows'][name] = {
            'since': since.isoformat() + 'Z',
            'events': {event: sorted(f'{o["slug"]} ({kind(o)})' for o in orgs
                                     if o.get(field) and o[field] >= since)
                       for event, field in EVENTS},
        }
    return out
