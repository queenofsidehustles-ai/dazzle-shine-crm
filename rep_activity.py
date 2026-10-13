"""What a Sales rep did, counted: calls against their daily target, and the
week or month behind it.

Read from prospect_activity -- one row per call, text, email, walkthrough and
hand-off, with who did it (see places_finder._record). Days are the
business's days, not the server's: a call at 9pm in Atlanta is that day's
call, though it is stored as tomorrow in UTC.
"""
from datetime import datetime, time, timedelta, timezone

# A sitting worth of calls when nobody has said otherwise. The call sheet
# stopped at twenty long before targets existed; it is the same number.
DEFAULT_DAILY_CALLS = 20

PERIODS = (('today', 'Today'), ('week', 'This week'), ('month', 'This month'))


def default_target():
    """The company's calls-a-day for every rep without their own number."""
    from models import BusinessSetting
    try:
        n = int(float(BusinessSetting.get('sales_daily_calls') or 0))
    except (TypeError, ValueError):
        n = 0
    return n if n > 0 else DEFAULT_DAILY_CALLS


def target_for(user):
    """A rep's calls a day: their own number if the owner set one."""
    own = getattr(user, 'daily_call_target', None) if user is not None else None
    return own if own and own > 0 else default_target()


def period_dates(period, today=None):
    """The first and last local day of a period, ending today."""
    from scheduling import local_today
    today = today or local_today()
    if period == 'week':
        return today - timedelta(days=today.weekday()), today
    if period == 'month':
        return today.replace(day=1), today
    return today, today


def utc_bounds(first, last):
    """Local days first..last as the naive-UTC range rows are stored in."""
    from scheduling import business_timezone
    tz = business_timezone()
    start = datetime.combine(first, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


def counts(user_ids, first, last):
    """{user id: {kind: n, 'conversations': n}} for each login, over local
    days first..last. One query, whoever is asked about.

    By login, not by name: a name can be reused -- a rep leaves, their login
    is deleted, somebody else is added under the same name -- and the new
    rep must not start with the old one's calls."""
    from models import ProspectActivity
    start, end = utc_bounds(first, last)
    out = {i: _blank() for i in user_ids}
    if not user_ids:
        return out
    rows = (ProspectActivity.query
            .filter(ProspectActivity.user_id.in_(list(user_ids)),
                    ProspectActivity.created_at >= start,
                    ProspectActivity.created_at < end)
            .with_entities(ProspectActivity.user_id, ProspectActivity.kind,
                           ProspectActivity.outcome)
            .all())
    for uid, kind, outcome in rows:
        c = out.setdefault(uid, _blank())
        c[kind] = c.get(kind, 0) + 1
        if kind == 'call' and outcome not in ProspectActivity.NO_CONVERSATION:
            c['conversations'] += 1
    return out


def calls_today(user_id):
    """How many calls this login has logged today."""
    from scheduling import local_today
    today = local_today()
    return counts([user_id], today, today)[user_id]['call']


def recent(user_ids, limit=30):
    """The latest things these logins did, newest first."""
    from models import ProspectActivity
    return (ProspectActivity.query
            .filter(ProspectActivity.user_id.in_(list(user_ids) or [-1]))
            .order_by(ProspectActivity.created_at.desc()).limit(limit).all())


def won(names, first, last):
    """{name: [accounts]} -- commercial accounts each rep is credited with,
    signed (first invoice paid) in the period."""
    from models import CommercialAccount
    start, end = utc_bounds(first, last)
    out = {n: [] for n in names}
    if not names:
        return out
    for a in (CommercialAccount.query
              .filter(CommercialAccount.agent.in_(list(names)),
                      CommercialAccount.first_paid_at.isnot(None),
                      CommercialAccount.first_paid_at >= start,
                      CommercialAccount.first_paid_at < end).all()):
        out.setdefault(a.agent, []).append(a)
    return out


def _blank():
    from models import ProspectActivity
    return dict({k: 0 for k in ProspectActivity.KINDS}, conversations=0)
