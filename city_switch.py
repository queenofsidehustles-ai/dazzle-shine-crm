"""One owner, two cities, one login — without carrying a session across.

Dazzle & Shine runs Orlando and Huntsville as separate companies, because a
company holds exactly one price book and the two markets are priced
differently on purpose: North Alabama homes are bigger and cheaper per square
foot, so Orlando's curve ran a five-bedroom past what Huntsville pays. Keeping
them apart is what makes each city's prices correct.

What that cost was a second login. This closes that, and only that. The
companies stay separate; the owner stops having to log out to see the other one.

## Why a token rather than a shared cookie

A session is deliberately bound to one tenant. auth.bind_session_to_current_tenant
says why: a signed cookie minted for one company, replayed by hand against
another, would otherwise be accepted there. So switching cannot mean carrying a
session over. It means proving to the other city, in a way it can check for
itself, that this person is entitled to a session of its own.

The token is signed with SECRET_KEY, lives ninety seconds, names exactly one
destination, and may be spent once. None of those alone is enough:

- the signature stops it being forged;
- the expiry bounds how long a leaked one is worth anything;
- naming the destination stops a token for Huntsville being spent on Orlando;
- claiming the id in the control plane stops the same token being spent twice;
- and the destination re-checks entitlement from the control plane anyway, so
  a token is never the only thing standing between somebody and a login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

TTL_SECONDS = 90
_PREFIX = 'akyeswitch1.'


def _key() -> bytes:
    secret = (os.environ.get('SECRET_KEY') or '').strip()
    if not secret:
        raise RuntimeError('SECRET_KEY is not set; refusing to sign a switch token')
    return secret.encode('utf-8')


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _unb64(token: str) -> bytes:
    return base64.urlsafe_b64decode(token + '=' * (-len(token) % 4))


def _engine():
    import provisioning
    return provisioning._engine()


def _city_of(slug: str) -> str:
    """The city this company says it is in, or ''.

    Read with raw SQL on its own connection, never through the ORM session.
    This runs from a context processor on every page render, and the first
    version used tenancy.use_tenant plus db.session.remove() -- which discarded
    the live request's session mid-render and turned every page into a 500.
    A label has no business touching the session; the same raw-SQL pattern the
    tenant purge uses avoids it entirely.

    The schema name is derived from a slug that has already passed valid_slug,
    never taken from anything a visitor can set.
    """
    try:
        import provisioning
        import tenancy
        from sqlalchemy import text
        schema = tenancy.schema_for(slug)
        with provisioning._engine().connect() as conn:
            row = conn.execute(
                text(f'SELECT value FROM "{schema}".business_setting '
                     "WHERE key = 'city' LIMIT 1")).first()
        return (row[0] or '').strip() if row else ''
    except Exception:
        return ''


def _labels(names: dict) -> dict:
    """Short labels for a set of companies: {slug: label}.

    The sidebar already carries the business name above this menu, so repeating
    it against every entry says nothing and makes two entries look alike. What
    distinguishes them is the city.

    The company's own `city` setting first, because it is the only source that
    actually knows. Names were tried alone and are not enough: "Dazzle and
    Shine HSV" beside "Dazzle & Shine" share just the word "Dazzle", so
    stripping what they have in common produced "and Shine HSV" and "& Shine" --
    and Orlando's name does not contain its city at all, so no parsing could
    ever have recovered it.

    Falling back, a name with a dash is already brand-then-place; then whatever
    opening words every company shares; then the name itself.
    """
    out = {}
    for slug, name in names.items():
        city = _city_of(slug)
        if city:
            out[slug] = city
            continue
        label = (name or '').strip()
        for sep in ('\u2014', '\u2013', ' - '):
            if sep in label:
                tail = label.rsplit(sep, 1)[1].strip()
                if tail:
                    label = tail
                break
        out[slug] = label or slug

    # Only trim shared words off names that had to fall back -- a real city
    # name must never be shortened because another city happens to start the
    # same way.
    fallbacks = {k: v.split() for k, v in out.items()
                 if not _city_of(k) and v}
    if len(fallbacks) > 1:
        shared = 0
        shortest = min(len(w) for w in fallbacks.values())
        while shared < shortest - 1:
            if len({tuple(w[:shared + 1]) for w in fallbacks.values()}) != 1:
                break
            shared += 1
        if shared:
            for k, words in fallbacks.items():
                trimmed = ' '.join(words[shared:]).strip()
                if trimmed:
                    out[k] = trimmed
    return out


def cities_for(email: str) -> list[dict]:
    """Every company this email can sign into, newest first, name included.

    Read from tenant_logins, which records where an account was created. Its
    own docstring calls it a routing hint and not an authentication decision,
    and that is exactly how it is used here: to decide what to put in a menu.
    Entitlement is checked again, from the organizations row, when a switch is
    actually attempted.
    """
    import control_plane
    email = (email or '').strip().lower()
    if not email:
        return []
    engine = _engine()
    out = []
    for slug in control_plane.tenants_for_email(engine, email):
        org = control_plane.find(engine, slug)
        if not org or (org.get('status') or 'active') != 'active':
            continue
        out.append({'slug': slug, 'name': org.get('name') or slug})
    labels = _labels({c['slug']: c['name'] for c in out})
    for c in out:
        c['label'] = labels.get(c['slug'], c['name'])
    return out


def may_switch(email: str, slug: str) -> bool:
    """Is this email entitled to a session at this company?

    Checked at both ends of a switch -- before minting and again before
    spending -- so the token carries a claim that has already been true twice
    rather than a claim the destination takes on trust.
    """
    import control_plane
    email = (email or '').strip().lower()
    slug = (slug or '').strip().lower()
    if not email or not slug:
        return False
    engine = _engine()
    org = control_plane.find(engine, slug)
    if not org or (org.get('status') or 'active') != 'active':
        return False
    if (org.get('owner_email') or '').strip().lower() == email:
        return True
    # An account created at that company counts too: an owner who was added
    # there directly, rather than being the address on the company record.
    return slug in control_plane.tenants_for_email(engine, email)


def mint(email: str, slug: str) -> str:
    payload = {
        'v': 1,
        'email': (email or '').strip().lower(),
        'slug': (slug or '').strip().lower(),
        'exp': int(time.time()) + TTL_SECONDS,
        'jti': secrets.token_urlsafe(18),
    }
    raw = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    sig = hmac.new(_key(), raw, hashlib.sha256).digest()
    return _PREFIX + _b64(raw) + '.' + _b64(sig)


def verify(token: str, slug: str) -> str | None:
    """The email this token is good for at this company, or None.

    Returns None for anything wrong -- bad signature, expired, minted for a
    different company, already spent -- without saying which, because the
    caller has nothing useful to do with the distinction and a login flow that
    explains its refusals teaches whoever is probing it.
    """
    import control_plane
    if not isinstance(token, str) or not token.startswith(_PREFIX):
        return None
    try:
        body, sig = token[len(_PREFIX):].split('.', 1)
        raw = _unb64(body)
        expected = hmac.new(_key(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(sig), expected):
            return None
        payload = json.loads(raw)
    except Exception:
        return None

    if payload.get('v') != 1:
        return None
    if (payload.get('slug') or '') != (slug or '').strip().lower():
        return None
    if int(payload.get('exp') or 0) < int(time.time()):
        return None
    email = (payload.get('email') or '').strip().lower()
    if not email or not may_switch(email, slug):
        return None
    # Last, because a token that fails any check above should not burn its id.
    if not control_plane.claim_switch_token(_engine(), payload.get('jti')):
        return None
    return email


def url_for_city(slug: str, token: str) -> str:
    """Where to send the browser to spend a token."""
    import product
    base = (os.environ.get('BASE_DOMAIN') or product.domain() or '').strip()
    scheme = 'https'
    return f'{scheme}://{slug}.{base}/switch-city/accept?t={token}'
