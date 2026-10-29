"""The owner proving the signup email reaches them, or correcting it.

See email_confirm.py (the module, at the top level) for why this exists and
why the emailed link opens a page instead of confirming on its own.

    GET  /confirm-email/<token>    "Is this you?" — no sign-in needed
    POST /confirm-email/<token>    "Yes, this is me"
    GET  /confirm-email            the signed-in owner's page: code, resend, fix
    POST /confirm-email            typed the six digits
    POST /confirm-email/resend     send the code again
    POST /confirm-email/change     the address was wrong; use this one instead
"""
import os
from datetime import datetime

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, session, url_for)

import control_plane
import email_confirm
import provisioning
import tenancy
from auth import owner_required

email_confirm_bp = Blueprint('email_confirm', __name__)


def _engine():
    return provisioning._engine()


def _host(slug):
    return f'{slug}.{os.environ.get("BASE_DOMAIN") or ""}'


def _this_org():
    slug = getattr(g, 'tenant_slug', None)
    if not slug or not tenancy.is_tenant():
        abort(404)
    org = control_plane.find(_engine(), slug)
    if not org:
        abort(404)
    return org


def _from_link(raw):
    """The company this link is for, if it is for this company and the
    address it names is still the owner's. A link sent to an address since
    corrected must not confirm the new one."""
    org = _this_org()
    slug, email = email_confirm.read_token(raw)
    if slug != org['slug'] or not email or \
            email != (org.get('owner_email') or '').strip().lower():
        return org, False
    return org, True


@email_confirm_bp.route('/confirm-email/<token>', methods=['GET', 'POST'])
def by_link(token):
    org, good = _from_link(token)
    if not good:
        return render_template('admin/confirm_email_link.html', state='bad',
                               org=org), 400
    if request.method == 'POST':
        email_confirm.confirm(_engine(), org['slug'])
        return render_template('admin/confirm_email_link.html', state='done',
                               org=org)
    state = 'done' if org.get('email_confirmed_at') else 'ask'
    return render_template('admin/confirm_email_link.html', state=state, org=org)


@email_confirm_bp.route('/confirm-email', methods=['GET', 'POST'])
@owner_required
def page():
    org = _this_org()
    if request.method == 'POST':
        tries = int(session.get('confirm_code_tries') or 0)
        if tries >= email_confirm.MAX_CODE_TRIES:
            flash('Too many tries. Use the button in the email instead, or '
                  'send a new one.', 'error')
            return redirect(url_for('email_confirm.page'))
        if email_confirm.code_matches(org['slug'], org.get('owner_email'),
                                      request.form.get('code')):
            session.pop('confirm_code_tries', None)
            email_confirm.confirm(_engine(), org['slug'])
            flash('Thanks. Your email is confirmed.', 'success')
            return redirect(url_for('settings.getting_started'))
        session['confirm_code_tries'] = tries + 1
        flash('That code does not match. Check the latest email from us.',
              'error')
        return redirect(url_for('email_confirm.page'))
    return render_template('admin/confirm_email.html', org=org,
                           pending=email_confirm.pending(org),
                           may_change=_is_signup_owner(org))


@email_confirm_bp.route('/confirm-email/resend', methods=['POST'])
@owner_required
def resend():
    org = _this_org()
    if org.get('email_confirmed_at'):
        flash('Your email is already confirmed.', 'success')
        return redirect(url_for('settings.getting_started'))
    if not email_confirm.may_resend(org):
        flash('We just sent one. Give it a couple of minutes, and check your '
              'spam folder.', 'error')
        return redirect(url_for('email_confirm.page'))
    ok, _detail = email_confirm.send(org, _host(org['slug']), sent_by='owner',
                                     first=(session.get('user_name') or '').split(' ')[0])
    flash(f'Sent again to {org.get("owner_email")}.' if ok else
          'We could not send it just now. Please try again shortly.',
          'success' if ok else 'error')
    return redirect(url_for('email_confirm.page'))


def _signup_owner(org):
    """The owner login made at signup -- the one whose address this is."""
    from models import User
    email = (org.get('owner_email') or '').strip().lower()
    user = User.query.get(session.get('user_id'))
    if user and (user.username or '').strip().lower() == email:
        return user
    return None


def _is_signup_owner(org):
    try:
        return _signup_owner(org) is not None
    except Exception:
        return False


@email_confirm_bp.route('/confirm-email/change', methods=['POST'])
@owner_required
def change():
    """The address was mistyped. Put the right one on everything it is on:
    the owner's login, the business's contact email, and the company record.

    Asks for the password, because this changes how the owner signs in.
    """
    from extensions import db
    from models import BusinessSetting, User
    import notifications

    org = _this_org()
    user = _signup_owner(org)
    if not user:
        flash('Only the owner who signed up can change this address.', 'error')
        return redirect(url_for('email_confirm.page'))

    new = (request.form.get('email') or '').strip().lower()
    old = (org.get('owner_email') or '').strip().lower()
    if not user.check_password(request.form.get('password') or ''):
        flash('That password is not right.', 'error')
        return redirect(url_for('email_confirm.page'))
    if not notifications.looks_like_email(new):
        flash('That email address does not look right.', 'error')
        return redirect(url_for('email_confirm.page'))
    if new == old:
        flash('That is the address we already have.', 'error')
        return redirect(url_for('email_confirm.page'))
    clash = User.query.filter(db.func.lower(User.username) == new,
                              User.id != user.id).first()
    if clash:
        flash('Somebody on your team already signs in with that address.',
              'error')
        return redirect(url_for('email_confirm.page'))

    user.username = new
    if (BusinessSetting.get('email') or '').strip().lower() in ('', old):
        BusinessSetting.set('email', new)
    db.session.commit()

    engine = _engine()
    org = control_plane.set_email_state(engine, org['slug'], owner_email=new,
                                        email_confirmed_at=None)
    control_plane.forget_tenant_login(engine, old, org['slug'])
    control_plane.record_tenant_login(engine, new, org['slug'])

    ok, _detail = email_confirm.send(org, _host(org['slug']), sent_by='owner',
                                     first=(user.name or '').split(' ')[0])
    flash(f'Updated. You now sign in with {new}, and a new code is on its way '
          f'there.' if ok else
          f'Updated. You now sign in with {new}. We could not send the code '
          f'just now; press "Send it again" in a minute.',
          'success' if ok else 'error')
    return redirect(url_for('email_confirm.page'))
