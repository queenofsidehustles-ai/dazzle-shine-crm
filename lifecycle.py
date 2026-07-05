"""Customer-lifecycle email engine — run once per cron tick.

Sends each stage's email at most once (tracked with timestamps), respects
marketing opt-out, and stops when the customer acts (books / rebooks). All the
wording lives in editable EmailTemplate records. See EMAIL_AUTOMATION_PLAN.md.
"""
from datetime import datetime, timedelta
from extensions import db
from notifications import send_triggered_email, is_opted_out, unsubscribe_token
from pricing import FREQUENCY_DISCOUNTS

CRM_BASE = 'https://dazzle-shine-crm-production.up.railway.app'


def _setting(key, fallback):
    from models import BusinessSetting
    return BusinessSetting.get(key) or fallback


def _booking_link():
    return _setting('booking_link', 'https://www.dazzleandshinemaids.com/#book')


def _winback_code():
    return _setting('winback_code', 'WELCOME10')


def _unsub_url(email):
    return f"{CRM_BASE}/api/unsubscribe/{unsubscribe_token(email)}"


def _freq_prices(price):
    p = price or 0
    def disc(name):
        return f"{round(p * (1 - FREQUENCY_DISCOUNTS.get(name, 0) / 100), 2):.2f}"
    return {'monthly_price': disc('monthly'),
            'biweekly_price': disc('biweekly'),
            'weekly_price': disc('weekly')}


def _has_rebooked(email, after_dt):
    from models import Booking
    if not email:
        return False
    q = Booking.query.filter(db.func.lower(Booking.email) == email.lower())
    if after_dt:
        q = q.filter(Booking.created_at > after_dt)
    return q.count() > 0


def _send_marketing(trigger, email, name, variables):
    """Marketing send: skip opted-out recipients, attach an unsubscribe link."""
    if not email or is_opted_out(email):
        return False
    try:
        return send_triggered_email(trigger, email, name, variables,
                                    unsubscribe_url=_unsub_url(email))
    except Exception:
        return False


def _send_transactional(trigger, email, name, variables):
    if not email:
        return False
    try:
        return send_triggered_email(trigger, email, name, variables)
    except Exception:
        return False


def run_lifecycle_emails():
    """Process every lifecycle stage. Returns a dict of how many of each were sent."""
    from models import Booking, Lead, BookingRating, Staff
    now = datetime.utcnow()
    c = {'lead_final': 0, 'morning_of': 0, 'review_nudge': 0,
         'upsell': 0, 'upsell_nudge': 0, 'winback': 0, 'insurance_reminder': 0,
         'onboarding_reminder': 0}

    # ── A4 — final lead follow-up (~5 days after the last-chance drip) ──
    for lead in Lead.query.filter(Lead.drip_step == 3, Lead.status == 'new').all():
        last = lead.last_drip_at or lead.created_at
        if not last or last > now - timedelta(days=5):
            continue
        if _send_marketing('lead_drip_final', lead.email, lead.name, {
                'quote_amount': f"{lead.quoted_price:.0f}" if lead.quoted_price else '',
                'booking_link': _booking_link()}):
            c['lead_final'] += 1
        lead.drip_step = 4
        lead.last_drip_at = now
        db.session.commit()

    # ── B3 — morning-of note (job scheduled today) ──
    today = now.date().isoformat()
    for b in Booking.query.filter(Booking.status.in_(['pending', 'confirmed']),
                                  Booking.preferred_date == today,
                                  Booking.morning_note_at.is_(None)).all():
        _send_transactional('booking_morning_of', b.email, b.name, {})
        c['morning_of'] += 1
        b.morning_note_at = now
        db.session.commit()

    # ── C3 — review nudge (rating request 3+ days old, still unrated) ──
    for r in BookingRating.query.filter(BookingRating.rating.is_(None),
                                        BookingRating.created_at <= now - timedelta(days=3)).all():
        b = r.booking
        if not b or b.review_nudge_at:
            continue
        if _send_marketing('review_nudge', b.email, b.name,
                           {'rate_link': f"{CRM_BASE}/rate/{r.token}"}):
            c['review_nudge'] += 1
        b.review_nudge_at = now
        db.session.commit()

    # ── D1 / D2 — recurring upsell for one-time completed jobs ──
    one_time = db.or_(Booking.frequency == 'one_time', Booking.frequency.is_(None))
    for b in Booking.query.filter(Booking.status == 'completed', one_time,
                                  Booking.completed_at.isnot(None)).all():
        if _has_rebooked(b.email, b.completed_at):
            continue
        prices = _freq_prices(b.price)
        variables = {'booking_link': _booking_link(), **prices}
        if not b.upsell_sent_at and b.completed_at <= now - timedelta(days=2):
            if _send_marketing('recurring_upsell', b.email, b.name, variables):
                c['upsell'] += 1
            b.upsell_sent_at = now
            db.session.commit()
        elif (b.upsell_sent_at and not b.upsell_nudge_at
              and b.upsell_sent_at <= now - timedelta(days=7)):
            if _send_marketing('recurring_upsell_nudge', b.email, b.name, variables):
                c['upsell_nudge'] += 1
            b.upsell_nudge_at = now
            db.session.commit()

    # ── D3 — win-back (customer's latest completed job 50+ days ago, no rebook) ──
    seen = set()
    for b in Booking.query.filter(Booking.status == 'completed',
                                  Booking.completed_at.isnot(None)) \
                          .order_by(Booking.completed_at.desc()).all():
        key = (b.email or '').lower()
        if not key or key in seen:
            continue
        seen.add(key)                       # only their most-recent completed job
        if b.winback_sent_at or b.completed_at > now - timedelta(days=50):
            continue
        if _has_rebooked(b.email, b.completed_at):
            continue
        if _send_marketing('winback', b.email, b.name,
                           {'booking_link': _booking_link(), 'discount_code': _winback_code()}):
            c['winback'] += 1
        b.winback_sent_at = now
        db.session.commit()

    # ── Insurance reminder — after a contractor completes a few cleanings ──
    INSURANCE_AFTER_JOBS = 3
    for s in Staff.query.filter(Staff.is_active.is_(True),
                                Staff.insurance_reminder_sent_at.is_(None)).all():
        if not s.email or (s.worker_model or 'contractor') == 'employee':
            continue
        done = Booking.query.filter(
            db.func.lower(Booking.assigned_cleaner) == (s.name or '').lower(),
            Booking.status == 'completed').count()
        if done < INSURANCE_AFTER_JOBS:
            continue
        _send_transactional('contractor_insurance_reminder', s.email, s.name, {})
        c['insurance_reminder'] += 1
        s.insurance_reminder_sent_at = now
        db.session.commit()

    # ── Onboarding reminders — nudge recent new hires who haven't finished setup ──
    ONBOARD_MAX = 3
    for s in Staff.query.filter(Staff.is_active.is_(True)).all():
        if not s.email or not s.agreement_token:
            continue
        if not s.created_at or s.created_at < now - timedelta(days=30):
            continue                                  # only recent onboarders
        if s.agreement_signed_at and s.stripe_payouts_enabled:
            continue                                  # fully onboarded — done
        if (s.onboarding_reminder_count or 0) >= ONBOARD_MAX:
            continue
        last = s.onboarding_reminder_at or s.created_at
        if last and last > now - timedelta(days=2):
            continue                                  # every ~2 days
        link = f"{CRM_BASE}/contractors/onboarding/{s.agreement_token}"
        _send_transactional('contractor_onboarding_reminder', s.email, s.name,
                            {'onboarding_link': link})
        c['onboarding_reminder'] += 1
        s.onboarding_reminder_at = now
        s.onboarding_reminder_count = (s.onboarding_reminder_count or 0) + 1
        db.session.commit()

    return c
