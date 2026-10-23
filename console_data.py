"""What the console reads from inside each company, safely.

The control plane knows who a company is and what it pays. Whether it is
actually working -- are its automations running, is it throwing errors, is
anybody signing in -- lives inside the company's own schema, where the
console could not see it. Finding out meant holding the production database
URL, which is how the September automations outage went unnoticed: every job
was failing for every company, and no page anywhere said so.

Everything here reads through tenancy.use_tenant, the same boundary every
tenant request goes through, and copies what it needs into plain dicts before
the schema switches back. Two rules that are not tidiness:

  * db.session.remove() before and after every company. Each schema's ids
    start at 1, and a shared ORM identity map serves one company's cached row
    back as another's (see console.nana_proposals, where this was a real bug).

  * Nothing lazy leaves the `with` block. A relationship touched after the
    switch would be loaded from whichever schema happens to be current.

A company whose schema will not read is reported as unreadable, never allowed
to take the page down: one company's snapshot is not worth everybody's.
"""
from datetime import datetime, timedelta

from sqlalchemy import func

# Statuses whose schema is expected to exist and be read. A closed company's
# data is retained but deliberately not looked through.
READABLE = ('active', 'suspended')


def schema_ready(slug):
    """Whether this company's own schema actually exists.

    Checked before every read, because use_tenant sets the search path to
    `"<company schema>", public` and Postgres skips a schema that is not
    there. A company registered without one (half-provisioned, or added by
    hand) would silently be read from `public` -- showing whatever that
    schema holds as though it were theirs. Found by looking at the page, not
    by a test: a company with no schema showed ten errors.
    """
    import provisioning
    import tenancy
    try:
        return provisioning.schema_exists(provisioning._engine(),
                                          tenancy.schema_for(slug))
    except Exception:
        return False


def _usage_this_month():
    """What this company used this month of the things that cost Akye money.

    Each count is its own try: one that cannot be read is zero, and must not
    stop the company's other numbers from showing. Called inside the company's
    own schema."""
    import assistant
    import entitlements
    import setup_assistant
    out = {}
    for key, fn in (('sms', entitlements._count_sms_this_month),
                    ('nana', assistant.used_this_month),
                    ('setup_chat', setup_assistant.used_this_month),
                    ('lead_searches', entitlements._count_lead_searches_this_month)):
        try:
            out[key] = int(fn() or 0)
        except Exception:
            out[key] = 0
    return out


def snapshot(slug, now=None):
    """One company's health and activity, read inside its own schema."""
    import automations
    import tenancy
    from extensions import db
    from models import Booking, Client, ErrorLog, User

    if not schema_ready(slug):
        return {'ok': False, 'why': 'no schema'}
    now = now or datetime.utcnow()
    month_ago = now - timedelta(days=30)
    db.session.remove()
    try:
        with tenancy.use_tenant(slug):
            jobs = []
            for r in automations.overview():
                last = r['last']
                jobs.append({
                    'key': r['key'], 'label': r['label'], 'cadence': r['cadence'],
                    'state': r['state'], 'evidence': r['evidence'], 'on': r['on'],
                    'ran_at': last.ran_at if last else None,
                    'detail': (last.detail or '') if last else '',
                })
            # A refused cross-site form is the guard working, not a fault:
            # the owner's own Errors page already keeps those apart, and the
            # console counting them made a healthy company look broken.
            open_q = ErrorLog.query.filter_by(resolved=False).filter(
                ErrorLog.kind != 'blocked')
            errors = [{
                'id': e.id,
                'kind': e.kind, 'message': e.message, 'path': e.path,
                'count': e.count or 1, 'first_seen': e.first_seen,
                'last_seen': e.last_seen,
            } for e in open_q.order_by(ErrorLog.last_seen.desc()).limit(10).all()]
            usage = _usage_this_month()
            users = User.query.all()
            owner_logins = [u.last_login for u in users
                            if u.role == 'owner' and u.last_login]
            logins = [u.last_login for u in users if u.last_login]
            data = {
                'ok': True,
                'jobs': jobs,
                'jobs_broken': sum(1 for j in jobs
                                   if j['state'] in ('never', 'stale', 'failing')),
                'errors': errors,
                'usage': usage,
                'open_errors': open_q.count(),
                # Occurrences, not rows: one row stands for every repeat.
                'blocked': int(db.session.query(func.coalesce(
                    func.sum(ErrorLog.count), 0)).filter(
                    ErrorLog.kind == 'blocked').scalar() or 0),
                'users': sum(1 for u in users if u.active),
                'last_login': max(logins) if logins else None,
                'owner_last_login': max(owner_logins) if owner_logins else None,
                'clients': Client.query.count(),
                'bookings_30d': Booking.query.filter(
                    Booking.created_at >= month_ago).count(),
                'completed_30d': Booking.query.filter(
                    Booking.completed_at >= month_ago).count(),
            }
        return data
    except Exception as exc:
        db.session.rollback()
        return {'ok': False, 'why': type(exc).__name__}
    finally:
        db.session.remove()


def snapshots(orgs, now=None):
    """{slug: snapshot} for every company whose schema should be readable."""
    return {o['slug']: snapshot(o['slug'], now=now) for o in orgs
            if (o.get('status') or 'active') in READABLE}


def dedupe_leads(leads):
    """One row per email, newest first, with how many times they asked.

    The early-access form has no "already asked" check, and somebody who
    submits twice is one person to call, not two.
    """
    seen = {}
    for lead in leads:                                  # arrive newest first
        key = (lead.get('email') or '').strip().lower() or f"id:{lead.get('id')}"
        # A repeat ask is counted on the one row now (times_asked); older
        # repeats are still separate rows. Both add up the same way.
        asked = lead.get('times_asked') or 1
        if key in seen:
            seen[key]['times'] += asked
        else:
            seen[key] = dict(lead, times=asked)
    return list(seen.values())


# How long without the owner signing in before the console mentions it, and
# before it is a reason to reach out. A cleaning owner who books a week ahead
# can go a few days without opening it; a fortnight is somebody drifting off.
AWAY_WATCH_DAYS = 7
AWAY_HELP_DAYS = 14
# New enough that "not set up yet" is just "new". The first-week emails are
# already talking to them.
NEW_DAYS = 3

SUPPORT_LABELS = {'help': 'Needs help', 'watch': 'Watch', 'ok': 'Healthy',
                  'new': 'New', 'none': '—'}


def owner_last_seen(org, snap=None):
    """When the owner last used their CRM, as best we know: the later of the
    activity the app now records (organizations.owner_active_at) and their
    last password sign-in. The sign-in alone can be months old for somebody
    who never signs out, which is why it is only the fallback."""
    times = [t for t in ((org or {}).get('owner_active_at'),
                         (snap or {}).get('owner_last_login')) if t]
    return max(times) if times else None


def support_meter(org, snap, trial=None, now=None):
    """Whether a company needs somebody to reach out, and why, from what the
    console already reads: {'level', 'label', 'reasons'}.

    level is one of
      help   reach out now: not set up after the first days, the owner has
             not been back in a fortnight, or the trial is nearly over unused
      watch  worth a look: a week away, set up but no jobs, errors or failing
             automations, a payment past due
      ok     using it
      new    signed up in the last few days; the first-week emails have it
      none   a test or demo account, or not active -- nothing to support

    Pure, like trial_nudges.due(): the snapshot is passed in, so it can be
    tested by describing a company rather than building one."""
    now = now or datetime.utcnow()
    org = org or {}

    def out(level, reasons=()):
        return {'level': level, 'label': SUPPORT_LABELS[level],
                'reasons': list(reasons)}

    if org.get('is_test') or org.get('is_demo'):
        return out('none', ['Test or demo account'])
    if (org.get('status') or 'active') != 'active':
        return out('none', [f"Not active ({org.get('status')})"])
    if not snap or not snap.get('ok'):
        return out('watch', ["Could not read the company's data"])

    created = org.get('created_at') or now
    age = (now - created).days
    activated = bool(org.get('activated_at'))
    seen = owner_last_seen(org, snap)
    away = (now - seen).days if seen else None
    status = (org.get('subscription_status') or '').lower()
    paying = status == 'active'
    help_, watch = [], []

    if not activated and age >= NEW_DAYS:
        help_.append(f'Not set up after {age} days (no cleaner and customer yet)')
    if trial and trial.get('phase') == 'running' and not activated \
            and trial.get('days_left', 99) <= 7:
        left = trial['days_left']
        help_.append(f"Trial ends in {left} day{'' if left == 1 else 's'}, not set up")
    if away is None:
        if age >= NEW_DAYS:
            help_.append('The owner has not been seen using it')
    elif away >= AWAY_HELP_DAYS:
        help_.append(f'{"Paying, but the owner" if paying else "The owner"} '
                     f'has not been in for {away} days')
    elif away >= AWAY_WATCH_DAYS:
        watch.append(f'The owner has not been in for {away} days')
    if activated and age >= 14 and not snap.get('bookings_30d'):
        watch.append('Set up, but no jobs booked in 30 days')
    if snap.get('open_errors'):
        n = snap['open_errors']
        watch.append(f"{n} open error{'' if n == 1 else 's'}")
    # "never" is every automation on a company's first day, before the daily
    # run has reached it, so it only counts once there has been a day to run.
    jobs = snap.get('jobs')
    if jobs is None:
        n = snap.get('jobs_broken') or 0
    else:
        n = sum(1 for j in jobs if j.get('state') in ('stale', 'failing')
                or (j.get('state') == 'never' and age >= 2))
    if n:
        watch.append(f"{n} automation{'' if n == 1 else 's'} not running")
    if status == 'past_due':
        watch.append('Payment past due')

    if help_:
        return out('help', help_ + watch)
    if watch:
        return out('watch', watch)
    return out('new' if age < NEW_DAYS else 'ok')


def extended_trial_end(org, days, now=None):
    """Where a trial ends after adding `days`.

    Added to whichever is later, today or the current end: extending a trial
    that ran out last week by 7 days should give 7 days from now, not a trial
    that is still over.
    """
    now = now or datetime.utcnow()
    current = org.get('trial_ends_at')
    base = current if current and current > now else now
    return base + timedelta(days=days)
