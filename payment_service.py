import hashlib
import json
from datetime import datetime, timezone

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
    return _offsession(booking, booking.stripe_customer_id,
                       booking.stripe_payment_method_id, amount_cents, loud=True)


# A timeout, a dropped connection, Stripe's own 5xx, or a 429: the request may
# have been processed, or may be processed on a retry. Not a decline.
# An IdempotencyError is the same request still in flight from another worker
# (or one that differs from it): the answer is that request's, not a decline.
UNKNOWN_OUTCOME = (stripe.error.APIConnectionError, stripe.error.APIError,
                   stripe.error.RateLimitError, stripe.error.IdempotencyError)


def autocharge(booking) -> tuple:
    """Auto-pay: charge the FULL amount due on this booking to the saved card
    (the booking's own, or its client's card on file). Used morning-of for
    recurring / customer-portal auto-pay clients. Returns (success, error)."""
    from blueprints.payments import amount_due
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

    return _offsession(booking, customer_id, pm_id, cents, loud=False)


# Stripe remembers an idempotency key for 24 hours: a request repeated inside
# that window gets the first answer back, one repeated after it is a new charge.
# A charge left unanswered for longer than this is looked up instead of retried.
PENDING_REPEAT_HOURS = 23

UNKNOWN_MESSAGE = ('Stripe did not answer, so this charge may or may not have '
                   'gone through. Do not collect it another way; it will '
                   'settle automatically.')


def _pending(booking):
    raw = getattr(booking, 'charge_pending', None)
    if not raw:
        return None
    try:
        got = json.loads(raw)
    except (TypeError, ValueError):
        return None
    need = ('key', 'amount', 'customer', 'pm', 'description', 'at')
    return got if isinstance(got, dict) and all(k in got for k in need) else None


def _pending_hours(pending):
    try:
        at = datetime.fromisoformat(pending['at'])
    except (TypeError, ValueError):
        return PENDING_REPEAT_HOURS     # unreadable: look it up, do not repeat it
    return (datetime.utcnow() - at).total_seconds() / 3600


def _clear_pending(booking):
    from extensions import db
    if getattr(booking, 'charge_pending', None):
        booking.charge_pending = None
        db.session.commit()


def _offsession(booking, customer_id, pm_id, cents, loud):
    """The one way an off-session card charge is made: the hourly balance pass,
    the auto-pay pass and the Charge button all come here. Returns (ok, error).

    One attempt per obligation. The two passes used to send different
    idempotency keys ('balance' and 'autopay') for the same money, so when the
    balance charge timed out the auto-pay pass a moment later, finding the job
    still unpaid, charged the card again under a key Stripe had never seen.
    Now both send the same request, and a charge Stripe has not answered is
    written down (booking.charge_pending) before it is sent. Every later
    attempt, from any path, repeats that exact request -- same key, same
    amount, same card -- and so gets Stripe's first answer back instead of a
    second charge. It is only replaced once Stripe has given a definite answer,
    or a lookup shows it never charged anything.

    loud: tell the owner and customer about a failure that is not a decline
    (the balance pass always has; auto-pay has only ever reported declines)."""
    from extensions import db
    notify_email = branding.owner_email()
    pending = _pending(booking)
    if pending and (pending['amount'] > cents
                    or _pending_hours(pending) >= PENDING_REPEAT_HOURS):
        # Repeating it would be wrong: less is owed now than it asked for (so
        # if it never went through, repeating it overcharges), or Stripe has
        # forgotten the key (so repeating it is a fresh charge). Ask Stripe.
        state = settle_pending(booking)
        if state == 'recorded':
            return True, ''
        if state != 'none':
            return False, UNKNOWN_MESSAGE
        pending = None
    first = pending is None
    if first:
        key = charge_key('balance', booking, cents, pm_id)
        pending = {
            'key': key,
            # Carried in the intent's metadata, so an event or a lookup can
            # tell whether a payment is the answer to THIS request.
            'attempt': hashlib.sha256(key.encode()).hexdigest()[:20],
            'amount': cents, 'customer': customer_id, 'pm': pm_id,
            'description': f'Balance for Booking #{booking.id} — {booking.service_label}',
            'at': datetime.utcnow().isoformat(timespec='seconds'),
        }
        booking.charge_pending = json.dumps(pending)
        db.session.commit()

    try:
        intent = stripe.PaymentIntent.create(
            amount=pending['amount'],
            currency='usd',
            customer=pending['customer'],
            payment_method=pending['pm'],
            confirm=True,
            off_session=True,
            description=pending['description'],
            metadata=_metadata(booking, pending),
            idempotency_key=pending['key'],
        )
    except stripe.error.CardError as e:
        _clear_pending(booking)
        err = e.user_message or str(e)
        _notify_failed(booking, notify_email, err)
        return False, err
    except UNKNOWN_OUTCOME as e:
        # Stripe may well have taken the money; nobody here knows yet. This
        # used to text the customer that her payment failed and tell the owner
        # to collect it by hand -- the road to taking it twice. The request
        # stays pending: the next attempt repeats it and gets the first answer
        # back, and the payment_intent.succeeded webhook records it if it did
        # go through. The owner hears once, not on every hourly retry.
        if first:
            _notify_unknown(booking, notify_email, str(e), pending['amount'])
        return False, UNKNOWN_MESSAGE
    except stripe.error.StripeError as e:
        _clear_pending(booking)
        if loud:
            _notify_failed(booking, notify_email, str(e))
        return False, str(e)

    if intent.status == 'succeeded':
        # Credited by what Stripe says it took, once. Mark the booking PAID
        # when that is everything owed, not merely "balance collected": revenue
        # is counted by paid_at. mark_paid also sends the receipt and the owner
        # alert, so there is no bespoke email here.
        received = getattr(intent, 'amount_received', None) or pending['amount']
        _credit_intent(booking, intent.id, int(received))
        _clear_pending(booking)          # this IS the answer to the held request
        return True, ''
    _clear_pending(booking)
    if loud:
        _notify_failed(booking, notify_email, f'Unexpected status: {intent.status}')
    return False, f'Payment status: {intent.status}'


def _metadata(booking, pending):
    out = {'booking_id': str(booking.id), 'kind': 'balance'}
    if pending.get('attempt'):
        out['attempt'] = pending['attempt']
    return out


def _resolves_pending(booking, attempt):
    """Drop the held request if, and only if, this payment answers it. A
    replayed event for an earlier payment says nothing about a newer request
    still waiting on Stripe; dropping that would make its retry a new charge."""
    pending = _pending(booking)
    if pending and attempt and pending.get('attempt') == attempt:
        booking.charge_pending = None
        return True
    return False


def settle_pending(booking):
    """Find out from Stripe what became of an unanswered charge.

    Returns 'recorded' when it went through and is now credited, 'none' when
    Stripe holds no charge for it (the pending request is dropped, so the next
    attempt starts afresh), and 'unknown' when Stripe still cannot say -- the
    lookup failed, or a charge for this job is still in progress."""
    pending = _pending(booking)
    if not pending:
        return 'none'
    stripe.api_key = integrations.stripe_secret_key()
    if not stripe.api_key:
        return 'unknown'
    try:
        at = datetime.fromisoformat(pending['at']).replace(tzinfo=timezone.utc)
        since = int(at.timestamp()) - 600
    except (TypeError, ValueError):
        since = None
    try:
        query = {'customer': pending['customer'], 'limit': 100}
        if since:
            query['created'] = {'gte': since}
        intents = list(stripe.PaymentIntent.list(**query).auto_paging_iter())
    except stripe.error.StripeError:
        return 'unknown'
    for pi in intents:
        metadata = pi.get('metadata') or {}
        if str(metadata.get('booking_id') or '') != str(booking.id):
            continue
        if metadata.get('kind') not in ('balance', 'autopay'):
            continue
        status = pi.get('status')
        if status == 'succeeded':
            if record_offsession_success(booking, pi):
                return 'recorded'
            continue                     # already credited: not this request
        if status in ('processing', 'requires_capture', 'requires_confirmation'):
            return 'unknown'
    _clear_pending(booking)
    return 'none'


def record_offsession_success(booking, pi):
    """Record a balance or auto-pay charge Stripe says succeeded, from the
    payment_intent.succeeded webhook. This is the charge whose answer never
    reached charge_balance/autocharge -- a timeout, or the process dying after
    Stripe took the money -- so nothing here has recorded it.

    Returns True if it recorded something. Safe to receive twice, late, or
    after a newer charge on the same job: see _credit_intent."""
    if pi.get('status', 'succeeded') != 'succeeded':
        return False
    if (pi.get('currency') or 'usd').lower() != 'usd':
        return False
    client = getattr(booking, 'client', None)
    customers = {booking.stripe_customer_id,
                 client.stripe_customer_id if client else None} - {None, ''}
    if pi.get('customer') not in customers:
        return False
    return _credit_intent(booking, pi.get('id'), int(pi.get('amount_received') or 0),
                          attempt=(pi.get('metadata') or {}).get('attempt'))


def _credit_intent(booking, intent_id, received, attempt=None):
    """Credit one Stripe payment to this booking, once. True if it credited.

    Once means once whatever order things arrive in. The booking only keeps its
    latest intent id, so that alone could not tell an old payment's webhook,
    replayed after a newer charge on the same job, from a new payment -- and
    credited it again. Every intent handled is in payment_credit, unique."""
    from blueprints.payments import amount_due, collected, mark_paid, sync_balance
    from extensions import db
    from models import PaymentCredit
    from sqlalchemy.exc import IntegrityError
    if not intent_id or received <= 0:
        return False
    if booking.stripe_payment_intent == intent_id or \
            PaymentCredit.query.filter_by(stripe_payment_intent=intent_id).first():
        if _resolves_pending(booking, attempt):
            db.session.commit()
        return False
    due = int(round(amount_due(booking) * 100))
    outcome = 'credited' if due > 0 else 'overpaid'
    try:
        with db.session.begin_nested():
            db.session.add(PaymentCredit(stripe_payment_intent=intent_id,
                                         booking_id=booking.id,
                                         amount_cents=received, outcome=outcome))
    except IntegrityError:
        return False                     # another request handled it just now
    _resolves_pending(booking, attempt)
    if outcome == 'overpaid':
        # Money arrived on a job that was already paid -- most likely collected
        # another way while Stripe had not answered. Crediting it would report
        # income nobody is owed; the owner needs to refund one of them.
        db.session.commit()
        _notify_overpaid(booking, received, intent_id)
        return False
    booking.stripe_payment_intent = intent_id
    if received >= due:
        if not mark_paid(booking, method='card'):
            db.session.commit()
        if received > due:
            # More arrived than was owed: the price came down, or part was paid
            # another way, while Stripe had not answered. The job is paid; the
            # difference is the customer's, and the owner has to refund it.
            _notify_overpaid(booking, received - due, intent_id)
        return True
    # The price moved between the charge and now: credit what actually arrived
    # rather than calling the job settled, so any difference still shows owed.
    booking.amount_collected = round(collected(booking) + received / 100, 2)
    sync_balance(booking)
    db.session.commit()
    return True


def _notify_overpaid(booking, received, intent_id):
    """received: the cents that arrived beyond what the job was owed."""
    send_email(
        to_email=branding.owner_email(),
        to_name=branding.biz_name(),
        from_name=f'{branding.biz_name()} Payments',
        subject=f'Paid twice? {booking.name} — ${received / 100:.2f}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#d97706">Stripe took more than this job was owed</h2>
  <p><strong>Customer:</strong> {booking.name}</p>
  <p><strong>Booking #:</strong> {booking.id}</p>
  <p><strong>Amount:</strong> ${received / 100:.2f}</p>
  <p><strong>Stripe payment:</strong> {intent_id}</p>
  <p>This amount has not been added to what the job has collected. Check the
  booking and refund it to the customer.</p>
</div>""",
    )


def _notify_unknown(booking, notify_email, error_msg, cents=None):
    """Owner only. The customer is told nothing until there is something true
    to tell her."""
    amt = (cents / 100 if cents else
           booking.balance_due if booking.balance_due else (booking.price or 0))
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
