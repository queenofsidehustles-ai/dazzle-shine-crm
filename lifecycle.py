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
    return branding.booking_link()


def _winback_code():
    return _setting('winback_code', 'WELCOME10')


def _unsub_url(email):
    return f"{branding.crm_base()}/api/unsubscribe/{unsubscribe_token(email)}"


def _freq_prices(booking):
    """What ongoing maintenance cleans would cost this home, or None.

    This used to take a discount off whatever the customer last paid. For a
    customer whose last job was a deep clean that quoted a fortnightly price of
    $355 when the real figure was $234 — the deep clean is a one-off big job, not
    the basis for a maintenance rate.

    Prices come from the pricing matrix for the home's own size instead. If the
    home's size isn't recorded there is nothing to price from, and returning
    None means the email is skipped rather than sent with a made-up figure."""
    from pricing import calculate_price
    if not (booking.bedrooms and booking.bathrooms):
        return None
    out = {}
    for name in ('monthly', 'biweekly', 'weekly'):
        try:
            price = calculate_price('standard', booking.bedrooms, booking.bathrooms,
                                    extras='', frequency=name, sqft=booking.sqft)
        except Exception:
            return None
        if not price or price <= 0:
            return None
        out[f'{name}_price'] = f'{price:.2f}'
    return out


def _already_on_a_plan(email):
    """True if this customer already has ongoing cleanings booked.

    The old check only looked for bookings created AFTER the job completed, so
    somebody whose plan was set up first — a deep clean followed by a schedule,
    which is the normal way this starts — still got sold the plan they were
    already on."""
    from models import Booking
    if not email:
        return False
    return Booking.query.filter(
        db.func.lower(Booking.email) == email.lower(),
        Booking.status != 'cancelled',
        db.or_(Booking.recurring_group.isnot(None),
               Booking.frequency.notin_(['one_time', None]))).count() > 0


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


def _send_prospect_drip(p, sequence, n):
    """One step of a prospect's email sequence, in the commercial identity.

    Outreach and a customer's booking confirmation must not share a sender
    reputation: this is the mail that can be marked as spam, and that is not
    the mail that has to arrive.
    """
    import brands
    from notifications import send_email, unsubscribe_token
    from_name, from_email, reply_to = brands.send_identity(brands.COMMERCIAL)
    first = (p.contact_name or '').split()[0] if p.contact_name else 'there'
    place = p.business_name or 'your building'

    MSGS = {
        'send_info': {
            1: ("Did our information reach you?",
                f"<p>Hi {first},</p><p>Just making sure the information we sent over for "
                f"<strong>{place}</strong> arrived — it does sometimes land in junk.</p>"
                f"<p>Happy to answer anything, or walk the building whenever suits.</p>"),
            2: ("Twenty minutes at " + place + "?",
                f"<p>Hi {first},</p><p>Following up on what we sent through for "
                f"<strong>{place}</strong>. The most useful next step is usually a short "
                f"walkthrough — twenty minutes, and you get a real number rather than a "
                f"range.</p><p>Would either of the next two Tuesdays work?</p>"),
            3: ("Last note — and one question",
                f"<p>Hi {first},</p><p>Last note from me on <strong>{place}</strong>, I "
                f"promise. If the timing is simply wrong, that is completely fine.</p>"
                f"<p>One question if you have a second: roughly when does your current "
                f"cleaning contract come up? I would rather get in touch then than keep "
                f"emailing you now.</p>"),
        },
        'nurture': {
            1: ("Checking in on " + place,
                f"<p>Hi {first},</p><p>Just a quick hello — no pitch. If your current "
                f"cleaning is going well, genuinely glad to hear it.</p><p>If anything "
                f"has slipped, we keep a little capacity free for exactly that.</p>"),
            2: ("Still here if you need a second option",
                f"<p>Hi {first},</p><p>Touching base on <strong>{place}</strong>. Most "
                f"people we work with came to us mid-contract, when something stopped "
                f"working — so there is no bad time to have a second number on file.</p>"),
            3: ("Worth a conversation this quarter?",
                f"<p>Hi {first},</p><p>Checking in on <strong>{place}</strong>. If your "
                f"contract is coming up for renewal, this is usually the right moment to "
                f"get a comparison quote — it takes twenty minutes.</p>"),
            4: ("Last check-in from us",
                f"<p>Hi {first},</p><p>This is my last scheduled note on "
                f"<strong>{place}</strong> — I would rather stop than become the supplier "
                f"who keeps emailing.</p><p>We are here whenever the timing changes. Just "
                f"reply and I will pick it straight back up.</p>"),
        },
    }
    subject, inner = MSGS.get(sequence, {}).get(n, (None, None))
    if not subject:
        return False

    unsub = f"{branding.crm_base()}/api/unsubscribe/{unsubscribe_token(p.email)}"
    foot = ('You are receiving this because we spoke about cleaning at your '
            f'property. <a href="{unsub}" style="color:#9a95ad">Unsubscribe</a>.')
    html = brands.email_shell(brands.COMMERCIAL, None, inner, footer_note=foot)
    return send_email(p.email, p.contact_name or p.business_name, subject, html,
                      from_name=from_name, from_email=from_email,
                      reply_to=reply_to)


def run_prospect_sequences(now=None):
    """Send whichever step of each prospect's sequence has come due.

    One step per prospect per run, even if two are overdue -- a prospect whose
    dates were backdated by an import should get a sequence, not a pile of mail
    in one morning.
    """
    from models import Prospect, db
    import prospecting
    now = now or datetime.utcnow()
    sent = 0

    for p in Prospect.query.filter(Prospect.sequence.isnot(None)).all():
        seq = prospecting.SEQUENCES.get(p.sequence)
        # Stopped, opted out, or never had an address. Each is a reason to skip
        # rather than to clear the sequence: the address may arrive later, and
        # an opt-out is not permission to start again if it is withdrawn.
        if not seq or not p.email or is_opted_out(p.email):
            continue
        # Moved on since the sequence started -- they rang back, or she moved
        # them herself. Either way the chasing is over.
        if (p.stage or 'new') not in seq['stages']:
            p.sequence = None
            db.session.commit()
            continue

        base = p.last_drip_at or p.created_at
        if not base:
            continue
        step = p.drip_step or 0
        for days, target in seq['schedule']:
            if step < target and base <= now - timedelta(days=days):
                try:
                    if _send_prospect_drip(p, p.sequence, target):
                        sent += 1
                except Exception:
                    pass
                p.drip_step = target
                # Deliberately NOT reset to now: the schedule is measured from
                # the day the sequence started, so step 2 lands on day 7 rather
                # than seven days after step 1 happened to go out.
                if target >= seq['schedule'][-1][1]:
                    # Finished. It stays on the call list; it stops being mailed.
                    p.sequence = None
                db.session.commit()
                break
    return sent


def run_lifecycle_emails():
    """Process every lifecycle stage. Returns a dict of how many of each were sent."""
    from models import Booking, BookingCrew, Lead, BookingRating, Staff
    now = datetime.utcnow()
    c = {'lead_final': 0, 'morning_of': 0, 'review_nudge': 0,
         'upsell': 0, 'upsell_nudge': 0, 'winback': 0, 'insurance_reminder': 0,
         'onboarding_reminder': 0, 'invoice': 0,
         'quote_followup': 0, 'recurring_topup': 0, 'recurring_expenses': 0,
         'renewals_woken': 0, 'prospect_drip': 0}

    # ── Keep recurring plans filled ~12 weeks ahead (rolling generation) ──
    try:
        import recurring
        c['recurring_topup'] = recurring.topup_all()
    except Exception:
        pass

    # ── Put prospects back on the list before their contract renews ───────
    # Sends nothing; it moves a resting prospect onto today's call list. It
    # rides the daily job rather than getting a cron of its own because a
    # second schedule is a second thing that can silently stop, and this one
    # only has to be right to the day.
    try:
        import prospecting
        c['renewals_woken'] = prospecting.wake_renewals()
    except Exception:
        pass

    # ── The emails that go out between the calls ──────────────────────────
    try:
        c['prospect_drip'] = run_prospect_sequences(now)
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
        # Their own quote link where they have one, so the last email lands them
        # on the price they were given rather than on a calculator.
        import quoting
        link = quoting.quote_url(lead) if lead.quote_token else _booking_link()
        if _send_marketing('lead_drip_final', lead.email, lead.name, {
                'quote_amount': f"{lead.quoted_price:.0f}" if lead.quoted_price else '',
                'booking_link': link}):
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
    # The business's own date. The server runs on UTC, so after early evening
    # local time its idea of "today" is already tomorrow.
    import scheduling
    now_local = scheduling.local_now()
    today = now_local.date().isoformat()
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
        # Hold the invoice until their slot begins, for the same reason the
        # card charge waits: an invoice hours before anyone arrives reads as
        # being asked to pay for work that hasn't started.
        if not scheduling.due_for_charge(b, now_local):
            continue
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
                                  # A move-out clean means they have left. Offering
                                  # to keep that home sparkling every fortnight is
                                  # at best absurd and at worst insulting.
                                  Booking.service_type != 'moveout',
                                  Booking.completed_at.isnot(None)).all():
        if _has_rebooked(b.email, b.completed_at) or _already_on_a_plan(b.email):
            continue
        prices = _freq_prices(b)
        if not prices:
            # Nothing to quote from. Better to say nothing than to quote a price
            # that isn't real.
            continue
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

    return c


def send_cleaner_schedule_reminders():
    """Text/email every active cleaner about tomorrow's jobs. Once per cleaner
    per day, tracked on Staff.schedule_reminder_date.

    Split out from run_lifecycle_emails() (see IAM-02/JOURNEY-01-era launch-
    readiness notes): that function is gated entirely behind the "Follow-ups
    and win-backs" automation, described to the owner only as nudges to
    customers who have gone quiet. A cleaner's day-before job reminder has
    nothing to do with that, so turning off customer win-back texts was
    silently also turning this off, with no way to tell from the toggle's own
    label. Called from the same daily cron as the customer-facing day-before
    reminder (/api/reminders) instead, under the "Day-before reminders"
    automation, which already fires at the right cadence for this and needs
    no new scheduled trigger to exist.

    Also fixes a real, separate bug found alongside the above: this used to
    compute "tomorrow" from datetime.utcnow().date(), not the business's own
    local date -- the same trap the customer-facing reminder route was
    deliberately fixed for (see blueprints/api.py's send_reminders()). A
    business west of UTC could have this fire a day early by server clock.
    """
    from models import Booking, BookingCrew, Staff
    from notifications import send_sms
    import scheduling
    today = scheduling.local_today()
    today_str = today.isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    sent = 0
    for s in Staff.query.filter(Staff.is_active.is_(True)).all():
        if s.schedule_reminder_date == today_str or not s.agreement_token:
            continue
        # Crew members who aren't the lead still need tomorrow's reminder.
        # Held jobs keep the date they were going to be on, so without this a
        # cleaner gets "you have 1 job tomorrow" for a clean that was called off.
        jobs = Booking.query.outerjoin(BookingCrew, BookingCrew.booking_id == Booking.id).filter(
            db.or_(db.func.lower(Booking.assigned_cleaner) == (s.name or '').lower(),
                   BookingCrew.staff_id == s.id),
            Booking.status.notin_(Booking.OFF_SCHEDULE),
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
        sent += 1
        db.session.commit()
    return sent
