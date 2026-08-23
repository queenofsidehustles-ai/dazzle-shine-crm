"""Are the scheduled jobs actually running?

Nothing in this application schedules itself. Every automation — reminders,
charging cards on the day, follow-up drips — is an HTTP endpoint that an outside
cron calls on a timetable. That arrangement has one bad property: when the cron
stops, the app carries on looking perfectly healthy. There is no error, because
nothing failed. There is just silence, and customers who stop being reminded.

Finding that out used to mean opening the Sent log and reasoning about which
entries could only have come from a schedule rather than from somebody clicking
something. This turns it into a page.

Two independent signals, because each covers the other's blind spot:

  Recorded runs — every call now writes a CronRun row. Precise, but only from
  the day it shipped, so it says nothing about last month.

  Missed work — jobs that should have been done and weren't: a booking whose
  date passed with no reminder recorded against it. Retrospective, and works on
  data that was already there, which is what answers "has this ever run?"
"""
from datetime import datetime, timedelta

# (key, label, what it does, how often it should run)
JOBS = [
    ('reminders', 'Day-before reminders',
     'Texts and emails every customer booked tomorrow.', 'daily'),
    ('charge-balances', 'Charge balances',
     'Takes the balance off the card on file, at each job&rsquo;s start time.', 'hourly'),
    ('lifecycle-emails', 'Follow-ups and win-backs',
     'Thank-yous, review asks and nudges to customers who have gone quiet.', 'daily'),
    ('send-drips', 'Lead nurture drips',
     'Keeps quoting leads warm until they book or opt out.', 'daily'),
    ('applicant-followups', 'Applicant follow-ups',
     'Chases candidates who started an application and stalled.', 'daily'),
]

# How long without a run before a job is treated as stopped rather than idle.
STALE_HOURS = {'hourly': 6, 'daily': 36}


def record(job, items=0, ok=True, detail=None):
    """Note that a scheduled job ran. Never raises: a failure to write the
    bookkeeping must not fail the job itself."""
    try:
        from models import CronRun
        from extensions import db
        db.session.add(CronRun(job=job, items=items or 0, ok=ok,
                               detail=(detail or '')[:300]))
        db.session.commit()
    except Exception:
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass


def _missed_reminders(days=30):
    """Bookings whose day came and went with no reminder recorded.

    Only counts bookings created early enough to have been caught by a
    day-before run — one booked the same morning was never going to get one,
    and counting it would make a working schedule look broken."""
    from models import Booking
    import scheduling
    today = scheduling.local_today()
    since = (today - timedelta(days=days)).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()

    rows = Booking.query.filter(
        Booking.preferred_date >= since,
        Booking.preferred_date <= yesterday,
        Booking.status.in_(['pending', 'confirmed', 'completed']),
        Booking.reminder_sent_at.is_(None),
    ).all()

    missed = 0
    for b in rows:
        try:
            job_day = datetime.strptime(b.preferred_date, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        created = (b.created_at.date() if b.created_at else None)
        if created and created >= job_day:
            continue        # booked the day of, or later — nothing to send
        missed += 1
    return missed


def _uncharged(days=30):
    """Jobs that finished with a balance still sitting on a saved card."""
    from models import Booking
    import scheduling
    today = scheduling.local_today()
    since = (today - timedelta(days=days)).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()
    return Booking.query.filter(
        Booking.preferred_date >= since,
        Booking.preferred_date <= yesterday,
        Booking.status.in_(['confirmed', 'completed']),
        Booking.balance_collected == False,      # noqa: E712 — SQL, not Python
        Booking.balance_due > 0,
        Booking.stripe_payment_method_id.isnot(None),
    ).count()


def overview():
    """One row per job: when it last ran, whether that's recent enough, and
    what evidence there is of work it should have done and didn't."""
    from models import CronRun
    now = datetime.utcnow()
    out = []

    for key, label, blurb, cadence in JOBS:
        last = (CronRun.query.filter_by(job=key)
                .order_by(CronRun.ran_at.desc()).first())
        hours = None if not last else (now - last.ran_at).total_seconds() / 3600.0
        limit = STALE_HOURS.get(cadence, 36)

        if last is None:
            state = 'never'
        elif not last.ok:
            state = 'failing'
        elif hours is not None and hours > limit:
            state = 'stale'
        else:
            state = 'ok'

        evidence = None
        if key == 'reminders':
            n = _missed_reminders()
            if n:
                evidence = (f"{n} booking{'s' if n != 1 else ''} in the last 30 days came and went "
                            f"with no reminder sent.")
        elif key == 'charge-balances':
            n = _uncharged()
            if n:
                evidence = (f"{n} finished job{'s' if n != 1 else ''} still {'have' if n != 1 else 'has'} "
                            f"an uncollected balance on a saved card.")

        out.append({
            'key': key, 'label': label, 'blurb': blurb, 'cadence': cadence,
            'last': last, 'hours': hours, 'state': state, 'evidence': evidence,
        })
    return out


def summary():
    rows = overview()
    broken = [r for r in rows if r['state'] in ('never', 'stale', 'failing')]
    return {'rows': rows, 'broken': broken, 'all_ok': not broken}
