import json
from flask import Blueprint, render_template, request, session, redirect, url_for
from entitlements import requires_plan
from auth import login_required, owner_required, authenticate, is_owner_session
from models import Booking, Client, Lead
from extensions import db
from sqlalchemy import func
from datetime import datetime, date, timedelta

import finance

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/version')
def version():
    """Which build this instance is running, and which release channel it
    follows. Deliberately public and deliberately boring, so 'did the deploy
    land?' can be answered from a phone, from a browser that is not logged in,
    or by whoever is standing up the next white-label instance.

    channel 'stable' is a customer instance, which only moves when a release is
    promoted. 'main' is this business's own, which moves on every push.
    """
    import branding, os
    from flask import current_app
    out = {'build': branding.version(),
           'channel': branding.release_channel(),
           'release': branding.release_tag()}

    # Which engine is actually in use, and a plain warning when that is the one
    # combination that cannot work. This is here rather than only in the deploy
    # log because a deploy log is somewhere you have to know to look, and this
    # is a URL you can open on a phone.
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    out['db'] = uri.split(':', 1)[0].split('+')[0] or 'unknown'
    if out['db'] == 'sqlite' and (os.environ.get('BASE_DOMAIN') or '').strip():
        out['problem'] = ('DATABASE_URL is not set. Running on SQLite, so no '
                          'company can be signed up and nothing survives a '
                          'restart. Point DATABASE_URL at the Postgres.')

    # Whether the product itself can email anybody — trial reminders, and the
    # alert that says a customer's CRM just broke. Both fail silently by
    # nature: nobody notices an email that was never sent, and the crash alert
    # is the one thing whose whole job is to be noticed.
    try:
        import product
        mail = product.mail_status()
        if mail['applies']:
            out['product_mail'] = 'ok' if not mail['problem'] else 'not configured'
            if mail['problem']:
                # Under its own key as well as the headline. A missing
                # DATABASE_URL is more urgent and wins `problem`, but it must
                # not hide this one — two faults at once is exactly when a
                # deployment is being set up, and exactly when both matter.
                out['product_mail_problem'] = mail['problem']
                out.setdefault('problem', mail['problem'])
    except Exception:
        pass
    return out


def _daily_plan():
    """The day's list must never be the reason the dashboard fails to load."""
    try:
        import daily_plan
        return daily_plan.summary()
    except Exception:
        return {'items': [], 'nothing': False, 'say': None}


def _by_start_time(jobs):
    """A day's jobs in the order they happen. The time is free text ("9am",
    "between 1 and 3"); anything that cannot be read goes last, not first."""
    from scheduling import parse_time
    def key(b):
        t = parse_time(b.preferred_time or '')
        return (t is None, t or (0, 0), b.id)
    return sorted(jobs, key=key)


@admin_bp.route('/')
@login_required
def dashboard():
    today = date.today().isoformat()
    total_bookings = Booking.query.count()
    pending = Booking.query.filter_by(status='pending').count()
    confirmed = Booking.query.filter_by(status='confirmed').count()
    completed = Booking.query.filter_by(status='completed').count()
    total_clients = Client.query.count()
    today_bookings = _by_start_time(Booking.query.filter_by(preferred_date=today).all())
    import recurring
    # Collapse recurring plans BEFORE trimming — otherwise all eight rows
    # are the same client's next twelve months.
    recent = recurring.collapse(
        Booking.query.order_by(Booking.created_at.desc()).limit(300).all())[:8]

    # This month's money, cash basis — only the owner sees the money tiles.
    money = None
    if is_owner_session():
        d = date.today()
        start, end = finance.month_bounds(d.year, d.month)
        money = finance.profit_and_loss(start, end)

    # The things a dashboard is actually for: what is happening today, and what
    # will go wrong tomorrow if nobody touches it. A wall of totals tells an
    # owner how the month went; it does not tell her that nobody is booked for
    # the 9am.
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    tomorrow_jobs = Booking.query.filter(
        Booking.preferred_date == tomorrow,
        Booking.status.in_(['confirmed', 'pending'])).all()
    tomorrow_jobs = _by_start_time(tomorrow_jobs)
    unassigned_tomorrow = [b for b in tomorrow_jobs if b.needs_cleaner]
    # Everything ahead, not only tomorrow. A job three days out with nobody on
    # it is the same problem noticed earlier — and this dashboard would say
    # nothing about it until the night before, which is the point at which
    # finding somebody is hardest.
    unassigned_soon = [b for b in Booking.query.filter(
        Booking.preferred_date > tomorrow,
        Booking.status.in_(['confirmed', 'pending'])).order_by(
            Booking.preferred_date).all() if b.needs_cleaner]
    unpaid_done = Booking.query.filter(
        Booking.status == 'completed',
        Booking.balance_collected.is_(False)).count()
    open_claims = Booking.query.filter(
        Booking.open_for_claim.is_(True),
        Booking.status.in_(['confirmed', 'pending'])).count()

    return render_template(
        'admin/dashboard.html',
        plan=_daily_plan(),
        tomorrow_jobs=tomorrow_jobs,
        unassigned_tomorrow=unassigned_tomorrow,
        unassigned_soon=unassigned_soon,
        unpaid_done=unpaid_done,
        open_claims=open_claims,
        total_bookings=total_bookings,
        pending=pending,
        confirmed=confirmed,
        completed=completed,
        total_clients=total_clients,
        today_bookings=today_bookings,
        recent=recent,
        money=money,
        this_month=date.today().strftime('%B'),
    )


@admin_bp.route('/reports')
@owner_required
@requires_plan('reports')
def reports():
    today = date.today()

    # Revenue is CASH BASIS everywhere — counted on the day payment landed, not
    # the day the job was booked. See finance.py for why that change was made.
    monthly_data = []
    for i in range(5, -1, -1):
        year, month = today.year, today.month - i
        while month <= 0:
            month += 12
            year -= 1
        m_start, m_end = finance.month_bounds(year, month)
        monthly_data.append({'month': m_start.strftime('%b %Y'),
                             'revenue': finance.revenue_between(m_start, m_end)})

    this_start, this_end = finance.month_bounds(today.year, today.month)
    ly, lm = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    last_start, last_end = finance.month_bounds(ly, lm)

    revenue_this_month = finance.revenue_between(this_start, this_end)
    revenue_last_month = finance.revenue_between(last_start, last_end)
    revenue_ytd = finance.revenue_between(date(today.year, 1, 1), today)
    profit_this_month = finance.profit_and_loss(this_start, this_end)['net_profit']
    profit_ytd = finance.profit_and_loss(date(today.year, 1, 1), today)['net_profit']

    this_month_start = datetime(today.year, today.month, 1)

    balance_outstanding = db.session.query(func.sum(Booking.balance_due)).filter(
        Booking.balance_collected == False,
        Booking.status.in_(['confirmed', 'completed', 'pending']),
    ).scalar() or 0

    deposits_collected = db.session.query(func.count(Booking.id)).filter(
        Booking.deposit_paid == True,
    ).scalar() or 0

    # Top services
    service_rows = db.session.query(
        Booking.service_type,
        func.count(Booking.id).label('jobs'),
        func.sum(Booking.price).label('revenue'),
    ).filter(Booking.status.in_(['completed', 'confirmed'])).group_by(Booking.service_type).all()

    service_data = sorted([
        {'type': Booking.SERVICE_LABELS.get(r.service_type, r.service_type.title()),
         'jobs': r.jobs, 'revenue': round(float(r.revenue or 0), 2)}
        for r in service_rows
    ], key=lambda x: x['revenue'], reverse=True)

    # Leads funnel
    leads_total = Lead.query.count()
    leads_converted = Lead.query.filter_by(status='converted').count()
    leads_this_month = Lead.query.filter(Lead.created_at >= this_month_start).count()
    conversion_rate = round(leads_converted / leads_total * 100, 1) if leads_total else 0

    # Upcoming 14 days
    today_str = today.isoformat()
    end_str = (today + timedelta(days=14)).isoformat()
    upcoming = Booking.query.filter(
        Booking.preferred_date >= today_str,
        Booking.preferred_date <= end_str,
        Booking.status.in_(['confirmed', 'pending']),
    ).order_by(Booking.preferred_date).all()

    return render_template('admin/reports.html',
        monthly_labels=json.dumps([d['month'] for d in monthly_data]),
        monthly_values=json.dumps([d['revenue'] for d in monthly_data]),
        revenue_this_month=revenue_this_month,
        revenue_last_month=revenue_last_month,
        revenue_ytd=revenue_ytd,
        profit_this_month=profit_this_month,
        profit_ytd=profit_ytd,
        balance_outstanding=round(float(balance_outstanding), 2),
        deposits_collected=deposits_collected,
        service_data=service_data,
        leads_total=leads_total,
        leads_converted=leads_converted,
        leads_this_month=leads_this_month,
        conversion_rate=conversion_rate,
        upcoming=upcoming,
    )


PENDING_2FA_KEY = 'pending_2fa_user_id'


@admin_bp.route('/demo-enter')
def demo_enter():
    """Credential-free entry exists only for the explicitly isolated demo.

    No password is embedded in a public page. The server resolves the seeded
    demo owner inside the demo tenant, binds an ordinary tenant session, then
    redirects to the chosen read/write product surface. demo_guard is the
    authorization boundary; a copied URL on any real tenant is a 404.
    """
    import demo_guard
    if not demo_guard.active():
        abort(404)
    from models import User
    from auth import bind_authenticated_session
    owner = User.query.filter_by(role='owner', active=True).first()
    if not owner:
        abort(503)
    bind_authenticated_session(owner)
    session.permanent = True
    destinations = {
        'today': 'admin.dashboard',
        'customer': 'admin.clients',
        'team': 'team.team',
        'money': 'money.money',
        'explore': 'admin.dashboard',
    }
    endpoint = destinations.get((request.args.get('tour') or 'explore').lower(),
                                'admin.dashboard')
    try:
        return redirect(url_for(endpoint))
    except Exception:
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    # The product's root domain never reaches this view for /login at all --
    # marketing.install()'s _front_door() before_request hook already
    # redirects it to marketing.workspace() before any blueprint route
    # would run, since there is no tenant here to check a password against.
    # See marketing.workspace() for "which company" routing, cookie and all.
    import security
    error = None

    if request.method == 'POST' and 'totp_code' in request.form:
        return _login_2fa_step()

    if request.method == 'POST':
        # A fresh username/password attempt abandons any earlier pending 2FA
        # step -- switching accounts, or trying again, must not leave a stale
        # "which user was mid-code-entry" marker sitting in the session.
        session.pop(PENDING_2FA_KEY, None)
        # Guessing at the password is now something that has to be done slowly.
        # The wait is by address, not by account: locking the *account* would
        # let a stranger shut the owner out of her own business by typing her
        # username wrong ten times.
        blocked, mins = security.login_blocked()
        if blocked:
            error = (f'Too many failed sign-ins. Please wait about {mins} '
                     f'minute{"s" if mins != 1 else ""} and try again.')
        else:
            username = request.form.get('username', '')
            ok, info = authenticate(username, request.form.get('password', ''))
            security.record_login(username, ok)
            if ok is True:
                session.permanent = True
                session['logged_in'] = True
                session['role'] = info['role']
                session['user_id'] = info['user_id']
                session['user_name'] = info['name']
                return redirect(url_for('admin.dashboard'))
            if ok == '2fa':
                session[PENDING_2FA_KEY] = info['user_id']
                return render_template('admin/login_2fa.html', error=None)
            error = 'Wrong username or password.'
    # A freshly deployed instance with no owner login and no accounts can't be
    # opened by anybody. Say so plainly rather than leaving someone guessing.
    from auth import env_login_configured, _hosted_multitenant
    from models import User
    not_set_up = not env_login_configured() and User.query.count() == 0
    switch_company_url = None
    if _hosted_multitenant():
        # marketing.workspace() only ever answers on the product's own root
        # domain (_require_product_site() 404s everywhere else), so this has
        # to be an absolute link -- a relative one would try to load it on
        # this tenant's own subdomain instead.
        import product
        root = product.domain()
        switch_company_url = f'{product.scheme_for(root)}://{root}/workspace?forget=1'
    return render_template('admin/login.html', error=error, not_set_up=not_set_up,
                           switch_company_url=switch_company_url)


def _login_2fa_step():
    """The second step of a 2FA-required login: a live TOTP code, or one of
    the account's backup codes. The password was already checked in step
    one -- this only ever runs with session[PENDING_2FA_KEY] already set to a
    user this app itself verified the password for a moment ago.

    Throttled the same way and for the same reason as the password step: a
    six-digit code is guessable in bulk without a lockout, so a wrong one
    counts against the same per-IP window as a wrong password.
    """
    import security, totp
    from extensions import db
    from models import User
    from auth import complete_2fa_login

    user_id = session.get(PENDING_2FA_KEY)
    user = User.query.get(user_id) if user_id else None
    if not user or not user.totp_enabled:
        session.pop(PENDING_2FA_KEY, None)
        return redirect(url_for('admin.login'))

    blocked, mins = security.login_blocked()
    if blocked:
        error = (f'Too many failed sign-ins. Please wait about {mins} '
                 f'minute{"s" if mins != 1 else ""} and try again.')
        return render_template('admin/login_2fa.html', error=error)

    code = request.form.get('totp_code', '')
    ok = totp.verify_totp(user.totp_secret, code)
    if not ok:
        remaining = totp.consume_backup_code(user.totp_backup_codes, code)
        if remaining is not None:
            user.totp_backup_codes = remaining
            db.session.commit()
            ok = True
    security.record_login(user.username, ok)
    if not ok:
        return render_template('admin/login_2fa.html', error='Wrong code. Try again.')

    session.pop(PENDING_2FA_KEY, None)
    info = complete_2fa_login(user)
    session.permanent = True
    session['logged_in'] = True
    session['role'] = info['role']
    session['user_id'] = info['user_id']
    session['user_name'] = info['name']
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('admin.login'))
