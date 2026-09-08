"""What to do today, worked out from what is actually true.

The difference between software that reports and software worth paying for is
whether it tells you anything you would not have gone looking for. "You made
$4,200 last month" is a fact. "Three people asked for a price yesterday and
nobody has replied" is a morning.

## Computed, never generated

Every line here comes from a count against the database. No model is involved
and nothing is invented, which matters more than it sounds: a made-up task is
worse than no task, because the person doing it loses an hour and stops trusting
the list.

## No standing orders

"Post on Facebook. Call ten leads." is the same every day whether or not it
means anything, and a list that says the same thing every morning is one nobody
reads by Friday. Everything below is a real gap with a real number in it, and
disappears the day it stops being true. A quiet day should look quiet.

## Ordered by what it costs to ignore

Not by how hard it is. A lead going cold costs you the job; an unassigned
cleaner tomorrow costs you the customer. Money already earned but uncollected
sits above prospecting, because chasing it is quicker than replacing it.
"""
from datetime import timedelta


def _today():
    import scheduling
    return scheduling.local_today()


def _money(n):
    return f'${n:,.2f}'


def _plural(n, one, many=None):
    return one if n == 1 else (many or one + 's')


def items():
    """Everything worth doing today, most costly to ignore first.

    Each is (urgency, sentence, link). Nothing is added unless its count is
    real, so an empty list is a genuine answer and not a failure.
    """
    from models import Booking, Lead, Prospect, CommercialQuote
    out = []
    today = _today()

    # ── Somebody is waiting on you ────────────────────────────────────────
    # A price request goes cold in hours. This is the only thing on the list
    # where the delay itself is what loses the job.
    new_leads = Lead.query.filter(Lead.status == 'new').count()
    if new_leads:
        out.append(('now',
                    f'{new_leads} {_plural(new_leads, "enquiry", "enquiries")} '
                    f'waiting for a price. They are deciding today.',
                    '/leads/'))

    # ── Somebody will not turn up ─────────────────────────────────────────
    tomorrow = today + timedelta(days=1)
    unassigned = Booking.query.filter(
        Booking.preferred_date == tomorrow.isoformat(),
        Booking.status.in_(['confirmed', 'pending']),
        (Booking.assigned_cleaner.is_(None)) | (Booking.assigned_cleaner == ''),
    ).count()
    if unassigned:
        out.append(('now',
                    f'{unassigned} {_plural(unassigned, "job")} tomorrow with '
                    f'nobody assigned.',
                    '/bookings/'))

    # ── Money already earned ──────────────────────────────────────────────
    # Above prospecting on purpose: collecting what you are owed is faster than
    # finding the same amount again.
    import finance
    owed = finance.unpaid_outstanding()
    if owed > 0:
        out.append(('today',
                    f'{_money(owed)} owed on work booked or already done.',
                    '/money/pnl'))

    # ── Pipeline that has gone quiet ──────────────────────────────────────
    due = Prospect.query.filter(
        Prospect.next_action_date.isnot(None),
        Prospect.next_action_date <= today.isoformat(),
    ).count()
    if due:
        out.append(('today',
                    f'{due} commercial {_plural(due, "prospect")} due a call back.',
                    '/find-leads/'))

    # sent_at is a real timestamp, unlike Booking.preferred_date and
    # Prospect.next_action_date which are ISO strings. Comparing a DATETIME
    # column against a date string is the kind of thing that quietly matches
    # everything or nothing depending on the database underneath.
    from datetime import datetime as _dt, time as _time
    cutoff = _dt.combine(today - timedelta(days=4), _time.min)
    cold_quotes = CommercialQuote.query.filter(
        CommercialQuote.status.in_(['sent', 'pending']),
        CommercialQuote.responded_at.is_(None),
        CommercialQuote.sent_at.isnot(None),
        CommercialQuote.sent_at <= cutoff,
    ).count()
    if cold_quotes:
        out.append(('today',
                    f'{cold_quotes} commercial {_plural(cold_quotes, "quote")} sent '
                    f'over four days ago with no answer.',
                    '/commercial/quotes'))

    # ── Empty diary ───────────────────────────────────────────────────────
    # The one that is easy to ignore until it is too late to fix. A gap next
    # week is work you can still win; a gap this week is already lost.
    booked_days = {b.preferred_date for b in Booking.query.filter(
        Booking.preferred_date >= (today + timedelta(days=7)).isoformat(),
        Booking.preferred_date < (today + timedelta(days=14)).isoformat(),
        Booking.status.in_(['confirmed', 'pending']),
    ).all()}
    weekdays = [today + timedelta(days=7 + i) for i in range(7)]
    open_days = [d for d in weekdays
                 if d.weekday() < 5 and d.isoformat() not in booked_days]
    if len(open_days) >= 3:
        out.append(('this week',
                    f'{len(open_days)} weekdays next week with nothing booked. '
                    f'That is the week to fill, while there is still time.',
                    '/find-leads/'))

    return out


def summary():
    """The list, plus a sentence for when there is nothing on it."""
    rows = items()
    return {
        'items': rows,
        'nothing': not rows,
        'say': ('Nothing needs you today — no enquiries waiting, everyone is '
                'assigned, and nothing is overdue.') if not rows else None,
    }


def as_text():
    """The same thing, said out loud. Used by Nana."""
    data = summary()
    if data['nothing']:
        return data['say']
    lines = [f'· {text}' for _urg, text, _link in data['items']]
    n = len(lines)
    return (f'{n} {_plural(n, "thing")} worth doing today:\n' + '\n'.join(lines))
