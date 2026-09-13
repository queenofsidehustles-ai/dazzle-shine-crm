"""The locks on the front door.

Three gaps, none of them on fire, all of them worth closing before another
company's customer list is in here:

**Anyone could guess at the login as fast as the server would answer.** No
delay, no lockout, no record. A single owner password protecting a business's
entire customer list, addresses and payroll, with unlimited attempts at it.

**The session cookie was running on defaults nobody chose.** Not marked
HTTPS-only, no SameSite policy, no expiry.

**Nothing checked that a form submission came from this site.** A logged-in
owner who opened a malicious page could have had it act as her — create a
booking, change a price, delete an expense — because the browser would have
sent her session cookie along with the request.

## About the CSRF approach

The textbook fix is a hidden token in every form. That means touching every
template in the application, and a missed one is a form that stops working —
in a live business, mid-week.

This does two cheaper things that together cover the same attack:

1. **SameSite=Lax on the session cookie.** The browser refuses to send the
   session at all on a cross-site POST, so the forged request arrives logged
   out and does nothing.
2. **Origin checking.** Browsers are required to send an `Origin` header on
   cross-origin POSTs. If one arrives claiming to come from somewhere else,
   it is refused.

Mismatched origin is rejected; *absent* origin is allowed, because some
privacy tools strip these headers from ordinary same-site requests and
breaking a real cleaner's checklist submission is worse than the residual
risk. A browser cannot be made to omit `Origin` on a genuine cross-site POST,
which is the case that matters.

Token-based CSRF is still the fuller answer and is worth doing when the
templates are next touched anyway.
"""
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import request, session, g

# State-changing requests bypass origin checking only when they are explicitly
# designed to be called by an external browser/site or by a signed/authenticated
# machine. Never exempt the whole /api namespace: doing that would silently make
# every future authenticated API mutation CSRF-exempt.
CSRF_EXEMPT_PATHS = frozenset({
    # Public website API. These routes are intentionally unauthenticated and
    # have their own CORS / payment integrity controls where applicable.
    '/api/quote',
    '/api/commercial-lead',
    '/api/apply',
    '/api/validate-code',
    '/api/price',
    '/api/create-payment-intent',
    '/api/booking',

    # Machine-to-machine routes. Cron routes require X-Api-Key; Stripe and
    # Twilio routes verify their provider signatures in their handlers.
    '/api/reminders',
    '/api/charge-balances',
    '/api/send-drips',
    '/api/lsa-followups',
    '/api/insurance-expiry',
    '/api/applicant-followups',
    '/api/lifecycle-emails',
    '/api/stripe-webhook',
    '/messages/incoming',
})

# REMINDER_API_KEY is a bearer secret. Every cron route must reject the legacy
# ?api_key= transport because URLs routinely escape into proxy/access logs,
# monitoring traces, screenshots, browser history and support artifacts.
QUERY_SECRET_FORBIDDEN_PATHS = frozenset({
    '/api/reminders',
    '/api/charge-balances',
    '/api/send-drips',
    '/api/lsa-followups',
    '/api/insurance-expiry',
    '/api/applicant-followups',
    '/api/lifecycle-emails',
})

# The same seven machine routes are tenant-scoped operations in Akye. Keeping
# this alias explicit makes the host boundary auditable without duplicating the
# list and risking one route being added to one protection but not the other.
CRON_PATHS = QUERY_SECRET_FORBIDDEN_PATHS

# Failed logins allowed from one address before it is asked to wait.
MAX_FAILED_LOGINS = 10
LOCKOUT_WINDOW = timedelta(minutes=15)
_WEAK_SECRETS = {'', 'dev-secret-change-me', 'insecure-dev-key', 'changeme'}


# ---------------------------------------------------------------------------
# Session cookie
# ---------------------------------------------------------------------------

def harden_session(app):
    """Decide the cookie settings instead of inheriting Flask's defaults."""
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = _is_production()
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=14)


def validate_secret(app):
    """Refuse a production boot with a guessable session-signing secret."""
    secret = str(app.config.get('SECRET_KEY') or '')
    if _is_production() and (secret.lower() in _WEAK_SECRETS or len(secret) < 32):
        raise RuntimeError(
            'Production requires SECRET_KEY with at least 32 characters; '
            'the development fallback cannot sign owner sessions.'
        )


def _is_production():
    if (os.environ.get('FLASK_ENV') or '').lower() == 'development':
        return False
    return bool(os.environ.get('RAILWAY_ENVIRONMENT')
                or os.environ.get('RAILWAY_PROJECT_ID')
                or (os.environ.get('CRM_BASE') or '').startswith('https://'))


# ---------------------------------------------------------------------------
# Request credentials and origin
# ---------------------------------------------------------------------------

def reject_query_credentials():
    """Refuse cron bearer secrets supplied in the URL query string."""
    if request.path in QUERY_SECRET_FORBIDDEN_PATHS and 'api_key' in request.args:
        from flask import abort
        abort(403, description='API credentials must be sent in X-Api-Key.')
    return None


def require_tenant_for_cron():
    """Never run a tenant cron job against Akye's public schema.

    In the hosted multi-tenant product the hostname is the authority selecting
    the tenant schema. A valid cron bearer secret on the product apex, a malformed
    deep hostname, or any other host that does not resolve to a tenant must not
    be allowed to execute a tenant automation against ``public``. Single-business
    installations have no BASE_DOMAIN and retain their historical behavior.
    """
    if request.path not in CRON_PATHS:
        return None
    if not (os.environ.get('BASE_DOMAIN') or '').strip():
        return None
    if not getattr(g, 'tenant_slug', None):
        from flask import abort
        abort(404)
    return None


def _same_site(url, host):
    """True when `url` belongs to the host serving this request."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if not parsed.netloc:
        return False
    return parsed.netloc.split(':')[0].lower() == (host or '').split(':')[0].lower()


def check_request_origin():
    """Refuse a state-changing request that says it came from somewhere else."""
    if request.method in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
        return None
    path = request.path or ''
    if path in CSRF_EXEMPT_PATHS:
        return None

    host = request.host
    for header in ('Origin', 'Referer'):
        value = request.headers.get(header)
        verdict = _same_site(value, host)
        if verdict is None:
            continue
        if verdict:
            return None
        _record_rejected_origin(header, value, path)
        from flask import abort
        abort(403, description='This form was submitted from another site.')
    return None


def _record_rejected_origin(header, value, path):
    try:
        from models import ErrorLog
        ErrorLog.record(
            kind='blocked',
            message=f'Cross-site form submission refused ({header}: {value[:120]})',
            path=path, method=request.method,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Login throttling
# ---------------------------------------------------------------------------

def client_ip():
    """The caller address already resolved by the app's trusted-proxy layer."""
    return (request.remote_addr or 'unknown')[:45]


def login_blocked():
    """(blocked, minutes_left) for the address making this request."""
    try:
        from models import LoginAttempt
        since = datetime.utcnow() - LOCKOUT_WINDOW
        recent = (LoginAttempt.query
                  .filter(LoginAttempt.ip == client_ip(),
                          LoginAttempt.ok.is_(False),
                          LoginAttempt.created_at >= since)
                  .order_by(LoginAttempt.created_at.asc())
                  .all())
        if len(recent) < MAX_FAILED_LOGINS:
            return False, 0
        unlock = recent[-MAX_FAILED_LOGINS].created_at + LOCKOUT_WINDOW
        left = max(1, int((unlock - datetime.utcnow()).total_seconds() // 60) + 1)
        return True, left
    except Exception:
        return False, 0


def record_login(username, ok):
    """Write down an attempt. Never the password."""
    try:
        from models import LoginAttempt
        from extensions import db
        db.session.add(LoginAttempt(
            ip=client_ip(),
            username=(username or '')[:80].lower(),
            ok=bool(ok),
        ))
        db.session.commit()
    except Exception:
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass


def prune_login_attempts(days=30):
    """Old attempts are noise. Called from the nightly cron."""
    try:
        from models import LoginAttempt
        from extensions import db
        cutoff = datetime.utcnow() - timedelta(days=days)
        n = LoginAttempt.query.filter(LoginAttempt.created_at < cutoff).delete()
        db.session.commit()
        return n
    except Exception:
        return 0


def install(app):
    """Wire everything into the application."""
    validate_secret(app)
    harden_session(app)
    app.before_request(reject_query_credentials)
    app.before_request(require_tenant_for_cron)
    app.before_request(check_request_origin)
