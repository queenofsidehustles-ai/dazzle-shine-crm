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


def counts(names, first, last):
    """{name: {kind: n, 'conversations': n}} for each name, over local days
    first..last. One query, whoever is asked about."""
    from models import ProspectActivity
    start, end = utc_bounds(first, last)
    out = {n: _blank() for n in names}
    if not names:
        return out
    rows = (ProspectActivity.query
            .filter(ProspectActivity.user_name.in_(list(names)),
                    ProspectActivity.created_at >= start,
                    ProspectActivity.created_at < end)
            .with_entities(ProspectActivity.user_name, ProspectActivity.kind,
                           ProspectActivity.outcome)
            .all())
    for name, kind, outcome in rows:
        c = out.setdefault(name, _blank())
        c[kind] = c.get(kind, 0) + 1
        if kind == 'call' and outcome not in ProspectActivity.NO_CONVERSATION:
            c['conversations'] += 1
    return out


def calls_today(name):
    """How many calls `name` has logged today."""
    from scheduling import local_today
    today = local_today()
    return counts([name], today, today)[name]['call']


def recent(names=None, limit=30):
    """The latest things done, newest first -- everybody's, or these people's."""
    from models import ProspectActivity
    q = ProspectActivity.query
    if names is not None:
        q = q.filter(ProspectActivity.user_name.in_(list(names) or ['']))
    return q.order_by(ProspectActivity.created_at.desc()).limit(limit).all()


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
