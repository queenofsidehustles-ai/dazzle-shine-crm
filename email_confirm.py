"""Does the email address typed at signup actually reach the owner?

It is typed once and never checked. A slipped key and the welcome email -- the
only written record of their own web address -- goes nowhere, and so does
every trial email after it. Nothing tells anybody why that company never came
back.

So the welcome email carries a six-digit code and a button. Either one proves
the address works.

Two decisions worth knowing:

  * The button opens a page with a "Yes, this is me" button on it. It does not
    confirm by being clicked. Mail scanners open every link in a message to
    check it, so a one-click link would confirm an address nobody ever read
    (blueprints/confirm.py found this first, for customer bookings).

  * Nothing is blocked while it is unconfirmed. They are signed in and
    working before the email has even arrived; a gate here would stop the
    person this is meant to help. A soft banner asks instead, and lets them
    correct the address if it was wrong.

The code and the link are both worked out from the company and the address,
signed with SECRET_KEY, so nothing secret is stored -- and correcting the
address changes the code, so an old email cannot confirm the new address.
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta

# How long the "Yes, this is me" link works.
LINK_MAX_AGE = timedelta(days=30)
# Resend no more often than this, whoever presses the button.
RESEND_EVERY = timedelta(minutes=2)
# Wrong codes allowed per signed-in session before it stops listening.
MAX_CODE_TRIES = 8

_SALT = 'akye-owner-email-confirm'


def _secret():
    return (os.environ.get('SECRET_KEY') or '').encode()


def _norm(email):
    return (email or '').strip().lower()


def code(slug, email):
    """Six digits, the same every time for this company and this address."""
    msg = f'{_SALT}|{slug}|{_norm(email)}'.encode()
    digest = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()
    return f'{int(digest[:12], 16) % 1_000_000:06d}'


def code_matches(slug, email, typed):
    typed = ''.join(ch for ch in (typed or '') if ch.isdigit())
    return len(typed) == 6 and hmac.compare_digest(typed, code(slug, email))


def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(os.environ.get('SECRET_KEY') or '', salt=_SALT)


def token(slug, email):
    return _serializer().dumps({'s': slug, 'e': _norm(email)})


def read_token(raw):
    """(slug, email) from a link, or (None, None) when it is bad or old."""
    try:
        data = _serializer().loads(raw, max_age=int(LINK_MAX_AGE.total_seconds()))
        return data.get('s'), data.get('e')
    except Exception:
        return None, None


def link(host, slug, email):
    """The "is this you?" page, on the company's own address."""
    import product
    host = (host or '').replace('https://', '').replace('http://', '').strip('/')
    return f'{product.scheme_for(host)}://{host}/confirm-email/{token(slug, email)}'


def pending(org):
    """Is this company being asked to confirm, and has not yet?

    Only companies whose signup asked: the ones from before this existed were
    never sent a code and must never be nagged for one.
    """
    return bool(org and org.get('email_confirm_sent_at')
                and not org.get('email_confirmed_at'))


def may_resend(org, now=None):
    last = (org or {}).get('email_confirm_sent_at')
    return not last or (now or datetime.utcnow()) - last >= RESEND_EVERY


def confirm(engine, slug):
    """Mark it done. Keeps the first time, if done twice."""
    import control_plane
    org = control_plane.find(engine, slug)
    if not org:
        return None
    if org.get('email_confirmed_at'):
        return org
    return control_plane.set_email_state(engine, slug,
                                         email_confirmed_at=datetime.utcnow())


def send(org, host, first=None, sent_by='auto'):
    """(Re)send the welcome email, which is where the code lives.

    One email rather than a welcome and a separate confirm: two arriving in
    the same minute read as a mistake, and the welcome is the one people keep.
    """
    import control_plane
    import provisioning
    import welcome_email
    slug = org['slug']
    email = org.get('owner_email') or ''
    ok, detail = welcome_email.send(
        org.get('name') or slug, email, host, first=first,
        confirm_code=code(slug, email), confirm_url=link(host, slug, email))
    engine = provisioning._engine()
    if ok:
        control_plane.set_email_state(engine, slug,
                                      email_confirm_sent_at=datetime.utcnow())
    control_plane.record_product_message(
        engine, slug, 'welcome', email,
        f'{org.get("name") or slug} is set up — here is your address', ok,
        detail, sent_by)
    return ok, detail
