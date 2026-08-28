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

# Requests that are not a browser form and must never be origin-checked.
#
# /api/*            cron jobs and the Stripe webhook. Called by machines that
#                   send no Origin, and already guarded — the cron routes by
#                   REMINDER_API_KEY, the webhook by Stripe's signature.
# /messages/incoming Twilio delivering an inbound text from a customer.
CSRF_EXEMPT_PREFIXES = ('/api/', '/messages/incoming')

# Failed logins allowed from one address before it is asked to wait.
MAX_FAILED_LOGINS = 10
LOCKOUT_WINDOW = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Session cookie
# ---------------------------------------------------------------------------

def harden_session(app):
    """Decide the cookie settings instead of inheriting Flask's defaults."""
    app.config['SESSION_COOKIE_HTTPONLY'] = True      # JavaScript cannot read it
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'     # not sent on cross-site POST
    # HTTPS-only in production. Not locally, or the cookie would never be set
    # over http://127.0.0.1 and nobody could log in to test anything.
    app.config['SESSION_COOKIE_SECURE'] = _is_production()
    # A shared laptop in an office should not stay logged in forever. Long
    # enough that an owner is not signing in every morning.
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=14)


def _is_production():
    if (os.environ.get('FLASK_ENV') or '').lower() == 'development':
        return False
    # Railway sets this on every deployment; its absence means a laptop.
    return bool(os.environ.get('RAILWAY_ENVIRONMENT')
                or os.environ.get('RAILWAY_PROJECT_ID')
                or (os.environ.get('CRM_BASE') or '').startswith('https://'))


# ---------------------------------------------------------------------------
# Where a request claims to come from
# ---------------------------------------------------------------------------

def _same_site(url, host):
    """True when `url` belongs to the host serving this request."""
    if not url:
        return None                      # nothing to check
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if not parsed.netloc:
        return False
    return parsed.netloc.split(':')[0].lower() == (host or '').split(':')[0].lower()


def check_request_origin():
    """Refuse a state-changing request that says it came from somewhere else.

    Registered as a before_request. Returns None to allow.
    """
    if request.method in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
        return None
    path = request.path or ''
    if any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES):
        return None

    host = request.host
    for header in ('Origin', 'Referer'):
        value = request.headers.get(header)
        verdict = _same_site(value, host)
        if verdict is None:
            continue                     # header absent — try the next one
        if verdict:
            return None                  # it came from us
        # Present and pointing elsewhere. That is the attack.
        _record_rejected_origin(header, value, path)
        from flask import abort
        abort(403, description='This form was submitted from another site.')
    return None                          # neither header present — allow


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
    """The caller's address, honouring Railway's proxy header.

    Only the FIRST entry in X-Forwarded-For is meaningful; the rest can be
    written by the caller, so trusting the last one would let anybody claim to
    be a fresh address on every attempt and never be throttled at all."""
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()[:45]
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
        # A throttle that cannot read its own table must not become the reason
        # an owner cannot log in to her own business.
        return False, 0


def record_login(username, ok):
    """Write down an attempt. Never the password, and never enough of the
    username to be worth stealing on its own."""
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
    harden_session(app)
    app.before_request(check_request_origin)
