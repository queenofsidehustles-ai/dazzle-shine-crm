import os
import secrets
import stripe
from datetime import date, timedelta, datetime
from flask import Blueprint, request, jsonify
from models import Booking, Client
from extensions import db
from pricing import calculate_price, SERVICES, EXTRAS, FREQUENCY_LABELS, DEPOSIT_AMOUNT
from notifications import send_email, send_sms, add_to_mailerlite
import branding
import integrations
import automations

api_bp = Blueprint('api', __name__, url_prefix='/api')

# Local addresses used while developing. The real ones come from whichever
# website this business actually has — hardcoding one company's domain meant no
# other company's site could ever reach its own CRM.
DEV_ORIGINS = ['http://localhost:3000', 'http://127.0.0.1:5500']


def allowed_origins():
    import branding
    out = list(DEV_ORIGINS)
    extra = (os.environ.get('ALLOWED_ORIGINS') or '').split(',')
    out += [o.strip().rstrip('/') for o in extra if o.strip()]
    site = (branding.website() or '').strip().rstrip('/')
    if site:
        host = site.replace('https://', '').replace('http://', '')
        bare = host[4:] if host.startswith('www.') else host
        out += ['https://' + bare, 'https://www.' + bare]
    base = branding.crm_base()
    if base:
        out.append(base.rstrip('/'))
    return out


def add_cors(response, origin):
    if origin in allowed_origins():
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


# ── Public config (Stripe publishable key) ───────────────────────────────────

@api_bp.route('/config', methods=['GET', 'OPTIONS'])
def get_config():
    origin = request.headers.get('Origin', '')
    if request.method == 'OPTIONS':
        return add_cors(jsonify({}), origin), 200
    resp = jsonify({'stripe_pk': integrations.stripe_publishable_key()})
    return add_cors(resp, origin), 200


# ── 24-hour reminder sender (call from a cron or Railway scheduled job) ───────

@api_bp.route('/reminders', methods=['POST'])
def send_reminders():
    api_key = request.headers.get('X-Api-Key') or request.args.get('api_key', '')
    expected = os.environ.get('REMINDER_API_KEY', '')
    if not expected or api_key != expected:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    # The business's own date, not the server's. In the evening a UTC server
    # already believes it is tomorrow, so "tomorrow" would land a day late —
    # the same trap charge-balances was fixed for.
    import scheduling
    tomorrow = (scheduling.local_today() + timedelta(days=1)).isoformat()
    bookings = Booking.query.filter(
        Booking.preferred_date == tomorrow,
        Booking.status.in_(['pending', 'confirmed']),
        # Once per booking, ever. This used to re-send to everyone booked
        # tomorrow on every call, so an hourly cron would have texted the same
        # customer twenty-four times in a day.
        Booking.reminder_sent_at.is_(None),
    ).all()

    count = 0
    failed = []
    for b in bookings:
        # Per booking, so one bad record can't take the run down with it. That
        # is exactly what happened before: a recurring visit with no balance
        # set raised, the request 500'd, and nobody on the list got anything.
        try:
            _send_reminder(b)
            b.reminder_sent_at = datetime.utcnow()
            count += 1
        except Exception as e:      # noqa: BLE001 — a bad row is not fatal
            db.session.rollback()
            failed.append(f'#{b.id} {b.name}: {e}')
    db.session.commit()

    automations.record('reminders', items=count, ok=not failed,
                       detail='; '.join(failed) or None)
    return jsonify({'ok': True, 'reminders_sent': count, 'failed': failed})


# ── Auto-charge balances (cron — run hourly) ─────────────────────────────────
#
# Runs hourly rather than at one set time. Each booking is charged when its own
# appointment starts, so nobody's card is touched before the day they were told
# somebody would arrive. A single morning run only ever suited whoever happened
# to be booked at that hour.

@api_bp.route('/charge-balances', methods=['POST'])
def charge_balances():
    api_key = request.headers.get('X-Api-Key') or request.args.get('api_key', '')
    expected = os.environ.get('REMINDER_API_KEY', '')
    if not expected or api_key != expected:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    import scheduling
    from payment_service import charge_balance as do_charge
    # The business's own date, not the server's — in the evening the server
    # already believes it is tomorrow.
    today = scheduling.local_today().isoformat()
    now_local = scheduling.local_now()
    bookings = Booking.query.filter(
        Booking.preferred_date == today,
        Booking.status.in_(['confirmed', 'pending']),
        Booking.balance_collected == False,
        Booking.stripe_customer_id != None,
        Booking.stripe_payment_method_id != None,
    ).all()

    results = []
    waiting = []
    for b in bookings:
        if not scheduling.due_for_charge(b, now_local):
            waiting.append({'booking_id': b.id, 'name': b.name,
                            'due_at': scheduling.describe(b)})
            continue
        ok, err = do_charge(b)
        results.append({'booking_id': b.id, 'name': b.name, 'ok': ok, 'error': err})
    db.session.commit()

    # Second pass: portal / recurring auto-pay clients — charge the FULL amount to
    # the client's card on file. Guarded so a booking already handled above (paid /
    # balance_collected) is skipped, and only fires when the CLIENT opted into autopay.
    from payment_service import autocharge
    auto = Booking.query.filter(
        Booking.preferred_date == today,
        Booking.status.in_(['confirmed', 'pending']),
        Booking.paid_at.is_(None),
        Booking.balance_collected == False,
    ).all()
    for b in auto:
        client = b.client
        if not (client and client.autopay):
            continue
        has_card = (b.stripe_customer_id and b.stripe_payment_method_id) or \
                   (client.stripe_customer_id and client.stripe_payment_method_id)
        if not has_card:
            continue
        if not scheduling.due_for_charge(b, now_local):
            waiting.append({'booking_id': b.id, 'name': b.name,
                            'due_at': scheduling.describe(b), 'autopay': True})
            continue
        ok, err = autocharge(b)
        results.append({'booking_id': b.id, 'name': b.name, 'ok': ok, 'error': err, 'autopay': True})
    db.session.commit()

    charged = len([r for r in results if r['ok']])
    failed = [r for r in results if not r['ok']]
    automations.record('charge-balances', items=charged, ok=not failed,
                       detail='; '.join(str(r.get('error')) for r in failed) or None)
    return jsonify({'ok': True, 'charged': charged,
                    'results': results,
                    'waiting_for_their_appointment': waiting})


# ── Lead quote capture (from website) ─────────────────────────────────────────

@api_bp.route('/quote', methods=['POST', 'OPTIONS'])
def capture_quote():
    origin = request.headers.get('Origin', '')
    if request.method == 'OPTIONS':
        return add_cors(jsonify({}), origin), 200

    # Accept JSON, form-encoded, or query params — never silently reject a real lead
    data = request.get_json(silent=True) or {}
    if not data:
        data = request.form.to_dict() or request.values.to_dict() or {}
    if not data.get('name') or not data.get('email'):
        resp = jsonify({'ok': False, 'error': 'Name and email required'})
        return add_cors(resp, origin), 400

    from pricing import get_lead_fee
    total = calculate_price(
        service_type=data.get('service_type', ''),
        bedrooms=data.get('bedrooms', 1),
        bathrooms=data.get('bathrooms', 1),
        extras=data.get('extras', ''),
        frequency=data.get('frequency', 'one_time'),
        sqft=data.get('sqft'),
    ) + get_lead_fee()   # bake in the (invisible) lead fee

    from models import Lead
    lead = Lead(
        name=data['name'].strip(), email=data['email'].lower().strip(),
        phone=data.get('phone', '').strip(), service_type=data.get('service_type', ''),
        bedrooms=data.get('bedrooms', ''), bathrooms=data.get('bathrooms', ''),
        extras=data.get('extras', ''), frequency=data.get('frequency', 'one_time'),
        address=data.get('address', '').strip(), city=data.get('city', '').strip(),
        zip_code=data.get('zip_code', '').strip(),
        quoted_price=total, source='website', status='new', drip_step=1,
    )
    db.session.add(lead)
    db.session.commit()

    _send_quote_email(lead, total)
    _send_speed_to_lead(lead, total)   # instant text to lead + alert to owner
    add_to_mailerlite(lead.email, lead.name)
    resp = jsonify({'ok': True, 'total': total, 'deposit': DEPOSIT_AMOUNT,
                    'balance_due': round(total - DEPOSIT_AMOUNT, 2)})
    return add_cors(resp, origin), 201


# ── Commercial / janitorial lead capture (from /commercial/) ──────────────────

COMMERCIAL_FACILITY_LABELS = {
    'office': 'Professional office / suite',
    'medical': 'Medical or dental practice',
    'retail': 'Retail center / storefront',
    'fitness': 'Fitness studio / gym',
    'childcare': 'Childcare / learning center',
    'church': 'Church / event hall',
    'salon': 'Salon, spa or clinic',
    'warehouse': 'Warehouse / light industrial',
    'hoa': 'HOA clubhouse / commons',
    'bank': 'Bank / credit union',
    'apartment': 'Apartment community / rental portfolio',
    'other': 'Other facility',
}


@api_bp.route('/commercial-lead', methods=['POST', 'OPTIONS'])
def capture_commercial_lead():
    """Walkthrough request from a facility or property manager.

    Deliberately returns NO price. Commercial scope is set per site at the
    walkthrough, so there is no bed/bath matrix to quote from — sending these
    leads through /api/quote would email them a residential number that means
    nothing. This just captures the lead and alerts the owner to call.

    Saved with drip_step=0 so the residential price-drip cron skips them:
    those drip emails interpolate lead.quoted_price, which is None here.
    """
    origin = request.headers.get('Origin', '')
    if request.method == 'OPTIONS':
        return add_cors(jsonify({}), origin), 200

    # Same permissive parsing as /api/quote — never silently reject a real lead
    data = request.get_json(silent=True) or {}
    if not data:
        data = request.form.to_dict() or request.values.to_dict() or {}

    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone = (data.get('phone') or '').strip()
    if not name or not email:
        return add_cors(jsonify({'ok': False, 'error': 'Name and email required'}), origin), 400

    inquiry = data.get('inquiry_type') or 'commercial'
    if inquiry not in ('commercial', 'apartment_turnover'):
        inquiry = 'commercial'

    company = (data.get('company') or '').strip()
    facility = (data.get('facility_type') or '').strip()
    sqft = (str(data.get('sqft') or '')).strip()
    frequency = (data.get('frequency') or '').strip()
    message = (data.get('message') or '').strip()

    # Lead has no commercial columns and the app uses db.create_all() with no
    # migrations, so the site detail goes in notes rather than new columns.
    facility_label = COMMERCIAL_FACILITY_LABELS.get(facility, facility or '—')
    notes = '\n'.join([
        'COMMERCIAL WALKTHROUGH REQUEST',
        f'Company / property: {company or "—"}',
        f'Facility type: {facility_label}',
        f'Approx. square footage: {sqft or "—"}',
        f'Frequency wanted: {frequency or "—"}',
        f'Notes from them: {message or "—"}',
    ])

    from models import Lead
    lead = Lead(
        name=name, email=email, phone=phone,
        service_type=inquiry,
        frequency=frequency or 'custom',
        city=(data.get('city') or '').strip(),
        zip_code=(data.get('zip_code') or '').strip(),
        notes=notes,
        quoted_price=None,          # priced at walkthrough, never on the website
        source='website_commercial',
        status='new',
        drip_step=0,                # excluded from the residential drip sequence
    )
    db.session.add(lead)
    db.session.commit()

    _send_commercial_alert(lead, company, facility_label, sqft, frequency, message)

    resp = jsonify({'ok': True})
    return add_cors(resp, origin), 201


def _send_commercial_alert(lead, company, facility_label, sqft, frequency, message):
    """Text + email the owner. No customer-facing price, so no quote text."""
    from models import BusinessSetting
    biz = branding.biz_name()
    owner_phone = (BusinessSetting.get('owner_phone') or BusinessSetting.get('phone')
                   or os.environ.get('OWNER_PHONE', ''))
    owner_email = (BusinessSetting.get('email')
                   or branding.owner_email())

    kind = 'APARTMENT TURNOVER' if lead.service_type == 'apartment_turnover' else 'COMMERCIAL'
    alert = (f"\U0001F3E2 NEW {kind} LEAD — call them now! {lead.name}"
             f"{' at ' + company if company else ''}, {lead.phone or 'no phone'}. "
             f"{facility_label}, {sqft or '?'} sqft, {frequency or 'frequency TBD'}.")
    if owner_phone:
        send_sms(owner_phone, alert)

    try:
        send_email(
            to_email=owner_email, to_name=biz,
            from_name=biz,
            subject=f"\U0001F3E2 New {kind.title()} lead: {lead.name} — call them now!",
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">New {kind.title()} Walkthrough Request</h2>
  <p><strong>Name:</strong> {lead.name} &nbsp; <strong>Phone:</strong> {lead.phone or '—'}</p>
  <p><strong>Email:</strong> {lead.email}</p>
  <p><strong>Company / property:</strong> {company or '—'}</p>
  <p><strong>Facility type:</strong> {facility_label}</p>
  <p><strong>Approx. square footage:</strong> {sqft or '—'}</p>
  <p><strong>Frequency wanted:</strong> {frequency or '—'}</p>
  <p><strong>Notes:</strong> {message or '—'}</p>
  <p style="color:#5f5878;font-size:0.9rem">No price was quoted — scope is set at the walkthrough.</p>
</div>""",
        )
    except Exception:
        pass


# ── Lead drip emails (cron — use same REMINDER_API_KEY) ───────────────────────

@api_bp.route('/send-drips', methods=['POST'])
def send_drips():
    api_key = request.headers.get('X-Api-Key') or request.args.get('api_key', '')
    expected = os.environ.get('REMINDER_API_KEY', '')
    if not expected or api_key != expected:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    from models import Lead
    today = date.today()
    step2 = Lead.query.filter(Lead.drip_step == 1, Lead.status == 'new',
                               Lead.created_at <= today - timedelta(days=2)).all()
    step3 = Lead.query.filter(Lead.drip_step == 2, Lead.status == 'new',
                               Lead.last_drip_at <= today - timedelta(days=3)).all()
    count = 0
    for lead in step2:
        _send_drip_followup(lead)
        lead.drip_step = 2
        lead.last_drip_at = datetime.utcnow()
        count += 1
    for lead in step3:
        _send_drip_lastchance(lead)
        lead.drip_step = 3
        lead.last_drip_at = datetime.utcnow()
        count += 1
    db.session.commit()
    automations.record('send-drips', items=count)
    return jsonify({'ok': True, 'drips_sent': count})


# ── Applicant interview follow-ups (cron — run once daily) ────────────────────
# Re-sends the bilingual video interview link every 2 days to applicants who
# haven't responded (up to 2 extra nudges), then marks them "No Response".

@api_bp.route('/applicant-followups', methods=['POST'])
def applicant_followups():
    api_key = request.headers.get('X-Api-Key') or request.args.get('api_key', '')
    expected = os.environ.get('REMINDER_API_KEY', '')
    if not expected or api_key != expected:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    from models import ContractorApplication
    from blueprints.interviews import send_interview_invite_email

    now = datetime.utcnow()
    cutoff = now - timedelta(days=2)   # spacing between nudges

    def _qualifies(a):
        """Same rule the apply form uses: needs experience + transportation."""
        exp = (a.years_experience or '').strip().lower()
        return bool(exp) and exp not in ('no experience', 'none') and bool(a.has_transportation)

    # Include applicants who never got a link at all ('not_sent'/None), so a missed
    # timer can never leave a qualified person stuck without their interview.
    candidates = ContractorApplication.query.filter(
        ContractorApplication.status.notin_(['rejected', 'hired', 'onboarding', 'no_response']),
        db.or_(
            ContractorApplication.interview_status.in_(['pending', 'sent', 'in_progress', 'not_sent']),
            ContractorApplication.interview_status.is_(None),
        ),
    ).all()

    nudged = 0
    first_sent = 0
    no_response = 0
    for a in candidates:
        iv = a.interview_status or 'not_sent'

        # ── Backstop: qualified applicant who never actually received a link ──
        # Covers a missed 10-min timer AND anyone stuck at 'not_sent'/'reviewing'.
        if not a.interview_sent_at and iv in ('pending', 'not_sent'):
            applied_ago_ok = a.created_at and a.created_at <= now - timedelta(minutes=10)
            if _qualifies(a) and applied_ago_ok:
                if not a.interview_token:
                    a.interview_token = secrets.token_urlsafe(32)
                a.interview_status = 'sent'
                a.interview_sent_at = now
                a.interview_last_sent_at = now
                db.session.commit()
                try:
                    send_interview_invite_email(a)
                    first_sent += 1
                except Exception:
                    pass
            continue

        if iv not in ('sent', 'in_progress'):
            continue  # e.g. completed — nothing to nudge

        last = a.interview_last_sent_at or a.interview_sent_at
        if not last or last > cutoff:
            continue  # not enough time has passed since the last send

        count = a.interview_nudge_count or 0
        if count < 2:
            try:
                send_interview_invite_email(a)
                a.interview_nudge_count = count + 1
                a.interview_last_sent_at = now
                nudged += 1
                db.session.commit()
            except Exception:
                db.session.rollback()
        else:
            # Original + 2 nudges sent, still silent → move out of the active list
            a.status = 'no_response'
            no_response += 1
            db.session.commit()

    automations.record('applicant-followups', items=nudged + first_sent)
    return jsonify({'ok': True, 'nudged': nudged,
                    'first_invites_sent': first_sent,
                    'moved_to_no_response': no_response})


# ── Lifecycle marketing emails (cron — run daily or every 15 min) ─────────────
# Final lead drip, morning-of note, review nudge, recurring upsell + nudge, win-back.

@api_bp.route('/lifecycle-emails', methods=['POST'])
def lifecycle_emails():
    api_key = request.headers.get('X-Api-Key') or request.args.get('api_key', '')
    expected = os.environ.get('REMINDER_API_KEY', '')
    if not expected or api_key != expected:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403
    import lifecycle
    counts = lifecycle.run_lifecycle_emails()
    automations.record('lifecycle-emails', items=sum(v for v in counts.values()
                                                     if isinstance(v, int)))
    return jsonify({'ok': True, **counts})


# ── One-click unsubscribe (public) ────────────────────────────────────────────

@api_bp.route('/unsubscribe/<token>')
def unsubscribe(token):
    from notifications import verify_unsubscribe_token
    from models import EmailOptOut
    email = verify_unsubscribe_token(token)
    page = ("<div style='font-family:Inter,sans-serif;max-width:480px;margin:60px auto;"
            "text-align:center;color:#1f1333;padding:0 20px'>")
    if not email:
        return page + "<h2>Invalid link</h2><p>This unsubscribe link is not valid.</p></div>", 400
    if not EmailOptOut.query.filter_by(email=email).first():
        db.session.add(EmailOptOut(email=email))
        db.session.commit()
    return page + ("<h2 style='color:#b98a33'>You're unsubscribed ✓</h2>"
                   "<p>You won't receive any more marketing emails from us. "
                   "You'll still get important messages about your bookings and payments.</p></div>")


# ── Contractor application (from website) ─────────────────────────────────────

@api_bp.route('/apply', methods=['POST', 'OPTIONS'])
def contractor_apply():
    origin = request.headers.get('Origin', '')
    if request.method == 'OPTIONS':
        return add_cors(jsonify({}), origin), 200

    data = request.get_json(silent=True) or {}

    if not data.get('name') or not data.get('email'):
        return add_cors(jsonify({'ok': False, 'error': 'Name and email required'}), origin), 400

    from models import ContractorApplication

    def to_bool(v):
        return v in (True, 'true', 'on', '1', 1)

    a = ContractorApplication(
        name=data.get('name', '').strip(),
        email=data.get('email', '').strip(),
        phone=data.get('phone', '').strip(),
        years_experience=data.get('years_experience', ''),
        services=data.get('services', ''),
        availability=data.get('availability', ''),
        has_transportation=to_bool(data.get('has_transportation')),
        has_supplies=to_bool(data.get('has_supplies')),
        has_references=to_bool(data.get('has_references')),
        background_check_consent=to_bool(data.get('background_check_consent')),
        agrees_to_ic_terms=to_bool(data.get('agrees_to_ic_terms')),
        why_interested=data.get('why_interested', '').strip(),
        status='new',
    )
    db.session.add(a)
    db.session.commit()

    notify = branding.owner_email()
    send_email(
        to_email=notify, to_name=branding.biz_name(),
        from_name=f'{branding.biz_name()} Hiring',
        subject=f'New Cleaner Application: {a.name}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">New Contractor Application</h2>
  <p><strong>Name:</strong> {a.name} &nbsp; <strong>Phone:</strong> {a.phone}</p>
  <p><strong>Email:</strong> {a.email}</p>
  <p><strong>Experience:</strong> {a.years_experience}</p>
  <p><strong>Services:</strong> {a.services or '—'}</p>
  <p><strong>Availability:</strong> {a.availability or '—'}</p>
  <p><strong>Has car:</strong> {'Yes' if a.has_transportation else 'No'}</p>
  <p><strong>Why interested:</strong> {a.why_interested or '—'}</p>
</div>""",
    )

    resp = jsonify({'ok': True})
    return add_cors(resp, origin), 201


# ── Validate promo code ────────────────────────────────────────────────────────

@api_bp.route('/validate-code', methods=['POST', 'OPTIONS'])
def validate_code():
    origin = request.headers.get('Origin', '')
    if request.method == 'OPTIONS':
        return add_cors(jsonify({}), origin), 200
    from models import DiscountCode
    data = request.get_json(silent=True) or {}
    code_str = data.get('code', '').strip().upper()
    price = float(data.get('price', 0))
    if not code_str:
        return add_cors(jsonify({'ok': False, 'error': 'No code entered'}), origin), 400
    c = DiscountCode.query.filter_by(code=code_str).first()
    if not c:
        resp = jsonify({'ok': False, 'error': 'Code not found'})
        return add_cors(resp, origin), 404
    valid, msg = c.check_valid()
    if not valid:
        return add_cors(jsonify({'ok': False, 'error': msg}), origin), 400
    discounted = c.apply(price)
    resp = jsonify({
        'ok': True, 'code': c.code,
        'label': c.discount_label(),
        'original_price': price,
        'discounted_price': discounted,
        'savings': round(price - discounted, 2),
    })
    return add_cors(resp, origin), 200


# ── Pricing calculator endpoint ──────────────────────────────────────────────

@api_bp.route('/price', methods=['POST', 'OPTIONS'])
def get_price():
    origin = request.headers.get('Origin', '')
    if request.method == 'OPTIONS':
        return add_cors(jsonify({}), origin), 200

    data = request.get_json(silent=True) or {}
    from pricing import get_lead_fee
    total = calculate_price(
        service_type=data.get('service_type', ''),
        bedrooms=data.get('bedrooms', 1),
        bathrooms=data.get('bathrooms', 1),
        extras=data.get('extras', ''),
        frequency=data.get('frequency', 'one_time'),
        sqft=data.get('sqft'),
    ) + get_lead_fee()   # bake in the (invisible) lead fee
    resp = jsonify({
        'total': total,
        'deposit': DEPOSIT_AMOUNT,
        'balance_due': round(total - DEPOSIT_AMOUNT, 2),
    })
    return add_cors(resp, origin), 200


# ── Stripe: create payment intent for $50 deposit ────────────────────────────

@api_bp.route('/create-payment-intent', methods=['POST', 'OPTIONS'])
def create_payment_intent():
    origin = request.headers.get('Origin', '')
    if request.method == 'OPTIONS':
        return add_cors(jsonify({}), origin), 200

    stripe.api_key = integrations.stripe_secret_key()
    if not stripe.api_key:
        resp = jsonify({'ok': False, 'error': 'Payments not configured'})
        return add_cors(resp, origin), 500

    data = request.get_json(silent=True) or {}
    total = calculate_price(
        service_type=data.get('service_type', ''),
        bedrooms=data.get('bedrooms', 1),
        bathrooms=data.get('bathrooms', 1),
        extras=data.get('extras', ''),
        frequency=data.get('frequency', 'one_time'),
    )

    try:
        # Create a Stripe Customer so we can save the card for the balance charge later
        customer = stripe.Customer.create(
            name=data.get('name', ''),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
        )
        intent = stripe.PaymentIntent.create(
            amount=int(DEPOSIT_AMOUNT * 100),
            currency='usd',
            customer=customer.id,
            setup_future_usage='off_session',  # saves the card for future off-session charges
            metadata={
                'service_type': data.get('service_type', ''),
                'total_price': str(total),
                'balance_due': str(round(total - DEPOSIT_AMOUNT, 2)),
                'customer_name': data.get('name', ''),
                'customer_email': data.get('email', ''),
            },
        )
        resp = jsonify({
            'ok': True,
            'client_secret': intent.client_secret,
            'stripe_customer_id': customer.id,
            'total': total,
            'deposit': DEPOSIT_AMOUNT,
            'balance_due': round(total - DEPOSIT_AMOUNT, 2),
        })
        return add_cors(resp, origin), 200
    except stripe.error.StripeError as e:
        resp = jsonify({'ok': False, 'error': str(e)})
        return add_cors(resp, origin), 400


# ── Create booking after successful payment ───────────────────────────────────

@api_bp.route('/booking', methods=['POST', 'OPTIONS'])
def create_booking():
    origin = request.headers.get('Origin', '')
    if request.method == 'OPTIONS':
        return add_cors(jsonify({}), origin), 200

    data = request.get_json(silent=True) or request.form.to_dict()

    required = ['name', 'email', 'phone', 'service_type']
    missing = [f for f in required if not data.get(f)]
    if missing:
        resp = jsonify({'ok': False, 'error': f'Missing: {", ".join(missing)}'})
        return add_cors(resp, origin), 400

    # Find or create client
    client = Client.query.filter_by(email=data['email'].lower().strip()).first()
    if not client:
        client = Client(
            name=data['name'].strip(),
            email=data['email'].lower().strip(),
            phone=data.get('phone', '').strip(),
            address=data.get('address', '').strip(),
            city=data.get('city', '').strip(),
            zip_code=data.get('zip_code', '').strip(),
        )
        db.session.add(client)
        db.session.flush()

    total = calculate_price(
        service_type=data.get('service_type', ''),
        bedrooms=data.get('bedrooms', 1),
        bathrooms=data.get('bathrooms', 1),
        extras=data.get('extras', ''),
        frequency=data.get('frequency', 'one_time'),
    )

    booking = Booking(
        client_id=client.id,
        service_type=data.get('service_type', ''),
        bedrooms=data.get('bedrooms', ''),
        bathrooms=data.get('bathrooms', ''),
        extras=data.get('extras', ''),
        frequency=data.get('frequency', 'one_time'),
        preferred_date=data.get('preferred_date', ''),
        preferred_time=data.get('preferred_time', ''),
        name=data['name'].strip(),
        email=data['email'].lower().strip(),
        phone=data.get('phone', '').strip(),
        address=data.get('address', '').strip(),
        city=data.get('city', '').strip(),
        zip_code=data.get('zip_code', '').strip(),
        notes=data.get('notes', '').strip(),
        stripe_payment_intent=data.get('payment_intent_id', ''),
        stripe_customer_id=data.get('stripe_customer_id', ''),
        stripe_payment_method_id=data.get('stripe_payment_method_id', ''),
        discount_code=data.get('discount_code', ''),
        discount_amount=float(data.get('discount_amount', 0) or 0),
        deposit_paid=True if data.get('payment_intent_id') else False,
        deposit_token=secrets.token_urlsafe(32),
        price=total,
        balance_due=round(total - DEPOSIT_AMOUNT, 2),
        status='confirmed' if data.get('payment_intent_id') else 'pending',
    )
    db.session.add(booking)
    db.session.commit()

    if booking.deposit_paid:
        # Deposit was paid up front → fully confirmed, and receipt the money.
        # Going through mark_deposit_paid also stamps the booking as notified,
        # so the webhook for this same payment doesn't send it all a second time.
        from blueprints.payments import mark_deposit_paid
        mark_deposit_paid(booking)
    else:
        # Tentative booking → ask for the deposit to confirm
        _send_deposit_request(booking)

    resp = jsonify({'ok': True, 'booking_id': booking.id,
                    'deposit_paid': booking.deposit_paid,
                    'deposit_token': None if booking.deposit_paid else booking.deposit_token})
    return add_cors(resp, origin), 201


# ── Stripe webhook ─────────────────────────────────────────────────────────────

@api_bp.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    stripe.api_key = integrations.stripe_secret_key()
    webhook_secret = integrations.stripe_webhook_secret()
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception:
        return jsonify({'ok': False}), 400

    if event['type'] == 'payment_intent.succeeded':
        pi = event['data']['object']
        booking = Booking.query.filter_by(stripe_payment_intent=pi['id']).first()
        if booking:
            # Confirming the booking and saying nothing to the customer is how
            # someone ends up having paid with no receipt. This fires precisely
            # when the browser never got to post its own confirm — tab closed,
            # connection dropped — which is when they most need telling.
            from blueprints.payments import mark_deposit_paid
            mark_deposit_paid(booking, amount_cents=pi.get('amount_received'))

    return jsonify({'ok': True}), 200


# ── Notification helpers ───────────────────────────────────────────────────────

def _send_confirmation(booking: Booking):
    notify_email = branding.owner_email()
    freq_label = FREQUENCY_LABELS.get(booking.frequency or 'one_time', 'One-Time')
    date_text = booking.preferred_date or 'Flexible'
    time_text = booking.preferred_time or 'Flexible'
    extras_text = f'<p><strong>Add-ons:</strong> {booking.extras}</p>' if booking.extras else ''

    from notifications import send_triggered_email
    send_triggered_email(
        trigger='booking_confirmed',
        to_email=booking.email,
        to_name=booking.name,
        variables={
            'service_type': booking.service_label,
            'frequency': freq_label,
            'beds': booking.bedrooms,
            'baths': booking.bathrooms,
            'extras': booking.extras or '',
            'booking_date': date_text,
            'booking_time': time_text,
            'address': f'{booking.address}, {booking.city} {booking.zip_code}',
            'price': f'{booking.price:.2f}',
            'deposit': '50.00',
            'balance': f'{booking.balance_due:.2f}',
            'notes': booking.notes or '',
        }
    )

    # SMS to customer
    send_sms(
        booking.phone,
        f"Hi {booking.name.split()[0]}! Your {branding.biz_name()} cleaning is confirmed for {date_text}. "
        f"Deposit received. Balance due: ${booking.balance_due:.2f}. "
        f"Questions? {branding.phone_line('Call ')} Reply STOP to opt out.",
    )

    # Notification to owner
    send_email(
        to_email=notify_email,
        to_name=branding.biz_name(),
        from_name=f'{branding.biz_name()} Bookings',
        subject=f'New booking + deposit paid: {booking.name} — {booking.service_label}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2>New Booking — $50 Deposit Received</h2>
  <p><strong>Name:</strong> {booking.name}</p>
  <p><strong>Email:</strong> {booking.email}</p>
  <p><strong>Phone:</strong> {booking.phone}</p>
  <p><strong>Service:</strong> {booking.service_label}</p>
  <p><strong>Frequency:</strong> {freq_label}</p>
  <p><strong>Bedrooms:</strong> {booking.bedrooms} &nbsp; <strong>Bathrooms:</strong> {booking.bathrooms}</p>
  {extras_text}
  <p><strong>Date:</strong> {date_text} &nbsp; <strong>Time:</strong> {time_text}</p>
  <p><strong>Address:</strong> {booking.address}, {booking.city} {booking.zip_code}</p>
  <p><strong>Total:</strong> ${booking.price:.2f} &nbsp; <strong>Balance due:</strong> ${booking.balance_due:.2f}</p>
  <p><strong>Notes:</strong> {booking.notes or '—'}</p>
</div>""",
    )


def _send_deposit_request(booking: Booking):
    """Tentative booking: confirm we received it, but make clear it's NOT locked in
    until the $50 deposit is paid. Includes a secure Pay Deposit link."""
    from flask import url_for
    from models import BusinessSetting
    notify_email = branding.owner_email()
    biz = branding.biz_name()
    freq_label = FREQUENCY_LABELS.get(booking.frequency or 'one_time', 'One-Time')
    date_text = booking.preferred_date or 'Flexible'
    time_text = booking.preferred_time or 'Flexible'
    first = (booking.name or 'there').split()[0]

    try:
        pay_url = url_for('deposit.pay_deposit_page', token=booking.deposit_token, _external=True)
    except Exception:
        pay_url = '#'

    # Customer email — friendly but crystal clear it's not confirmed yet
    html = f"""
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;background:#f6f5fb">
  <div style="background:#1f1333;padding:26px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;font-family:Georgia,serif;margin:0;font-size:1.7rem">{biz}</h1>
  </div>
  <div style="padding:30px;background:#fff">
    <h2 style="color:#1f1333;margin:0 0 12px">Hi {first}, we got your booking request! 🧹</h2>

    <div style="background:#fff8e1;border:2px solid #f59e0b;border-radius:10px;padding:16px 18px;margin:0 0 22px">
      <p style="margin:0;color:#92400e;font-weight:700;font-size:1rem">⚠️ Your booking is NOT confirmed yet</p>
      <p style="margin:8px 0 0;color:#7c4a04;line-height:1.6;font-size:0.92rem">
        To lock in your date and time, please pay your <strong>$50 deposit</strong> below.
        Your spot is held only once the deposit is received. The deposit goes toward your total —
        it is not an extra charge.
      </p>
    </div>

    <table style="width:100%;font-size:0.95rem;color:#1f1333;border-collapse:collapse;margin-bottom:22px">
      <tr><td style="padding:5px 0;color:#9a95ad">Service</td><td style="padding:5px 0;font-weight:600;text-align:right">{booking.service_label}</td></tr>
      <tr><td style="padding:5px 0;color:#9a95ad">Home</td><td style="padding:5px 0;font-weight:600;text-align:right">{booking.bedrooms} bed / {booking.bathrooms} bath</td></tr>
      <tr><td style="padding:5px 0;color:#9a95ad">Date</td><td style="padding:5px 0;font-weight:600;text-align:right">{date_text} {('· ' + time_text) if time_text != 'Flexible' else ''}</td></tr>
      <tr><td style="padding:5px 0;color:#9a95ad">Estimated total</td><td style="padding:5px 0;font-weight:600;text-align:right">${booking.price:.2f}</td></tr>
      <tr><td style="padding:5px 0;color:#9a95ad">Deposit to confirm</td><td style="padding:5px 0;font-weight:700;text-align:right;color:#065f46">$50.00</td></tr>
      <tr><td style="padding:5px 0;color:#9a95ad">Balance after cleaning</td><td style="padding:5px 0;font-weight:600;text-align:right">${booking.balance_due:.2f}</td></tr>
    </table>

    <div style="text-align:center;margin-bottom:18px">
      <a href="{pay_url}" style="background:#d3a84f;color:#1f1333;padding:16px 40px;border-radius:8px;
         text-decoration:none;font-weight:700;font-size:1.1rem;display:inline-block">
        Pay My $50 Deposit & Confirm →
      </a>
    </div>

    <p style="color:#5f5878;font-size:0.85rem;line-height:1.6;text-align:center;margin:0">
      Questions or want to change something? {branding.phone_line("Call or text us at ")}
    </p>
  </div>
  <div style="padding:14px;background:#1f1333;border-radius:0 0 12px 12px;text-align:center">
    <p style="color:rgba(255,255,255,0.4);font-size:0.78rem;margin:0">{biz}</p>
  </div>
</div>"""
    send_email(to_email=booking.email, to_name=booking.name,
               subject=f"Action needed: confirm your cleaning with a $50 deposit — {biz}",
               html=html)

    # SMS to customer
    send_sms(
        booking.phone,
        f"Hi {first}! {biz} got your booking request for {date_text}. "
        f"It's NOT confirmed until your $50 deposit is paid. "
        f"Pay here to lock your spot: {pay_url}  Reply STOP to opt out.",
    )

    # Owner alert — a tentative booking needs follow-up
    send_email(
        to_email=notify_email, to_name=biz, from_name=f'{biz} Bookings',
        subject=f"⚠️ Tentative booking (no deposit yet): {booking.name} — {booking.service_label}",
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2>Tentative Booking — Deposit Not Paid Yet</h2>
  <p>This booking is held but <strong>not confirmed</strong> until the $50 deposit is paid.
     Consider following up if the deposit isn't paid soon.</p>
  <p><strong>Name:</strong> {booking.name}</p>
  <p><strong>Email:</strong> {booking.email}</p>
  <p><strong>Phone:</strong> <a href="tel:{booking.phone}">{booking.phone}</a></p>
  <p><strong>Service:</strong> {booking.service_label} ({freq_label})</p>
  <p><strong>Home:</strong> {booking.bedrooms} bed / {booking.bathrooms} bath</p>
  <p><strong>Date:</strong> {date_text} · {time_text}</p>
  <p><strong>Address:</strong> {booking.address}, {booking.city} {booking.zip_code}</p>
  <p><strong>Total:</strong> ${booking.price:.2f} · <strong>Balance after:</strong> ${booking.balance_due:.2f}</p>
  <p><strong>Notes:</strong> {booking.notes or '—'}</p>
</div>""",
    )


def _send_reminder(booking: Booking):
    date_text = booking.preferred_date or 'Tomorrow'
    time_text = booking.preferred_time or 'your scheduled time'
    # balance_due is nullable and is None on every visit a recurring series
    # generates. Formatting that with :.2f raises, which took down the whole
    # run — one such booking on the calendar and nobody got a reminder.
    balance = booking.balance_due or 0.0
    first = (booking.name or 'there').split()[0] if (booking.name or '').strip() else 'there'
    where = ', '.join(p for p in [booking.address, booking.city] if p)

    from notifications import send_triggered_email
    send_triggered_email(
        trigger='booking_reminder_24h',
        to_email=booking.email,
        to_name=booking.name,
        variables={
            'service_type': booking.service_label,
            'booking_date': date_text,
            'booking_time': time_text,
            'address': where,
            'balance': f'{balance:.2f}',
        }
    )

    # {phone} used to be written as {{phone}} inside an f-string, which is just
    # a literal — customers were being told to "Call {phone}". The email goes
    # through the template engine and substitutes properly; this text never did.
    if not booking.phone:
        return
    reschedule = branding.phone_line('Need to reschedule? Call ')
    send_sms(
        booking.phone,
        f"Hi {first}! Reminder: your cleaning is tomorrow at {time_text}. "
        + (f"Balance due: ${balance:.2f}. " if balance > 0 else "")
        + (f"{reschedule}. " if reschedule else "")
        + "Reply STOP to opt out.",
    )


def _send_speed_to_lead(lead, total):
    """Instant response the moment a website lead comes in:
       1) text the LEAD so they feel taken care of,
       2) alert the OWNER (text + email) so they can call while the lead is hot."""
    from models import BusinessSetting
    biz = branding.biz_name()
    owner_phone = (BusinessSetting.get('owner_phone') or BusinessSetting.get('phone')
                   or os.environ.get('OWNER_PHONE', ''))
    owner_email = (BusinessSetting.get('email')
                   or branding.owner_email())

    first = (lead.name or 'there').split()[0]
    service = lead.service_label or 'cleaning'

    # 1) Instant text to the LEAD
    if lead.phone:
        send_sms(
            lead.phone,
            f"Hi {first}! It's {biz} \U0001F9F9 We just received your request for a "
            f"{service} and your estimate is ${total:.0f}. We're getting your booking "
            f"details ready now — reply here with any questions or to lock in your spot! "
            f"Reply STOP to opt out."
        )

    # 2) Instant alert to the OWNER so they can call within minutes
    alert = (f"\U0001F514 NEW LEAD — call them NOW! {lead.name}, {lead.phone or 'no phone'}. "
             f"{service}, {lead.bedrooms}bd/{lead.bathrooms}ba. Quote ${total:.0f}. "
             f"{lead.city or ''} {lead.zip_code or ''}".strip())
    if owner_phone:
        send_sms(owner_phone, alert)

    try:
        send_email(
            to_email=owner_email,
            to_name=biz,
            subject=f"\U0001F514 New lead: {lead.name} — call them now!",
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;padding:24px;background:#f6f5fb">
  <div style="background:#1f1333;padding:20px;border-radius:12px;text-align:center;margin-bottom:20px">
    <h2 style="color:#d3a84f;margin:0">New Lead — Respond Fast!</h2>
  </div>
  <div style="background:#fff;border-radius:12px;padding:22px 24px">
    <p style="color:#3b2b6b;line-height:1.8;margin:0 0 14px">
      The faster you call, the more likely you win the job. Aim for under 5 minutes.
    </p>
    <table style="width:100%;font-size:0.95rem;color:#1f1333;border-collapse:collapse">
      <tr><td style="padding:6px 0;color:#9a95ad">Name</td><td style="padding:6px 0;font-weight:600">{lead.name}</td></tr>
      <tr><td style="padding:6px 0;color:#9a95ad">Phone</td><td style="padding:6px 0;font-weight:600"><a href="tel:{lead.phone}" style="color:#d3a84f">{lead.phone or '—'}</a></td></tr>
      <tr><td style="padding:6px 0;color:#9a95ad">Email</td><td style="padding:6px 0;font-weight:600">{lead.email}</td></tr>
      <tr><td style="padding:6px 0;color:#9a95ad">Service</td><td style="padding:6px 0;font-weight:600">{service}</td></tr>
      <tr><td style="padding:6px 0;color:#9a95ad">Home</td><td style="padding:6px 0;font-weight:600">{lead.bedrooms} bed / {lead.bathrooms} bath</td></tr>
      <tr><td style="padding:6px 0;color:#9a95ad">Quote</td><td style="padding:6px 0;font-weight:600">${total:.2f}</td></tr>
      <tr><td style="padding:6px 0;color:#9a95ad">Area</td><td style="padding:6px 0;font-weight:600">{lead.city or '—'} {lead.zip_code or ''}</td></tr>
    </table>
    <a href="tel:{lead.phone}" style="display:block;text-align:center;background:#d3a84f;color:#1f1333;
       padding:14px;border-radius:8px;font-weight:700;text-decoration:none;margin-top:18px">
      \U0001F4DE Call {first} Now
    </a>
  </div>
</div>""",
        )
    except Exception:
        pass


def _send_quote_email(lead, total):
    from notifications import send_triggered_email
    send_triggered_email(
        trigger='lead_quote',
        to_email=lead.email,
        to_name=lead.name,
        variables={
            'service_type': lead.service_label,
            'beds': lead.bedrooms,
            'baths': lead.bathrooms,
            'quote_amount': f'{total:.2f}',
        }
    )


def _send_drip_followup(lead):
    from notifications import send_triggered_email
    send_triggered_email(
        trigger='lead_drip_day2',
        to_email=lead.email,
        to_name=lead.name,
        variables={
            'quote_amount': f'{lead.quoted_price:.2f}',
            'booking_link': '',
        }
    )


def _send_drip_lastchance(lead):
    discounted = round((lead.quoted_price or 0) * 0.90, 2)
    from notifications import send_triggered_email
    send_triggered_email(
        trigger='lead_drip_lastchance',
        to_email=lead.email,
        to_name=lead.name,
        variables={
            'quote_amount': f'{lead.quoted_price:.2f}',
            'discount_code': 'WELCOME10',
            'discounted_price': f'{discounted:.2f}',
            'booking_link': '',
        }
    )
