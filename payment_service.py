import os
import stripe
from notifications import send_email, send_sms
import branding
import integrations


def charge_balance(booking) -> tuple:
    """Charge saved card for the remaining balance. Returns (success: bool, error: str).

    The amount comes from amount_due() — price minus any deposit, worked out
    fresh. It used to come from the stored balance_due column, which is only
    ever written by the price-correction route: never at booking, never when the
    price is edited. So on a hand-made booking it sat at $0 and this refused to
    charge anything at all."""
    from blueprints.payments import amount_due
    stripe.api_key = integrations.stripe_secret_key()
    notify_email = branding.owner_email()

    if not stripe.api_key:
        return False, 'Stripe not configured'
    if booking.paid_at:
        return False, 'This booking is already paid in full'
    if booking.balance_collected:
        return False, 'Balance already collected'
    if not booking.stripe_customer_id or not booking.stripe_payment_method_id:
        return False, 'No saved payment method on file'

    due = amount_due(booking)
    booking.balance_due = due          # keep the stored figure honest
    amount_cents = int(round(due * 100))
    if amount_cents <= 0:
        return False, 'No balance due — check the total price on this booking.'

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
            # Mark the booking PAID, not merely "balance collected".
            #
            # This used to set balance_collected and stop there, leaving paid_at
            # empty. Revenue is counted by paid_at and "still owed" is anything
            # without it — so a job could be charged in full, the money arrive in
            # Stripe, and the CRM still report it as unpaid and missing from
            # income. autocharge() has always called mark_paid; this didn't.
            #
            # mark_paid also sends the receipt and the owner alert, so the
            # bespoke email that used to live here has gone rather than send the
            # customer two.
            from blueprints.payments import mark_paid
            booking.stripe_payment_intent = intent.id
            mark_paid(booking, method='card')
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
    stripe.api_key = integrations.stripe_secret_key()
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
        notify_email = branding.owner_email()
        _notify_failed(booking, notify_email, e.user_message or str(e))
        return False, (e.user_message or str(e))
    except stripe.error.StripeError as e:
        return False, str(e)


def _notify_failed(booking, notify_email, error_msg):
    amt = booking.balance_due if booking.balance_due else (booking.price or 0)
    send_email(
        to_email=notify_email,
        to_name=branding.biz_name(),
        from_name=f'{branding.biz_name()} Payments',
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
        f"Hi {booking.name.split()[0]}, your {branding.biz_name()} payment of ${amt:.2f} "
        f"didn't go through. {branding.phone_line('Please call us at ')} Thank you!",
    )
