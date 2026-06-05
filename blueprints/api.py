import os
import requests
from flask import Blueprint, request, jsonify
from models import Booking, Client
from extensions import db

api_bp = Blueprint('api', __name__, url_prefix='/api')

ALLOWED_ORIGINS = [
    'https://www.dazzleandshinemaids.com',
    'https://dazzleandshinemaids.com',
    'http://localhost:3000',
    'http://127.0.0.1:5500',  # Live Server during dev
]


def add_cors(response, origin):
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@api_bp.route('/booking', methods=['POST', 'OPTIONS'])
def create_booking():
    origin = request.headers.get('Origin', '')

    if request.method == 'OPTIONS':
        resp = jsonify({})
        return add_cors(resp, origin), 200

    data = request.get_json(silent=True) or request.form.to_dict()

    # Validate required fields
    required = ['name', 'email', 'phone', 'service_type']
    missing = [f for f in required if not data.get(f)]
    if missing:
        resp = jsonify({'ok': False, 'error': f'Missing: {", ".join(missing)}'})
        return add_cors(resp, origin), 400

    # Find or create client record
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

    booking = Booking(
        client_id=client.id,
        service_type=data.get('service_type', ''),
        bedrooms=data.get('bedrooms', ''),
        bathrooms=data.get('bathrooms', ''),
        extras=data.get('extras', ''),
        preferred_date=data.get('preferred_date', ''),
        preferred_time=data.get('preferred_time', ''),
        name=data['name'].strip(),
        email=data['email'].lower().strip(),
        phone=data.get('phone', '').strip(),
        address=data.get('address', '').strip(),
        city=data.get('city', '').strip(),
        zip_code=data.get('zip_code', '').strip(),
        notes=data.get('notes', '').strip(),
        status='pending',
    )
    db.session.add(booking)
    db.session.commit()

    _send_confirmation(booking)

    resp = jsonify({'ok': True, 'booking_id': booking.id})
    return add_cors(resp, origin), 201


def _send_email(api_key, from_email, from_name, to_email, to_name, subject, html):
    try:
        requests.post(
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

    extras_text = ''
    if booking.extras:
        extras_text = f"<p><strong>Add-ons:</strong> {booking.extras}</p>"

    date_text = booking.preferred_date or 'Flexible'
    time_text = booking.preferred_time or 'Flexible'

    # Confirmation to customer
    _send_email(
        api_key=api_key,
        from_email=from_email,
        from_name='Dazzle & Shine Maids',
        to_email=booking.email,
        to_name=booking.name,
        subject='Your booking request was received — Dazzle & Shine Maids',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333;">
  <h2 style="color:#b98a33;">We got your request!</h2>
  <p>Hi {booking.name},</p>
  <p>Thanks for booking with Dazzle &amp; Shine Maids. We'll confirm your appointment within 24 hours.</p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0;" />
  <p><strong>Service:</strong> {booking.service_label}</p>
  <p><strong>Bedrooms:</strong> {booking.bedrooms or '—'} &nbsp;&nbsp; <strong>Bathrooms:</strong> {booking.bathrooms or '—'}</p>
  {extras_text}
  <p><strong>Preferred date:</strong> {date_text}</p>
  <p><strong>Preferred time:</strong> {time_text}</p>
  <p><strong>Address:</strong> {booking.address}, {booking.city} {booking.zip_code}</p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0;" />
  <p>Questions? Call or text us at <strong>(407) 743-1944</strong> or reply to this email.</p>
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
        subject=f'New booking: {booking.name} — {booking.service_label}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333;">
  <h2>New Booking Request</h2>
  <p><strong>Name:</strong> {booking.name}</p>
  <p><strong>Email:</strong> {booking.email}</p>
  <p><strong>Phone:</strong> {booking.phone}</p>
  <p><strong>Service:</strong> {booking.service_label}</p>
  <p><strong>Bedrooms:</strong> {booking.bedrooms} &nbsp; <strong>Bathrooms:</strong> {booking.bathrooms}</p>
  {extras_text}
  <p><strong>Date:</strong> {date_text} &nbsp; <strong>Time:</strong> {time_text}</p>
  <p><strong>Address:</strong> {booking.address}, {booking.city} {booking.zip_code}</p>
  <p><strong>Notes:</strong> {booking.notes or '—'}</p>
</div>
""",
    )
