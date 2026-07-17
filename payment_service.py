import os
import stripe
from notifications import send_email, send_sms


def charge_balance(booking) -> tuple:
    """Charge saved card for the remaining balance. Returns (success: bool, error: str)."""
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
    notify_email = os.environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com')

    if not stripe.api_key:
        return False, 'Stripe not configured'
    if booking.balance_collected:
        return False, 'Balance already collected'
    if not booking.stripe_customer_id or not booking.stripe_payment_method_id:
        return False, 'No saved payment method on file'

    amount_cents = int((booking.balance_due or 0) * 100)
    if amount_cents <= 0:
        return False, 'No balance due'

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency='usd',
            customer=booking.stripe_customer_id,
            payment_method=booking.stripe_payment_method_id,
            confirm=True,
            off_session=True,
            description=f'Balance for Booking #{booking.id} — {booking.service_label}',
        )
        if intent.status == 'succeeded':
            booking.balance_collected = True
            send_email(
                to_email=booking.email,
                to_name=booking.name,
                subject='Balance payment received — Dazzle & Shine Maids',
                html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Payment Received ✓</h2>
  <p>Hi {booking.name},</p>
  <p>Your balance of <strong>${booking.balance_due:.2f}</strong> has been collected. You're all set!</p>
  <p>Thank you for choosing Dazzle &amp; Shine Maids — we appreciate your business.</p>
  <p style="color:#9a95ad;font-size:13px">Dazzle &amp; Shine Maids · Orlando, FL</p>
</div>""",
            )
            return True, ''
        else:
            _notify_failed(booking, notify_email, f'Unexpected status: {intent.status}')
            return False, f'Payment status: {intent.status}'

    except stripe.error.CardError as e:
        err = e.user_message or str(e)
        _notify_failed(booking, notify_email, err)
        return False, err
    except stripe.error.StripeError as e:
        _notify_failed(booking, notify_email, str(e))
        return False, str(e)


def autocharge(booking) -> tuple:
    """Auto-pay: charge the FULL amount due on this booking to the saved card
    (the booking's own, or its client's card on file). Used morning-of for
    recurring / customer-portal auto-pay clients. Returns (success, error)."""
    from blueprints.payments import amount_due, mark_paid
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
    if not stripe.api_key:
        return False, 'Stripe not configured'
    if booking.paid_at:
        return False, 'Already paid'

    client = getattr(booking, 'client', None)
    customer_id = booking.stripe_customer_id or (client.stripe_customer_id if client else None)
    pm_id = booking.stripe_payment_method_id or (client.stripe_payment_method_id if client else None)
    if not customer_id or not pm_id:
        return False, 'No saved card on file'

    amount = amount_due(booking)
    cents = int(amount * 100)
    if cents <= 0:
        return False, 'Nothing due'

    try:
        intent = stripe.PaymentIntent.create(
            amount=cents, currency='usd', customer=customer_id,
            payment_method=pm_id, confirm=True, off_session=True,
            description=f'Auto-pay for Booking #{booking.id} — {booking.service_label}',
            metadata={'booking_id': str(booking.id), 'kind': 'autopay'},
        )
        if intent.status == 'succeeded':
            booking.stripe_payment_intent = intent.id
            mark_paid(booking, method='card')   # commits + sends receipt + owner alert
            return True, ''
        return False, f'Payment status: {intent.status}'
    except stripe.error.CardError as e:
        notify_email = os.environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com')
        _notify_failed(booking, notify_email, e.user_message or str(e))
        return False, (e.user_message or str(e))
    except stripe.error.StripeError as e:
        return False, str(e)


def _notify_failed(booking, notify_email, error_msg):
    amt = booking.balance_due if booking.balance_due else (booking.price or 0)
    send_email(
        to_email=notify_email,
        to_name='Dazzle & Shine Maids',
        from_name='Dazzle & Shine Payments',
        subject=f'PAYMENT FAILED: {booking.name} — ${amt:.2f}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#ef4444">Balance Charge Failed</h2>
  <p><strong>Customer:</strong> {booking.name}</p>
  <p><strong>Phone:</strong> {booking.phone}</p>
  <p><strong>Booking #:</strong> {booking.id}</p>
  <p><strong>Amount:</strong> ${amt:.2f}</p>
  <p><strong>Error:</strong> {error_msg}</p>
  <p>Please contact the customer to collect payment manually.</p>
</div>""",
    )
    send_sms(
        booking.phone,
        f"Hi {booking.name.split()[0]}, your Dazzle & Shine payment of ${amt:.2f} "
        f"didn't go through. Please call us at (689) 999-0194. Thank you!",
    )
