import os
import stripe
from datetime import date, timedelta, datetime
from flask import Blueprint, request, jsonify
from models import Booking, Client
from extensions import db
from pricing import calculate_price, SERVICES, EXTRAS, FREQUENCY_LABELS, DEPOSIT_AMOUNT
from notifications import send_email, send_sms, add_to_mailerlite

api_bp = Blueprint('api', __name__, url_prefix='/api')

ALLOWED_ORIGINS = [
    'https://www.dazzleandshinemaids.com',
    'https://dazzleandshinemaids.com',
    'http://localhost:3000',
    'http://127.0.0.1:5500',
]


def add_cors(response, origin):
    if origin in ALLOWED_ORIGINS:
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
    resp = jsonify({'stripe_pk': os.environ.get('STRIPE_PUBLISHABLE_KEY', '')})
    return add_cors(resp, origin), 200


# ── 24-hour reminder sender (call from a cron or Railway scheduled job) ───────

@api_bp.route('/reminders', methods=['POST'])
def send_reminders():
    api_key = request.headers.get('X-Api-Key') or request.args.get('api_key', '')
    expected = os.environ.get('REMINDER_API_KEY', '')
    if not expected or api_key != expected:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    bookings = Booking.query.filter(
        Booking.preferred_date == tomorrow,
        Booking.status.in_(['pending', 'confirmed']),
    ).all()

    count = 0
    for b in bookings:
        _send_reminder(b)
        count += 1

    return jsonify({'ok': True, 'reminders_sent': count})


# ── Auto-charge balances (cron — runs every morning) ─────────────────────────

@api_bp.route('/charge-balances', methods=['POST'])
def charge_balances():
    api_key = request.headers.get('X-Api-Key') or request.args.get('api_key', '')
    expected = os.environ.get('REMINDER_API_KEY', '')
    if not expected or api_key != expected:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    from payment_service import charge_balance as do_charge
    today = date.today().isoformat()
    bookings = Booking.query.filter(
        Booking.preferred_date == today,
        Booking.status.in_(['confirmed', 'pending']),
        Booking.balance_collected == False,
        Booking.stripe_customer_id != None,
        Booking.stripe_payment_method_id != None,
    ).all()

    results = []
    for b in bookings:
        ok, err = do_charge(b)
        results.append({'booking_id': b.id, 'name': b.name, 'ok': ok, 'error': err})
    db.session.commit()

    return jsonify({'ok': True, 'charged': len([r for r in results if r['ok']]), 'results': results})


# ── Lead quote capture (from website) ─────────────────────────────────────────

@api_bp.route('/quote', methods=['POST', 'OPTIONS'])
def capture_quote():
    origin = request.headers.get('Origin', '')
    if request.method == 'OPTIONS':
        return add_cors(jsonify({}), origin), 200

    data = request.get_json(silent=True) or {}
    if not data.get('name') or not data.get('email'):
        resp = jsonify({'ok': False, 'error': 'Name and email required'})
        return add_cors(resp, origin), 400

    total = calculate_price(
        service_type=data.get('service_type', ''),
        bedrooms=data.get('bedrooms', 1),
        bathrooms=data.get('bathrooms', 1),
        extras=data.get('extras', ''),
        frequency=data.get('frequency', 'one_time'),
    )

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
    add_to_mailerlite(lead.email, lead.name)
    resp = jsonify({'ok': True, 'total': total, 'deposit': DEPOSIT_AMOUNT,
                    'balance_due': round(total - DEPOSIT_AMOUNT, 2)})
    return add_cors(resp, origin), 201


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
    return jsonify({'ok': True, 'drips_sent': count})


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

    notify = os.environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com')
    send_email(
        to_email=notify, to_name='Dazzle & Shine Maids',
        from_name='Dazzle & Shine Hiring',
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
    total = calculate_price(
        service_type=data.get('service_type', ''),
        bedrooms=data.get('bedrooms', 1),
        bathrooms=data.get('bathrooms', 1),
        extras=data.get('extras', ''),
        frequency=data.get('frequency', 'one_time'),
    )
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

    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
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
        price=total,
        balance_due=round(total - DEPOSIT_AMOUNT, 2),
        status='pending',
    )
    db.session.add(booking)
    db.session.commit()

    _send_confirmation(booking)

    resp = jsonify({'ok': True, 'booking_id': booking.id})
    return add_cors(resp, origin), 201


# ── Stripe webhook ─────────────────────────────────────────────────────────────

@api_bp.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
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
            booking.deposit_paid = True
            booking.status = 'confirmed'
            db.session.commit()

    return jsonify({'ok': True}), 200


# ── Notification helpers ───────────────────────────────────────────────────────

def _send_confirmation(booking: Booking):
    notify_email = os.environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com')
    freq_label = FREQUENCY_LABELS.get(booking.frequency or 'one_time', 'One-Time')
    date_text = booking.preferred_date or 'Flexible'
    time_text = booking.preferred_time or 'Flexible'

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
        f"Hi {booking.name.split()[0]}! Your Dazzle & Shine cleaning is confirmed for {date_text}. "
        f"Deposit received. Balance due: ${booking.balance_due:.2f}. "
        f"Questions? Call (689) 999-0194. Reply STOP to opt out.",
    )

    # Notification to owner
    send_email(
        to_email=notify_email,
        to_name='Dazzle & Shine Maids',
        from_name='Dazzle & Shine Bookings',
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


def _send_reminder(booking: Booking):
    date_text = booking.preferred_date or 'Tomorrow'
    time_text = booking.preferred_time or 'your scheduled time'

    from notifications import send_triggered_email
    send_triggered_email(
        trigger='booking_reminder_24h',
        to_email=booking.email,
        to_name=booking.name,
        variables={
            'service_type': booking.service_label,
            'booking_date': date_text,
            'booking_time': time_text,
            'address': f'{booking.address}, {booking.city}',
            'balance': f'{booking.balance_due:.2f}',
        }
    )

    send_sms(
        booking.phone,
        f"Hi {booking.name.split()[0]}! Reminder: your cleaning is tomorrow at {time_text}. "
        f"Balance due: ${booking.balance_due:.2f}. Need to reschedule? Call {{phone}}. Reply STOP to opt out.",
    )


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
