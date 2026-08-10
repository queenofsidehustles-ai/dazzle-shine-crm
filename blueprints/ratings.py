import os
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from models import BookingRating
from extensions import db
import branding

ratings_bp = Blueprint('ratings', __name__, url_prefix='/rate')

def review_link():
    """The owner's Google review page, from Settings.

    There is deliberately no default. A wrong link here would send a delighted
    customer to leave five stars on somebody else's business, so an unset link
    returns empty and the template hides the button entirely."""
    from models import BusinessSetting
    return BusinessSetting.get('google_review_link') or ''


def _saved_card(booking):
    """(customer_id, payment_method_id) already on file for this booking, or its
    client. Prepay and auto-pay customers have one, which is what makes a
    one-tap tip possible for exactly the people who couldn't tip at payment."""
    client = getattr(booking, 'client', None)
    cus = booking.stripe_customer_id or (client.stripe_customer_id if client else None)
    pm = booking.stripe_payment_method_id or (client.stripe_payment_method_id if client else None)
    return (cus, pm) if (cus and pm) else (None, None)


def _tip_context(r):
    """What the thank-you page needs to offer a tip — or None to offer nothing.

    A tip is only ever offered after a good rating. Asking someone who was
    disappointed for extra money turns a fixable complaint into a chargeback."""
    import integrations
    b = r.booking
    if not b or (r.rating or 0) < 4:
        return None
    if not integrations.stripe_ready():
        return None
    if (b.tip_amount or 0) > 0:
        return None                       # they already tipped when they paid
    cleaner = (b.crew_label or b.assigned_cleaner or '').strip()
    cus, pm = _saved_card(b)
    return {
        'cleaner': cleaner.split()[0] if cleaner else '',
        'one_tap': bool(cus and pm),
        'pk': integrations.stripe_publishable_key(),
    }


def _record_tip(booking, amount, intent_id=None):
    """Add a tip to the booking. Tips are the cleaner's money — they are never
    revenue and never touch the job's price."""
    booking.tip_amount = round((booking.tip_amount or 0) + amount, 2)
    if intent_id:
        booking.tip_payment_intent = intent_id
    db.session.commit()


def _alert_low_rating(r):
    """Email the owner when a customer rates below 4 stars, so they can make it right."""
    if not r.rating or r.rating >= 4:
        return
    try:
        from models import BusinessSetting
        from notifications import send_triggered_email
        owner = (BusinessSetting.get('email') or os.environ.get('OWNER_EMAIL')
                 or branding.owner_email())
        b = r.booking
        send_triggered_email('owner_low_rating', owner, branding.biz_name(), {
            'client_name': (b.name if b else '') or 'A customer',
            'stars': r.rating,
            'comment': r.comment or '—',
        })
    except Exception:
        pass


@ratings_bp.route('/<token>/<int:stars>')
def submit(token, stars):
    r = BookingRating.query.filter_by(token=token).first_or_404()
    if r.rated_at:
        return render_template('public/rate_done.html', r=r,
                               review_link=review_link(), tip=_tip_context(r))
    if stars < 1 or stars > 5:
        return redirect(url_for('ratings.page', token=token))
    r.rating = stars
    r.rated_at = datetime.utcnow()
    comment = request.args.get('comment', '').strip()
    if comment:
        r.comment = comment
    db.session.commit()
    _alert_low_rating(r)
    return render_template('public/rate_done.html', r=r, just_rated=True,
                           review_link=review_link(), tip=_tip_context(r))


@ratings_bp.route('/<token>', methods=['GET', 'POST'])
def page(token):
    r = BookingRating.query.filter_by(token=token).first_or_404()
    if r.rated_at:
        return render_template('public/rate_done.html', r=r,
                               review_link=review_link(), tip=_tip_context(r))
    if request.method == 'POST':
        stars = int(request.form.get('stars', 0))
        if 1 <= stars <= 5:
            r.rating = stars
            r.comment = request.form.get('comment', '').strip()
            r.rated_at = datetime.utcnow()
            db.session.commit()
            _alert_low_rating(r)
            return render_template('public/rate_done.html', r=r, just_rated=True,
                                   review_link=review_link(), tip=_tip_context(r))
    return render_template('public/rate.html', r=r)


@ratings_bp.route('/<token>/tip', methods=['POST'])
def tip(token):
    """Charge a tip after the cleaning.

    Customers who prepay in the morning have no way to tip at payment time —
    they haven't seen the work yet. This is the other end of that: the amount is
    whatever they type, because people are generous about a job done well and a
    suggested figure tends to become a ceiling."""
    import stripe, integrations
    r = BookingRating.query.filter_by(token=token).first_or_404()
    b = r.booking
    if not b or (r.rating or 0) < 4:
        return jsonify({'ok': False, 'error': 'No tip to add here.'}), 400

    data = request.get_json(silent=True) or {}
    try:
        amount = round(float(data.get('amount') or 0), 2)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': "That doesn't look like an amount."}), 400
    if amount <= 0:
        return jsonify({'ok': False, 'error': 'Please enter an amount.'}), 400
    if amount > 2000:
        return jsonify({'ok': False, 'error': 'That looks like a typo — please check the amount.'}), 400

    stripe.api_key = integrations.stripe_secret_key()
    if not stripe.api_key:
        return jsonify({'ok': False, 'error': 'Tips are not set up yet.'}), 500

    cents = int(round(amount * 100))
    meta = {'booking_id': str(b.id), 'kind': 'tip', 'customer_name': b.name or ''}
    cus, pm = _saved_card(b)
    try:
        if cus and pm:
            # Card already on file — one tap, no re-typing.
            intent = stripe.PaymentIntent.create(
                amount=cents, currency='usd', customer=cus, payment_method=pm,
                confirm=True, off_session=True, metadata=meta,
                description=f'Tip for booking #{b.id}')
            if intent.status != 'succeeded':
                return jsonify({'ok': False, 'error': 'That card was declined.'}), 400
            _record_tip(b, amount, intent.id)
            return jsonify({'ok': True, 'done': True})

        # No card on file — hand back a secret so they can enter one.
        intent = stripe.PaymentIntent.create(amount=cents, currency='usd', metadata=meta,
                                             description=f'Tip for booking #{b.id}')
        return jsonify({'ok': True, 'done': False, 'client_secret': intent.client_secret})
    except stripe.error.CardError as e:
        return jsonify({'ok': False, 'error': e.user_message or 'That card was declined.'}), 400
    except stripe.error.StripeError:
        return jsonify({'ok': False, 'error': "That didn't go through. Please try again."}), 400


@ratings_bp.route('/<token>/tip/confirm', methods=['POST'])
def tip_confirm(token):
    """Record a tip paid with a freshly entered card."""
    import stripe, integrations
    r = BookingRating.query.filter_by(token=token).first_or_404()
    b = r.booking
    data = request.get_json(silent=True) or {}
    pi_id = (data.get('payment_intent_id') or '').strip()
    stripe.api_key = integrations.stripe_secret_key()
    if not (b and pi_id and stripe.api_key):
        return jsonify({'ok': False, 'error': 'Could not confirm that tip.'}), 400
    try:
        pi = stripe.PaymentIntent.retrieve(pi_id)
        if pi.status != 'succeeded':
            return jsonify({'ok': False, 'error': 'That payment did not complete.'}), 400
        # Trust Stripe for the amount, not the browser.
        _record_tip(b, round((pi.amount or 0) / 100.0, 2), pi_id)
        return jsonify({'ok': True})
    except stripe.error.StripeError:
        return jsonify({'ok': False, 'error': 'Could not confirm that tip.'}), 400
