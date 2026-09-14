"""The locks on the front door.

Security boundaries shared by the tenant CRM: session hardening, login
throttling, origin/CSRF checks, machine-route host authority, provider callback
authentication, and public booking payment integrity.
"""
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import current_app, g, request, session

CSRF_EXEMPT_PATHS = frozenset({
    '/api/quote',
    '/api/commercial-lead',
    '/api/apply',
    '/api/validate-code',
    '/api/price',
    '/api/create-payment-intent',
    '/api/booking',
    '/api/reminders',
    '/api/charge-balances',
    '/api/send-drips',
    '/api/lsa-followups',
    '/api/insurance-expiry',
    '/api/applicant-followups',
    '/api/lifecycle-emails',
    '/api/stripe/webhook',
    '/messages/incoming',
})

QUERY_SECRET_FORBIDDEN_PATHS = frozenset({
    '/api/reminders',
    '/api/charge-balances',
    '/api/send-drips',
    '/api/lsa-followups',
    '/api/insurance-expiry',
    '/api/applicant-followups',
    '/api/lifecycle-emails',
})
CRON_PATHS = QUERY_SECRET_FORBIDDEN_PATHS
PROVIDER_WEBHOOK_PATHS = frozenset({
    '/api/stripe/webhook',
    '/messages/incoming',
})
TENANT_MACHINE_PATHS = CRON_PATHS | PROVIDER_WEBHOOK_PATHS

BOOKING_PAYMENT_PURPOSE = 'booking_deposit'
BOOKING_PAYMENT_META_TENANT = 'akye_tenant'
BOOKING_PAYMENT_META_PURPOSE = 'akye_purpose'
BOOKING_PAYMENT_META_CHECKOUT = 'akye_checkout'
SINGLE_BUSINESS_PAYMENT_TENANT = '__single_business__'

MAX_FAILED_LOGINS = 10
LOCKOUT_WINDOW = timedelta(minutes=15)
_WEAK_SECRETS = {'', 'dev-secret-change-me', 'insecure-dev-key', 'changeme'}


def harden_session(app):
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = _is_production()
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=14)


def validate_secret(app):
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


def reject_query_credentials():
    if request.path in QUERY_SECRET_FORBIDDEN_PATHS and 'api_key' in request.args:
        from flask import abort
        abort(403, description='API credentials must be sent in X-Api-Key.')
    return None


def require_tenant_for_machine_route():
    if request.path not in TENANT_MACHINE_PATHS:
        return None
    if not (os.environ.get('BASE_DOMAIN') or '').strip():
        return None
    if not getattr(g, 'tenant_slug', None):
        from flask import abort
        abort(404)
    return None


def _booking_payment_tenant_key():
    """Stable authority written into Stripe metadata for this checkout."""
    slug = str(getattr(g, 'tenant_slug', None) or '').strip().lower()
    if slug:
        return slug
    if (os.environ.get('BASE_DOMAIN') or '').strip():
        return None
    return SINGLE_BUSINESS_PAYMENT_TENANT


def require_tenant_for_payment_creation():
    """Do not create a hosted PaymentIntent outside an actual tenant host."""
    if request.path != '/api/create-payment-intent' or request.method != 'POST':
        return None
    if _booking_payment_tenant_key() is None:
        from flask import abort
        abort(404)
    return None


def _checkout_signature(payment_intent_id, tenant, nonce):
    key = str(current_app.config.get('SECRET_KEY') or '').encode('utf-8')
    message = '|'.join((tenant, BOOKING_PAYMENT_PURPOSE,
                        payment_intent_id, nonce)).encode('utf-8')
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _new_checkout_binding(payment_intent_id, tenant, nonce=None):
    nonce = nonce or secrets.token_urlsafe(24)
    return nonce + '.' + _checkout_signature(payment_intent_id, tenant, nonce)


def _checkout_binding_valid(binding, payment_intent_id, tenant):
    try:
        nonce, supplied = str(binding or '').split('.', 1)
    except ValueError:
        return False
    if len(nonce) < 20 or not supplied:
        return False
    expected = _checkout_signature(payment_intent_id, tenant, nonce)
    return hmac.compare_digest(supplied, expected)


def _replace_json_response(response, payload, status):
    """Fail closed while preserving CORS headers already attached by the route."""
    response.set_data(json.dumps(payload))
    response.status_code = status
    response.content_type = 'application/json'
    return response


def bind_created_booking_payment(response):
    """Stamp a new public-booking PaymentIntent before its secret leaves Akye.

    The API route predates multi-tenancy and creates Stripe objects directly.
    An after-request guard lets security bind the resulting intent without a
    risky rewrite of that large route module. The client secret contains the
    PaymentIntent id; before the response is returned we add authenticated
    metadata covering tenant, purpose and a unique signed checkout nonce.
    """
    if request.path != '/api/create-payment-intent' or request.method != 'POST':
        return response
    if response.status_code < 200 or response.status_code >= 300:
        return response

    tenant = _booking_payment_tenant_key()
    data = response.get_json(silent=True) or {}
    client_secret = str(data.get('client_secret') or '')
    payment_intent_id = client_secret.split('_secret_', 1)[0] if '_secret_' in client_secret else ''
    if not tenant or not payment_intent_id.startswith('pi_'):
        return _replace_json_response(
            response,
            {'ok': False, 'error': 'Payment checkout could not be securely bound.'},
            502,
        )

    binding = _new_checkout_binding(payment_intent_id, tenant)
    try:
        import integrations
        import stripe
        secret = (integrations.stripe_secret_key() or '').strip()
        if not secret:
            raise RuntimeError('Stripe is not configured')
        stripe.api_key = secret
        stripe.PaymentIntent.modify(
            payment_intent_id,
            metadata={
                BOOKING_PAYMENT_META_TENANT: tenant,
                BOOKING_PAYMENT_META_PURPOSE: BOOKING_PAYMENT_PURPOSE,
                BOOKING_PAYMENT_META_CHECKOUT: binding,
            },
        )
    except Exception:
        return _replace_json_response(
            response,
            {'ok': False, 'error': 'Payment checkout could not be securely bound.'},
            502,
        )
    return response


def validate_booking_payment_intent():
    """Verify a browser's paid-booking claim directly with Stripe.

    A succeeded intent must be the exact deposit amount/customer and must carry
    Akye's signed tenant/purpose/checkout binding. This closes the shared-Stripe
    fallback-account replay gap: a PaymentIntent minted for tenant A or another
    payment purpose cannot be presented on tenant B's public booking endpoint.
    Pending bookings without a PaymentIntent remain allowed.
    """
    if request.path != '/api/booking' or request.method != 'POST':
        return None

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    payment_intent_id = (data.get('payment_intent_id') or '').strip()
    if not payment_intent_id:
        return None

    claimed_customer = (data.get('stripe_customer_id') or '').strip()
    if not claimed_customer:
        from flask import abort
        abort(400, description='Paid booking requires its Stripe customer.')

    tenant = _booking_payment_tenant_key()
    if tenant is None:
        from flask import abort
        abort(404)

    import integrations
    import stripe

    secret = (integrations.stripe_secret_key() or '').strip()
    if not secret:
        from flask import abort
        abort(400, description='Payments are not configured.')
    stripe.api_key = secret

    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except Exception:
        from flask import abort
        abort(400, description='Payment could not be verified.')

    def field(name, default=None):
        if isinstance(intent, dict):
            return intent.get(name, default)
        return getattr(intent, name, default)

    metadata = field('metadata', {}) or {}

    def meta(name):
        if isinstance(metadata, dict):
            return metadata.get(name)
        return getattr(metadata, name, None)

    expected_cents = int(round(float(__import__('pricing').get_deposit()) * 100))
    received = field('amount_received')
    if received is None:
        received = field('amount')

    verified = (
        str(field('id') or '') == payment_intent_id
        and field('status') == 'succeeded'
        and str(field('currency') or '').lower() == 'usd'
        and int(received or 0) == expected_cents
        and str(field('customer') or '') == claimed_customer
        and str(meta(BOOKING_PAYMENT_META_TENANT) or '').lower() == tenant
        and meta(BOOKING_PAYMENT_META_PURPOSE) == BOOKING_PAYMENT_PURPOSE
        and _checkout_binding_valid(meta(BOOKING_PAYMENT_META_CHECKOUT),
                                    payment_intent_id, tenant)
    )

    claimed_method = (data.get('stripe_payment_method_id') or '').strip()
    actual_method = str(field('payment_method') or '')
    if claimed_method and claimed_method != actual_method:
        verified = False

    if not verified:
        from flask import abort
        abort(400, description='Payment does not match this booking deposit.')

    from models import Booking
    if Booking.query.filter_by(stripe_payment_intent=payment_intent_id).first():
        from flask import abort
        abort(400, description='Payment has already been used for a booking.')
    return None


def validate_twilio_webhook():
    if request.path != '/messages/incoming':
        return None

    import integrations
    token = (integrations.twilio_auth_token() or '').strip()
    signature = (request.headers.get('X-Twilio-Signature') or '').strip()
    if not token or not signature:
        from flask import abort
        abort(403)

    try:
        from twilio.request_validator import RequestValidator
        valid = RequestValidator(token).validate(request.url, request.form, signature)
    except Exception:
        valid = False
    if not valid:
        from flask import abort
        abort(403)
    return None


def _same_site(url, host):
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


def client_ip():
    return (request.remote_addr or 'unknown')[:45]


def login_blocked():
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
    validate_secret(app)
    harden_session(app)
    app.before_request(reject_query_credentials)
    app.before_request(require_tenant_for_machine_route)
    app.before_request(require_tenant_for_payment_creation)
    app.before_request(validate_booking_payment_intent)
    app.before_request(validate_twilio_webhook)
    app.before_request(check_request_origin)
    app.after_request(bind_created_booking_payment)
