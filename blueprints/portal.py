"""Customer Portal — a self-serve page each client opens with a private link.

Shows their upcoming cleanings, history, and invoices, and lets them save a card
for automatic morning-of billing (auto-pay). The card is stored on the *client*
(via Stripe), so it carries across every visit in a recurring series.
"""
import os
import secrets
from datetime import date, datetime
import stripe
from flask import Blueprint, render_template, request, jsonify, abort
from models import Client, BusinessSetting
from extensions import db
from blueprints.payments import amount_due, ensure_pay_token

portal_bp = Blueprint('portal', __name__)


def ensure_portal_token(client):
    """Give a client a portal link token if they don't have one yet."""
    if not client.portal_token:
        client.portal_token = secrets.token_urlsafe(24)
        db.session.commit()
    return client.portal_token


def _client(token):
    c = Client.query.filter_by(portal_token=token).first()
    if not c:
        abort(404)
    return c


def _biz():
    return BusinessSetting.get('business_name', 'Dazzle & Shine Maids')


@portal_bp.route('/portal/<token>')
def home(token):
    client = _client(token)
    today = date.today().isoformat()
    active = [b for b in client.bookings if b.status != 'cancelled']

    upcoming = sorted([b for b in active if (b.preferred_date or '') >= today and not b.paid_at],
                      key=lambda b: b.preferred_date or '')
    # make sure every upcoming unpaid visit has a pay link ready for the "Pay now" button
    for b in upcoming:
        if amount_due(b) > 0:
            ensure_pay_token(b)

    history = sorted([b for b in active if b.paid_at or (b.preferred_date or '') < today],
                     key=lambda b: b.preferred_date or '', reverse=True)
    invoices = sorted([b for b in active if b.invoice_number],
                      key=lambda b: b.invoice_issued_at or datetime.min, reverse=True)

    pk = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    return render_template('public/portal.html', client=client, token=token,
                           upcoming=upcoming, history=history, invoices=invoices,
                           amount_due=amount_due, stripe_pk=pk, biz=_biz(), today=today)


@portal_bp.route('/portal/<token>/setup-intent', methods=['POST'])
def setup_intent(token):
    """Start saving a card — creates the client's Stripe customer + a SetupIntent."""
    client = _client(token)
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
    if not stripe.api_key:
        return jsonify({'ok': False, 'error': 'Payments not configured'}), 500
    try:
        if not client.stripe_customer_id:
            cust = stripe.Customer.create(name=client.name, email=client.email,
                                          phone=client.phone)
            client.stripe_customer_id = cust.id
            db.session.commit()
        si = stripe.SetupIntent.create(customer=client.stripe_customer_id,
                                       usage='off_session')
        return jsonify({'ok': True, 'client_secret': si.client_secret})
    except stripe.error.StripeError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@portal_bp.route('/portal/<token>/save-card', methods=['POST'])
def save_card(token):
    """Store the confirmed card on the client + turn on auto-pay, and backfill the
    card onto their upcoming unpaid visits so the morning cron can charge them."""
    client = _client(token)
    data = request.get_json(silent=True) or {}
    pm_id = (data.get('payment_method_id') or '').strip()
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
    if not pm_id or not stripe.api_key:
        return jsonify({'ok': False, 'error': 'Missing card details'}), 400
    try:
        pm = stripe.PaymentMethod.retrieve(pm_id)
        brand = (pm.card.brand if pm.card else '') or ''
        last4 = (pm.card.last4 if pm.card else '') or ''
    except stripe.error.StripeError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    client.stripe_payment_method_id = pm_id
    client.card_brand = brand.title()
    client.card_last4 = last4
    client.autopay = True

    today = date.today().isoformat()
    for b in client.bookings:
        if b.status != 'cancelled' and (b.preferred_date or '') >= today and not b.paid_at:
            b.stripe_customer_id = client.stripe_customer_id
            b.stripe_payment_method_id = pm_id
    db.session.commit()
    return jsonify({'ok': True, 'brand': client.card_brand, 'last4': last4})


@portal_bp.route('/portal/<token>/autopay', methods=['POST'])
def toggle_autopay(token):
    """Customer turns auto-pay on/off (card stays on file either way)."""
    client = _client(token)
    data = request.get_json(silent=True) or {}
    client.autopay = bool(data.get('on'))
    db.session.commit()
    return jsonify({'ok': True, 'autopay': client.autopay})
