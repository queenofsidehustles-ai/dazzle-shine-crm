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
            open_q = ErrorLog.query.filter_by(resolved=False)
            errors = [{
                'kind': e.kind, 'message': e.message, 'path': e.path,
                'count': e.count or 1, 'first_seen': e.first_seen,
                'last_seen': e.last_seen,
            } for e in open_q.order_by(ErrorLog.last_seen.desc()).limit(10).all()]
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
                'open_errors': open_q.count(),
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
        if key in seen:
            seen[key]['times'] += 1
        else:
            seen[key] = dict(lead, times=1)
    return list(seen.values())


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
