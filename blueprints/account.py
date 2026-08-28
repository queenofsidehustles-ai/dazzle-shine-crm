"""Getting back in, and setting a password for the first time.

Until this existed, a forgotten password had exactly one remedy: the person who
sold you the software editing an environment variable on your hosting account.
That is a support call, for every customer, forever, and it means somebody else
can always let themselves in.

## Deliberately vague replies

Asking to reset an address that has no account gives the same answer as asking
to reset one that does. Otherwise the form is a way to find out who banks here:
type an address, read the response, learn whether that company is a customer.
The page says "if that address has an account, a link is on its way" whatever
happened, and only the inbox knows the difference.

## Requests are throttled

The same address cannot be asked for repeatedly. Without that, anybody can use
the form to fill somebody else's inbox, from a page that requires no login.
"""
import os
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session)

import branding
from extensions import db
from models import User, LoginToken

account_bp = Blueprint('account', __name__)

# One reset email per address per this long. Long enough to stop the form being
# used as a way to hammer somebody's inbox; short enough that a person who
# genuinely mistyped their address is not locked out of trying again.
RESEND_COOLDOWN = timedelta(minutes=3)


def _reset_url(raw):
    return f'{branding.crm_base()}{url_for("account.reset_password", token=raw)}'


def _recently_sent(user):
    cutoff = datetime.utcnow() - RESEND_COOLDOWN
    return (LoginToken.query
            .filter(LoginToken.user_id == user.id,
                    LoginToken.purpose == 'reset',
                    LoginToken.created_at >= cutoff)
            .first() is not None)


@account_bp.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    sent = False
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip().lower()
        user = User.query.filter_by(username=username, active=True).first()
        if user and not _recently_sent(user):
            raw, _ = LoginToken.issue(user, 'reset', email=username)
            _send_reset(user, _reset_url(raw))
        # Always the same answer, whether or not anything was found or sent.
        sent = True
    return render_template('admin/forgot_password.html', sent=sent)


@account_bp.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Checked on GET as well, so a dead link says so on the page the person
    # opened rather than after they have typed a new password twice.
    user = _peek(token, 'reset')
    if not user:
        return render_template('admin/reset_password.html', invalid=True)

    if request.method == 'POST':
        pw = request.form.get('password') or ''
        confirm = request.form.get('confirm') or ''
        problem = _password_problem(pw, confirm)
        if problem:
            return render_template('admin/reset_password.html', error=problem)

        real = LoginToken.consume(token, 'reset')
        if not real:
            return render_template('admin/reset_password.html', invalid=True)

        real.set_password(pw)
        db.session.commit()
        # Every other reset link in flight stops working. If somebody else
        # requested one, this is the moment it becomes useless to them.
        LoginToken.revoke_all(real, 'reset')
        # And they start a fresh session rather than resuming any old one.
        session.clear()
        flash('Password changed. You can sign in now.', 'success')
        return redirect(url_for('admin.login'))

    return render_template('admin/reset_password.html')


def _peek(token, purpose):
    """Is this token good, without spending it."""
    row = LoginToken.query.filter_by(
        token_hash=LoginToken._hash(token), purpose=purpose).first()
    if not row or row.used_at or row.expires_at < datetime.utcnow():
        return None
    return User.query.get(row.user_id)


def _password_problem(pw, confirm):
    if len(pw) < 8:
        return 'Please use at least 8 characters.'
    if pw != confirm:
        return 'The two passwords do not match.'
    if pw.lower() in ('password', '12345678', 'changeme', 'qwertyui'):
        return 'That password is too easy to guess.'
    return None


def _send_reset(user, link):
    import notifications
    biz = branding.biz_name()
    notifications.send_email(
        to_email=user.username, to_name=user.name,
        subject=f'Reset your {biz} password',
        html=f'''
<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Reset your password</h2>
  <p>Hi {(user.name or 'there').split()[0]} — someone asked to reset the password
     for your {biz} account.</p>
  <p style="margin:22px 0"><a href="{link}"
     style="background:#d3a84f;color:#1a1225;padding:13px 26px;border-radius:999px;
            text-decoration:none;font-weight:700">Choose a new password →</a></p>
  <p style="color:#5f5878">This link works once and expires in an hour.</p>
  <p style="color:#9a95ad;font-size:0.88rem">If this wasn't you, ignore this
     email — nothing has changed and your password still works.</p>
</div>''')
