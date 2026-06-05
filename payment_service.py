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


def _notify_failed(booking, notify_email, error_msg):
    send_email(
        to_email=notify_email,
        to_name='Dazzle & Shine Maids',
        from_name='Dazzle & Shine Payments',
        subject=f'PAYMENT FAILED: {booking.name} — ${booking.balance_due:.2f}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#ef4444">Balance Charge Failed</h2>
  <p><strong>Customer:</strong> {booking.name}</p>
  <p><strong>Phone:</strong> {booking.phone}</p>
  <p><strong>Booking #:</strong> {booking.id}</p>
  <p><strong>Amount:</strong> ${booking.balance_due:.2f}</p>
  <p><strong>Error:</strong> {error_msg}</p>
  <p>Please contact the customer to collect payment manually.</p>
</div>""",
    )
    send_sms(
        booking.phone,
        f"Hi {booking.name.split()[0]}, your Dazzle & Shine balance payment of ${booking.balance_due:.2f} "
        f"didn't go through. Please call us at (407) 743-1944. Thank you!",
    )
