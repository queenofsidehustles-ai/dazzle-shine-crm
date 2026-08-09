"""Proactive recurring scheduling.

Instead of creating the next visit only after one is completed (reactive), this
generates a rolling window of FUTURE visits so a recurring client's whole
schedule shows on the calendar ahead of time. Visits in one plan share a
`recurring_group` token. A rolling top-up (run from the cron) keeps the window
filled as time passes.
"""
import calendar
import secrets
from datetime import date, timedelta

FREQ_DAYS = {'weekly': 7, 'biweekly': 14}

# 'monthly' is deliberately absent above. It used to be 30 days, which drifts
# about five days a year — a client told "the 9th of every month" would have
# been on the 6th by February. Monthly now lands on the same date each month.
MONTHLY = 'monthly'

# How far ahead to fill the calendar, by frequency. One flat window doesn't work:
# 12 weeks is three months of weekly visits but barely two monthly ones, so a
# monthly client's plan looked like it had failed to generate at all.
HORIZON_WEEKS = {'weekly': 12, 'biweekly': 16, MONTHLY: 52}
DEFAULT_HORIZON_WEEKS = 12


def horizon_weeks(frequency):
    return HORIZON_WEEKS.get(frequency, DEFAULT_HORIZON_WEEKS)


# How a monthly plan repeats. Customers think about their cleaning in one of two
# ways and both are common: "the 9th of every month", or "the second Wednesday".
BY_DATE = 'date'
BY_WEEKDAY = 'weekday'

_ORDINALS = {1: '1st', 2: '2nd', 3: '3rd', 4: '4th', 5: 'last'}
_WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def weekday_position(d):
    """(weekday, ordinal) for a date — Wednesday the 9th is (2, 2): the second
    Wednesday. An occurrence with no fifth in some months is treated as 'last',
    so a plan never silently skips a month."""
    ordinal = (d.day - 1) // 7 + 1
    if ordinal >= 5 or d.day + 7 > calendar.monthrange(d.year, d.month)[1]:
        # The last of its kind this month — repeat it as "last", which exists in
        # every month, rather than a fifth that often doesn't.
        if d.day + 7 > calendar.monthrange(d.year, d.month)[1]:
            ordinal = 5
    return d.weekday(), ordinal


def describe_weekday(d):
    """'2nd Wednesday' — for showing the owner what she's choosing."""
    weekday, ordinal = weekday_position(d)
    return f'{_ORDINALS.get(ordinal, str(ordinal))} {_WEEKDAYS[weekday]}'


def _nth_weekday(year, month, weekday, ordinal):
    """The nth given weekday of a month; ordinal 5 means the last one."""
    first_weekday = date(year, month, 1).weekday()
    offset = (weekday - first_weekday) % 7
    last_day = calendar.monthrange(year, month)[1]
    if ordinal >= 5:
        day = 1 + offset + ((last_day - 1 - offset) // 7) * 7
    else:
        day = 1 + offset + (ordinal - 1) * 7
        if day > last_day:
            day -= 7
    return date(year, month, day)


def _add_month(anchor_year, anchor_month, anchor_day, months_out):
    """The same day-of-month, `months_out` months after the anchor.

    Clamped to the end of short months: a plan anchored on the 31st visits the
    28th in February and returns to the 31st in March, rather than sliding
    permanently earlier."""
    total = (anchor_year * 12) + (anchor_month - 1) + months_out
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def _copy_visit(seed, on_date, group):
    from models import Booking
    return Booking(
        client_id=seed.client_id, service_type=seed.service_type,
        bedrooms=seed.bedrooms, bathrooms=seed.bathrooms, extras=seed.extras,
        sqft=seed.sqft, frequency=seed.frequency,
        preferred_date=on_date.isoformat(), preferred_time=seed.preferred_time,
        name=seed.name, email=seed.email, phone=seed.phone,
        address=seed.address, city=seed.city, zip_code=seed.zip_code,
        access_notes=seed.access_notes, assigned_cleaner=seed.assigned_cleaner,
        # A big house still needs a crew every visit — but each visit gets claimed
        # fresh, so carry the size, not the people.
        crew_size=seed.crew_size or 1,
        status='pending', price=seed.price, balance_due=seed.balance_due,
        source=seed.source, agent=seed.agent,
        # carry the card on file so morning-of auto-pay works for the whole series
        stripe_customer_id=seed.stripe_customer_id,
        stripe_payment_method_id=seed.stripe_payment_method_id,
        monthly_mode=getattr(seed, 'monthly_mode', None),
        recurring_group=group, recurring_active=True,
    )


def _visit_dates(seed, from_date, horizon, anchor=None):
    """Every date this plan should be cleaned, after `from_date` up to `horizon`.

    `anchor` is the date the plan started, which fixes the day-of-month for a
    monthly plan. Without it a top-up months later would re-anchor to whatever
    the last visit happened to be, and a February visit clamped to the 28th
    would drag every later visit to the 28th for good."""
    if seed.frequency == MONTHLY:
        anchor = anchor or from_date
        by_weekday = (getattr(seed, 'monthly_mode', None) or BY_DATE) == BY_WEEKDAY
        weekday, ordinal = weekday_position(anchor)
        out, n = [], 1
        while True:
            if by_weekday:
                total = (anchor.year * 12) + (anchor.month - 1) + n
                year, month = divmod(total, 12)
                d = _nth_weekday(year, month + 1, weekday, ordinal)
            else:
                d = _add_month(anchor.year, anchor.month, anchor.day, n)
            if d > horizon:
                break
            if d > from_date:
                out.append(d)
            n += 1
        return out

    delta = FREQ_DAYS.get(seed.frequency)
    if not delta:
        return []
    out, d = [], from_date + timedelta(days=delta)
    while d <= horizon:
        out.append(d)
        d += timedelta(days=delta)
    return out


def _fill(seed, group, from_date, horizon, existing_dates, anchor=None):
    """Add visits from `from_date` (exclusive) up to `horizon`. Returns count."""
    from extensions import db
    created = 0
    for d in _visit_dates(seed, from_date, horizon, anchor):
        iso = d.isoformat()
        if iso not in existing_dates:
            db.session.add(_copy_visit(seed, d, group))
            existing_dates.add(iso)
            created += 1
    return created


def generate_series(seed, weeks_ahead=None):
    """Fill the calendar with future visits for this recurring booking.

    `weeks_ahead` defaults to a window that suits the frequency — a year for a
    monthly plan, a quarter for a weekly one — so every plan generates a
    sensible number of visits rather than whatever a single fixed window
    happens to yield."""
    from models import Booking
    from extensions import db
    if (seed.frequency not in FREQ_DAYS and seed.frequency != MONTHLY) or not seed.preferred_date:
        return 0
    if weeks_ahead is None:
        weeks_ahead = horizon_weeks(seed.frequency)
    if not seed.recurring_group:
        seed.recurring_group = secrets.token_hex(8)
    seed.recurring_active = True
    try:
        start = date.fromisoformat(seed.preferred_date)
    except ValueError:
        return 0
    existing = {b.preferred_date for b in
                Booking.query.filter_by(recurring_group=seed.recurring_group).all()}
    horizon = date.today() + timedelta(weeks=weeks_ahead)
    # The first visit's date is the anchor for a monthly plan.
    n = _fill(seed, seed.recurring_group, start, horizon, existing, anchor=start)
    db.session.commit()
    return n


def stop_series(group):
    """Stop a recurring plan: deactivate it and remove FUTURE unstarted visits
    (keeps past/completed ones for history). Returns count removed."""
    from models import Booking
    from extensions import db
    today = date.today().isoformat()
    removed = 0
    for b in Booking.query.filter_by(recurring_group=group).all():
        b.recurring_active = False
        if b.status == 'pending' and (b.preferred_date or '') > today:
            db.session.delete(b)
            removed += 1
    db.session.commit()
    return removed


def clear_future(seed):
    """Remove not-yet-started future visits in this plan, keeping the seed.

    Used when the plan's pattern changes and the generated dates are no longer
    the right ones. Deliberately narrow: a visit that is confirmed, completed,
    or already in the past is history and is never touched."""
    from models import Booking
    from extensions import db
    if not seed.recurring_group:
        return 0
    today = date.today().isoformat()
    removed = 0
    for b in Booking.query.filter_by(recurring_group=seed.recurring_group).all():
        if b.id == seed.id:
            continue
        if b.status == 'pending' and (b.preferred_date or '') > today:
            db.session.delete(b)
            removed += 1
    db.session.commit()
    return removed


def upcoming_count(group):
    from models import Booking
    today = date.today().isoformat()
    return Booking.query.filter(
        Booking.recurring_group == group,
        Booking.status != 'cancelled',
        Booking.preferred_date >= today).count()


def topup_all(weeks_ahead=None, min_weeks=None):
    """Rolling generator — keep every active recurring series filled out to a
    window that suits its own frequency. Call from the lifecycle cron. Returns
    count of visits created."""
    from models import Booking
    from extensions import db
    today = date.today()
    groups = {b.recurring_group for b in Booking.query.filter(
        Booking.recurring_group.isnot(None),
        Booking.recurring_active.is_(True)).all() if b.recurring_group}
    total = 0
    for g in groups:
        visits = Booking.query.filter(Booking.recurring_group == g,
                                      Booking.status != 'cancelled').all()
        dates = []
        for v in visits:
            try:
                dates.append(date.fromisoformat(v.preferred_date))
            except (ValueError, TypeError):
                pass
        seed = max(visits, key=lambda v: v.preferred_date or '')
        weeks = weeks_ahead if weeks_ahead is not None else horizon_weeks(seed.frequency)
        floor = min_weeks if min_weeks is not None else max(2, int(weeks * 0.66))
        horizon = today + timedelta(weeks=weeks)
        if not dates or max(dates) >= today + timedelta(weeks=floor):
            continue
        # Anchor on the plan's FIRST visit, not its latest, so a monthly plan
        # keeps the day of the month it started on.
        total += _fill(seed, g, max(dates), horizon,
                       {v.preferred_date for v in visits}, anchor=min(dates))
    if total:
        db.session.commit()
    return total
