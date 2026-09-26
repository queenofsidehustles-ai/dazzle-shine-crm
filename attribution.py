"""Where a company came from: the link that brought its owner to the site.

Without this the Funnel could say how many companies signed up but never
which channel sent them, so a week of outreach ended in a guess. Two kinds of
link are read, both only on the product's own site:

  tracking tags   ?utm_source=newsletter&utm_medium=email&utm_campaign=founding
  a referral      /r/<company address>, or ?ref=<company address> on any page

## First touch, kept in a cookie

The tags are on the page somebody lands on, not on the signup form they reach
three clicks later, so the first page that carries them writes them into a
cookie and signup reads the cookie. First touch wins: a later visit with
different tags does not overwrite it. A referral is the one exception -- a
personal invitation is added to a cookie that does not have one yet, because
"a friend sent me the link" is the fact worth crediting even if an ad got
there first.

A visitor with no tags who arrived from another site is recorded by that
site's name (google.com, facebook.com), so organic arrivals are not all
lumped into "direct".

The cookie is signed with the app's secret key. Faking one would only
mislabel your own signup, but referrals may earn a reward, and a reward
should not be claimable by editing a cookie.

## What is stored

Short, cleaned strings only -- never a full URL with whatever else was in its
query string. A referral names a company by its address and is only kept if
that company exists and is not the one signing up (see control_plane.create).
"""
import json
import re
from datetime import datetime

COOKIE = 'akye_src'
MAX_AGE = 90 * 24 * 3600          # a quarter: long enough for a slow decision
PARAMS = {'utm_source': 'source', 'utm_medium': 'medium',
          'utm_campaign': 'campaign'}
FIELDS = ('source', 'medium', 'campaign', 'ref', 'referrer', 'landing')

_UNSAFE = re.compile(r'[^a-z0-9 _.+\-]')
_REF_UNSAFE = re.compile(r'[^a-z0-9\-]')
_PATH_UNSAFE = re.compile(r'[^a-z0-9/_.\-]')


def clean(value, limit=80):
    """Lower-case, printable, short. '' for anything that cleans to nothing."""
    value = _UNSAFE.sub('', (value or '').strip().lower())
    return value[:limit].strip()


def clean_ref(value):
    """A company address: the same characters a slug may use."""
    return _REF_UNSAFE.sub('', (value or '').strip().lower())[:40]


def _serializer(secret):
    from itsdangerous import URLSafeSerializer
    return URLSafeSerializer(secret, salt='akye-attribution')


def _external_host(referrer, own_host):
    """The site a visitor came from, or '' if it was this site or none."""
    from urllib.parse import urlparse
    host = (urlparse(referrer or '').hostname or '').lower()
    if not host:
        return ''
    own = (own_host or '').split(':')[0].lower()
    base = own[4:] if own.startswith('www.') else own
    if host == own or host == base or host.endswith('.' + base):
        return ''                   # a click from one of our own pages
    return clean(host[4:] if host.startswith('www.') else host, 120)


def from_request(args, referrer, host, path):
    """What this one request says about where the visitor came from."""
    found = {field: clean(args.get(param)) for param, field in PARAMS.items()}
    found = {k: v for k, v in found.items() if v}
    ref = clean_ref(args.get('ref'))
    if ref:
        found['ref'] = ref
    if not found:
        outside = _external_host(referrer, host)
        if outside:
            found['referrer'] = outside
    if found:
        found['landing'] = _PATH_UNSAFE.sub('', (path or '/').lower())[:120] or '/'
    return found


def read(cookies, secret):
    """The stored attribution, or {} if there is none or it was tampered with."""
    raw = cookies.get(COOKIE)
    if not raw:
        return {}
    try:
        data = _serializer(secret).loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(data[k])[:120] for k in FIELDS if data.get(k)}


def merge(stored, found):
    """First touch wins; a referral is added if none is stored yet."""
    if not found:
        return None
    if not stored:
        return found
    if found.get('ref') and not stored.get('ref'):
        return dict(stored, ref=found['ref'])
    return None                     # nothing new worth writing


def write(response, data, secret, secure):
    data = dict(data, at=datetime.utcnow().strftime('%Y-%m-%d'))
    response.set_cookie(COOKIE, _serializer(secret).dumps(data),
                        max_age=MAX_AGE, httponly=True, samesite='Lax',
                        secure=secure)
    return response


def forget(response):
    response.delete_cookie(COOKIE)
    return response


def label(row):
    """One short name for where a company or lead came from.

    Reads either a cookie's fields or an organizations row's signup_* columns.
    A referral counts as the channel 'referral' whatever tags came with it:
    the invitation is what brought them.
    """
    get = lambda k: row.get(k) or row.get(f'signup_{k}') or ''
    if row.get('referred_by') or get('ref'):
        return 'referral'
    source = get('source')
    if source:
        campaign = get('campaign')
        return f'{source} · {campaign}' if campaign else source
    return get('referrer') or 'direct'


def install(app):
    """Remember tracking tags and referrals seen on the product's own site."""
    from flask import request

    @app.after_request
    def _remember_where_they_came_from(response):
        try:
            import product
            if request.method != 'GET' or not product.is_product_site():
                return response
            if request.path.startswith(('/static', '/r/')):
                return response     # /r/ writes its own cookie
            secret = app.secret_key
            found = from_request(request.args, request.referrer,
                                 request.host, request.path)
            new = merge(read(request.cookies, secret), found)
            if new:
                write(response, new, secret, secure=request.is_secure)
        except Exception as e:
            # Losing a label must never cost somebody the page they asked for.
            print(f'  ⚠️  attribution not recorded: {type(e).__name__}: {e}')
        return response
