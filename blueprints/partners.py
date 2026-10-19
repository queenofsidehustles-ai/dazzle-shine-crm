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


def partners_url():
    """The partner page's own address, for emails."""
    host = product.canonical_host() or product.domain()
    return f'{product.scheme_for(host)}://{host}/partners' if host else '/partners'


@partners_bp.route('')
@partners_bp.route('/')
@partner_required
def dashboard():
    partner = request.partner
    data = affiliates.portal(_engine(), partner)
    import partner_payouts
    data.update(link=link_for(partner['code']), now=datetime.utcnow(),
                money=affiliates.money, payouts_available=partner_payouts.configured())
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
        deliver_link(partner, _trusted_url('partners.confirm', token=raw))
    except Exception as e:
        print(f'  ⚠️  partner sign-in link not sent: {type(e).__name__}: {e}')


def _trusted_url(endpoint, **values):
    """An absolute link built from the product's own host, never the request's.

    The Host header is whatever the caller sent. A sign-in link emailed under an
    attacker's host hands them the token the moment a mail scanner or the
    partner opens it."""
    path = url_for(endpoint, **values)
    host = product.canonical_host() or product.domain()
    if not host:
        return url_for(endpoint, _external=True, **values)   # single-business deployment
    return f'{product.scheme_for(host)}://{host}{path}'


def deliver_link(partner, url):
    """The sign-in email. Also used by the console's 'send a link' button."""
    import partner_mail
    subject, html = partner_mail.login_email(partner, url)
    return partner_mail.deliver(partner, subject, html, 'partner_login', _engine())


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


@partners_bp.route('/payouts/setup', methods=['GET', 'POST'])
@partner_required
def payouts_setup():
    """Send the partner to Stripe to say where their money should go.

    GET as well as POST because Stripe's onboarding link expires and its
    `refresh_url` sends the partner back here to get a new one. Either way it
    only ever creates the partner's own account or a link for it."""
    import partner_payouts
    partner = request.partner
    if not partner_payouts.configured():
        flash('Payouts are not switched on yet. We will email you when they are.', 'error')
        return redirect(url_for('partners.dashboard'))
    engine = _engine()
    ok, account = affiliates.ensure_payout_account(
        engine, partner['id'],
        lambda email, name: partner_payouts.create_account(
            email, name, idempotency_key=f'affiliate-account-{partner["id"]}'))
    if not ok:
        flash(f'Stripe could not start your setup: {account}', 'error')
        return redirect(url_for('partners.dashboard'))
    here = url_for('partners.payouts_setup', _external=True)
    back = url_for('partners.payouts_return', _external=True)
    ok, value = partner_payouts.onboarding_link(account, here, back)
    if not ok:
        flash(f'Stripe could not open your setup page: {value}', 'error')
        return redirect(url_for('partners.dashboard'))
    return redirect(value)


@partners_bp.route('/payouts/return')
@partner_required
def payouts_return():
    """Where Stripe sends them back. Ask Stripe, rather than trusting the visit."""
    ok, ready = affiliates.refresh_payout_status(_engine(), request.partner)
    if not ok:
        flash(f'We could not check with Stripe just now: {ready}', 'error')
    elif ready:
        flash('Payouts are set up. We will pay you by bank transfer once your balance reaches the minimum.', 'success')
    else:
        flash('Stripe still needs a few details before it can pay you. Open setup again to finish.', 'error')
    return redirect(url_for('partners.dashboard'))


@partners_bp.route('/logout', methods=['POST'])
def logout():
    _product_site_only()
    session.pop(SESSION_KEY, None)
    return redirect(url_for('partners.login'))
