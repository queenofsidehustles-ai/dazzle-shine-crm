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
    # Fallback: Monica's original env-based login — always treated as owner.
    if (username == os.environ.get('ADMIN_USER', 'admin') and
            password == os.environ.get('ADMIN_PASS', 'changeme')):
        return True, {'user_id': None, 'role': 'owner', 'name': 'Owner'}
    return False, None


def check_credentials(username, password):
    """Backward-compatible env-only check (kept for any legacy callers)."""
    return (
        username == os.environ.get('ADMIN_USER', 'admin') and
        password == os.environ.get('ADMIN_PASS', 'changeme')
    )
