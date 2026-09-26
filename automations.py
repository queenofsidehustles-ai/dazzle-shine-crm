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
     'Texts and emails every customer booked tomorrow, and every cleaner with a job tomorrow.', 'daily'),
    ('charge-balances', 'Charge balances',
     'Takes the balance off the card on file, at each job&rsquo;s start time.', 'hourly'),
    ('lifecycle-emails', 'Follow-ups and win-backs',
     'Thank-yous, review asks and nudges to customers who have gone quiet.', 'daily'),
    ('send-drips', 'Lead nurture drips',
     'Keeps quoting leads warm until they book or opt out.', 'daily'),
    ('applicant-followups', 'Applicant follow-ups',
     'Chases candidates who started an application and stalled.', 'daily'),
    ('lsa-followups', 'Google Ads follow-ups',
     'Texts the people who called through Google Ads and never booked.', 'daily'),
    # Only does anything for a business using subcontractors. Harmless and
    # silent for everybody else, which is why it is on by default: the ones
    # who need it are exactly the ones who will not think to switch it on.
    ('insurance-expiry', 'Subcontractor insurance',
     'Warns you before a subcontractor&rsquo;s insurance or workers&rsquo; '
     'compensation runs out.', 'daily'),
    # Off by default, unlike the rest of this list. Those five are what
    # somebody signed up for; this is a daily email nobody asked to start
    # receiving, and the one automation here whose entire value depends on
    # being wanted rather than merely tolerated.
    ('owner-digest', 'Morning digest',
     'Emails you each morning with what actually needs you today — the same '
     'specific list Nana can read back, sent before you open the app.', 'daily'),
]

# Everything above defaults to on. This one is the exception: an inbox that
# starts filling up the day somebody signs up, before they have asked for it,
# is the fastest way to get every automation email filtered straight past
# them — including the ones that matter.
DEFAULT_OFF = {'owner-digest'}

# What a business has decided about each job. Absence means on: the five that
# send messages are what somebody signed up for, and a new company should not
# have to switch its reminders on.
#
# Balances are the exception and have three answers rather than two, because
# "off" is two different businesses: one that wants telling when money is owed,
# and one that collects it in cash and does not want the card touched at all.
BALANCE_MODES = ('auto', 'ask', 'never')
BALANCE_DEFAULT = 'ask'


def _setting(key, default=''):
    try:
        from models import BusinessSetting
        return (BusinessSetting.get(key) or default).strip()
    except Exception:
        # A settings lookup must never be the reason a job does not run. On the
        # message jobs that means carrying on; on the money one the default is
        # the cautious answer, so a broken read cannot charge anybody.
        return default


def is_enabled(job):
    """Has this business turned this job off?

    Checked by the job itself rather than by whatever woke it, so the answer
    holds however it is triggered -- the nightly run, a run by hand, or anything
    built later that nobody has thought of yet.
    """
    if job == 'charge-balances':
        return balance_mode() == 'auto'
    if job in DEFAULT_OFF:
        return _setting(f'automation_{job}_on') == '1'
    return _setting(f'automation_{job}_off') != '1'


def balance_mode():
    """auto: charge the card on the day.
       ask:  do not charge; show it as owed so the owner decides.
       never: do not charge, and do not offer to -- collected outside here.

    Defaults to `ask`. Charging a card cannot be undone, so the default is the
    one that cannot surprise a customer.
    """
    mode = _setting('balance_collection', BALANCE_DEFAULT)
    return mode if mode in BALANCE_MODES else BALANCE_DEFAULT


def set_enabled(job, on):
    from models import BusinessSetting
    if job in DEFAULT_OFF:
        # Absence has to mean off here, the opposite of every other job's
        # switch -- so it needs its own key. Writing '1'/'' to the shared
        # `_off` key would mean a business that had never touched this
        # setting and one that had explicitly turned it off were
        # indistinguishable, and is_enabled() would have no way to tell
        # "never asked" from "asked, and said no."
        BusinessSetting.set(f'automation_{job}_on', '1' if on else '')
        return
    BusinessSetting.set(f'automation_{job}_off', '' if on else '1')


def set_balance_mode(mode):
    from models import BusinessSetting
    BusinessSetting.set('balance_collection',
                        mode if mode in BALANCE_MODES else BALANCE_DEFAULT)


def cleaner_reminders_enabled():
    """The cleaner half of the day-before reminders job, switched separately
    from `is_enabled('reminders')`, which is the customer half.

    One daily job, one cron address -- this doesn't split into a second row
    in JOBS, because there is no second endpoint to call. It's two
    independent questions asked of the same run: a business might want her
    customers left alone while cleaners still get warned tomorrow's job
    exists, or the other way round."""
    return _setting('automation_reminders_cleaner_off') != '1'


def set_cleaner_reminders_enabled(on):
    from models import BusinessSetting
    BusinessSetting.set('automation_reminders_cleaner_off', '' if on else '1')


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

        on = is_enabled(key)
        if key == 'reminders':
            # Two independent switches share this one row -- it only reads as
            # fully "off" when neither customers nor cleaners are getting
            # anything, not just because one of the two was turned down.
            on = on or cleaner_reminders_enabled()
        if not on:
            # Off on purpose is not the same as broken, and a page that cannot
            # tell them apart trains people to ignore it.
            state, evidence = 'off', ''
        out.append({
            'key': key, 'label': label, 'blurb': blurb, 'cadence': cadence,
            'last': last, 'hours': hours, 'state': state, 'evidence': evidence,
            'on': on,
        })
    return out


def summary():
    rows = overview()
    broken = [r for r in rows if r['state'] in ('never', 'stale', 'failing')]
    return {'rows': rows, 'broken': broken, 'all_ok': not broken}
