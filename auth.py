import os
from functools import wraps
from datetime import datetime
from flask import session, redirect, url_for, flash, g


def _hosted_multitenant():
    """Whether one deployment is serving multiple companies by subdomain."""
    return bool((os.environ.get('BASE_DOMAIN') or '').strip())


def current_tenant_slug():
    """Tenant resolved from the current request host, or None outside a tenant."""
    return getattr(g, 'tenant_slug', None)


def bind_session_to_current_tenant():
    """Bind a newly authenticated session to exactly one tenant host.

    Flask's signed session proves that *we* issued the cookie, not which tenant
    issued it. Without this binding, somebody who owns a valid session for
    tenant A can replay that same signed cookie manually against tenant B and
    login_required() would accept it there. Host-only browser cookies reduce
    accidental crossover, but they are not an authorization boundary.
    """
    slug = current_tenant_slug()
    if _hosted_multitenant() and not slug:
        raise RuntimeError('refusing to create a CRM session outside a tenant host')
    session['tenant_slug'] = slug


def session_matches_current_tenant():
    """True only when the authenticated session belongs to this request tenant.

    Single-business deployments have no tenant subdomain and keep their legacy
    session behavior. Hosted Akye sessions fail closed if the binding is
    missing, stale, or replayed against another company's host.
    """
    if not session.get('logged_in'):
        return False
    if not _hosted_multitenant():
        return True
    slug = current_tenant_slug()
    return bool(slug) and session.get('tenant_slug') == slug


def _reject_wrong_tenant_session():
    """Discard only the cookie presented to the wrong host and require login."""
    session.clear()
    return redirect(url_for('admin.login'))


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin.login'))
        if not session_matches_current_tenant():
            return _reject_wrong_tenant_session()
        return f(*args, **kwargs)
    return decorated


def is_owner_session():
    """True only for this tenant's authenticated session explicitly marked owner.

    Authorization fails closed. A stale signed session created before roles or
    tenant binding existed must not gain owner authority merely because fields
    are missing.
    """
    return session_matches_current_tenant() and session.get('role') == 'owner'


def owner_required(f):
    """Guard owner-only pages such as payroll, reports and settings."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin.login'))
        if not session_matches_current_tenant():
            return _reject_wrong_tenant_session()
        if not is_owner_session():
            flash('That area is owner-only.', 'error')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated


# Passwords that are not passwords. A deployment left with any of these is
# effectively open, so the built-in login refuses to work at all rather than
# quietly accepting them.
_WEAK = {'changeme', 'password', 'admin', 'admin123', '123456', 'letmein', ''}


def env_login_configured():
    """True only for a single-business deployment with a real owner login.

    ADMIN_USER/ADMIN_PASS is a deployment-wide credential. On a hosted
    multi-tenant deployment that would be a master key accepted on every
    company's subdomain, so it is deliberately disabled whenever BASE_DOMAIN
    turns on shared tenancy. Hosted tenants authenticate only against users in
    their own schema.
    """
    if _hosted_multitenant():
        return False
    user = (os.environ.get('ADMIN_USER') or '').strip()
    pw = (os.environ.get('ADMIN_PASS') or '').strip()
    return bool(user) and pw.lower() not in _WEAK


def authenticate(username, password):
    """Check a login attempt. Returns (ok, info) with user_id, role and name.

    Real tenant-local user accounts are always checked first. The legacy env
    owner login exists only on single-business deployments; env_login_configured
    deliberately disables it on hosted multi-tenant Akye.
    """
    from models import User
    from extensions import db
    uname = (username or '').strip().lower()
    user = User.query.filter_by(username=uname, active=True).first()
    if user and user.check_password(password or ''):
        user.last_login = datetime.utcnow()
        db.session.commit()
        # Authentication happens after app.before_request resolved the host.
        # Stamp that tenant into the signed session before the login route marks
        # it logged in, so the cookie cannot later be replayed on another host.
        bind_session_to_current_tenant()
        return True, {'user_id': user.id, 'role': user.role, 'name': user.name}
    if env_login_configured():
        if (username == os.environ.get('ADMIN_USER', '').strip()
                and password == (os.environ.get('ADMIN_PASS') or '')):
            bind_session_to_current_tenant()
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
