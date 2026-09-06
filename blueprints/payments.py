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
from pricing import DEPOSIT_AMOUNT, get_deposit
import branding
import integrations

payments_bp = Blueprint('payments', __name__)



def payment_link_url(booking, kind='full'):
    """Absolute URL for the customer's payment page (works outside a request too)."""
    if kind == 'deposit':
        if not booking.deposit_token:
            booking.deposit_token = secrets.token_urlsafe(32)
            db.session.commit()
        return f"{branding.crm_base()}/pay-deposit/{booking.deposit_token}"
    ensure_pay_token(booking)
    return f"{branding.crm_base()}/pay/{booking.pay_token}"


def send_payment_link(booking, kind='full'):
    """Email + text the customer their payment link. Returns True if anything sent."""
    from notifications import send_email, send_sms
    url = payment_link_url(booking, kind)
    first = (booking.name or 'there').split()[0]
    if kind == 'deposit':
        amt_text = f"${get_deposit():.0f} deposit"
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
  <p style="color:#9a95ad;font-size:13px;margin-top:18px">{_biz()}{" · " + branding.city_line() if branding.city_line() else ""}</p>
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


def stripe_customer_id_for(booking):
    """This booking's Stripe customer, created on first use.

    The email is only sent to Stripe if it could actually be delivered to.
    Stripe validates the address and rejects the whole call when it is
    malformed, and because the customer is created *before* the payment intent,
    one mistyped address stopped the customer paying at all — with nothing in
    the Stripe dashboard to show for it, because no charge was ever attempted.
    A typo in a contact detail must not be able to refuse somebody's money. The
    address is still stored on the booking either way, so correcting it and
    resending is all it takes to get a receipt out.

    Shared by the deposit page and the balance page so the two cannot drift."""
    if booking.stripe_customer_id:
        return booking.stripe_customer_id
    from notifications import looks_like_email
    fields = {'name': booking.name, 'phone': booking.phone}
    if looks_like_email(booking.email):
        fields['email'] = booking.email
    customer = stripe.Customer.create(**fields)
    booking.stripe_customer_id = customer.id
    return customer.id


def collected(booking):
    """Money actually received against this booking's price, tips excluded.

    Recorded as an amount on the booking, because a flag saying "paid" is only
    true against the price on the day it was set. When a scope correction raises
    the price afterwards, an amount stays a fact and a flag becomes a lie.

    NULL means the booking predates the column, so fall back to what those rows
    do record, in order of how much it tells us:

      * settled — paid_at is set, so the whole price was taken. That is right for
        every booking whose price has not been touched since, and wrong only for
        one that has: for those the figure is the *new* price, and nobody can
        recover the old one from the row. That is what the Payment card's
        "money actually received" correction is for (bookings.fix_amount_collected),
        and why this fallback is never written into the column as if it were a
        fact of its own.
      * a deposit and no more — credit what was charged on the day, not what the
        deposit happens to be now. Those were the same number while the deposit
        was a constant, and stopped being the same the moment it became a
        setting the owner can change: crediting today's figure would collect the
        difference too little on every booking that paid the old one. Bookings
        older than that column fall back to the deposit in force, which for them
        is right, because it has not moved since they were taken.
      * nothing.
    """
    if booking.amount_collected is not None:
        return round(float(booking.amount_collected), 2)
    if booking.paid_at:
        return round(float(booking.price or 0), 2)
    if booking.deposit_paid:
        paid = booking.deposit_amount_paid
        if paid is None:
            from pricing import get_deposit
            paid = get_deposit()
        return round(float(paid), 2)
    return 0.0


def amount_due(booking):
    """What the customer still owes: the price less what has actually been paid.

    This used to answer $0.00 for anything carrying a paid_at, whatever the
    price said. So raising the price on a settled booking — the ordinary
    consequence of a scope change, a three-bed that turns out to be a four-bed —
    produced a job the CRM called paid in full and short-changed the business by
    the difference, with no route anywhere in the system to collect it."""
    return round(max(0.0, (booking.price or 0) - collected(booking)), 2)


def is_settled(booking):
    """Paid in full: money has been taken, and none is still owed.

    Both halves matter. Without the first, a $0 booking reads as settled; without
    the second, a booking whose price has risen since goes on claiming to be."""
    return collected(booking) > 0 and amount_due(booking) <= 0


def sync_balance(booking, commit=False):
    """Bring the stored balance columns back in line with the numbers.

    balance_due and balance_collected are denormalised copies that several
    queries and the charge button read. Nothing recomputed them when a price
    moved, so a re-scoped job kept insisting the balance had been collected
    while $92 of it had not. Call this anywhere the price or the money changes."""
    booking.balance_due = amount_due(booking)
    booking.balance_collected = is_settled(booking)
    if commit:
        db.session.commit()
    return booking.balance_due


def mark_paid(booking, method='card', when=None, notify=True):
    """Record a booking as settled in full and notify. Idempotent-ish.

    `when` is the day the money actually arrived. Revenue is counted by this
    date, so recording a cash payment days after the fact would otherwise book
    the income in the wrong month. Card payments happen now by definition.

    Every caller reaches here having taken whatever was outstanding — the pay
    page, the saved-card charge, auto-pay, and the owner recording cash — so
    what is written is that the price has now been collected in full. Written as
    the amount rather than a flag: if the price rises later, the difference
    shows up as owed instead of vanishing.

    notify=False records the payment without emailing the customer. That matters
    when a payment has already been receipted some other way, or on a booking
    that has turned contentious — a second unexpected receipt can restart a
    conversation the owner has good reason not to reopen. The books are updated
    either way; only the customer's inbox is spared."""
    # What this payment was, before the booking is updated to say it arrived.
    # The receipt has to quote the money that just moved: a customer settling a
    # $92 shortfall told "we've received your payment of $482.00" will assume
    # she has been charged the whole job twice.
    paying = amount_due(booking)
    if not booking.paid_at:
        booking.paid_at = when or datetime.utcnow()
    booking.paid_method = method
    booking.amount_collected = round(float(booking.price or 0), 2)
    booking.balance_collected = True
    booking.balance_due = 0
    booking.deposit_paid = True
    if booking.status in ('pending', None):
        booking.status = 'confirmed'
    db.session.commit()
    if notify:
        _send_receipt(booking, method, paying)
        _alert_owner_paid(booking, method, paying)


def mark_deposit_paid(booking, req=None, amount_cents=None):
    """Record a paid deposit and tell the customer — exactly once.

    Three separate things can land here for the same $50: the browser posting to
    /pay-deposit/<token>/confirm once Stripe has confirmed the card, Stripe's own
    payment_intent.succeeded webhook, and the booking widget when the deposit is
    taken up front. Whichever arrived first used to set deposit_paid, and the
    others then saw the flag already set and did nothing — but only the browser
    path ever sent the customer anything. So a webhook that won the race, or a
    customer who closed the tab before the confirm POST landed, meant the money
    was taken in complete silence.

    That is why "have we told them" is its own column. deposit_paid tracks the
    money; deposit_notified_at tracks the email. Returns True if this call is
    the one that notified the customer.

    amount_cents is what Stripe actually took, when the caller knows it. A
    receipt should quote the charge, not what we meant to charge."""
    # Read before writing. collected() falls back to the deposit fields when the
    # running total is NULL, so a total worked out after they are set would
    # count this deposit as already received and then add it again.
    already = collected(booking)
    booking.deposit_paid = True
    if not booking.deposit_paid_at:
        booking.deposit_paid_at = datetime.utcnow()
    # Pin what was actually charged. Stripe's own figure when the caller knows
    # it, otherwise the deposit in force right now -- which is what was quoted,
    # because this runs moments after the customer was shown it. Written once
    # and never revised: a later change to the setting must not rewrite what
    # somebody already paid.
    if booking.deposit_amount_paid is None:
        from pricing import get_deposit
        booking.deposit_amount_paid = (round((amount_cents or 0) / 100, 2)
                                       or float(get_deposit()))
        # And count it towards what has been received. Inside this guard on
        # purpose: the browser and the webhook both land here for the same $50,
        # and a running total that added it twice would report a job as paid
        # that is still half owed.
        #
        # Not on a job already settled in full, though. Stripe's webhook for the
        # deposit can arrive after the balance has been paid — that is the whole
        # reason this function is written to be called more than once — and by
        # then the $50 is already inside the total. Adding it again would book
        # fifty dollars of income that nobody ever paid.
        if not booking.paid_at:
            booking.amount_collected = round(already + float(booking.deposit_amount_paid), 2)
    if booking.status in ('pending', None):
        booking.status = 'confirmed'
    sync_balance(booking)
    db.session.commit()

    # Paying is how a customer accepts the terms, so snapshot them — but only
    # from the customer's own request. The webhook's request belongs to Stripe,
    # and its IP address is not evidence of anything.
    if req is not None:
        import customer_terms
        customer_terms.record_acceptance(booking, req)

    if booking.deposit_notified_at:
        return False
    # A job already settled in full has had its receipt from mark_paid, which
    # covers the deposit as part of the total. A second one would only confuse.
    if booking.paid_at:
        return False

    # Stamp before sending rather than after: two of these can be in flight at
    # once, and a duplicate receipt is worse than a late one.
    booking.deposit_notified_at = datetime.utcnow()
    db.session.commit()

    try:
        from blueprints.api import _send_confirmation
        _send_confirmation(booking)
    except Exception:
        pass
    _send_deposit_receipt(booking, round((amount_cents or 0) / 100, 2) or float(get_deposit()))
    return True


def _biz():
    return branding.biz_name()


def send_deposit_receipt_now(booking):
    """Send the deposit receipt on demand, from the back office. Returns
    (ok, detail) so the button can say what actually happened.

    Deposits taken before the receipt existed have no recorded payment date, and
    dating the receipt "today" would misstate when the customer paid. Stripe
    still holds the truth, so look it up and keep it — a receipt is a document
    someone may have to rely on, and a wrong date makes it worthless."""
    if not booking.deposit_paid_at and booking.stripe_payment_intent:
        try:
            stripe.api_key = integrations.stripe_secret_key()
            if stripe.api_key:
                pi = stripe.PaymentIntent.retrieve(booking.stripe_payment_intent)
                created = getattr(pi, 'created', None)
                if created:
                    booking.deposit_paid_at = datetime.utcfromtimestamp(created)
                    db.session.commit()
        except Exception:
            pass  # fall through — the receipt simply omits the date

    amount = None
    if booking.stripe_payment_intent:
        try:
            stripe.api_key = integrations.stripe_secret_key()
            if stripe.api_key:
                pi = stripe.PaymentIntent.retrieve(booking.stripe_payment_intent)
                cents = getattr(pi, 'amount_received', None) or getattr(pi, 'amount', None)
                # Only trust this if it looks like the deposit. Once a balance has
                # been charged the booking's payment intent points at that instead,
                # and quoting the balance as the deposit would be a lie.
                if cents and round(cents / 100, 2) <= (booking.price or 0):
                    amount = round(cents / 100, 2)
        except Exception:
            pass
    if amount is None:
        amount = float(get_deposit())

    ok, detail = _send_deposit_receipt(booking, amount)
    if ok and not booking.deposit_notified_at:
        booking.deposit_notified_at = datetime.utcnow()
        db.session.commit()
    return ok, detail


def _send_deposit_receipt(booking, amount):
    """The receipt for the deposit itself. Returns (ok, detail).

    _send_receipt below covers a job settled in full and quotes the full price,
    so a deposit had no receipt of its own anywhere. The confirmation email
    mentions the $50 in passing, but it never says the money arrived and it is
    dated to the booking, not the payment — nothing a customer could reasonably
    treat as proof that they paid."""
    if not booking.email:
        return False, 'No email address on this booking.'
    from notifications import send_email
    first = (booking.name or 'there').split()[0]
    remaining = round(max(0.0, (booking.price or 0) - amount), 2)
    # No invented dates. If we genuinely don't know when the money arrived, the
    # row comes off the receipt rather than carrying a guess.
    date_row = ''
    if booking.deposit_paid_at:
        date_row = f"""
    <tr><td style="padding:6px 0;color:#6b6580">Date paid</td>
        <td style="padding:6px 0;text-align:right">{booking.deposit_paid_at.strftime('%d %b %Y')}</td></tr>"""
    try:
        return send_email(
            to_email=booking.email, to_name=booking.name,
            subject=f'Receipt for your ${amount:.2f} deposit — {_biz()}',
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Thank you, {first}! ✅</h2>
  <p>We've received your deposit. Your {booking.service_label.lower()} is confirmed.</p>
  <table style="width:100%;border-collapse:collapse;margin:18px 0;font-size:14px">
    <tr><td style="padding:6px 0;color:#6b6580">Deposit paid</td>
        <td style="padding:6px 0;text-align:right"><strong>${amount:.2f}</strong></td></tr>{date_row}
    <tr><td style="padding:6px 0;color:#6b6580">Paid by</td>
        <td style="padding:6px 0;text-align:right">Card</td></tr>
    <tr><td style="padding:6px 0;color:#6b6580">Booking reference</td>
        <td style="padding:6px 0;text-align:right">#{booking.id}</td></tr>
    <tr><td style="padding:10px 0 0;border-top:1px solid #ece8f5;color:#6b6580">Balance due on the day</td>
        <td style="padding:10px 0 0;border-top:1px solid #ece8f5;text-align:right"><strong>${remaining:.2f}</strong></td></tr>
  </table>
  <p>Keep this email as your receipt. Any questions, just reply to it.</p>
  <p style="color:#9a95ad;font-size:13px;margin-top:20px">{_biz()}{" · " + branding.city_line() if branding.city_line() else ""}</p>
</div>""",
        )
    except Exception as e:
        return False, str(e)


def _send_receipt(booking, method, amount=None):
    """Receipt for a payment. `amount` is what this payment was, which is the
    whole price on an ordinary job and only the shortfall on one that had
    already paid against a lower price."""
    if not booking.email:
        return
    from notifications import send_email
    first = (booking.name or 'there').split()[0]
    how = 'card' if method == 'card' else method
    total = round(float(booking.price or 0), 2)
    if amount is None or round(amount, 2) >= total:
        amount = total
        settles = ''
    else:
        settles = (f' That settles your ${total:,.2f} total for this cleaning '
                   f'in full — nothing further is owed.')
    try:
        send_email(
            to_email=booking.email, to_name=booking.name,
            subject=f'Payment received — {_biz()}',
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Thank you, {first}! ✅</h2>
  <p>We've received your payment of <strong>${amount:,.2f}</strong> ({how}) for your
     {booking.service_label.lower()}.{settles} You're all set — thank you for choosing {_biz()}!</p>
  <p style="color:#9a95ad;font-size:13px;margin-top:20px">{_biz()}{" · " + branding.city_line() if branding.city_line() else ""}</p>
</div>""",
        )
    except Exception:
        pass


def _alert_owner_paid(booking, method, amount=None):
    from notifications import send_sms
    phone = BusinessSetting.get('owner_alert_phone') or os.environ.get('OWNER_PHONE')
    if not phone:
        return
    total = round(float(booking.price or 0), 2)
    if amount is None or round(amount, 2) >= total:
        amount, of_total = total, ''
    else:
        of_total = f' (the balance of a ${total:,.2f} job)'
    try:
        send_sms(phone, f"💰 Payment received: {booking.name} paid ${amount:,.2f}{of_total} ({method}).")
    except Exception:
        pass


@payments_bp.route('/pay/<token>')
def pay_page(token):
    booking = Booking.query.filter_by(pay_token=token).first_or_404()
    pk = integrations.stripe_publishable_key()
    # Name the cleaner on the tip prompt — people tip a person, not a company.
    import customer_terms
    cleaner = booking.crew_label or booking.assigned_cleaner or ''
    return render_template('public/pay.html', booking=booking, token=token,
                           terms=customer_terms.as_html(),
                           stripe_pk=pk, due=amount_due(booking),
                           cleaner_first=cleaner.split()[0] if cleaner else '',
                           # Whether there is anything left to pay, not whether a
                           # payment was once made. A customer sent a link for the
                           # $92 their re-scoped job went up by used to be shown
                           # "already paid" and could not hand over the money.
                           already_paid=is_settled(booking), biz=_biz())


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
    stripe.api_key = integrations.stripe_secret_key()
    if not stripe.api_key:
        return jsonify({'ok': False, 'error': 'Payments not configured'}), 500
    try:
        customer_id = stripe_customer_id_for(booking)
        intent = stripe.PaymentIntent.create(
            amount=int(round((due + tip) * 100)), currency='usd', customer=customer_id,
            metadata={'booking_id': str(booking.id), 'pay_token': token,
                      'kind': 'full_payment', 'customer_name': booking.name or '',
                      'tip': f'{tip:.2f}'},
        )
        # The tip is deliberately NOT written here. This runs when the customer
        # opens the payment form, before any card is charged -- and if they
        # close the tab, or the card declines, or they pay cash instead, a tip
        # that never arrived stays on the booking. Payroll then tells the owner
        # the customer tipped, she hands the cleaner money out of her own
        # pocket, and the P&L counts it as income. It is recorded in confirm(),
        # from the intent Stripe says actually succeeded.
        booking.stripe_payment_intent = intent.id
        db.session.commit()
        return jsonify({'ok': True, 'client_secret': intent.client_secret})
    except stripe.error.StripeError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


def record_tip_from_intent(booking, pi):
    """Write the tip a customer actually paid, from the intent Stripe confirmed.

    Called from two places on purpose, and from nowhere else: the browser's own
    confirm(), and the payment_intent.succeeded webhook for when the browser
    never got to make that call -- tab closed, phone locked, signal dropped.
    Whichever arrives first records it; the second finds the same figure and
    changes nothing, so a replayed webhook cannot double a tip.

    It is deliberately not written when the payment form is opened. A tip typed
    into a form that is then abandoned used to stay on the booking, and payroll
    would tell the owner the customer had tipped. She hands the cleaner money
    that never arrived, out of her own pocket, and the P&L counts it as income.

    `pi` may be a Stripe object or the plain dict from a webhook payload. Both
    behave like dicts.
    """
    try:
        meta = pi.get('metadata') or {}
        tipped = round(float(meta.get('tip') or 0), 2)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    if tipped > 0 and (booking.tip_amount or 0) != tipped:
        booking.tip_amount = tipped
        db.session.commit()
    return tipped


@payments_bp.route('/pay/<token>/confirm', methods=['POST'])
def confirm(token):
    booking = Booking.query.filter_by(pay_token=token).first_or_404()
    data = request.get_json(silent=True) or {}
    pi_id = (data.get('payment_intent_id') or '').strip()
    stripe.api_key = integrations.stripe_secret_key()
    if pi_id and stripe.api_key:
        try:
            pi = stripe.PaymentIntent.retrieve(pi_id)
            if pi.status != 'succeeded':
                return jsonify({'ok': False, 'error': 'Payment not completed'}), 400
            booking.stripe_payment_intent = pi_id
            if pi.payment_method:
                booking.stripe_payment_method_id = pi.payment_method
            record_tip_from_intent(booking, pi)
        except stripe.error.StripeError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
    import customer_terms
    customer_terms.record_acceptance(booking, request)
    mark_paid(booking, method='card')
    return jsonify({'ok': True})
