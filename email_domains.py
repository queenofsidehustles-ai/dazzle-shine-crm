"""Proving a cleaning company owns the domain it sends cold email from.

Transactional mail -- reminders, work orders, receipts -- goes out on Akye's
own verified domain and needs nothing from the company. Cold outreach does not
get that privilege. One company sending bad cold email from akyehq.com would
cost every other company on the platform their deliverability, and the ones
who paid that price would be the ones whose work orders stopped arriving.

So outreach sends from the company's own domain, proven. That is the one place
in this product where asking somebody to do setup is worth it: it is three DNS
records, once, before one feature, and it protects everybody else.

What this replaces is worse than nothing: `brand_domain_verified` was a
dropdown the owner set herself, checked by no one. Ticking it without doing
the DNS did not make mail send from her domain -- it made it fail, silently,
with the setting cheerfully reading "verified".

House style mirrors places_finder.py: read the key, return a (success, data,
error) tuple, never raise. The domains live on Akye's own Resend account, so
every call here uses the product's key and never a company's.
"""
import requests

API = 'https://api.resend.com/domains'
TIMEOUT = 20

# What Resend calls a domain that is ready to send. Anything else is not.
VERIFIED = 'verified'


def _key():
    import product
    return product.resend_api_key()


def _headers(key):
    return {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}


def _fail(resp):
    """Resend's own words where it has them, rather than a status code."""
    try:
        payload = resp.json()
    except Exception:
        return f'Email service returned {resp.status_code}.'
    msg = (payload.get('message') or payload.get('error') or '').strip()
    return msg or f'Email service returned {resp.status_code}.'


def register(domain):
    """Tell Resend about a domain. Returns (ok, {id, status, records}, error).

    Safe to call twice: a domain Resend already holds comes back as an error
    naming it, and the caller is expected to fall back to `status()` with the
    id it already stored rather than treating that as a failure.
    """
    key = _key()
    if not key:
        return False, {}, 'Email is not configured on this deployment.'
    domain = (domain or '').strip().lower().lstrip('@')
    if not domain or '.' not in domain or ' ' in domain:
        return False, {}, ('That does not look like a domain. Enter just the domain, like yourbusiness.com — no www and no https.')
    try:
        r = requests.post(API, headers=_headers(key), json={'name': domain},
                          timeout=TIMEOUT)
    except Exception as e:
        return False, {}, f'Could not reach the email service: {type(e).__name__}'
    if r.status_code not in (200, 201):
        return False, {}, _fail(r)
    body = r.json()
    return True, {'id': body.get('id'), 'status': body.get('status'),
                  'records': body.get('records') or []}, ''


def status(domain_id):
    """Where Resend thinks this domain is. Returns (ok, {status, records}, error)."""
    key = _key()
    if not key:
        return False, {}, 'Email is not configured on this deployment.'
    if not domain_id:
        return False, {}, 'No domain has been registered yet.'
    try:
        r = requests.get(f'{API}/{domain_id}', headers=_headers(key), timeout=TIMEOUT)
    except Exception as e:
        return False, {}, f'Could not reach the email service: {type(e).__name__}'
    if r.status_code != 200:
        return False, {}, _fail(r)
    body = r.json()
    return True, {'status': body.get('status'), 'name': body.get('name'),
                  'records': body.get('records') or []}, ''


def verify(domain_id):
    """Ask Resend to go and look at the DNS now.

    Resend checks on its own schedule too; this is the button that says "I have
    added the records", so that somebody who has just done it is not told to
    wait without knowing for how long.
    """
    key = _key()
    if not key:
        return False, {}, 'Email is not configured on this deployment.'
    if not domain_id:
        return False, {}, 'No domain has been registered yet.'
    try:
        r = requests.post(f'{API}/{domain_id}/verify', headers=_headers(key),
                          timeout=TIMEOUT)
    except Exception as e:
        return False, {}, f'Could not reach the email service: {type(e).__name__}'
    if r.status_code not in (200, 201):
        return False, {}, _fail(r)
    return status(domain_id)


def is_verified(state):
    return (state or {}).get('status') == VERIFIED


# ── What this company has, and whether an address may use it ───────────────
#
# One sending domain per company, not one per brand. A cleaning company with a
# commercial trading name sends both from the same domain in practice, and two
# domains to prove is two chances to get stuck before the feature works once.

KEY_NAME = 'sending_domain'
KEY_ID = 'sending_domain_id'
KEY_STATUS = 'sending_domain_status'


def saved():
    """{name, id, status} for this company. Empty strings when unset."""
    from models import BusinessSetting
    try:
        return {
            'name': (BusinessSetting.get(KEY_NAME) or '').strip().lower(),
            'id': (BusinessSetting.get(KEY_ID) or '').strip(),
            'status': (BusinessSetting.get(KEY_STATUS) or '').strip(),
        }
    except Exception:
        return {'name': '', 'id': '', 'status': ''}


def save(name=None, domain_id=None, state=None):
    """Write back whatever we have just learned. Only the parts given."""
    from models import BusinessSetting
    from extensions import db
    if name is not None:
        BusinessSetting.set(KEY_NAME, (name or '').strip().lower())
    if domain_id is not None:
        BusinessSetting.set(KEY_ID, domain_id or '')
    if state is not None:
        BusinessSetting.set(KEY_STATUS, state or '')
    db.session.commit()


def verified_domain():
    """The domain this company has actually proven, or ''.

    Read from what Resend last told us, never from anything the owner typed.
    That is the whole point of this module."""
    s = saved()
    return s['name'] if s['status'] == VERIFIED else ''


def may_send_as(address):
    """True when this address is on the domain this company has proven.

    `sales@yourbusiness.com` passes once that domain is verified;
    `sales@gmail.com` never does, and neither does an address on a domain
    somebody else proved."""
    addr = (address or '').strip().lower()
    good = verified_domain()
    if not addr or '@' not in addr or not good:
        return False
    return addr.rsplit('@', 1)[1] == good


def refresh():
    """Ask Resend where the domain stands and write it down. (ok, state, error)."""
    s = saved()
    if not s['id']:
        return False, {}, 'No domain has been registered yet.'
    ok, data, err = status(s['id'])
    if ok:
        save(state=data.get('status') or '')
    return ok, data, err
