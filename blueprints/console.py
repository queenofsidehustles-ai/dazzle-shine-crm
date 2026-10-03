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
import html
import os
import re
from datetime import datetime, timedelta

import markdown
from flask import (Blueprint, Response, flash, redirect, render_template,
                   request, session, url_for)

import control_plane
import product
import provisioning

console_bp = Blueprint('console', __name__, url_prefix='/console')

# The session key. Named apart from the CRM's own 'logged_in' so that being
# signed into a cleaning company can never, by any mistake, be signed in here.
SESSION_KEY = 'console_email'
# Right password, code still owed. Never the same key as SESSION_KEY, so a
# half-finished sign-in cannot open a single console page.
PENDING_2FA_KEY = 'console_pending_2fa'
# The pages somebody who must set up two-factor can still reach.
_TWO_FACTOR_SETUP = frozenset({'console.security_view', 'console.security_start',
                               'console.security_confirm', 'console.logout'})


def two_factor_required():
    """Every console login must use two-factor on the live product.

    CONSOLE_REQUIRE_2FA=1 or 0 overrides; otherwise it is on in production and
    off on a laptop, so local runs and the test suite do not need a phone."""
    raw = (os.environ.get('CONSOLE_REQUIRE_2FA') or '').strip()
    if raw in ('0', '1'):
        return raw == '1'
    import security
    return security._is_production()


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
        if (two_factor_required() and not user.get('totp_enabled')
                and request.endpoint not in _TWO_FACTOR_SETUP):
            flash('Set up two-factor sign-in before using the console. It sees '
                  'every company, so a password alone is not enough.', 'error')
            return redirect(url_for('console.security_view'))
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
        nxt = request.args.get('next') or ''
        nxt = nxt if nxt.startswith('/console') else url_for('console.inbox')
        if user and user.get('totp_enabled'):
            session.pop(SESSION_KEY, None)
            session[PENDING_2FA_KEY] = user['email']
            session['console_next'] = nxt
            return redirect(url_for('console.login_code'))
        if user:
            session.pop(PENDING_2FA_KEY, None)
            session[SESSION_KEY] = user['email']
            control_plane.log_console(engine, user['email'], 'signed in')
            return redirect(nxt)
        # One message for both "no such account" and "wrong password". Telling
        # them apart is how somebody learns which addresses are real.
        flash('Too many tries — wait a few minutes.' if why == 'locked'
              else 'That email and password do not match.', 'error')
    return render_template('console/login.html')


@console_bp.route('/logout')
def logout():
    session.pop(SESSION_KEY, None)
    session.pop(PENDING_2FA_KEY, None)
    return redirect(url_for('console.login'))


@console_bp.route('/login/code', methods=['GET', 'POST'])
def login_code():
    """The second step: a code from the authenticator app, or a backup code."""
    email = session.get(PENDING_2FA_KEY)
    if not email:
        return redirect(url_for('console.login'))
    if request.method == 'POST':
        engine = _engine()
        user, why = control_plane.check_console_code(
            engine, email, request.form.get('code') or '')
        if user:
            session.pop(PENDING_2FA_KEY, None)
            nxt = session.pop('console_next', None) or url_for('console.inbox')
            session[SESSION_KEY] = user['email']
            control_plane.log_console(engine, user['email'], 'signed in')
            return redirect(nxt if nxt.startswith('/console') else url_for('console.inbox'))
        if why == 'locked':
            session.pop(PENDING_2FA_KEY, None)
            flash('Too many tries — wait a few minutes.', 'error')
            return redirect(url_for('console.login'))
        flash('That code did not match. Try the newest one on your phone.', 'error')
    return render_template('console/login_code.html')


@console_bp.route('/security')
@console_required
def security_view():
    return render_template('console/security.html', me=request.console_user,
                           required=two_factor_required(), secret=None,
                           otpauth_uri=None, backup_codes=None,
                           counts=_counts(_engine()))


@console_bp.route('/security/start', methods=['POST'])
@console_required
def security_start():
    import totp
    me = request.console_user
    secret = control_plane.start_console_totp(_engine(), me['email'])
    return render_template('console/security.html', me=dict(me, totp_enabled=False),
                           required=two_factor_required(),
                           secret=totp.format_secret(secret),
                           otpauth_uri=totp.provisioning_uri(
                               secret, me['email'], f'{product.name()} console'),
                           backup_codes=None, counts=_counts(_engine()))


@console_bp.route('/security/confirm', methods=['POST'])
@console_required
def security_confirm():
    import totp
    engine = _engine()
    me = request.console_user
    codes = control_plane.enable_console_totp(engine, me['email'],
                                              request.form.get('code') or '')
    if not codes:
        flash('That code did not match. Check the time on your phone and try '
              'the newest code.', 'error')
        fresh = control_plane.console_user(engine, me['email']) or me
        secret = fresh.get('totp_secret') or ''
        return render_template('console/security.html', me=fresh,
                               required=two_factor_required(),
                               secret=totp.format_secret(secret) if secret else None,
                               otpauth_uri=totp.provisioning_uri(
                                   secret, me['email'], f'{product.name()} console')
                               if secret else None,
                               backup_codes=None, counts=_counts(engine))
    control_plane.log_console(engine, me['email'], 'turned on two-factor')
    flash('Two-factor sign-in is on.', 'success')
    # The only time these are shown -- only their hashes are kept.
    return render_template('console/security.html',
                           me=control_plane.console_user(engine, me['email']),
                           required=two_factor_required(), secret=None,
                           otpauth_uri=None, backup_codes=codes,
                           counts=_counts(engine))


@console_bp.route('/security/disable', methods=['POST'])
@console_required
def security_disable():
    from werkzeug.security import check_password_hash
    engine = _engine()
    me = request.console_user
    if not check_password_hash(me.get('password_hash') or '',
                               request.form.get('password') or ''):
        flash('Your password was not correct.', 'error')
        return redirect(url_for('console.security_view'))
    control_plane.disable_console_totp(engine, me['email'])
    control_plane.log_console(engine, me['email'], 'turned off two-factor')
    flash('Two-factor sign-in is off.', 'success')
    return redirect(url_for('console.security_view'))


@console_bp.route('/', strict_slashes=False)
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


def _may_operate():
    """Managers and the owner may change a company. Helpers read."""
    role = (getattr(request, 'console_user', {}) or {}).get('role')
    return control_plane.rank(role) >= control_plane.rank('manager')


def _refuse(where):
    flash('Only a manager or the owner can do that.', 'error')
    return redirect(where)


@console_bp.route('/companies')
@console_required
def companies():
    """Every company, with enough on each row to know which one needs you."""
    import billing
    import console_data
    engine = _engine()
    orgs = control_plane.all_orgs(engine)
    snaps = console_data.snapshots(orgs)
    rows = [dict(o, trial=billing.trial_state(o), snap=snaps.get(o['slug']))
            for o in orgs]
    return render_template('console/companies.html', rows=rows,
                           leads=console_data.dedupe_leads(control_plane.all_leads(engine)),
                           me=request.console_user, counts=_counts(engine))


@console_bp.route('/companies/<slug>')
@console_required
def company(slug):
    """One company: who they are, what they pay, and whether it is working."""
    import billing
    import console_data
    import tenant_data_lifecycle
    engine = _engine()
    org = control_plane.find(engine, slug)
    if not org:
        flash(f'No company at {slug}.', 'error')
        return redirect(url_for('console.companies'))
    import attribution
    readable = (org.get('status') or 'active') in console_data.READABLE
    closed_at = org.get('closed_at')
    return render_template(
        'console/company.html', org=org, trial=billing.trial_state(org),
        came_from=attribution.label(org),
        referred=control_plane.referred_by(engine, slug),
        snap=console_data.snapshot(slug) if readable else None,
        reports=[f for f in control_plane.all_feedback(engine)
                 if f.get('org_slug') == slug][:20],
        history=[r for r in control_plane.console_log_all(engine)
                 if r.get('target') == slug][:20],
        purge_from=(closed_at + timedelta(days=tenant_data_lifecycle.RETENTION_DAYS)
                    if closed_at else None),
        may_operate=_may_operate(),
        me=request.console_user, counts=_counts(engine))


@console_bp.route('/companies/<slug>/trial', methods=['POST'])
@console_required
def extend_trial(slug):
    import console_data
    here = url_for('console.company', slug=slug)
    if not _may_operate():
        return _refuse(here)
    engine = _engine()
    org = control_plane.find(engine, slug)
    try:
        days = int(request.form.get('days') or 0)
    except ValueError:
        days = 0
    if not org or days not in (7, 14, 30):
        flash('Pick 7, 14 or 30 days.', 'error')
        return redirect(here)
    if (org.get('subscription_status') or 'trialing').lower() != 'trialing':
        flash('They are not on a trial — their plan is set by Stripe.', 'error')
        return redirect(here)
    ends = console_data.extended_trial_end(org, days)
    control_plane.set_billing(engine, slug, trial_ends_at=ends)
    control_plane.log_console(engine, request.console_user['email'],
                              'extended trial', slug,
                              f'+{days} days, now ends {ends:%d %b %Y}')
    flash(f'Trial extended by {days} days, to {ends:%d %b %Y}.', 'success')
    return redirect(here)


@console_bp.route('/companies/<slug>/welcome', methods=['POST'])
@console_required
def send_welcome(slug):
    """Send (or re-send) the welcome email to a company's owner.

    Signups before this existed got no welcome at all — their own web address
    was on one confirmation screen and nowhere else. This is how those people
    get it, and it is also the honest way to re-send for anybody who lost it.

    From the console rather than a command line because the product mail key
    lives here, on the host, and not on anybody's laptop.
    """
    here = url_for('console.company', slug=slug)
    engine = _engine()
    org = control_plane.find(engine, slug)
    if not org:
        flash('No such company.', 'error')
        return redirect(here)
    email = (org.get('owner_email') or '').strip()
    if not email:
        flash('That company has no owner email on file.', 'error')
        return redirect(here)

    import welcome_email, product
    host = f"{slug}.{os.environ.get('BASE_DOMAIN', 'akyehq.com')}"
    ok, detail = welcome_email.send(org.get('name') or slug, email, host)
    control_plane.log_console(engine, request.console_user['email'],
                              'welcome-email', slug, ('sent' if ok else str(detail))[:300])
    if ok:
        flash(f'Welcome email sent to {email}.', 'success')
    else:
        flash(f'Could not send it: {detail}', 'error')
    return redirect(here)


@console_bp.route('/companies/<slug>/suspend', methods=['POST'])
@console_required
def suspend_company(slug):
    here = url_for('console.company', slug=slug)
    if not _may_operate():
        return _refuse(here)
    engine = _engine()
    org = control_plane.find(engine, slug)
    reason = (request.form.get('reason') or '').strip()
    if not org or org.get('status') != 'active':
        flash('Only an active company can be suspended.', 'error')
        return redirect(here)
    if not reason:
        # Somebody will ask why their business stopped working. The answer
        # has to be written down by whoever did it, at the time.
        flash('Say why — it goes in the record.', 'error')
        return redirect(here)
    control_plane.set_status(engine, slug, 'suspended')
    control_plane.log_console(engine, request.console_user['email'],
                              'suspended', slug, reason[:300])
    flash(f'{org["name"]} is suspended. Nobody there can sign in until it is '
          f'reactivated.', 'success')
    return redirect(here)


@console_bp.route('/companies/<slug>/test', methods=['POST'])
@console_required
def mark_test_account(slug):
    """Mark or unmark a company as a test account. Changes the numbers only."""
    here = url_for('console.company', slug=slug)
    if not _may_operate():
        return _refuse(here)
    engine = _engine()
    org = control_plane.find(engine, slug)
    if not org:
        flash(f'No company at {slug}.', 'error')
        return redirect(url_for('console.companies'))
    is_test = request.form.get('on') == '1'
    if org.get('is_demo') and not is_test:
        flash(f'{org["name"]} is the demo company, so it stays a test account — '
              f'its customers are made up.', 'info')
        return redirect(here)
    control_plane.set_test_account(engine, slug, is_test)
    control_plane.log_console(engine, request.console_user['email'],
                              'marked as test account' if is_test
                              else 'marked as a real company', slug)
    flash(f'{org["name"]} is {"now" if is_test else "no longer"} a test account — '
          f'{"left out of" if is_test else "counted in"} the funnel and sales numbers'
          f'{" and never sent trial reminders" if is_test else ""}.', 'success')
    return redirect(here)


@console_bp.route('/companies/<slug>/reactivate', methods=['POST'])
@console_required
def reactivate_company(slug):
    here = url_for('console.company', slug=slug)
    if not _may_operate():
        return _refuse(here)
    engine = _engine()
    org = control_plane.find(engine, slug)
    if not org or org.get('status') != 'suspended':
        # Closed is deliberately not reversible from here: closure starts the
        # retention clock, and reopening is an operator decision made from a
        # terminal (tenant_lifecycle_cli.py), not a button.
        flash('Only a suspended company can be reactivated here.', 'error')
        return redirect(here)
    control_plane.set_status(engine, slug, 'active')
    control_plane.log_console(engine, request.console_user['email'],
                              'reactivated', slug)
    flash(f'{org["name"]} is active again.', 'success')
    return redirect(here)


@console_bp.route('/leads.csv')
@console_required
def leads_csv():
    """The early-access list, for a spreadsheet. Same columns as the CLI."""
    import csv
    import io
    engine = _engine()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['when', 'name', 'company', 'email', 'phone', 'cleaners',
                'note', 'source', 'contacted'])
    for r in control_plane.all_leads(engine):
        w.writerow([_csv_safe(v) for v in (
            r['created_at'].strftime('%Y-%m-%d %H:%M') if r.get('created_at') else '',
            r.get('name'), r.get('company'), r.get('email'), r.get('phone'),
            r.get('cleaners'), (r.get('note') or '').replace('\n', ' '),
            r.get('source'),
            r['contacted_at'].strftime('%Y-%m-%d') if r.get('contacted_at') else '')])
    control_plane.log_console(engine, request.console_user['email'],
                              'exported', 'early-access leads')
    return Response(buf.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': 'attachment; filename=akye-early-access.csv'})


def _csv_safe(value):
    """Stop a lead typed as `=HYPERLINK(...)` running as a formula in a sheet.

    These are strangers' form entries opened in a spreadsheet by somebody with
    access to every company, which is exactly who a formula injection wants.
    """
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


@console_bp.route('/health')
@console_required
def health():
    """Is the product working, for everybody, right now."""
    import console_data
    import tenant_data_lifecycle
    import trial_nudges
    engine = _engine()
    orgs = control_plane.all_orgs(engine)
    snaps = console_data.snapshots(orgs)
    preview = trial_nudges.run(engine, dry_run=True)
    names = {o['slug']: o['name'] for o in orgs}
    closed = [dict(o, purge_from=o['closed_at'] + timedelta(
                  days=tenant_data_lifecycle.RETENTION_DAYS))
              for o in orgs if o.get('status') == 'closed' and o.get('closed_at')
              and not o.get('purged_at')]
    job_labels = [(key, label) for key, label, _b, _c in _automation_jobs()]
    return render_template(
        'console/health.html', orgs=[o for o in orgs if o['slug'] in snaps],
        snaps=snaps, job_labels=job_labels, mail=product.mail_status(),
        nudges=preview.get('plan') or [], names=names, closed=closed,
        may_operate=_may_operate(), me=request.console_user,
        counts=_counts(engine))


def _automation_jobs():
    import automations
    return automations.JOBS


@console_bp.route('/health/test-email', methods=['POST'])
@console_required
def test_email():
    """Send the product's own email to whoever pressed the button."""
    import notifications
    engine = _engine()
    me = request.console_user
    st = product.mail_status()
    if not st['applies'] or st['problem']:
        flash(st['problem'] or 'This deployment has no product email to test.', 'error')
        return redirect(url_for('console.health'))
    ok, detail = notifications.send_email(
        me['email'], me.get('name') or 'there', f'{product.name()} test email',
        '<p>If you are reading this, the product can send email: the same '
        'path as trial reminders and crash alerts.</p>',
        from_name=product.name(), from_email=st['from'], reply_to=st['to'],
        api_key=product.resend_api_key())
    control_plane.log_console(engine, me['email'], 'test email',
                              me['email'], 'accepted' if ok else f'failed: {detail}'[:300])
    if ok:
        flash(f'Accepted by the provider. Check {me["email"]} — accepted is not '
              f'the same as arrived.', 'success')
    else:
        flash(f'Not sent: {detail}', 'error')
    return redirect(url_for('console.health'))


@console_bp.route('/health/trial-emails', methods=['POST'])
@console_required
def send_trial_emails():
    """Send the trial reminders due today. Each is recorded, so twice is safe."""
    import trial_nudges
    if not _may_operate():
        return _refuse(url_for('console.health'))
    engine = _engine()
    counts = trial_nudges.run(engine)
    plan = counts.get('plan') or []
    sent = len(plan) - counts.get('failed', 0)
    control_plane.log_console(
        engine, request.console_user['email'], 'sent trial emails',
        f'{sent} sent', ', '.join(f'{slug}:{kind}' for slug, kind, _e in plan)[:400])
    if counts.get('failed'):
        flash(f'{sent} sent, {counts["failed"]} failed — they stay due and can be '
              f'sent again.', 'error')
    else:
        flash(f'{sent} trial email{"s" if sent != 1 else ""} sent.', 'success')
    return redirect(url_for('console.health'))


@console_bp.route('/funnel')
@console_required
def funnel_view():
    """How people become paying customers, and who needs a nudge today.

    Read-only apart from marking a lead contacted. The numbers come from
    funnel.compute, which reads only what the control plane already records;
    see that module for what each stage means and what it leaves out.
    """
    import funnel
    engine = _engine()
    window = request.args.get('window', funnel.DEFAULT_WINDOW)
    if window not in funnel.WINDOWS:
        window = funnel.DEFAULT_WINDOW
    data = funnel.compute(control_plane.all_orgs(engine),
                          control_plane.all_leads(engine),
                          days=funnel.WINDOWS[window])
    return render_template('console/funnel.html', f=data, window=window,
                           windows=list(funnel.WINDOWS),
                           me=request.console_user, counts=_counts(engine))


@console_bp.route('/funnel/sales')
@console_required
def sales_view():
    """The funnel in money: recurring revenue, how it moved, what is coming."""
    import entitlements
    import funnel
    engine = _engine()
    window = request.args.get('window', funnel.DEFAULT_WINDOW)
    if window not in funnel.WINDOWS:
        window = funnel.DEFAULT_WINDOW
    data = funnel.sales(control_plane.all_orgs(engine), entitlements.PLANS,
                        days=funnel.WINDOWS[window])
    return render_template('console/sales.html', s=data, window=window,
                           windows=list(funnel.WINDOWS),
                           me=request.console_user, counts=_counts(engine))


PROMO_CODE_RE = re.compile(r'^[A-Z0-9][A-Z0-9_-]{2,39}$')


@console_bp.route('/discounts', methods=['GET', 'POST'])
@console_required
def discounts():
    """Discount codes for Akye's plans, made in Stripe, typed at checkout."""
    import billing
    engine = _engine()
    here = url_for('console.discounts')
    if request.method == 'POST':
        if not _may_operate():
            return _refuse(here)
        form, problem = _promo_form(request.form)
        if not problem and control_plane.find_promo_code(engine, code=form['code']):
            problem = f'{form["code"]} already exists.'
        if problem:
            flash(problem, 'error')
            return redirect(here)
        try:
            coupon_id, promo_id = billing.create_promo_code(
                form['code'], percent_off=form['percent_off'],
                amount_off_cents=form['amount_off_cents'], duration=form['duration'],
                duration_months=form['duration_months'],
                max_redemptions=form['max_redemptions'],
                expires_at=form['expires_at'], note=form['note'])
        except Exception as exc:
            flash(f'Stripe did not create it: {getattr(exc, "user_message", None) or exc}',
                  'error')
            return redirect(here)
        control_plane.add_promo_code(
            engine, stripe_coupon_id=coupon_id, stripe_promotion_id=promo_id,
            created_by=request.console_user['email'], **form)
        control_plane.log_console(engine, request.console_user['email'],
                                  'created discount code', form['code'],
                                  _describe_promo(form))
        flash(f'{form["code"]} is live. Customers type it at checkout.', 'success')
        return redirect(here)

    import entitlements
    import funnel
    rows = control_plane.all_promo_codes(engine)
    used = funnel.sales(control_plane.all_orgs(engine), entitlements.PLANS)['codes']
    redeemed = billing.promo_redemptions()
    for r in rows:
        r['describe'] = _describe_promo(r)
        r['redeemed'] = redeemed.get(r.get('stripe_promotion_id'))
        r['usage'] = used.get(r['code'], {'used': 0, 'paying': 0, 'mrr': 0})
    return render_template('console/discounts.html', rows=rows,
                           may_operate=_may_operate(),
                           stripe_ready=bool(billing.stripe_key()),
                           me=request.console_user, counts=_counts(engine))


@console_bp.route('/discounts/<code>/active', methods=['POST'])
@console_required
def discount_active(code):
    import billing
    engine = _engine()
    here = url_for('console.discounts')
    if not _may_operate():
        return _refuse(here)
    row = control_plane.find_promo_code(engine, code=code)
    turn_on = request.form.get('on') == '1'
    if not row:
        flash('No such code.', 'error')
        return redirect(here)
    try:
        billing.set_promo_code_active(row['stripe_promotion_id'], turn_on)
    except Exception as exc:
        flash(f'Stripe did not change it: {getattr(exc, "user_message", None) or exc}',
              'error')
        return redirect(here)
    control_plane.set_promo_active(engine, row['code'], turn_on)
    control_plane.log_console(engine, request.console_user['email'],
                              'turned on discount code' if turn_on
                              else 'turned off discount code', row['code'])
    flash(f'{row["code"]} is {"on" if turn_on else "off"}. Anybody already using it '
          f'keeps their discount.', 'success')
    return redirect(here)


def _promo_form(form):
    """Read and check the new-code form. Returns (clean values, problem or None)."""
    code = (form.get('code') or '').strip().upper()
    if not PROMO_CODE_RE.match(code):
        return None, 'A code is 3 to 40 letters, numbers, dashes or underscores.'
    out = {'code': code, 'percent_off': None, 'amount_off_cents': None,
           'duration_months': None, 'max_redemptions': None, 'expires_at': None,
           'note': (form.get('note') or '').strip()[:300] or None}
    try:
        if form.get('kind') == 'amount':
            dollars = float(form.get('amount') or 0)
            if not 0 < dollars <= 10000:
                return None, 'A dollar discount is between $0.01 and $10,000.'
            out['amount_off_cents'] = int(round(dollars * 100))
        else:
            pct = int(form.get('percent') or 0)
            if not 1 <= pct <= 100:
                return None, 'A percentage is between 1 and 100.'
            out['percent_off'] = pct
        duration = form.get('duration') or 'once'
        if duration not in ('once', 'repeating', 'forever'):
            return None, 'Pick how long the discount lasts.'
        # A 100%-off code makes the checkout $0 due today, which is why
        # checkout skips asking for a card at all (payment_method_collection
        # is 'if_required' -- see billing.checkout_session). That is only
        # safe for a code that stays 100% off forever: a temporary one lapses
        # into a full-price renewal with no card on file to charge it to.
        if out['percent_off'] == 100 and duration != 'forever':
            return None, ('A 100% discount has to last forever -- a temporary '
                          'one leaves nothing to charge once it ends, because '
                          'no card was ever collected.')
        out['duration'] = duration
        if duration == 'repeating':
            months = int(form.get('months') or 0)
            if not 1 <= months <= 36:
                return None, 'For a number of months, pick between 1 and 36.'
            out['duration_months'] = months
        if (form.get('max_redemptions') or '').strip():
            n = int(form['max_redemptions'])
            if n < 1:
                return None, 'A use limit is at least 1.'
            out['max_redemptions'] = n
        if (form.get('expires') or '').strip():
            ends = datetime.strptime(form['expires'].strip(), '%Y-%m-%d').replace(
                hour=23, minute=59, second=59)
            if ends <= datetime.utcnow():
                return None, 'The expiry date has to be in the future.'
            out['expires_at'] = ends
    except ValueError:
        return None, 'One of the numbers or the date did not read as one.'
    return out, None


def _describe_promo(p):
    off = (f'{p["percent_off"]}% off' if p.get('percent_off')
           else f'${(p.get("amount_off_cents") or 0) / 100:,.2f} off')
    how = {'once': 'the first payment', 'forever': 'every payment',
           'repeating': f'{p.get("duration_months")} months'}.get(p.get('duration'), '')
    return f'{off} {how}'.strip()


@console_bp.route('/leads/<int:lead_id>/contacted', methods=['POST'])
@console_required
def lead_contacted(lead_id):
    engine = _engine()
    if control_plane.mark_lead_contacted(engine, lead_id):
        control_plane.log_console(engine, request.console_user['email'],
                                  'contacted', f'lead #{lead_id}')
    window = request.form.get('window')
    if window:
        return redirect(url_for('console.funnel_view', window=window))
    return redirect(url_for('console.leads_view'))


@console_bp.route('/leads/<int:lead_id>/do-not-text', methods=['POST'])
@console_required
def lead_do_not_text(lead_id):
    """Mark one lead as not to be texted, or allow texting again. Separate
    from the person's own STOP, which only their START undoes."""
    if not _may_operate():
        return _refuse(url_for('console.leads_view'))
    engine = _engine()
    on = request.form.get('on') != '0'
    if control_plane.set_lead_do_not_text(engine, lead_id, on):
        control_plane.log_console(engine, request.console_user['email'],
                                  'marked do not text' if on else 'allowed texts',
                                  f'lead #{lead_id}')
    return redirect(url_for('console.leads_view'))


@console_bp.route('/leads')
@console_required
def leads_view():
    """Every prospect the product knows about -- whether they asked for early
    access themselves or somebody here uploaded them -- in one place to upload
    more, invite them, or mark one as reached."""
    import lead_outreach as lo
    engine = _engine()
    signup_emails = _signup_emails(engine)
    rows = control_plane.all_leads(engine)
    for r in rows:
        r['is_customer'] = bool(r.get('email')) and \
            r['email'].strip().lower() in signup_emails
    email_subject, email_body = lo.default_email()
    return render_template('console/leads.html', rows=rows,
                           can_act=_may_operate(),
                           email_ready=lo.email_ready(),
                           email_from=product.outreach_from_email(),
                           sms_ready=bool(lo.sms_credentials()),
                           sms_closed=lo.quiet_hours(),
                           email_subject=email_subject, email_body=email_body,
                           sms_body=lo.default_text(),
                           email_block=lo.email_block, sms_block=lo.sms_block,
                           history=control_plane.lead_messages(engine, limit=50),
                           me=request.console_user, counts=_counts(engine))


@console_bp.route('/leads/send', methods=['POST'])
@console_required
def leads_send():
    """Email or text the leads ticked on the list, with the message typed in
    the compose box. lead_outreach.py decides who can be reached and how."""
    import lead_outreach as lo
    if not _may_operate():
        return _refuse(url_for('console.leads_view'))
    engine = _engine()
    channel = request.form.get('channel')
    if channel not in ('email', 'sms'):
        flash('Choose email or text.', 'error')
        return redirect(url_for('console.leads_view'))
    ids = {int(i) for i in request.form.getlist('lead_id') if i.isdigit()}
    leads = [l for l in control_plane.all_leads(engine) if l['id'] in ids]
    if not leads:
        flash('Tick at least one lead to send to.', 'error')
        return redirect(url_for('console.leads_view'))
    body = (request.form.get('body') or '').strip()
    if not body:
        flash('Write the message first.', 'error')
        return redirect(url_for('console.leads_view'))
    me = request.console_user['email']
    result = lo.send_many(engine, leads, channel, request.form.get('subject', ''),
                          body, me)
    word = 'email' if channel == 'email' else 'text'
    control_plane.log_console(engine, me, f'sent {word}s',
                              f'{result["sent"]} lead(s)',
                              f'{result["failed"]} failed' if result['failed'] else None)
    msg = f'Sent {result["sent"]} {word}{"s" if result["sent"] != 1 else ""}.'
    if result['failed']:
        msg += f' {result["failed"]} failed -- see Recent outreach below for why.'
    for reason, n in result['skipped'].items():
        msg += f' Skipped {n}: {reason}.'
    flash(msg, 'success' if result['sent'] and not result['failed'] else
          ('warning' if result['sent'] else 'error'))
    return redirect(url_for('console.leads_view'))


# Matched case-insensitively against a CSV's header row. Extra columns in the
# file are ignored rather than refused -- an export from a spreadsheet a
# prospect list was built in almost always carries more than this needs.
LEAD_CSV_COLUMNS = ('name', 'company', 'email', 'phone', 'cleaners', 'note')
# An optional column marking single rows "do not text" -- what a list checked
# against the Do Not Call registry usually carries. Anything but blank or an
# explicit no counts, so "yes", "x", "DNC" and "1" all do.
DO_NOT_TEXT_COLUMNS = ('do_not_text', 'do not text', 'dnc')
_NO = ('', '0', 'no', 'n', 'false', 'f')


@console_bp.route('/leads/upload', methods=['POST'])
@console_required
def leads_upload():
    """Add a list of prospects from a CSV, for outreach rather than something
    they filled in themselves -- see product_leads.source below."""
    if not _may_operate():
        return _refuse(url_for('console.leads_view'))
    engine = _engine()
    file = request.files.get('file')
    if not file or not file.filename:
        flash('Choose a CSV file first.', 'error')
        return redirect(url_for('console.leads_view'))

    import csv
    import io
    try:
        text = file.read().decode('utf-8-sig', errors='replace')
    except Exception:
        flash('Could not read that file as text.', 'error')
        return redirect(url_for('console.leads_view'))

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        flash('That file has no header row.', 'error')
        return redirect(url_for('console.leads_view'))
    # Case-insensitive, so "Email" and "email" both find the column.
    by_lower = {(h or '').strip().lower(): h for h in reader.fieldnames}

    # The box on the form marks the whole file; the column marks single rows.
    whole_file = request.form.get('do_not_text') == '1'
    dnt_col = next((by_lower[c] for c in DO_NOT_TEXT_COLUMNS if c in by_lower), None)

    import notifications
    added = skipped = already = flagged = failed = 0
    for row in reader:
        email = (row.get(by_lower.get('email', ''), '') or '').strip().lower()
        phone = (row.get(by_lower.get('phone', ''), '') or '').strip()
        # notifications.looks_like_email, not just "has an @": "person@example"
        # passes a bare '@' check and then bounces at Resend. A lead is still
        # contactable by phone with a bad email in the column, but an address
        # good enough to store has to be good enough to actually send to.
        email_ok = notifications.looks_like_email(email)
        # A prospect is contactable if either channel exists. Email is still
        # required for the email-invite action, but not for being a lead.
        if not email_ok and not phone:
            skipped += 1
            continue
        fields = {col: (row.get(by_lower[col], '') or '').strip()
                  for col in LEAD_CSV_COLUMNS if col in by_lower}
        fields['email'] = email if email_ok else ''
        fields['phone'] = phone
        fields['source'] = 'console upload'
        no_text = whole_file or (
            dnt_col is not None
            and (row.get(dnt_col, '') or '').strip().lower() not in _NO)
        result = control_plane.add_lead(engine, do_not_text=no_text, **fields)
        if result is None:
            # Nothing was written -- not the row, and not the mark. Saying
            # "marked do not text" here would be a promise nobody kept.
            failed += 1
            continue
        if result:
            added += 1
        else:
            already += 1
        flagged += bool(no_text)

    control_plane.log_console(engine, request.console_user['email'],
                              'uploaded', f'{added} lead(s)',
                              ', '.join(x for x in (
                                  f'{skipped + already} skipped' if skipped + already else '',
                                  f'{flagged} do not text' if flagged else '',
                                  f'{failed} failed' if failed else '') if x) or None)
    msg = f'Added {added} lead{"s" if added != 1 else ""}.'
    if skipped:
        msg += (f' Skipped {skipped} row{"s" if skipped != 1 else ""} '
                f'with no usable email or phone.')
    if already:
        msg += (f' {already} {"were" if already != 1 else "was"} already on the list '
                f'and not added again.')
    if flagged:
        msg += (f' Marked {flagged} as do not text -- '
                f'{"they" if flagged != 1 else "it"} can be emailed but not texted.')
    if failed:
        msg += (f' {failed} row{"s" if failed != 1 else ""} could not be saved, '
                f'and {"were" if failed != 1 else "was"} not marked either -- upload '
                f'the file again.')
    flash(msg, 'error' if failed else ('success' if added else 'warning'))
    return redirect(url_for('console.leads_view'))


def _signup_emails(engine):
    """Every real (non-test) company's owner email, lower-cased -- the same
    set funnel.py uses to say a lead has already converted. A lead whose
    address is already on this list has an account; inviting them to sign up
    again is noise, not outreach."""
    return {(o.get('owner_email') or '').strip().lower()
            for o in control_plane.all_orgs(engine)
            if o.get('owner_email') and not o.get('is_test')}


def _send_lead_invite(lead, sent_by='console'):
    """Ask this prospect to try the product. Returns (ok, detail).

    The standard invite, sent through lead_outreach like any other console
    email: as the product, never as a cleaning company (see trial_nudges._send
    for why), with an unsubscribe link and the postal address, never to an
    address that has unsubscribed, and written into the outreach history. The
    link is tagged so a signup through it counts under its own channel on the
    Funnel (see attribution.py)."""
    import lead_outreach as lo
    subject, body = lo.default_email()
    return lo.send_email(_engine(), lead, subject, body, sent_by)


@console_bp.route('/leads/<int:lead_id>/invite', methods=['POST'])
@console_required
def lead_invite(lead_id):
    if not _may_operate():
        return _refuse(url_for('console.leads_view'))
    engine = _engine()
    lead = next((l for l in control_plane.all_leads(engine)
                if l['id'] == lead_id), None)
    if not lead:
        flash('That lead no longer exists.', 'error')
        return redirect(url_for('console.leads_view'))
    if (lead.get('email') or '').strip().lower() in _signup_emails(engine):
        flash(f'{lead.get("email")} already has an account -- not inviting '
              f'them to sign up again.', 'warning')
        return redirect(url_for('console.leads_view'))
    # Claim before sending, not after: claiming after the email is already
    # out cannot stop a second click (or a concurrent "invite all") from
    # sending a second one while this request is still in flight.
    if not control_plane.mark_lead_invited(engine, lead_id):
        flash('Already invited.', 'warning')
        return redirect(url_for('console.leads_view'))
    ok, detail = _send_lead_invite(lead, request.console_user['email'])
    if ok:
        control_plane.log_console(engine, request.console_user['email'],
                                  'invited', lead.get('email') or f'lead #{lead_id}')
        flash(f'Invited {lead.get("email")}.', 'success')
    else:
        control_plane.unmark_lead_invited(engine, lead_id)
        flash(f'Could not send that invite: {detail}', 'error')
    return redirect(url_for('console.leads_view'))


@console_bp.route('/leads/invite-all', methods=['POST'])
@console_required
def lead_invite_all():
    """Everybody on the list who has never been sent one, in one press --
    uploading a list of a hundred prospects to click a hundred times is not a
    feature."""
    if not _may_operate():
        return _refuse(url_for('console.leads_view'))
    engine = _engine()
    signup_emails = _signup_emails(engine)
    due = [l for l in control_plane.all_leads(engine)
           if not l.get('invited_at') and l.get('email') and not l.get('unsubscribed_at')
           and (l.get('email') or '').strip().lower() not in signup_emails]
    sent = failed = 0
    for lead in due:
        # Claimed here, one row at a time, so a second "invite all" (or a
        # single invite) running at the same moment skips whatever this one
        # already claimed instead of sending it twice.
        if not control_plane.mark_lead_invited(engine, lead['id']):
            continue
        ok, _detail = _send_lead_invite(lead, request.console_user['email'])
        if ok:
            sent += 1
        else:
            control_plane.unmark_lead_invited(engine, lead['id'])
            failed += 1
    control_plane.log_console(engine, request.console_user['email'],
                              'invited', f'{sent} lead(s)',
                              f'{failed} failed' if failed else None)
    msg = f'Invited {sent} lead{"s" if sent != 1 else ""}.'
    if failed:
        msg += f' {failed} failed to send.'
    flash(msg, 'success' if sent else 'warning')
    return redirect(url_for('console.leads_view'))


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


@console_bp.route('/nana')
@console_required
def nana_proposals():
    """Where Nana's offers actually land, across every company at once.

    Everything she can change -- marking a job finished, sending outreach,
    turning on the morning digest -- is written down as an AssistantProposal
    before anybody presses anything (see proposals.py). That makes it exist
    per tenant, under that tenant's own schema, with no cross-company view
    of it anywhere. A one-off "has anyone asked about X" is a database
    query away for whoever holds the URL; this is the standing answer, so
    the next capability that ships does not need its own investigation.

    Reads each tenant under its own schema via tenancy.use_tenant -- the
    same boundary every tenant-scoped read in this app goes through, so
    seeing across companies here does not mean weakening the wall between
    them. A schema that fails to read (never migrated, mid-provisioning) is
    skipped rather than failing the whole page: one company's row count is
    not worth the rest going blank.

    db.session.remove() between companies is not tidiness -- it is the fix
    for a real bug this page hit in testing. Every tenant's AssistantProposal
    table starts its own id sequence at 1, and without clearing the ORM
    session between schemas, SQLAlchemy's identity map served the *first*
    company's cached row back for every later company sharing that same id,
    silently relabelling one company's proposal as another's and dropping
    the row it should have shown instead. The SQL sent to Postgres was
    always scoped correctly; the leak was in the Python object cache sitting
    in front of it.
    """
    import console_data
    import tenancy
    from extensions import db
    from models import AssistantProposal
    engine = _engine()
    # schema_ready: without it a company with no schema is read from `public`
    # and somebody else's proposals are shown under its name.
    orgs = [o for o in control_plane.all_orgs(engine) if o.get('status') != 'closed'
            and console_data.schema_ready(o['slug'])]

    rows = []
    by_action = {}
    for org in orgs:
        # Clear the identity map before every switch, not only after a
        # failure -- the collision above happens on the successful path.
        db.session.remove()
        try:
            with tenancy.use_tenant(org['slug']):
                proposals = AssistantProposal.query.order_by(
                    AssistantProposal.created_at.desc()).limit(100).all()
        except Exception:
            db.session.rollback()
            continue
        for p in proposals:
            rows.append({
                'company': org.get('name') or org['slug'], 'slug': org['slug'],
                'action': p.action, 'summary': p.summary,
                'asked_by': p.asked_by, 'created_at': p.created_at,
                'pressed': p.used_at is not None, 'used_at': p.used_at,
                'outcome': p.outcome,
            })
            stat = by_action.setdefault(p.action, {'offered': 0, 'pressed': 0})
            stat['offered'] += 1
            if p.used_at is not None:
                stat['pressed'] += 1

    rows.sort(key=lambda r: r['created_at'], reverse=True)
    return render_template('console/nana.html', rows=rows[:300],
                           by_action=sorted(by_action.items()),
                           me=request.console_user, counts=_counts(engine))


@console_bp.route('/playbooks')
@console_required
def playbooks():
    """Reference material for the product -- growth plans, launch runbooks,
    anything that used to live as a link pasted into somebody's inbox."""
    engine = _engine()
    return render_template('console/playbooks.html',
                           rows=control_plane.all_console_docs(engine),
                           can_edit=control_plane.rank(request.console_user['role'])
                                     >= control_plane.rank('manager'),
                           me=request.console_user, counts=_counts(engine))


# A step somebody ticks off: "[ ]" or "[x]" at the start of a line, on its own
# or after a list marker ("- [ ] Call Dana", "1. [x] Lock the offer").
_TASK_LINE = re.compile(r'^(\s*(?:(?:[-*+]|\d+\.)\s+)?)\[( |x|X)\](?=\s)', re.M)
# The same steps once Markdown has turned them into HTML: at the start of a
# list item, a paragraph, or a line after a <br> (nl2br).
_TASK_HTML = re.compile(r'(<li>\n<p>|<li>|<p>|<br />\n)\[( |x|X)\](?=\s)')


def _render_playbook(content, tickable=False):
    """Playbook content to HTML -- tables, headings, bold, lists, checkboxes.

    Escaped before Markdown ever sees it, so a literal `<` typed or pasted
    into a playbook (an HTML tag, a stray `<script>`) renders as text rather
    than running in every other console user's browser. Markdown's own
    syntax (`**`, `|`, `#`, `-`) uses none of the characters escape() touches,
    so real Markdown still renders -- only raw HTML stops working, which a
    playbook was never written in anyway.

    A step written "[ ]" or "[x]" becomes a checkbox. Each box carries its
    position among the steps in the text, which is how a tick finds its way
    back to the right line (see playbook_task). If the boxes found in the HTML
    and the steps found in the text ever disagree in number, the boxes are
    shown but cannot be ticked: a tick landing on the wrong step is worse
    than no tick."""
    escaped = html.escape(content)
    out = markdown.markdown(escaped, extensions=['tables', 'nl2br'])
    # Inside `code`, Markdown escapes the escape: a link's "&" came out as
    # the literal text "&amp;". Undo only that second layer -- what is left
    # is still an escaped entity, so nothing becomes markup.
    out = re.sub(r'&amp;(amp|lt|gt|quot|#x27);', r'&\1;', out)
    found = list(_TASK_HTML.finditer(out))
    usable = tickable and len(found) == len(_TASK_LINE.findall(content))
    position = iter(range(len(found)))

    def box(m):
        i, done = next(position), m.group(2) in 'xX'
        attrs = (f' data-task="{i}"' if usable else ' disabled') + (' checked' if done else '')
        tag = f'<input type="checkbox" class="pb-box" aria-label="Done"{attrs}>'
        if m.group(1).startswith('<li>'):
            # A loose list wraps the item's text in <p>; keep it, class the <li>.
            return f'<li class="pb-task{" done" if done else ""}">{m.group(1)[4:]}{tag}'
        return f'{m.group(1)}{tag}'

    return _TASK_HTML.sub(box, out)


def _set_task(content, index, done):
    """The content with step number `index` ticked or unticked, or None."""
    for i, m in enumerate(_TASK_LINE.finditer(content)):
        if i == index:
            start = m.end() - 2              # the character between [ and ]
            return content[:start] + ('x' if done else ' ') + content[start + 1:]
    return None


def _playbook_rev(doc):
    """Which version of a playbook a page was showing, so a tick made on a
    page that is out of date is refused instead of landing on a moved line."""
    when = doc.get('updated_at') or doc.get('created_at')
    return when.isoformat() if when else ''


@console_bp.route('/playbooks/<int:doc_id>')
@console_required
def playbook_view(doc_id):
    engine = _engine()
    doc = control_plane.console_doc(engine, doc_id)
    if not doc:
        flash('No such playbook.', 'error')
        return redirect(url_for('console.playbooks'))
    can_edit = (control_plane.rank(request.console_user['role'])
                >= control_plane.rank('manager'))
    return render_template('console/playbook_view.html', doc=doc,
                           content_html=_render_playbook(doc['content'],
                                                         tickable=can_edit),
                           rev=_playbook_rev(doc), can_edit=can_edit,
                           me=request.console_user, counts=_counts(engine))


@console_bp.route('/playbooks/<int:doc_id>/task', methods=['POST'])
@console_required
def playbook_task(doc_id):
    """Tick or untick one step. Saved in the playbook, so everybody sees it.

    Ticking changes the playbook's text, so it takes the same rank as editing
    it. The page sends the version it was showing; if the playbook has been
    edited since, the tick is refused and the page asks to be reloaded.
    """
    from flask import jsonify
    if control_plane.rank(request.console_user['role']) < control_plane.rank('manager'):
        return jsonify(ok=False, error='Only a manager or the owner can tick steps.'), 403
    engine = _engine()
    doc = control_plane.console_doc(engine, doc_id)
    if not doc:
        return jsonify(ok=False, error='No such playbook.'), 404
    if (request.form.get('rev') or '') != _playbook_rev(doc):
        return jsonify(ok=False, error='This playbook changed since the page loaded. '
                                       'Reload the page and tick it again.'), 409
    try:
        index = int(request.form.get('index', ''))
    except ValueError:
        index = -1
    done = request.form.get('done') == '1'
    content = _set_task(doc['content'], index, done) if index >= 0 else None
    if content is None:
        return jsonify(ok=False, error='That step is not in this playbook.'), 400
    if content != doc['content']:
        control_plane.update_console_doc(engine, doc_id, doc['title'], content)
        control_plane.log_console(engine, request.console_user['email'],
                                  'ticked a step' if done else 'unticked a step',
                                  doc['title'], f'step {index + 1}')
    return jsonify(ok=True, rev=_playbook_rev(control_plane.console_doc(engine, doc_id)))


@console_bp.route('/playbooks/new', methods=['GET', 'POST'])
@console_required
@can_manage
def playbook_new():
    engine = _engine()
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        content = (request.form.get('content') or '').strip()
        if not title or not content:
            flash('A title and some content, please.', 'error')
            return redirect(url_for('console.playbook_new'))
        doc_id = control_plane.add_console_doc(
            engine, title, content, created_by=request.console_user['email'])
        control_plane.log_console(engine, request.console_user['email'],
                                  'added playbook', title)
        flash('Saved.', 'success')
        return redirect(url_for('console.playbook_view', doc_id=doc_id))
    return render_template('console/playbook_form.html', doc=None,
                           me=request.console_user, counts=_counts(engine))


@console_bp.route('/playbooks/<int:doc_id>/edit', methods=['GET', 'POST'])
@console_required
@can_manage
def playbook_edit(doc_id):
    engine = _engine()
    doc = control_plane.console_doc(engine, doc_id)
    if not doc:
        flash('No such playbook.', 'error')
        return redirect(url_for('console.playbooks'))
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        content = (request.form.get('content') or '').strip()
        if not title or not content:
            flash('A title and some content, please.', 'error')
            return redirect(url_for('console.playbook_edit', doc_id=doc_id))
        control_plane.update_console_doc(engine, doc_id, title, content)
        control_plane.log_console(engine, request.console_user['email'],
                                  'edited playbook', title)
        flash('Saved.', 'success')
        return redirect(url_for('console.playbook_view', doc_id=doc_id))
    return render_template('console/playbook_form.html', doc=doc,
                           me=request.console_user, counts=_counts(engine))


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
            'support': control_plane.unanswered_support(engine),
            'leads': control_plane.new_leads_count(engine)}


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
