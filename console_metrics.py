"""One machine-readable answer to "how many customers are there, and are they paying".

Written because the question had no answer that did not involve reading source
code. The console shows all of this, on pages built for a person: every figure
is in HTML, behind a session and a TOTP prompt, spread across /companies and
/funnel. A weekly operator report, a spreadsheet, or anything that is not a
human with a browser could not reach it, so the customer count got worked out
from the repository instead -- which is how a number ends up being inferred
from code that describes intent rather than from the database that holds fact.

So: the same aggregates, as JSON, read-only, in one request.

Three things it deliberately reports that the HTML does not put in one place:

  * Test and demo companies counted apart from real ones. A total of twelve
    tenants is not twelve customers, and the difference is the whole number
    anybody actually wants. These come from the is_test/is_demo flags on the
    control-plane row rather than from guessing at slugs -- a company called
    `akyetest` that nobody flagged is counted as real here, on purpose,
    because an unflagged test account is a data-quality problem that should be
    visible rather than papered over by a naming heuristic.

  * How each company has asked for balances to be collected. The hourly
    charge job runs for everybody and charges only those who chose `auto`
    (automations.is_enabled('charge-balances')), so a timetable that is firing
    correctly and a business that has opted in are two different facts, and
    only the second one moves money. Without this, "the cron is fixed" and
    "the cron is earning" are indistinguishable from outside.

  * The build that produced the answer. Two branches have deployed this
    application; a figure with no provenance cannot be compared with last
    week's.

Nothing here writes. Every per-company read goes through console_data, which
goes through tenancy.use_tenant -- the same boundary a tenant request uses.
"""
from datetime import datetime


def _iso(value):
    """A date that json.dumps can take, or None."""
    return value.isoformat() if hasattr(value, 'isoformat') else None


def _count(rows, key):
    out = {}
    for r in rows:
        out[r.get(key) or 'unknown'] = out.get(r.get(key) or 'unknown', 0) + 1
    return dict(sorted(out.items()))


def collect(engine, now=None):
    """Every tenant, what it pays, and whether its automations are working."""
    import branding
    import control_plane
    import console_data
    import attribution

    now = now or datetime.utcnow()
    orgs = control_plane.all_orgs(engine)
    snaps = console_data.snapshots(orgs)

    companies = []
    for o in orgs:
        snap = snaps.get(o['slug']) or {}
        readable = bool(snap.get('ok'))
        companies.append({
            'slug': o['slug'],
            'name': o.get('name'),
            'status': o.get('status') or 'active',
            'plan': o.get('plan') or 'solo',
            'subscription_status': o.get('subscription_status'),
            'mrr_cents': o.get('mrr_cents') or 0,
            'is_test': bool(o.get('is_test')),
            'is_demo': bool(o.get('is_demo')),
            'grandfathered': bool(o.get('grandfathered')),
            'created_at': _iso(o.get('created_at')),
            'activated_at': _iso(o.get('activated_at')),
            'paid_since': _iso(o.get('paid_since')),
            'trial_ends_at': _iso(o.get('trial_ends_at')),
            'came_from': attribution.label(o),
            # Only present when the company's own schema would read. A tenant
            # that will not read is said to be unreadable rather than reported
            # as a company with no clients and no bookings, which looks the
            # same in a chart and is not the same thing at all.
            'readable': readable,
            'why_unreadable': None if readable else (snap.get('why') or 'unknown'),
            'balance_mode': snap.get('balance_mode'),
            'clients': snap.get('clients'),
            'users': snap.get('users'),
            'bookings_30d': snap.get('bookings_30d'),
            'completed_30d': snap.get('completed_30d'),
            'jobs_broken': snap.get('jobs_broken'),
            'open_errors': snap.get('open_errors'),
            'last_login': _iso(snap.get('last_login')),
            'owner_last_login': _iso(snap.get('owner_last_login')),
        })

    real = [c for c in companies if not c['is_test'] and not c['is_demo']]
    live = [c for c in real if c['status'] == 'active']
    paying = [c for c in real
              if (c['subscription_status'] or '') == 'active']

    # How balances are actually being collected, across real companies only.
    # 'auto' is the only value the hourly job charges anything for.
    modes = {}
    for c in real:
        modes[c['balance_mode'] or 'unknown'] = \
            modes.get(c['balance_mode'] or 'unknown', 0) + 1

    return {
        'as_of': now.isoformat(),
        # Which code answered. See the module docstring.
        'build': {
            'version': branding.version(),
            'channel': branding.release_channel(),
            'release': branding.release_tag(),
        },
        'tenants': {
            'total': len(companies),
            'real': len(real),
            'test': sum(1 for c in companies if c['is_test']),
            'demo': sum(1 for c in companies if c['is_demo']),
            'active': len(live),
            'unreadable': sum(1 for c in companies if not c['readable']),
            'by_status': _count(real, 'status'),
            'by_plan': _count(real, 'plan'),
            'by_subscription': _count(real, 'subscription_status'),
        },
        'revenue': {
            'paying': len(paying),
            'mrr_cents': sum(c['mrr_cents'] for c in paying),
            'trialing': sum(1 for c in real
                            if (c['subscription_status'] or '') == 'trialing'),
            'past_due': sum(1 for c in real
                            if (c['subscription_status'] or '') == 'past_due'),
        },
        # The gap between "the job runs" and "the job collects".
        'balance_collection': {
            'by_mode': dict(sorted(modes.items())),
            'auto': modes.get('auto', 0),
            'would_charge': modes.get('auto', 0),
            'of_real': len(real),
        },
        'health': {
            'jobs_broken': sum(c['jobs_broken'] or 0 for c in real),
            'open_errors': sum(c['open_errors'] or 0 for c in real),
            'companies_with_broken_jobs': sum(
                1 for c in real if (c['jobs_broken'] or 0) > 0),
        },
        'companies': companies,
    }
