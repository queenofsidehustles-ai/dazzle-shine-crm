"""Proactive recurring scheduling.

Instead of creating the next visit only after one is completed (reactive), this
generates a rolling window of FUTURE visits so a recurring client's whole
schedule shows on the calendar ahead of time. Visits in one plan share a
`recurring_group` token. A rolling top-up (run from the cron) keeps the window
filled as time passes.
"""
import secrets
from datetime import date, timedelta

FREQ_DAYS = {'weekly': 7, 'biweekly': 14, 'monthly': 30}


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
        status='pending', price=seed.price, balance_due=seed.balance_due,
        source=seed.source, agent=seed.agent,
        # carry the card on file so morning-of auto-pay works for the whole series
        stripe_customer_id=seed.stripe_customer_id,
        stripe_payment_method_id=seed.stripe_payment_method_id,
        recurring_group=group, recurring_active=True,
    )


def _fill(seed, group, from_date, horizon, existing_dates):
    """Add visits from `from_date` (exclusive) up to `horizon`. Returns count."""
    from extensions import db
    delta = FREQ_DAYS.get(seed.frequency)
    if not delta:
        return 0
    created = 0
    d = from_date + timedelta(days=delta)
    while d <= horizon:
        iso = d.isoformat()
        if iso not in existing_dates:
            db.session.add(_copy_visit(seed, d, group))
            existing_dates.add(iso)
            created += 1
        d += timedelta(days=delta)
    return created


def generate_series(seed, weeks_ahead=12):
    """Fill the calendar with future visits for this recurring booking, up to
    `weeks_ahead` out. Attaches a recurring_group if the booking has none.
    Returns the number of visits created."""
    from models import Booking
    from extensions import db
    if seed.frequency not in FREQ_DAYS or not seed.preferred_date:
        return 0
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
    n = _fill(seed, seed.recurring_group, start, horizon, existing)
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


def upcoming_count(group):
    from models import Booking
    today = date.today().isoformat()
    return Booking.query.filter(
        Booking.recurring_group == group,
        Booking.status != 'cancelled',
        Booking.preferred_date >= today).count()


def topup_all(weeks_ahead=12, min_weeks=8):
    """Rolling generator — keep every active recurring series filled ~weeks_ahead
    out. Call from the lifecycle cron. Returns count of visits created."""
    from models import Booking
    from extensions import db
    today = date.today()
    min_horizon = today + timedelta(weeks=min_weeks)
    horizon = today + timedelta(weeks=weeks_ahead)
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
        if not dates or max(dates) >= min_horizon:
            continue
        seed = max(visits, key=lambda v: v.preferred_date or '')
        total += _fill(seed, g, max(dates), horizon, {v.preferred_date for v in visits})
    if total:
        db.session.commit()
    return total
