"""Ask a customer to confirm a proposed cleaning — or tell you it's a no.

Some people go quiet. They asked about regular cleaning, sounded keen, and then
didn't answer a text or a call. Chasing harder rarely works; giving them
something concrete to react to usually does. A specific date at a specific price
with two buttons is easier to answer than "are you still interested?".

The decision is deliberately NOT a link in the email. Mail providers follow every
URL in a message to scan it, so a one-click confirm link can be pressed by a
security scanner before the customer has read a word — booking a job nobody
agreed to, or cancelling one they wanted. The email opens a page; the page has
the buttons.
"""
import secrets
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for

import branding
from extensions import db
from models import Booking

confirm_bp = Blueprint('confirm', __name__)


def ensure_token(booking):
    if not booking.confirm_token:
        booking.confirm_token = secrets.token_urlsafe(32)
        db.session.commit()
    return booking.confirm_token


def proposal_url(booking):
    return f"{branding.crm_base()}/confirm/{ensure_token(booking)}"


def _booking(token):
    from flask import abort
    b = Booking.query.filter_by(confirm_token=token).first()
    if not b:
        abort(404)
    return b


@confirm_bp.route('/confirm/<token>')
def page(token):
    b = _booking(token)
    return render_template('public/confirm.html', b=b, token=token,
                           biz=branding.biz_name(), phone=branding.phone(),
                           answered=b.confirm_response)


@confirm_bp.route('/confirm/<token>/respond', methods=['POST'])
def respond(token):
    """Record the customer's answer. POST only — a scanner following links can
    never reach this."""
    b = _booking(token)
    answer = 'yes' if request.form.get('answer') == 'yes' else 'no'

    if not b.confirm_response:
        b.confirm_response = answer
        b.confirm_responded_at = datetime.utcnow()
        if answer == 'yes':
            if b.status in ('pending', None):
                b.status = 'confirmed'
        else:
            b.status = 'cancelled'
        db.session.commit()
        _tell_the_owner(b, answer)

    return redirect(url_for('confirm.page', token=token))


def _tell_the_owner(booking, answer):
    """However they answer, the owner hears about it — a silent 'no' is just the
    same silence they were already getting."""
    from notifications import send_sms, send_email
    word = 'CONFIRMED' if answer == 'yes' else 'declined'
    when = booking.preferred_date or 'the proposed date'
    line = (f"{booking.name} {word} their cleaning for {when}"
            + (f" at ${booking.price:.2f}" if booking.price else ''))
    try:
        from models import BusinessSetting
        phone = BusinessSetting.get('owner_alert_phone') or branding.phone()
        if phone:
            send_sms(phone, f"{'✅' if answer == 'yes' else '❌'} {line}.")
    except Exception:
        pass
    try:
        send_email(to_email=branding.owner_email(), to_name=branding.biz_name(),
                   subject=f"{'✅' if answer == 'yes' else '❌'} {booking.name} {word}",
                   html=f'<div style="font-family:Inter,sans-serif">'
                        f'<p>{line}.</p>'
                        f'<p style="color:#9a95ad;font-size:0.85rem">Booking #{booking.id}</p></div>')
    except Exception:
        pass
