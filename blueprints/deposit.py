import os
import stripe
from flask import Blueprint, render_template, request, jsonify
from models import Booking
from extensions import db
from pricing import DEPOSIT_AMOUNT
import integrations

deposit_bp = Blueprint('deposit', __name__)


@deposit_bp.route('/pay-deposit/<token>')
def pay_deposit_page(token):
    booking = Booking.query.filter_by(deposit_token=token).first_or_404()
    pk = integrations.stripe_publishable_key()
    import customer_terms
    return render_template('public/pay_deposit.html',
        booking=booking,
        token=token,
        stripe_pk=pk,
        terms=customer_terms.as_html(),
        deposit=DEPOSIT_AMOUNT,
        already_paid=bool(booking.deposit_paid),
    )


@deposit_bp.route('/pay-deposit/<token>/intent', methods=['POST'])
def create_deposit_intent(token):
    booking = Booking.query.filter_by(deposit_token=token).first_or_404()
    if booking.deposit_paid:
        return jsonify({'ok': False, 'error': 'Deposit already paid'}), 400

    stripe.api_key = integrations.stripe_secret_key()
    if not stripe.api_key:
        return jsonify({'ok': False, 'error': 'Payments not configured'}), 500

    try:
        # Reuse an existing Stripe customer if we have one, else create
        if booking.stripe_customer_id:
            customer_id = booking.stripe_customer_id
        else:
            customer = stripe.Customer.create(
                name=booking.name, email=booking.email, phone=booking.phone,
            )
            customer_id = customer.id
            booking.stripe_customer_id = customer_id

        intent = stripe.PaymentIntent.create(
            amount=int(DEPOSIT_AMOUNT * 100),
            currency='usd',
            customer=customer_id,
            setup_future_usage='off_session',  # save card for the balance charge later
            metadata={
                'booking_id': str(booking.id),
                'deposit_token': token,
                'customer_name': booking.name or '',
                'customer_email': booking.email or '',
            },
        )
        booking.stripe_payment_intent = intent.id
        db.session.commit()
        return jsonify({'ok': True, 'client_secret': intent.client_secret})
    except stripe.error.StripeError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@deposit_bp.route('/pay-deposit/<token>/confirm', methods=['POST'])
def confirm_deposit(token):
    booking = Booking.query.filter_by(deposit_token=token).first_or_404()
    data = request.get_json(silent=True) or {}
    pi_id = (data.get('payment_intent_id') or '').strip()

    # Verify the payment actually succeeded before marking paid
    stripe.api_key = integrations.stripe_secret_key()
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

    if not booking.deposit_paid:
        booking.deposit_paid = True
        booking.status = 'confirmed'
        db.session.commit()
        # They have just agreed to the terms by paying. Snapshot them.
        import customer_terms
        customer_terms.record_acceptance(booking, request)
        # Fire the full confirmation email/SMS (same as a paid-up-front booking)
        try:
            from blueprints.api import _send_confirmation
            _send_confirmation(booking)
        except Exception:
            pass

    return jsonify({'ok': True})
