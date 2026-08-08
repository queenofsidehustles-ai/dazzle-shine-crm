"""Customer-lifecycle email engine — run once per cron tick.

Sends each stage's email at most once (tracked with timestamps), respects
marketing opt-out, and stops when the customer acts (books / rebooks). All the
wording lives in editable EmailTemplate records. See EMAIL_AUTOMATION_PLAN.md.
"""
from datetime import datetime, timedelta
from extensions import db
from notifications import send_triggered_email, is_opted_out, unsubscribe_token
from pricing import FREQUENCY_DISCOUNTS
import branding



def _setting(key, fallback):
    from models import BusinessSetting
    return BusinessSetting.get(key) or fallback


def _booking_link():
    return _setting('booking_link', 'https://www.dazzleandshinemaids.com/#book')


def _winback_code():
    return _setting('winback_code', 'WELCOME10')


def _unsub_url(email):
    return f"{branding.crm_base()}/api/unsubscribe/{unsubscribe_token(email)}"


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


def _send_quote_followup(q, n):
    """Send nurture follow-up #n for a sent-but-unanswered commercial quote,
    branded to the quote's brand (commercial or primary)."""
    import brands
    from notifications import send_email, unsubscribe_token
    brand = q.brand or brands.brand_for_property(q.property_type)
    from_name, from_email, reply_to = brands.send_identity(brand)
    url = f"{branding.crm_base()}/quotes/view/{q.token}"
    first = (q.contact_name or '').split()[0] if q.contact_name else 'there'
    company = q.company or 'your property'
    MSGS = {
        1: ("Just checking in on your cleaning proposal",
            f"<p>Hi {first},</p><p>Just making sure our cleaning proposal for <strong>{company}</strong> "
            f"reached you. Whenever you're ready, you can review everything and accept it right here.</p>"),
        2: ("Any questions about your cleaning quote?",
            f"<p>Hi {first},</p><p>Following up on the proposal for <strong>{company}</strong>. I'd be glad to "
            f"answer questions, adjust the scope, or tweak the schedule — just reply and let me know. "
            f"Your full quote is still ready here:</p>"),
        3: ("Still here whenever you're ready",
            f"<p>Hi {first},</p><p>Last quick note on your cleaning proposal for <strong>{company}</strong>. "
            f"No pressure at all — whenever the timing is right, your quote is ready and waiting. "
            f"We'd love to earn your business.</p>"),
    }
    subject, inner = MSGS.get(n, MSGS[1])
    unsub = f"{branding.crm_base()}/api/unsubscribe/{unsubscribe_token(q.email)}"
    foot = ("You're receiving this because we sent you a cleaning quote. "
            f'<a href="{unsub}" style="color:#9a95ad">Unsubscribe</a>.')
    html = brands.email_shell(brand, None, inner, cta_text='View &amp; Accept Quote →',
                              cta_url=url, footer_note=foot)
    return send_email(q.email, q.contact_name, subject, html,
                      from_name=from_name, from_email=from_email, reply_to=reply_to)


def run_lifecycle_emails():
    """Process every lifecycle stage. Returns a dict of how many of each were sent."""
    from models import Booking, BookingCrew, Lead, BookingRating, Staff
    now = datetime.utcnow()
    c = {'lead_final': 0, 'morning_of': 0, 'review_nudge': 0,
         'upsell': 0, 'upsell_nudge': 0, 'winback': 0, 'insurance_reminder': 0,
         'onboarding_reminder': 0, 'schedule_reminder': 0, 'invoice': 0,
         'quote_followup': 0, 'recurring_topup': 0, 'recurring_expenses': 0}

    # ── Keep recurring plans filled ~12 weeks ahead (rolling generation) ──
    try:
        import recurring
        c['recurring_topup'] = recurring.topup_all()
    except Exception:
        pass

    # ── Post monthly costs whose day has come (insurance, software, phone) ──
    try:
        from blueprints.money import post_due_recurring
        c['recurring_expenses'] = post_due_recurring(now.date())
    except Exception:
        pass

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

    # ── Commercial quote nurture — follow up on sent, unanswered quotes (day 2/5/9) ──
    from models import CommercialQuote
    QUOTE_SCHEDULE = [(2, 1), (5, 2), (9, 3)]
    for q in CommercialQuote.query.filter(CommercialQuote.status == 'sent').all():
        if not q.email or is_opted_out(q.email):
            continue
        base = q.sent_at or q.created_at
        if not base:
            continue
        step = q.drip_step or 0
        for days, target in QUOTE_SCHEDULE:
            if step < target and base <= now - timedelta(days=days):
                try:
                    _send_quote_followup(q, target)
                    c['quote_followup'] += 1
                except Exception:
                    pass
                q.drip_step = target
                q.last_drip_at = now
                db.session.commit()
                break

    # ── B3 — morning-of note (job scheduled today) ──
    today = now.date().isoformat()
    for b in Booking.query.filter(Booking.status.in_(['pending', 'confirmed']),
                                  Booking.preferred_date == today,
                                  Booking.morning_note_at.is_(None)).all():
        _send_transactional('booking_morning_of', b.email, b.name, {})
        c['morning_of'] += 1
        b.morning_note_at = now
        db.session.commit()

    # ── Morning-of INVOICE — unpaid jobs today with no saved card get a pay link ──
    from blueprints.payments import send_payment_link
    for b in Booking.query.filter(Booking.status.in_(['pending', 'confirmed']),
                                  Booking.preferred_date == today,
                                  Booking.paid_at.is_(None),
                                  Booking.stripe_payment_method_id.is_(None),
                                  Booking.invoice_sent_at.is_(None)).all():
        try:
            send_payment_link(b, kind='full')
            c['invoice'] += 1
        except Exception:
            pass
        b.invoice_sent_at = now
        db.session.commit()

    # ── C3 — review nudge (rating request 3+ days old, still unrated) ──
    for r in BookingRating.query.filter(BookingRating.rating.is_(None),
                                        BookingRating.created_at <= now - timedelta(days=3)).all():
        b = r.booking
        if not b or b.review_nudge_at or b.skip_review:
            continue
        if _send_marketing('review_nudge', b.email, b.name,
                           {'rate_link': f"{branding.crm_base()}/rate/{r.token}"}):
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
        done = Booking.query.outerjoin(BookingCrew, BookingCrew.booking_id == Booking.id).filter(
            db.or_(db.func.lower(Booking.assigned_cleaner) == (s.name or '').lower(),
                   BookingCrew.staff_id == s.id),
            Booking.status == 'completed').distinct().count()
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
        link = f"{branding.crm_base()}/contractors/onboarding/{s.agreement_token}"
        _send_transactional('contractor_onboarding_reminder', s.email, s.name,
                            {'onboarding_link': link})
        c['onboarding_reminder'] += 1
        s.onboarding_reminder_at = now
        s.onboarding_reminder_count = (s.onboarding_reminder_count or 0) + 1
        db.session.commit()

    # ── Day-before schedule reminder — text/email cleaners about tomorrow's jobs ──
    from notifications import send_sms
    today_str = now.date().isoformat()
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    for s in Staff.query.filter(Staff.is_active.is_(True)).all():
        if s.schedule_reminder_date == today_str or not s.agreement_token:
            continue
        # Crew members who aren't the lead still need tomorrow's reminder.
        jobs = Booking.query.outerjoin(BookingCrew, BookingCrew.booking_id == Booking.id).filter(
            db.or_(db.func.lower(Booking.assigned_cleaner) == (s.name or '').lower(),
                   BookingCrew.staff_id == s.id),
            Booking.status != 'cancelled',
            Booking.preferred_date == tomorrow,
        ).distinct().all()
        if not jobs:
            continue
        n = len(jobs)
        myday = f"{branding.crm_base()}/contractors/my-day/{s.agreement_token}"
        _send_transactional('cleaner_schedule_reminder', s.email, s.name,
                            {'job_count': n, 'tomorrow_date': tomorrow, 'myday_link': myday})
        if s.phone:
            try:
                send_sms(s.phone, f"Reminder: you have {n} job(s) tomorrow ({tomorrow}). "
                                  f"See your day: {myday}")
            except Exception:
                pass
        s.schedule_reminder_date = today_str
        c['schedule_reminder'] += 1
        db.session.commit()

    return c
