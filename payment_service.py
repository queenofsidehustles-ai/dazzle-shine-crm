import stripe
from notifications import send_email, send_sms
import branding
import integrations


def charge_key(kind, booking, cents, payment_method):
    """Stripe's idempotency key for one off-session charge.

    Two requests with the same key within Stripe's 24 hours get the first one's
    result back instead of a second charge -- so a retried request, a second
    clock, or a button pressed while the hourly run is mid-way cannot take the
    same balance twice, whatever the lock in the API did. Built from what makes
    it the same charge: which company, which job, how much has been collected
    on it so far, how much this takes, which card. The amount already collected
    is what tells a retry from a new balance: a $100 balance charged, the price
    then raised by $100, is a second $100 owed on the same job and card -- the
    same key without it, which Stripe would answer with the first charge while
    the job was marked paid in full. A retry of a charge that never recorded
    has the same collected figure, so it still gets the first result."""
    from blueprints.payments import collected
    try:
        import tenancy
        where = tenancy.current_schema() or 'public'
    except Exception:
        where = 'public'
    have = int(round((collected(booking) or 0) * 100))
    return f'akye-{kind}-{where}-{booking.id}-{have}-{cents}-{payment_method}'[:255]


def charge_balance(booking) -> tuple:
    """Charge saved card for the remaining balance. Returns (success: bool, error: str).

    The amount comes from amount_due() — price minus what has actually been
    received, worked out fresh. It used to come from the stored balance_due
    column, which is only ever written by the price-correction route: never at
    booking, never when the price is edited. So on a hand-made booking it sat at
    $0 and this refused to charge anything at all.

    What is owed is the only thing that can stop a charge. It used to refuse on
    paid_at or balance_collected as well, which are records of a past payment
    rather than of the current balance: a job re-scoped upwards after it settled
    still owed the difference, and both flags refused to let anyone collect it.
    A job with nothing outstanding is still refused, by the one test that
    actually answers that question."""
    from blueprints.payments import sync_balance
    stripe.api_key = integrations.stripe_secret_key()
    notify_email = branding.owner_email()

    if not stripe.api_key:
        return False, 'Stripe not configured'
    # A held job is the one case where money must not move regardless of what is
    # owed. The customer has been emailed to say nothing will be charged while
    # she decides on a date, and this is the button that would do it anyway.
    # Note this is a question about the job's state, not about a past payment —
    # which is what the refusals removed from here used to be.
    if booking.status == 'on_hold':
        return False, ('This job is on hold — put it back on the calendar with a '
                       'date before charging her.')
    due = sync_balance(booking)        # keep the stored figures honest
    if due <= 0:
        return False, 'This booking is already paid in full'
    if not booking.stripe_customer_id or not booking.stripe_payment_method_id:
        return False, 'No saved payment method on file'

    amount_cents = int(round(due * 100))

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency='usd',
            customer=booking.stripe_customer_id,
            payment_method=booking.stripe_payment_method_id,
            confirm=True,
            off_session=True,
            description=f'Balance for Booking #{booking.id} — {booking.service_label}',
            metadata={'booking_id': str(booking.id), 'kind': 'balance'},
            idempotency_key=charge_key('balance', booking, amount_cents,
                                       booking.stripe_payment_method_id),
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
    except UNKNOWN_OUTCOME as e:
        # Stripe may well have taken the money; nobody here knows yet. This
        # used to text the customer that her payment failed and tell the owner
        # to collect it by hand -- the road to taking it twice. The next attempt
        # sends the same idempotency key and gets the first answer back, and
        # the payment_intent.succeeded webhook records it if it did go through.
        _notify_unknown(booking, notify_email, str(e))
        return False, ('Stripe did not answer, so this charge may or may not have '
                       'gone through. Do not collect it another way; it will '
                       'settle automatically.')
    except stripe.error.StripeError as e:
        _notify_failed(booking, notify_email, str(e))
        return False, str(e)


# A timeout, a dropped connection, Stripe's own 5xx, or a 429: the request may
# have been processed, or may be processed on a retry. Not a decline.
UNKNOWN_OUTCOME = (stripe.error.APIConnectionError, stripe.error.APIError,
                   stripe.error.RateLimitError)


def autocharge(booking) -> tuple:
    """Auto-pay: charge the FULL amount due on this booking to the saved card
    (the booking's own, or its client's card on file). Used morning-of for
    recurring / customer-portal auto-pay clients. Returns (success, error)."""
    from blueprints.payments import amount_due, mark_paid
    stripe.api_key = integrations.stripe_secret_key()
    if not stripe.api_key:
        return False, 'Stripe not configured'
    if booking.status == 'on_hold':
        return False, 'On hold'
    if booking.paid_at:
        return False, 'Already paid'

    client = getattr(booking, 'client', None)
    customer_id = booking.stripe_customer_id or (client.stripe_customer_id if client else None)
    pm_id = booking.stripe_payment_method_id or (client.stripe_payment_method_id if client else None)
    if not customer_id or not pm_id:
        return False, 'No saved card on file'

    amount = amount_due(booking)
    # round(), not int(). Binary floating point stores $1.13 as 1.12999...,
    # so int(amount * 100) truncates it to 112 cents and the customer is
    # undercharged a penny. It happens on about one amount in eighteen, in one
    # direction only, on every automatic morning-of charge. charge_balance()
    # above has always rounded; this was the one place that did not.
    cents = int(round(amount * 100))
    if cents <= 0:
        return False, 'Nothing due'

    try:
        intent = stripe.PaymentIntent.create(
            amount=cents, currency='usd', customer=customer_id,
            payment_method=pm_id, confirm=True, off_session=True,
            description=f'Auto-pay for Booking #{booking.id} — {booking.service_label}',
            metadata={'booking_id': str(booking.id), 'kind': 'autopay'},
            idempotency_key=charge_key('autopay', booking, cents, pm_id),
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


def record_offsession_success(booking, pi):
    """Record a balance or auto-pay charge Stripe says succeeded, from the
    payment_intent.succeeded webhook. This is the charge whose answer never
    reached charge_balance/autocharge -- a timeout, or the process dying after
    Stripe took the money -- so nothing here has recorded it.

    Returns True if it recorded something. Safe to receive twice: an intent
    already on the booking has been recorded, by this or by the charge itself."""
    from blueprints.payments import amount_due, collected, mark_paid, sync_balance
    from extensions import db
    if pi.get('status', 'succeeded') != 'succeeded':
        return False
    if (pi.get('currency') or 'usd').lower() != 'usd':
        return False
    client = getattr(booking, 'client', None)
    customers = {booking.stripe_customer_id,
                 client.stripe_customer_id if client else None} - {None, ''}
    if pi.get('customer') not in customers:
        return False
    if booking.stripe_payment_intent == pi.get('id'):
        return False
    received = int(pi.get('amount_received') or 0)
    if received <= 0:
        return False
    booking.stripe_payment_intent = pi.get('id')
    if received == int(round(amount_due(booking) * 100)):
        if not mark_paid(booking, method='card'):
            db.session.commit()
        return True
    # The price moved between the charge and now: credit what actually arrived
    # rather than calling the job settled, so any difference still shows owed.
    booking.amount_collected = round(collected(booking) + received / 100, 2)
    sync_balance(booking)
    db.session.commit()
    return True


def _notify_unknown(booking, notify_email, error_msg):
    """Owner only. The customer is told nothing until there is something true
    to tell her."""
    amt = booking.balance_due if booking.balance_due else (booking.price or 0)
    send_email(
        to_email=notify_email,
        to_name=branding.biz_name(),
        from_name=f'{branding.biz_name()} Payments',
        subject=f'Charge not confirmed yet: {booking.name} — ${amt:.2f}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#d97706">Waiting on Stripe</h2>
  <p>We asked Stripe to charge this balance and did not get an answer back, so it
  may or may not have gone through.</p>
  <p><strong>Customer:</strong> {booking.name}</p>
  <p><strong>Booking #:</strong> {booking.id}</p>
  <p><strong>Amount:</strong> ${amt:.2f}</p>
  <p><strong>Detail:</strong> {error_msg}</p>
  <p><strong>Please don't collect this another way yet.</strong> If Stripe took it, the
  booking will be marked paid automatically. If it didn't, the next attempt will try
  again without charging twice. The customer has not been told anything.</p>
</div>""",
    )


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
