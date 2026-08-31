"""The product's own identity, which is not any customer's identity.

There are two brands in this codebase now and keeping them apart matters more
than it sounds.

`branding.py` answers "whose CRM is this?" -- the cleaning company's name, their
colours, their review link. It is what a cleaner sees on a job text and what a
customer sees on an invoice. Every one of those has to be the *customer's*
business, which is the entire point of the white-label work that came before.

This answers a different question: "what is the thing they subscribe to?" It
appears on the marketing site, the signup page, the receipt for the
subscription, and nowhere else. A cleaning company's own customers should never
see it, and if this name ever turns up on somebody's invoice, that is a bug.

Everything is overridable by environment variable so the name can change without
a code change -- which it will, because it is a placeholder until the trademark
search comes back.
"""
import os

# Placeholder. Akye is Akan -- it is in "maakye", good morning -- which is when
# a cleaning crew starts, and is the story the name is meant to carry.
DEFAULT_NAME = 'Akye'
DEFAULT_TAGLINE = 'Hire your crew, pay them per job, and know the work got done.'


def name():
    return (os.environ.get('PRODUCT_NAME') or DEFAULT_NAME).strip()


def tagline():
    return (os.environ.get('PRODUCT_TAGLINE') or DEFAULT_TAGLINE).strip()


def domain():
    """The product's own domain. Empty on a single-business deployment, which
    is how everything here knows to stay out of the way."""
    return (os.environ.get('BASE_DOMAIN') or '').strip()


def scheme_for(host):
    """http for a local host, https for a real one.

    `startswith('localhost')` was wrong the moment the preview ran on
    `akye.localhost:5055` -- the name is in the middle, not at the front, so
    every local link came out as https and refused to connect."""
    h = (host or '').lower()
    local = ('localhost' in h or h.startswith('127.0.0.1')
             or h.startswith('0.0.0.0') or h.endswith('.local'))
    return 'http' if local else 'https'


def base_url():
    d = domain()
    if not d:
        return ''
    return f'{scheme_for(d)}://{d}'


DEFAULT_SUPPORT = 'support@akyehq.com'


def support_email():
    """Where a customer writes when something is wrong.

    Falls back to the deployment's own domain rather than a hardcoded address,
    so a private deployment does not point people at us -- but on the product
    itself this is the address on the terms, the privacy policy and every
    receipt, and it has to be one somebody is actually reading."""
    explicit = (os.environ.get('PRODUCT_SUPPORT_EMAIL') or '').strip()
    if explicit:
        return explicit
    d = domain()
    if not d:
        return ''
    return DEFAULT_SUPPORT if d == 'akyehq.com' else f'support@{d}'


def from_email():
    """The address the product's own mail is sent FROM.

    Separate from `support_email()` because they are answers to different
    questions. Support is where a person writes to reach us, and can be a
    Gmail address behind a forward. This one has to be on a domain verified
    with the email provider, or nothing sends at all — so it is set
    explicitly, and falls back to the support address only because on a
    properly-configured deployment they are the same thing.
    """
    explicit = (os.environ.get('PRODUCT_FROM_EMAIL') or '').strip()
    return explicit or support_email()


def resend_api_key():
    """The PRODUCT's own email key, from the environment only.

    Deliberately not `integrations.resend_api_key()`, which reads the settings
    of whichever cleaning company the current request belongs to. Our mail
    goes out on our key; theirs goes out on theirs. Mixing the two would bill
    a customer for our crash alerts and put them in their sending logs.
    """
    return (os.environ.get('PRODUCT_RESEND_API_KEY')
            or os.environ.get('RESEND_API_KEY') or '').strip()


def mail_status():
    """Whether the product can actually email anybody, and what is missing.

    Written because "I think I set that up" and "an email arrived" are
    different claims, and only the second one is worth anything. The same
    lesson as the backups: a thing nobody has tested is not a working thing,
    it is an assumption with a config value attached.

    Returns a dict, always. `problem` is None when it should work.
    """
    if not domain():
        # Not the hosted product. There is no product mail to send.
        return {'applies': False, 'problem': None, 'to': '', 'from': '',
                'key': False}
    to, sender, key = support_email(), from_email(), resend_api_key()
    problem = None
    if not key:
        problem = ('No email key. Set PRODUCT_RESEND_API_KEY (or RESEND_API_KEY) '
                   'or the product cannot send trial reminders or crash alerts.')
    elif not to:
        problem = ('No support address. Set PRODUCT_SUPPORT_EMAIL to an inbox '
                   'somebody reads, or crash alerts go nowhere.')
    elif not sender:
        problem = 'No from-address. Set PRODUCT_FROM_EMAIL.'
    elif '@' not in sender:
        problem = f'PRODUCT_FROM_EMAIL is not an email address: {sender!r}'
    return {'applies': True, 'problem': problem, 'to': to, 'from': sender,
            'key': bool(key)}


# Who is legally on the other side of the terms of service. This is OUR
# company -- the one selling the software -- and it is deliberately not in
# `branding.py`, which holds the details of the cleaning business that a given
# CRM belongs to. Confusing the two would put our address on a customer's
# invoice, or theirs on our privacy policy.
#
# It is overridable so that a private deployment states its own entity rather
# than ours, and blank on a deployment that has not set one, because a legal
# page that names the wrong company is worse than one that names none.
DEFAULT_LEGAL_ENTITY  = 'Yaa Mansa LLC'
DEFAULT_LEGAL_ADDRESS = '1317 Edgewater Drive\nOrlando, FL'


def legal_entity():
    """The company name on the terms, the privacy policy and the invoices."""
    explicit = (os.environ.get('PRODUCT_LEGAL_ENTITY') or '').strip()
    if explicit:
        return explicit
    return DEFAULT_LEGAL_ENTITY if domain() == 'akyehq.com' else ''


def legal_address():
    """The registered address that goes with it. Lines, for a template."""
    explicit = (os.environ.get('PRODUCT_LEGAL_ADDRESS') or '').strip()
    raw = explicit or (DEFAULT_LEGAL_ADDRESS if domain() == 'akyehq.com' else '')
    return [ln.strip() for ln in raw.split('\n') if ln.strip()]


def is_product_site():
    """True only on the product's own domain, signed out or not.

    False on a company's subdomain and false on a single-business instance, so
    the marketing pages cannot appear over somebody's CRM."""
    if not domain():
        return False
    try:
        import tenancy
        from flask import request
        return tenancy.slug_from_host(request.host, domain()) is None
    except Exception:
        return False
