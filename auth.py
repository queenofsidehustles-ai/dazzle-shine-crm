import os
from functools import wraps
from datetime import datetime
from flask import session, redirect, url_for, flash


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated


def owner_required(f):
    """Guards the money pages (payroll, contractor pay, reports, settings) so
    only an Owner can open them — even by typing the URL directly.
    Legacy sessions (logged in before roles existed) default to 'owner', since
    the single shared login was always the owner."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin.login'))
        if session.get('role', 'owner') != 'owner':
            flash('That area is owner-only.', 'error')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated


# Passwords that are not passwords. A deployment left with any of these is
# effectively open, so the built-in login refuses to work at all rather than
# quietly accepting them.
_WEAK = {'changeme', 'password', 'admin', 'admin123', '123456', 'letmein', ''}


def env_login_configured():
    """True only when this deployment has been given a real owner login.

    The built-in login used to fall back to admin/changeme whenever the
    environment variables were missing. On a single hand-configured server that
    was merely untidy. Once the same code runs a second company's business it is
    a guessable way into their customer list and their payment settings, so an
    unconfigured deployment now has no built-in login at all."""
    user = (os.environ.get('ADMIN_USER') or '').strip()
    pw = (os.environ.get('ADMIN_PASS') or '').strip()
    return bool(user) and pw.lower() not in _WEAK


def authenticate(username, password):
    """Check a login attempt. Returns (ok, info) where info holds user_id, role
    and name. Tries real user accounts first, then the env owner login."""
    from models import User
    from extensions import db
    uname = (username or '').strip().lower()
    user = User.query.filter_by(username=uname, active=True).first()
    if user and user.check_password(password or ''):
        user.last_login = datetime.utcnow()
        db.session.commit()
        return True, {'user_id': user.id, 'role': user.role, 'name': user.name}
    # The deployment's own owner login, from the environment. Only honoured
    # when it has actually been set to something — never a default.
    if env_login_configured():
        if (username == os.environ.get('ADMIN_USER', '').strip()
                and password == (os.environ.get('ADMIN_PASS') or '')):
            return True, {'user_id': None, 'role': 'owner', 'name': 'Owner'}
    return False, None


def check_credentials(username, password):
    """Backward-compatible env-only check (kept for any legacy callers)."""
    if not env_login_configured():
        return False
    return (
        username == os.environ.get('ADMIN_USER', '').strip() and
        password == (os.environ.get('ADMIN_PASS') or '')
    )
