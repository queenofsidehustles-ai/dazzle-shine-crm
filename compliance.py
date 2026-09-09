"""Certificates that stop being true, and the chase before they do.

A subcontractor's insurance is not a fact, it is a fact with a date on it. A
certificate collected in March and never looked at again is worse than none,
because by then you believe you are covered -- and the day you find out is the
day somebody has already been sent to a customer's house uninsured.

So the dates are watched, and somebody is told before they pass rather than
after. Three windows, because the right response is different in each:

  soon      thirty days out, which is time to ask for the renewal
  urgent    seven days out, which is time to stop sending them work
  expired   the certificate no longer covers anything

Nothing here sends anything to the subcontractor. It tells the business, and
the business decides -- chasing a renewal is a relationship, not a mailshot,
and a company that has just renewed does not want an automated demand.
"""
from datetime import date, timedelta

SOON_DAYS = 30
URGENT_DAYS = 7

# What is watched, and what to call it in a sentence somebody reads at 7am.
WATCHED = (
    ('insurance_expires', 'general liability insurance'),
    ('workers_comp_expires', "workers' compensation"),
)


def _as_date(value):
    """YYYY-MM-DD, or None. A blank or a typo is not an emergency."""
    try:
        return date.fromisoformat((value or '').strip())
    except (ValueError, AttributeError):
        return None


def _band(when, today):
    if when < today:
        return 'expired'
    if when <= today + timedelta(days=URGENT_DAYS):
        return 'urgent'
    if when <= today + timedelta(days=SOON_DAYS):
        return 'soon'
    return None


def expiring(today=None):
    """Every company whose paperwork is running out, worst first.

    Only companies, and only ones that are actually working with the business.
    Chasing a certificate belonging to somebody who was turned down eight
    months ago is noise, and noise is how a real warning gets ignored.
    """
    from models import ContractorApplication
    today = today or date.today()
    rows = []
    try:
        apps = ContractorApplication.query.filter(
            ContractorApplication.applicant_kind == 'company',
            ContractorApplication.status.notin_(['rejected', 'withdrawn'])).all()
    except Exception:
        return rows

    for a in apps:
        for field, label in WATCHED:
            when = _as_date(getattr(a, field, None))
            if not when:
                continue
            band = _band(when, today)
            if not band:
                continue
            rows.append({
                'id': a.id,
                'company': a.company_name or a.name,
                'what': label,
                'when': when,
                'days': (when - today).days,
                'band': band,
            })
    order = {'expired': 0, 'urgent': 1, 'soon': 2}
    rows.sort(key=lambda r: (order[r['band']], r['when']))
    return rows


def missing(today=None):
    """Companies working with the business that have no date on file at all.

    A blank is not reassuring. It means nobody has ever checked, which is the
    same exposure as an expired certificate and easier to miss because nothing
    ever turns red.
    """
    from models import ContractorApplication
    out = []
    try:
        apps = ContractorApplication.query.filter(
            ContractorApplication.applicant_kind == 'company',
            ContractorApplication.status.notin_(['rejected', 'withdrawn'])).all()
    except Exception:
        return out
    for a in apps:
        gaps = [label for field, label in WATCHED
                if not _as_date(getattr(a, field, None))]
        if gaps:
            out.append({'id': a.id, 'company': a.company_name or a.name,
                        'missing': gaps})
    return out


def sentence(row):
    """One line a person can act on without opening anything."""
    if row['band'] == 'expired':
        days = abs(row['days'])
        ago = 'today' if days == 0 else f'{days} day{"s" if days != 1 else ""} ago'
        return (f'{row["company"]} — {row["what"]} expired {ago}. '
                f'Do not send them work until it is renewed.')
    if row['band'] == 'urgent':
        return (f'{row["company"]} — {row["what"]} runs out in '
                f'{row["days"]} day{"s" if row["days"] != 1 else ""}.')
    return (f'{row["company"]} — {row["what"]} runs out on '
            f'{row["when"].strftime("%d %b")}.')
