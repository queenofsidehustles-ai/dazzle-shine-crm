"""Customer payment link — pay the full amount for a booking by card.
Used for the morning-of invoice and on-site collection. Modeled on the
deposit flow but charges whatever is still owed (total minus any deposit)."""
import os
import secrets
from datetime import datetime
import stripe
from flask import Blueprint, render_template, request, jsonify, url_for
from models import Booking, BusinessSetting
from extensions import db
from pricing import DEPOSIT_AMOUNT

payments_bp = Blueprint('payments', __name__)

CRM_BASE = 'https://dazzle-shine-crm-production.up.railway.app'


def payment_link_url(booking, kind='full'):
    """Absolute URL for the customer's payment page (works outside a request too)."""
    if kind == 'deposit':
        if not booking.deposit_token:
            booking.deposit_token = secrets.token_urlsafe(32)
            db.session.commit()
        return f"{CRM_BASE}/pay-deposit/{booking.deposit_token}"
    ensure_pay_token(booking)
    return f"{CRM_BASE}/pay/{booking.pay_token}"


def send_payment_link(booking, kind='full'):
    """Email + text the customer their payment link. Returns True if anything sent."""
    from notifications import send_email, send_sms
    url = payment_link_url(booking, kind)
    first = (booking.name or 'there').split()[0]
    if kind == 'deposit':
        amt_text = f"${DEPOSIT_AMOUNT:.0f} deposit"
        sms_line = f"tap to pay your {amt_text} and confirm your booking"
    else:
        amt_text = f"${amount_due(booking):.2f}"
        sms_line = f"here's your invoice for {amt_text} — tap to pay securely"
    sent = False
    if booking.email:
        try:
            send_email(
                to_email=booking.email, to_name=booking.name,
                subject=f'Your {_biz()} invoice — tap to pay',
                html=f"""
<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Hi {first} — here's your invoice</h2>
  <p>Your {booking.service_label.lower()} on <strong>{booking.preferred_date or 'your scheduled date'}</strong>.
     Amount due: <strong>{amt_text}</strong>.</p>
  <p style="margin:22px 0"><a href="{url}"
     style="background:#d3a84f;color:#1a1225;padding:13px 26px;border-radius:999px;text-decoration:none;font-weight:700">💳 Pay {amt_text} securely →</a></p>
  <p style="color:#9a95ad;font-size:0.85rem">Secure payment powered by Stripe. Questions? Just reply.</p>
  <p style="color:#9a95ad;font-size:13px;margin-top:18px">{_biz()} · Orlando, FL</p>
</div>""",
            )
            sent = True
        except Exception:
            pass
    if booking.phone:
        try:
            ok, _ = send_sms(booking.phone,
                             f"Hi {first}! {sms_line}: {url} — {_biz()}. Reply STOP to opt out.")
            sent = sent or bool(ok)
        except Exception:
            pass
    return sent


def ensure_pay_token(booking):
    if not booking.pay_token:
        booking.pay_token = secrets.token_urlsafe(32)
        db.session.commit()
    return booking.pay_token


def amount_due(booking):
    """What the customer still owes: total minus a paid deposit."""
    if booking.paid_at:
        return 0.0
    paid = DEPOSIT_AMOUNT if booking.deposit_paid else 0
    return round(max(0.0, (booking.price or 0) - paid), 2)


def mark_paid(booking, method='card', when=None, notify=True):
    """Flag a booking as paid in full and notify. Idempotent-ish.

    `when` is the day the money actually arrived. Revenue is counted by this
    date, so recording a cash payment days after the fact would otherwise book
    the income in the wrong month. Card payments happen now by definition.

    notify=False records the payment without emailing the customer. That matters
    when a payment has already been receipted some other way, or on a booking
    that has turned contentious — a second unexpected receipt can restart a
    conversation the owner has good reason not to reopen. The books are updated
    either way; only the customer's inbox is spared."""
    if not booking.paid_at:
        booking.paid_at = when or datetime.utcnow()
    booking.paid_method = method
    booking.balance_collected = True
    booking.deposit_paid = True
    if booking.status in ('pending', None):
        booking.status = 'confirmed'
    db.session.commit()
    if notify:
        _send_receipt(booking, method)
        _alert_owner_paid(booking, method)


def _biz():
    return BusinessSetting.get('business_name', 'Dazzle & Shine Maids')


def _send_receipt(booking, method):
    if not booking.email:
        return
    from notifications import send_email
    first = (booking.name or 'there').split()[0]
    how = 'card' if method == 'card' else method
    try:
        send_email(
            to_email=booking.email, to_name=booking.name,
            subject=f'Payment received — {_biz()}',
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Thank you, {first}! ✅</h2>
  <p>We've received your payment of <strong>${booking.price:.2f}</strong> ({how}) for your
     {booking.service_label.lower()}. You're all set — thank you for choosing {_biz()}!</p>
  <p style="color:#9a95ad;font-size:13px;margin-top:20px">{_biz()} · Orlando, FL</p>
</div>""",
        )
    except Exception:
        pass


def _alert_owner_paid(booking, method):
    from notifications import send_sms
    phone = BusinessSetting.get('owner_alert_phone') or os.environ.get('OWNER_PHONE')
    if not phone:
        return
    try:
        send_sms(phone, f"💰 Payment received: {booking.name} paid ${booking.price:.2f} ({method}).")
    except Exception:
        pass


@payments_bp.route('/pay/<token>')
def pay_page(token):
    booking = Booking.query.filter_by(pay_token=token).first_or_404()
    pk = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    # Name the cleaner on the tip prompt — people tip a person, not a company.
    import customer_terms
    cleaner = booking.crew_label or booking.assigned_cleaner or ''
    return render_template('public/pay.html', booking=booking, token=token,
                           terms=customer_terms.as_html(),
                           stripe_pk=pk, due=amount_due(booking),
                           cleaner_first=cleaner.split()[0] if cleaner else '',
                           already_paid=bool(booking.paid_at), biz=_biz())


def _read_tip(payload):
    """A tip the customer typed. Belongs entirely to the cleaner, so it's kept
    apart from the price and never counted as revenue."""
    try:
        tip = float((payload or {}).get('tip') or 0)
    except (TypeError, ValueError):
        return 0.0
    if tip <= 0:
        return 0.0
    return round(min(tip, 2000), 2)      # cap catches a mistyped amount


@payments_bp.route('/pay/<token>/intent', methods=['POST'])
def create_intent(token):
    booking = Booking.query.filter_by(pay_token=token).first_or_404()
    due = amount_due(booking)
    if due <= 0:
        return jsonify({'ok': False, 'error': 'This booking is already paid.'}), 400
    tip = _read_tip(request.get_json(silent=True))
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
    if not stripe.api_key:
        return jsonify({'ok': False, 'error': 'Payments not configured'}), 500
    try:
        if booking.stripe_customer_id:
            customer_id = booking.stripe_customer_id
        else:
            customer = stripe.Customer.create(name=booking.name, email=booking.email,
                                              phone=booking.phone)
            customer_id = customer.id
            booking.stripe_customer_id = customer_id
        intent = stripe.PaymentIntent.create(
            amount=int(round((due + tip) * 100)), currency='usd', customer=customer_id,
            metadata={'booking_id': str(booking.id), 'pay_token': token,
                      'kind': 'full_payment', 'customer_name': booking.name or '',
                      'tip': f'{tip:.2f}'},
        )
        booking.tip_amount = tip
        booking.stripe_payment_intent = intent.id
        db.session.commit()
        return jsonify({'ok': True, 'client_secret': intent.client_secret})
    except stripe.error.StripeError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@payments_bp.route('/pay/<token>/confirm', methods=['POST'])
def confirm(token):
    booking = Booking.query.filter_by(pay_token=token).first_or_404()
    data = request.get_json(silent=True) or {}
    pi_id = (data.get('payment_intent_id') or '').strip()
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
    if pi_id and stripe.api_key:
        try:
            pi = stripe.PaymentIntent.retrieve(pi_id)
            if pi.status != 'succeeded':
                return jsonify({'ok': False, 'error': 'Payment not completed'}), 400
            booking.stripe_payment_intent = pi_id
            if pi.payment_method:
                booking.stripe_payment_method_id = pi.payment_method
        except stripe.error.StripeError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
    mark_paid(booking, method='card')
    return jsonify({'ok': True})
