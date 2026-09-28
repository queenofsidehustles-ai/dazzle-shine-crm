"""Finding out that something broke, without a customer having to tell you.

Until this existed, an error on a live page went to the server log, which
nobody reads, and then nowhere. A cleaner who couldn't submit a checklist at
8pm either rang the owner or gave up. Most gave up, and the owner never knew
the page was broken at all.

Now every unhandled error is written down, grouped, and emailed the first time
it happens.

## Two people are told, and they are not the same person

The owner of the CRM it happened in, because it is their business and their
customer who just saw a broken page. And, on the hosted product only, whoever
runs the product — because a fault in one company's CRM is usually a fault in
everybody's, and without that copy the only person who knows the software is
broken is the customer it broke for. The most likely thing they do is say
nothing and quietly stop using it.

The two are sent independently. A company that has not set an owner email yet
is exactly the one most likely to hit something, so a missing owner address
must not swallow the copy that reaches us as well.

## Grouped, not listed

The same broken page hit forty times in an evening is one problem, not forty.
Errors are fingerprinted on where they happened and what went wrong, so the
fortieth increments a counter rather than sending a fortieth email. What the
owner sees is "this broke 40 times since Tuesday", which is the useful shape.

## Quiet on purpose

An alerting system that cries wolf gets filtered into a folder, and then it may
as well not exist. So: one email the first time a fault appears, and at most one
more per day while it persists. A fault that has been emailed about today is
counted silently.

## What is deliberately not recorded

No form bodies, no passwords, no card numbers, no cookies, no session contents.
A crash report is a place sensitive data leaks into by accident, and an error
log full of customer detail is a new problem rather than a fix for an old one.
The path, the method, the endpoint, the exception and the traceback are enough
to find almost anything.

If SENTRY_DSN is set the same error is also sent there. It is not required, and
nothing here depends on an account with anybody.
"""
import hashlib
import os
import traceback as tb_module
from datetime import datetime, timedelta

ALERT_COOLDOWN = timedelta(hours=24)

# Errors that mean "somebody typed a bad URL", not "the software is broken".
IGNORED_STATUS = {400, 401, 403, 404, 405, 408, 410, 429}


def fingerprint(endpoint, exc):
    """What makes two crashes the same crash.

    The endpoint plus the exception type plus the line it came from. The
    message itself is left out on purpose — 'Client 41 not found' and
    'Client 87 not found' are one bug, and grouping them by message would file
    them as two.
    """
    frame = ''
    tb = getattr(exc, '__traceback__', None)
    while tb is not None:
        frame = f'{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}'
        tb = tb.tb_next          # keep walking — we want the deepest frame
    raw = f'{endpoint}|{type(exc).__name__}|{frame}'
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def install(app):
    """Catch everything the application does not catch itself."""

    @app.errorhandler(Exception)
    def _handle(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException) and exc.code in IGNORED_STATUS:
            return exc               # a 404 is not an incident

        try:
            capture(exc)
        except Exception:
            pass                     # reporting a fault must never cause one

        if isinstance(exc, HTTPException):
            return exc

        # Never show a stack trace to a customer or a cleaner. They cannot act
        # on it and it describes the inside of the application to a stranger.
        from flask import render_template, request
        try:
            return render_template('error.html'), 500
        except Exception:
            return ('Something went wrong on our end. It has been reported '
                    'and we are looking at it.'), 500

    return app


def capture(exc, path=None, method=None):
    """Record one error and alert if it is worth alerting about."""
    from flask import request, session, has_request_context
    from models import ErrorLog

    endpoint = '-'
    if has_request_context():
        endpoint = request.endpoint or '-'
        path = path or request.path
        method = method or request.method

    who = ''
    try:
        if has_request_context() and session.get('logged_in'):
            who = (session.get('user_name') or 'owner')[:60]
    except Exception:
        pass

    trace = ''.join(tb_module.format_exception(
        type(exc), exc, exc.__traceback__))[-6000:]

    row, is_new = ErrorLog.record(
        kind=type(exc).__name__,
        message=str(exc)[:400],
        path=(path or '')[:300],
        method=(method or '')[:10],
        endpoint=endpoint[:120],
        who=who,
        traceback=trace,
        fingerprint=fingerprint(endpoint, exc),
        return_new=True,
    )

    _to_sentry(exc)

    if row is not None and _should_alert(row, is_new):
        _alert(row)
    return row


def _should_alert(row, is_new):
    if is_new:
        return True
    if not row.alerted_at:
        return True
    return datetime.utcnow() - row.alerted_at > ALERT_COOLDOWN


def _which_company():
    """Which company's CRM this happened in, for the product's own copy.

    Returns (slug, url) or (None, None) on a single-business install, where
    there is no such thing as "which company" and the question is meaningless.
    """
    try:
        import tenancy
        import product
        if not tenancy.is_tenant():
            return None, None
        schema = tenancy.current_schema() or ''
        slug = schema[len(tenancy.SCHEMA_PREFIX):] if schema.startswith(
            tenancy.SCHEMA_PREFIX) else schema
        domain = product.domain()
        return slug, (f'https://{slug}.{domain}' if slug and domain else None)
    except Exception:
        return None, None


def _alert(row):
    """Tell the people who need to know. Failing to send must not raise.

    Two recipients, and they are not the same person:

      * the owner of the CRM it happened in, because it is their business and
        their customer who just saw a broken page

      * whoever runs the product, because a fault in one company's CRM is
        usually a fault in everybody's. Without this copy the only person who
        knows the software is broken is the customer it broke for, and the
        most likely outcome is that they say nothing and quietly stop using
        it. During a beta that is the entire signal.

    They are sent independently on purpose. A brand-new company has not set an
    owner email yet, and that is exactly when it is most likely to hit
    something — so a missing owner address must not also swallow the copy that
    reaches us. It used to return early on that, before either was sent.
    """
    import notifications
    from extensions import db

    try:
        import branding
        biz = branding.biz_name()
        owner = branding.owner_email()
    except Exception:
        biz, owner = 'a CRM', None

    when = row.last_seen.strftime('%d %b %Y at %H:%M UTC') if row.last_seen else ''
    seen = (f'<p>This has now happened <strong>{row.count} times</strong>.</p>'
            if row.count and row.count > 1 else '')
    facts = f'''
        <table cellpadding="6" style="border-collapse:collapse;font-family:sans-serif">
          <tr><td><strong>Page</strong></td><td>{row.method} {row.path}</td></tr>
          <tr><td><strong>Problem</strong></td><td>{row.kind}: {row.message}</td></tr>
          <tr><td><strong>When</strong></td><td>{when}</td></tr>
          <tr><td><strong>Who hit it</strong></td><td>{row.who or 'a visitor'}</td></tr>
        </table>'''

    attempted = False

    # ── The owner's copy: their business, their customer, their words ───────
    if owner:
        attempted = True
        try:
            notifications.send_email(
                owner, biz,
                f'[{biz}] Something broke: {row.kind}',
                f'''<p>An error happened on your CRM. Nobody had to tell you — it
                reported itself.</p>
                {facts}
                {seen}
                <p>Full details are under <strong>Settings &rarr; Errors</strong> in your CRM.</p>
                <p style="color:#777;font-size:13px">You will not be emailed about
                this same fault again for 24 hours, however often it happens.</p>''')
        except Exception:
            pass

    # ── The product's copy: which company, and a traceback ──────────────────
    # Only on the hosted product. `support_email()` is empty when BASE_DOMAIN
    # is not set, which is precisely the single-business deployment — there the
    # owner is already the only person there is to tell.
    try:
        import product
        support = product.support_email()
    except Exception:
        support = ''

    slug, crm_url = _which_company()
    if support and support.lower() != (owner or '').lower():
        attempted = True
        try:
            trace = (row.traceback or '')[-4000:]
            notifications.send_email(
                support, product.name(),
                f'[{product.name()}] {biz}: {row.kind} on {row.path}',
                f'''<p><strong>{biz}</strong>{f" ({slug})" if slug else ""} hit an
                error. They have been emailed too{"" if owner else
                " — except they have not, because there is no owner email on "
                "the account yet"}.</p>
                {facts}
                {seen}
                {f'<p><a href="{crm_url}">{crm_url}</a></p>' if crm_url else ''}
                <p style="color:#777;font-size:13px">Traceback:</p>
                <pre style="font-size:12px;background:#f6f7fa;padding:10px;
                     border-radius:6px;overflow-x:auto;white-space:pre-wrap">{trace}</pre>''',
                from_name=product.name(),
                from_email=product.from_email() or support,
                reply_to=support,
                # Our key, not the customer's. Without this, a crash inside
                # their CRM emails us through their Resend account.
                api_key=product.resend_api_key() or None)
        except Exception:
            pass

    # Stamped once, whichever copies went. The cooldown is about how often a
    # fault is worth mentioning, not about who was told.
    if attempted:
        try:
            row.alerted_at = datetime.utcnow()
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass


def _to_sentry(exc):
    """Optional. Nothing here requires an account with anybody."""
    dsn = (os.environ.get('SENTRY_DSN') or '').strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def init_sentry():
    """Called at boot. A no-op unless SENTRY_DSN is set and the SDK installed."""
    dsn = (os.environ.get('SENTRY_DSN') or '').strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=0,
            send_default_pii=False,   # never customer data
            environment=os.environ.get('RAILWAY_ENVIRONMENT', 'production'),
        )
        return True
    except Exception:
        return False
