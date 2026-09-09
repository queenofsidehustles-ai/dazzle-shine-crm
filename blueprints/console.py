"""The room behind the product: every company, every report, in one place.

Until this, everything that spanned companies was a command-line tool run by
somebody holding the production database URL. That works while the somebody is
the founder. It does not work for an assistant, and it means beta feedback
lives in one person's inbox, which is where feedback goes to be forgotten.

## Its own accounts, deliberately

A cleaning company's owner can see their own business. Somebody signed in here
can see all of them. Those are different jobs with very different blast
radiuses, so they are never the same credential -- a console session is a
separate key in the session, and being an owner of a CRM grants nothing here.

## It shows and it triages. It does not fix.

Marking a report done is not the same as the bug being gone. The work still
happens in the code. What this removes is reports being invisible to everybody
except whoever owns the inbox.
"""
import functools
from datetime import datetime

from flask import (Blueprint, Response, flash, redirect, render_template,
                   request, session, url_for)

import control_plane
import product
import provisioning

console_bp = Blueprint('console', __name__, url_prefix='/console')

# The session key. Named apart from the CRM's own 'logged_in' so that being
# signed into a cleaning company can never, by any mistake, be signed in here.
SESSION_KEY = 'console_email'


def _engine():
    return provisioning._engine()


def console_required(f):
    @functools.wraps(f)
    def wrapper(*a, **kw):
        email = session.get(SESSION_KEY)
        if not email:
            return redirect(url_for('console.login', next=request.path))
        user = control_plane.console_user(_engine(), email)
        if not user or not user.get('active'):
            # Access removed while they were signed in. The session is not a
            # standing permission; it is checked against the list every time.
            session.pop(SESSION_KEY, None)
            return redirect(url_for('console.login'))
        request.console_user = user
        return f(*a, **kw)
    return wrapper


def can_manage(f):
    """Anybody who is allowed to bring somebody else in at all.

    Which is not the same as being allowed to act on any particular person --
    that is checked per target, because the whole point of the ranks is that a
    manager can remove a helper and cannot remove the owner.
    """
    @functools.wraps(f)
    def wrapper(*a, **kw):
        role = (getattr(request, 'console_user', {}) or {}).get('role')
        if control_plane.rank(role) < control_plane.rank('manager'):
            flash('You are not able to change who has access.', 'error')
            return redirect(url_for('console.people'))
        return f(*a, **kw)
    return wrapper


@console_bp.route('/login', methods=['GET', 'POST'])
def login():
    engine = _engine()
    control_plane.ensure_table(engine)
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        user, why = control_plane.check_console_login(
            engine, email, request.form.get('password') or '')
        if user:
            session[SESSION_KEY] = user['email']
            control_plane.log_console(engine, user['email'], 'signed in')
            nxt = request.args.get('next') or url_for('console.inbox')
            return redirect(nxt if nxt.startswith('/console') else url_for('console.inbox'))
        # One message for both "no such account" and "wrong password". Telling
        # them apart is how somebody learns which addresses are real.
        flash('Too many tries — wait a few minutes.' if why == 'locked'
              else 'That email and password do not match.', 'error')
    return render_template('console/login.html')


@console_bp.route('/logout')
def logout():
    session.pop(SESSION_KEY, None)
    return redirect(url_for('console.login'))


@console_bp.route('/')
@console_required
def inbox():
    """What the beta said, newest first."""
    engine = _engine()
    return render_template(
        'console/inbox.html',
        rows=control_plane.all_feedback(engine),
        support=control_plane.all_support_requests(engine, limit=50),
        me=request.console_user,
        counts=_counts(engine))


@console_bp.route('/feedback/<int:feedback_id>/done', methods=['POST'])
@console_required
def mark_done(feedback_id):
    engine = _engine()
    control_plane.mark_feedback_read(engine, feedback_id)
    control_plane.log_console(engine, request.console_user['email'],
                              'marked done', f'report #{feedback_id}')
    return redirect(url_for('console.inbox'))


@console_bp.route('/support/<int:request_id>/done', methods=['POST'])
@console_required
def support_done(request_id):
    engine = _engine()
    control_plane.mark_support_answered(engine, request_id)
    control_plane.log_console(engine, request.console_user['email'],
                              'marked answered', f'question #{request_id}')
    return redirect(url_for('console.inbox'))


@console_bp.route('/shot/<int:feedback_id>')
@console_required
def shot(feedback_id):
    blob, ctype = control_plane.feedback_shot(_engine(), feedback_id)
    if not blob:
        return ('', 404)
    return Response(blob, mimetype=ctype,
                    headers={'Cache-Control': 'private, max-age=600'})


@console_bp.route('/companies')
@console_required
def companies():
    engine = _engine()
    return render_template('console/companies.html',
                           rows=control_plane.all_orgs(engine),
                           leads=control_plane.all_leads(engine),
                           me=request.console_user, counts=_counts(engine))


# What each level means, in the words somebody choosing would use.
ROLE_MEANS = {
    'owner': 'everything, and cannot be switched off from here',
    'manager': 'everything except touching you or another manager',
    'helper': 'read the reports and mark them done',
}


@console_bp.route('/people')
@console_required
def people():
    engine = _engine()
    me = request.console_user
    return render_template(
        'console/people.html',
        rows=control_plane.console_users_all(engine),
        # The same rule the routes enforce, so the page only draws buttons
        # that would work. It is a courtesy, not the permission.
        can_act=lambda role: control_plane.may_act_on(me['role'], role),
        grantable=[r for r in control_plane.ROLES
                   if control_plane.may_grant(me['role'], r)],
        ROLE_MEANS=ROLE_MEANS,
        me=me, counts=_counts(engine))


@console_bp.route('/people/add', methods=['POST'])
@console_required
@can_manage
def add_person():
    engine = _engine()
    me = request.console_user
    email = (request.form.get('email') or '').strip().lower()
    name = (request.form.get('name') or '').strip()
    password = request.form.get('password') or ''
    role = (request.form.get('role') or 'helper').strip().lower()

    # You cannot hand out your own level, only something under it. So a
    # manager brings in helpers and only the owner appoints a manager.
    if not control_plane.may_grant(me['role'], role):
        flash(f'You cannot give somebody {role} access.', 'error')
        return redirect(url_for('console.people'))
    if not email or len(password) < 12:
        flash('An email and a password of at least 12 characters.', 'error')
        return redirect(url_for('console.people'))
    if control_plane.console_user(engine, email):
        flash('That email is already on the list.', 'error')
        return redirect(url_for('console.people'))

    control_plane.add_console_user(engine, email, name, password, role)
    control_plane.log_console(engine, me['email'], 'added', email,
                              f'as {role}')
    flash(f'{email} can sign in now as {role}. Tell them the password '
          f'yourself — it is not emailed.', 'success')
    return redirect(url_for('console.people'))


@console_bp.route('/people/<path:email>/off', methods=['POST'])
@console_required
@can_manage
def turn_off(email):
    engine = _engine()
    me = request.console_user
    target = control_plane.console_user(engine, email)

    if not target:
        flash('Nobody by that email.', 'error')
    elif email == me['email']:
        flash('You cannot switch off your own access.', 'error')
    elif not control_plane.may_act_on(me['role'], target['role']):
        # The rule the owner asked for, and it is the same rule for everybody:
        # you may act on somebody below you, never beside you or above you. So
        # a manager cannot switch off the owner or another manager, and no
        # amount of console access reaches the person who granted it.
        flash(f'You cannot change access for somebody who is '
              f'{target["role"]}.', 'error')
        article = 'an' if target['role'][0] in 'aeiou' else 'a'
        control_plane.log_console(engine, me['email'], 'refused', email,
                                  f'tried to switch off {article} {target["role"]}')
    else:
        control_plane.set_console_active(engine, email, False)
        control_plane.log_console(engine, me['email'], 'switched off', email,
                                  f'was {target["role"]}')
        flash(f'{email} can no longer sign in.', 'success')
    return redirect(url_for('console.people'))


@console_bp.route('/people/<path:email>/on', methods=['POST'])
@console_required
@can_manage
def turn_on(email):
    """Put somebody back. Same rule, so a manager cannot restore an owner."""
    engine = _engine()
    me = request.console_user
    target = control_plane.console_user(engine, email)
    if not target:
        flash('Nobody by that email.', 'error')
    elif not control_plane.may_act_on(me['role'], target['role']):
        flash(f'You cannot change access for somebody who is '
              f'{target["role"]}.', 'error')
    else:
        control_plane.set_console_active(engine, email, True)
        control_plane.log_console(engine, me['email'], 'switched on', email)
        flash(f'{email} can sign in again.', 'success')
    return redirect(url_for('console.people'))


@console_bp.route('/log')
@console_required
def log():
    """Who did what. Everybody with access can read it, including helpers --
    a record only the boss can see is a record the boss has to be asked for."""
    engine = _engine()
    return render_template('console/log.html',
                           rows=control_plane.console_log_all(engine),
                           me=request.console_user, counts=_counts(engine))


def _counts(engine):
    return {'feedback': control_plane.unread_feedback(engine),
            'support': control_plane.unanswered_support(engine)}


# --------------------------------------------------------------------------
# The question box on the public site
#
# Deliberately here rather than in marketing.py: it writes to the control
# plane and it is read from the console, so it belongs with the code that owns
# both. Nothing about it requires an account -- the people it is for do not
# have one yet.

@console_bp.route('/ask', methods=['POST'])
def public_question():
    """A question from somebody who is not a customer yet."""
    from flask import jsonify
    data = request.get_json(silent=True) or {}

    # A field a person never sees and a robot always fills. Cheaper and
    # quieter than a captcha, which asks real people to prove themselves.
    if (data.get('company') or '').strip():
        return jsonify({'ok': True, 'say': 'Thanks — we will come back to you.'})

    body = (data.get('body') or '').strip()
    email = (data.get('email') or '').strip()
    if not body or '@' not in email:
        return jsonify({'ok': False,
                        'say': 'A question and an email to reply to, please.'}), 400

    engine = _engine()
    try:
        control_plane.ensure_table(engine)
        control_plane.add_support_request(
            engine, name=(data.get('name') or '')[:120], email=email[:200],
            body=body[:4000], page=(data.get('page') or '')[:300],
            user_agent=(request.headers.get('User-Agent') or '')[:300])
    except Exception:
        return jsonify({'ok': False,
                        'say': 'That did not send. Try once more.'}), 500

    _tell_us_question(email, data.get('name'), body)
    return jsonify({'ok': True,
                    'say': 'Got it. We usually reply within one business day.'})


def _tell_us_question(email, name, body):
    to = product.support_email()
    if not to:
        return
    try:
        from html import escape
        from notifications import send_email
        send_email(
            to, product.name(), f'Question from {email}',
            f'<p style="font-size:15px;white-space:pre-wrap">{escape(body)}</p>'
            f'<p style="color:#777;font-size:13px">{escape(name or "no name")} · '
            f'{escape(email)}</p>',
            from_name=product.name(), from_email=product.from_email() or to,
            reply_to=email,           # so hitting reply goes to them, not to us
            api_key=product.resend_api_key() or None)
    except Exception:
        pass
