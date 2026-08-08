"""One place that knows whose CRM this is.

The application used to hardcode Dazzle & Shine's server address, email
addresses and business name in a couple of hundred places. That was fine while
there was one customer and fatal the moment there were two: a second company's
cleaners would have received job links pointing at the first company's server.

Everything brand-shaped now resolves through here — from environment variables
set per deployment, then from the owner's own settings, and only then from a
neutral fallback. Deploying for a new company means setting env vars and filling
in Settings → Business. No code changes, no forks.
"""
import os


def crm_base():
    """Absolute base URL of THIS deployment.

    Every texted link — job offers, claim pages, My Day, availability, payment
    pages — is built from this. Set CRM_BASE per deployment. Falls back to the
    live request's own host, which is right in almost every case and means a
    misconfigured instance still links to itself rather than to somebody else."""
    configured = (os.environ.get('CRM_BASE') or '').strip().rstrip('/')
    if configured:
        return configured
    try:
        from flask import request, has_request_context
        if has_request_context():
            return request.host_url.rstrip('/')
    except Exception:
        pass
    return ''


def biz_name():
    """The business's name, as it appears to customers and cleaners."""
    try:
        from models import BusinessSetting
        name = (BusinessSetting.get('business_name') or '').strip()
        if name:
            return name
    except Exception:
        pass
    return os.environ.get('BUSINESS_NAME', 'Your Cleaning Company')


def _setting(key, default=''):
    try:
        from models import BusinessSetting
        return (BusinessSetting.get(key) or '').strip() or default
    except Exception:
        return default


def from_email():
    """The address outgoing mail is sent from. Must be a domain verified with
    the email provider for this deployment."""
    return os.environ.get('FROM_EMAIL') or _setting('email') or 'noreply@example.com'


def reply_to():
    """Where replies land — the inbox the owner actually reads.

    Settings first, environment second: the owner can change where her mail goes
    from the Settings page without anyone redeploying the application."""
    return (_setting('email') or os.environ.get('REPLY_TO_EMAIL')
            or os.environ.get('OWNER_EMAIL') or from_email())


def owner_email():
    """Where the CRM sends the owner her own alerts — new bookings, payments,
    failed charges."""
    return (_setting('email') or os.environ.get('NOTIFY_EMAIL')
            or os.environ.get('OWNER_EMAIL') or from_email())


def phone():
    """The business's public phone number, as customers should dial it."""
    return _setting('phone') or os.environ.get('BUSINESS_PHONE', '')


def phone_line(prefix='Call us at '):
    """'Call us at (689) 999-0194' — or nothing at all if no number is set, so
    an unconfigured instance never tells a customer to call a blank."""
    num = phone()
    return f'{prefix}{num}' if num else ''


def website():
    return _setting('website') or os.environ.get('WEBSITE', '')


def booking_link():
    """Where a customer goes to book again. An explicit link if one is set, else
    the owner's own website, else this CRM's own public booking page — so the
    'Book again' button in a receipt always goes somewhere real."""
    explicit = _setting('booking_link')
    if explicit:
        return explicit
    site = website()
    if site:
        return site if site.startswith(('http://', 'https://')) else f'https://{site}'
    return crm_base()


def city_line():
    """'Orlando, FL' for email footers — blank rather than wrong if unset."""
    city = _setting('city')
    state = _setting('state')
    return ', '.join(p for p in (city, state) if p)
