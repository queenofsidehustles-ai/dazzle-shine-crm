"""How people become paying customers, from what is already written down.

Nothing is tracked for this page. Every stage is a fact some other part of the
product already records in the control plane:

  asked for early access   product_leads.created_at          (marketing.early_access)
  signed up                organizations.created_at          (signup)
  activated                organizations.activated_at        (billing.mark_activated:
                                                              first job assigned)
  chose a plan             organizations.stripe_subscription_id (Stripe checkout)
  paying                   subscription_status == 'active'   (Stripe webhooks)

Site visits are not recorded anywhere, so the funnel starts at the first thing
a person does, not the first thing they see.

The stages after signup are not strictly nested -- a company can pick a plan
before it assigns its first job -- so every stage is shown as a share of
signups rather than of the stage above. A "72% of the previous step" that is
secretly measured against a different group reads fine and means nothing.

Grandfathered companies are left out. They were never acquired through the
funnel (see app._grandfather_established_business), and counting them would
flatter every rate on the page.

Pure: takes rows, returns numbers. The console route does the reading, so this
can be tested without a database.
"""
from datetime import datetime, timedelta
from urllib.parse import urlparse

# Choices on the page, in days. None means everything ever recorded.
WINDOWS = {'30': 30, '90': 90, 'all': None}
DEFAULT_WINDOW = '90'

# A trial with this few days left, and no plan chosen, is worth a call today.
ENDING_SOON_DAYS = 3


def _email(value):
    return (value or '').strip().lower()


def _status(org):
    return (org.get('subscription_status') or '').lower()


def _gone(org):
    return org.get('status') in ('closing', 'closed')


def _pct(part, whole):
    return round(100 * part / whole) if whole else None


def lead_source(raw):
    """A referrer URL as the site it came from: 'google.com', not the full URL.

    The form stores the referrer as it arrived. Grouped by full URL, every
    search result would be its own row and no source would ever add up to
    anything.
    """
    raw = (raw or '').strip()
    if not raw or raw == 'direct':
        return 'direct'
    host = urlparse(raw if '//' in raw else f'//{raw}').hostname or raw
    return host[4:] if host.startswith('www.') else host


def compute(orgs, leads, now=None, days=None):
    """The funnel for companies and leads that arrived in the last `days` days.

    The follow-up lists ignore the window: somebody who signed up 95 days ago
    and is about to lapse still needs the call whichever window is showing.
    """
    import billing

    now = now or datetime.utcnow()
    since = now - timedelta(days=days) if days else None

    def arrived(row):
        when = row.get('created_at')
        return since is None or (when is not None and when >= since)

    counted = [o for o in orgs if not o.get('grandfathered')]
    companies = [o for o in counted if arrived(o)]
    window_leads = [l for l in leads if arrived(l)]

    # A lead "signed up" if any company, from any time, was opened with the
    # same email. Matching on email is the only link there is: the early-access
    # form and the signup form are separate, and nobody is asked to connect them.
    signup_emails = {_email(o.get('owner_email')) for o in orgs
                     if o.get('owner_email')}

    def lead_converted(lead):
        return _email(lead.get('email')) in signup_emails

    signed_up = len(companies)
    activated = [o for o in companies if o.get('activated_at')]
    chose_plan = [o for o in companies if o.get('stripe_subscription_id')]
    paying = [o for o in chose_plan if _status(o) == 'active' and not _gone(o)]

    stages = [
        {'key': 'signed_up', 'label': 'Signed up', 'n': signed_up,
         'means': 'opened a company'},
        {'key': 'activated', 'label': 'Activated', 'n': len(activated),
         'means': 'assigned their first job, which starts the 14-day trial'},
        {'key': 'chose_plan', 'label': 'Chose a plan', 'n': len(chose_plan),
         'means': 'went through Stripe checkout'},
        {'key': 'paying', 'label': 'Paying now', 'n': len(paying),
         'means': 'subscription active and the company still open'},
    ]
    for s in stages:
        s['pct'] = _pct(s['n'], signed_up)

    # Why companies that signed up are not paying. One reason each, the first
    # that applies, so the reasons add up to the number lost.
    lost = {'closed': 0, 'canceled': 0, 'trial_over': 0}
    for o in companies:
        if _gone(o):
            lost['closed'] += 1
        elif _status(o) == 'canceled':
            lost['canceled'] += 1
        elif not o.get('stripe_subscription_id'):
            trial = billing.trial_state(o, now)
            if trial and trial['expired']:
                lost['trial_over'] += 1

    gaps = [(o['activated_at'] - o['created_at']).total_seconds() / 86400
            for o in activated if o.get('created_at')]
    days_to_activate = _median(gaps)

    # Where leads came from, busiest first.
    by_source = {}
    for lead in window_leads:
        row = by_source.setdefault(lead_source(lead.get('source')),
                                   {'leads': 0, 'signed_up': 0})
        row['leads'] += 1
        if lead_converted(lead):
            row['signed_up'] += 1
    sources = sorted(by_source.items(), key=lambda kv: (-kv[1]['leads'], kv[0]))

    return {
        'since': since,
        'leads': len(window_leads),
        'leads_signed_up': sum(1 for l in window_leads if lead_converted(l)),
        'leads_pct': _pct(sum(1 for l in window_leads if lead_converted(l)),
                          len(window_leads)),
        'stages': stages,
        'lost': lost,
        'lost_total': sum(lost.values()),
        'past_due': sum(1 for o in companies
                        if _status(o) == 'past_due' and not _gone(o)),
        'days_to_activate': days_to_activate,
        'sources': sources,
        'follow_up': _follow_up(counted, leads, signup_emails, now, billing),
        'ending_soon_days': ENDING_SOON_DAYS,
        'excluded': sum(1 for o in orgs if o.get('grandfathered')),
    }


def _follow_up(orgs, leads, signup_emails, now, billing):
    """Who to get in touch with, and why. Windowless on purpose -- see compute."""
    not_started, ending, failing = [], [], []
    for o in orgs:
        if _gone(o):
            continue
        if _status(o) == 'past_due':
            failing.append(o)
            continue
        if o.get('stripe_subscription_id'):
            continue
        trial = billing.trial_state(o, now)
        if not trial or trial['expired']:
            continue
        row = dict(o, days_left=trial['days_left'])
        if trial['phase'] == 'not_started':
            not_started.append(row)
        elif trial['days_left'] <= ENDING_SOON_DAYS:
            ending.append(row)

    waiting = [l for l in leads
               if not l.get('contacted_at')
               and _email(l.get('email')) not in signup_emails]

    return {
        'not_started': sorted(not_started, key=lambda o: o['days_left']),
        'ending': sorted(ending, key=lambda o: o['days_left']),
        'failing': failing,
        'leads_waiting': sorted(waiting, key=lambda l: l.get('created_at') or now),
    }


def _median(values):
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return round(values[mid], 1)
    return round((values[mid - 1] + values[mid]) / 2, 1)
