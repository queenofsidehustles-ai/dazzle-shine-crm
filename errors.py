"""Finding out that something broke, without a customer having to tell you.

Until this existed, an error on a live page went to the server log, which
nobody reads, and then nowhere. A cleaner who couldn't submit a checklist at
8pm either rang the owner or gave up. Most gave up, and the owner never knew
the page was broken at all.

Now every unhandled error is written down, grouped, and emailed the first time
it happens.

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


def _alert(row):
    """Email the owner. Failing to send must not raise."""
    try:
        import notifications, branding
        from extensions import db
        to = branding.owner_email()
        if not to:
            return
        biz = branding.biz_name()
        when = row.last_seen.strftime('%d %b %Y at %H:%M UTC') if row.last_seen else ''
        seen = (f'<p>This has now happened <strong>{row.count} times</strong>.</p>'
                if row.count and row.count > 1 else '')
        notifications.send_email(
            to,
            f'[{biz}] Something broke: {row.kind}',
            f'''<p>An error happened on your CRM. Nobody had to tell you — it
            reported itself.</p>
            <table cellpadding="6" style="border-collapse:collapse;font-family:sans-serif">
              <tr><td><strong>Page</strong></td><td>{row.method} {row.path}</td></tr>
              <tr><td><strong>Problem</strong></td><td>{row.kind}: {row.message}</td></tr>
              <tr><td><strong>When</strong></td><td>{when}</td></tr>
              <tr><td><strong>Who hit it</strong></td><td>{row.who or 'a visitor'}</td></tr>
            </table>
            {seen}
            <p>Full details are under <strong>Settings &rarr; Errors</strong> in your CRM.</p>
            <p style="color:#777;font-size:13px">You will not be emailed about
            this same fault again for 24 hours, however often it happens.</p>''')
        row.alerted_at = datetime.utcnow()
        db.session.commit()
    except Exception:
        try:
            from extensions import db
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
