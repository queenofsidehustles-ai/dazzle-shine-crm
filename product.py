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


def base_url():
    d = domain()
    if not d:
        return ''
    scheme = 'http' if d.startswith('localhost') else 'https'
    return f'{scheme}://{d}'


def support_email():
    d = domain()
    return os.environ.get('PRODUCT_SUPPORT_EMAIL') or (f'help@{d}' if d else '')


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
