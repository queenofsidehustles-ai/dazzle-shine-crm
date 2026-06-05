import os
import stripe
import requests as http_requests
from flask import Blueprint, request, jsonify
from models import Booking, Client
from extensions import db
from pricing import calculate_price, SERVICES, EXTRAS, FREQUENCY_LABELS, DEPOSIT_AMOUNT

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
        intent = stripe.PaymentIntent.create(
            amount=int(DEPOSIT_AMOUNT * 100),  # cents
            currency='usd',
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


# ── Email helper ───────────────────────────────────────────────────────────────

def _send_email(api_key, from_email, from_name, to_email, to_name, subject, html):
    try:
        http_requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={'api-key': api_key, 'Content-Type': 'application/json'},
            json={
                'sender': {'name': from_name, 'email': from_email},
                'to': [{'email': to_email, 'name': to_name}],
                'subject': subject,
                'htmlContent': html,
            },
            timeout=10,
        )
    except Exception:
        pass


def _send_confirmation(booking: Booking):
    api_key = os.environ.get('BREVO_API_KEY')
    from_email = os.environ.get('FROM_EMAIL', 'bookings@dazzleandshinemaids.com')
    notify_email = os.environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com')
    if not api_key:
        return

    freq_label = FREQUENCY_LABELS.get(booking.frequency or 'one_time', 'One-Time')
    extras_text = f"<p><strong>Add-ons:</strong> {booking.extras}</p>" if booking.extras else ''
    date_text = booking.preferred_date or 'Flexible'
    time_text = booking.preferred_time or 'Flexible'

    # Email to customer
    _send_email(
        api_key=api_key,
        from_email=from_email,
        from_name='Dazzle & Shine Maids',
        to_email=booking.email,
        to_name=booking.name,
        subject='Your booking is confirmed — Dazzle & Shine Maids',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333;">
  <h2 style="color:#b98a33;">Booking Confirmed!</h2>
  <p>Hi {booking.name},</p>
  <p>Your $50 deposit has been received. Here's your booking summary:</p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0;" />
  <p><strong>Service:</strong> {booking.service_label}</p>
  <p><strong>Frequency:</strong> {freq_label}</p>
  <p><strong>Bedrooms:</strong> {booking.bedrooms} &nbsp; <strong>Bathrooms:</strong> {booking.bathrooms}</p>
  {extras_text}
  <p><strong>Date:</strong> {date_text} &nbsp; <strong>Time:</strong> {time_text}</p>
  <p><strong>Address:</strong> {booking.address}, {booking.city} {booking.zip_code}</p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0;" />
  <p><strong>Total price:</strong> ${booking.price:.2f}</p>
  <p><strong>Deposit paid:</strong> $50.00</p>
  <p><strong>Balance due after cleaning:</strong> ${booking.balance_due:.2f}</p>
  <p style="font-size:0.88rem;color:#9a95ad;">Deposit is non-refundable. You may reschedule your date at any time.</p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0;" />
  <p>Questions? Call or text <strong>(407) 743-1944</strong> or reply to this email.</p>
  <p style="color:#9a95ad;font-size:14px;">Dazzle &amp; Shine Maids · Orlando, FL</p>
</div>
""",
    )

    # Notification to owner
    _send_email(
        api_key=api_key,
        from_email=from_email,
        from_name='Dazzle & Shine Bookings',
        to_email=notify_email,
        to_name='Dazzle & Shine Maids',
        subject=f'New booking + deposit paid: {booking.name} — {booking.service_label}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333;">
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
</div>
""",
    )
