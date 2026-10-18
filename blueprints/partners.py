"""The partner page: what an affiliate partner can see about their own results.

`/partners` on the product site. A partner signs in with an emailed link (no
password to forget, and nothing to steal that works later), and sees their own
link, their clicks, the companies they brought and where each one is, what
they have earned, and what they have been paid.

## Its own session key

Named apart from the CRM's `logged_in` and the console's `console_email`, for
the reason the console gives: being signed in as a cleaning company's owner
must grant nothing here, and this must grant nothing there. A partner is not
staff and not a customer. It reads exactly one partner's numbers, chosen by the
session and never by anything in the URL, so there is no id to change to see
somebody else's.

## What it shows about a referred company

A name, a date, and a coarse stage. Never an address, a phone number or
anything from the company's own CRM (see affiliates.journey).
"""
import functools
import re
from datetime import datetime

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

import affiliates
import control_plane
import product
import provisioning

partners_bp = Blueprint('partners', __name__, url_prefix='/partners')

SESSION_KEY = 'affiliate_id'
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _engine():
    return provisioning._engine()


def _product_site_only():
    if not product.is_product_site():
        abort(404)


def partner_required(f):
    @functools.wraps(f)
    def wrapper(*a, **kw):
        _product_site_only()
        pid = session.get(SESSION_KEY)
        partner = affiliates.find(_engine(), pid) if pid else None
        # The session is not a standing permission: it is checked against the
        # list on every request, so ending a partner ends their access now.
        if not partner or partner['status'] not in ('active', 'pending', 'paused'):
            session.pop(SESSION_KEY, None)
            return redirect(url_for('partners.login'))
        request.partner = partner
        return f(*a, **kw)
    return wrapper


def link_for(code):
    host = product.canonical_host() or product.domain()
    return f'{product.scheme_for(host)}://{host}/p/{code}' if host else f'/p/{code}'


@partners_bp.route('')
@partners_bp.route('/')
@partner_required
def dashboard():
    partner = request.partner
    data = affiliates.portal(_engine(), partner)
    data.update(link=link_for(partner['code']), now=datetime.utcnow(),
                money=affiliates.money)
    return render_template('partners/dashboard.html', **data)


@partners_bp.route('/login', methods=['GET', 'POST'])
def login():
    _product_site_only()
    if session.get(SESSION_KEY):
        return redirect(url_for('partners.dashboard'))
    sent = False
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        sent = True                      # the same answer whoever the address is
        if EMAIL_RE.match(email):
            _send_link(email)
    return render_template('partners/login.html', sent=sent)


def _send_link(email):
    """Email a sign-in link if this address is a partner. Says nothing either
    way: whether an address is a partner is not for the asking."""
    try:
        engine = _engine()
        partner = affiliates.find_by_email(engine, email)
        if not partner or partner['status'] not in ('active', 'pending', 'paused'):
            return
        raw = affiliates.issue_login(engine, partner['id'])
        if not raw:
            return                       # asked for too many already
        deliver_link(partner, url_for('partners.confirm', token=raw, _external=True))
    except Exception as e:
        print(f'  ⚠️  partner sign-in link not sent: {type(e).__name__}: {e}')


def deliver_link(partner, url):
    """The email itself. Also used by the console's 'send a link' button."""
    import notifications
    name = product.name()
    html = f"""<div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:auto;color:#16213a;line-height:1.6">
  <p>Hi {_first(partner['name'])},</p>
  <p>Here is your sign-in link for your {name} partner page. It works once, for the next
     hour.</p>
  <p style="margin:26px 0"><a href="{url}" style="background:#D98A2B;color:#fff;padding:13px 28px;border-radius:999px;text-decoration:none;font-weight:700;display:inline-block">Open my partner page</a></p>
  <p style="color:#6b7590;font-size:14px">If you did not ask for this, ignore it. Nothing happens until the
     link is used.</p>
</div>"""
    ok, detail = notifications.send_email(
        partner['email'], partner['name'], f'Your {name} partner page', html,
        from_name=name, from_email=product.from_email() or None,
        reply_to=product.support_email() or None,
        api_key=product.resend_api_key() or None)
    control_plane.record_product_message(
        _engine(), None, 'partner_login', partner['email'],
        f'Your {name} partner page', ok, detail, sent_by='auto')
    return ok, detail


def _first(name):
    return (name or '').strip().split(' ')[0] or 'there'


@partners_bp.route('/login/<token>', methods=['GET', 'POST'])
def confirm(token):
    """The link in the email. A button, not a sign-in-by-visiting: mail
    scanners open every link they are sent, and would spend it first."""
    _product_site_only()
    engine = _engine()
    if request.method == 'GET':
        if not affiliates.peek_login(engine, token):
            return render_template('partners/login.html', sent=False, expired=True), 410
        return render_template('partners/confirm.html', token=token)
    partner = affiliates.consume_login(engine, token)
    if not partner:
        return render_template('partners/login.html', sent=False, expired=True), 410
    session[SESSION_KEY] = partner['id']
    session.permanent = True
    return redirect(url_for('partners.dashboard'))


@partners_bp.route('/logout', methods=['POST'])
def logout():
    _product_site_only()
    session.pop(SESSION_KEY, None)
    return redirect(url_for('partners.login'))
