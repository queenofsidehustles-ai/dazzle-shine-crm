import os
import hashlib
import hmac
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


def _auth_fingerprint(password_hash):
    """Opaque session binding to the credential version, never the hash itself."""
    return hashlib.sha256((password_hash or '').encode('utf-8')).hexdigest()


def session_matches_current_user():
    """Revalidate tenant-local account state on every authenticated request.

    A signed Flask cookie can otherwise outlive a database change.  Disabling
    or deleting an account, changing its role, or resetting its password must
    revoke an already-issued session immediately rather than waiting for cookie
    expiry.  The deployment-wide legacy owner has no User row and is allowed
    only in single-business mode, where env_login_configured() already guards
    that credential separately.
    """
    user_id = session.get('user_id')
    if user_id is None:
        return not _hosted_multitenant() and session.get('role') == 'owner'

    from models import User
    user = User.query.get(user_id)
    if not user or not user.active:
        return False

    import rbac
    stored_role = rbac.canonical_role(user.role)
    session_role = rbac.canonical_role(session.get('role'))
    if not stored_role or stored_role != session_role:
        return False

    expected = _auth_fingerprint(user.password_hash)
    presented = session.get('auth_fingerprint') or ''
    return bool(presented) and hmac.compare_digest(expected, presented)


def _reject_wrong_tenant_session():
    """Discard an invalid, stale, or wrong-tenant cookie and require login."""
    session.clear()
    return redirect(url_for('admin.login'))


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin.login'))
        if not session_matches_current_tenant():
            return _reject_wrong_tenant_session()
        if not session_matches_current_user():
            return _reject_wrong_tenant_session()
        # Route authentication and route authorization are separate boundaries.
        # rbac only acts on endpoints deliberately classified in its matrix;
        # unknown roles/permissions fail closed for those protected actions.
        import rbac
        rbac.enforce_current_request()
        return f(*args, **kwargs)
    return decorated


def is_owner_session():
    """True only for this tenant's authenticated session explicitly marked owner.

    Authorization fails closed. A stale signed session created before roles or
    tenant binding existed must not gain owner authority merely because fields
    are missing.
    """
    return (session_matches_current_tenant()
            and session_matches_current_user()
            and session.get('role') == 'owner')


def owner_required(f):
    """Guard owner-only pages such as payroll, reports and settings."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin.login'))
        if not session_matches_current_tenant():
            return _reject_wrong_tenant_session()
        if not session_matches_current_user():
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


def bind_authenticated_session(user):
    """Start a fully authenticated session for an already-verified User.

    The one place that sets every key a new login needs: tenant binding, the
    credential-version fingerprint, and the UI-facing identity keys.
    `authenticate()` has its own equivalent for the password-checked path;
    this is for a flow that has already established who the user is by some
    other means (signup, completing account setup) and has no password to
    re-check. Forgetting `auth_fingerprint` here is exactly how a brand-new
    signup was silently logged back out on its very next request -- see
    JOURNEY-01 in docs/launch-readiness/decision-evidence-register.md. Call
    this instead of hand-assigning session keys, so that mistake can't recur.
    """
    bind_session_to_current_tenant()
    session['auth_fingerprint'] = _auth_fingerprint(user.password_hash)
    session['logged_in'] = True
    session['role'] = user.role
    session['user_id'] = user.id
    session['user_name'] = user.name


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
        # Bind this cookie to the current credential version. A later password
        # reset changes password_hash, making every older cookie invalid.
        session['auth_fingerprint'] = _auth_fingerprint(user.password_hash)
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
