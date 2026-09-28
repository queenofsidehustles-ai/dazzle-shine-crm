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
    """Absolute base URL of THIS business — not of the deployment.

    Every texted link is built from this: job offers, claim pages, My Day,
    availability, payment pages, and the booking form a company embeds in its
    own website.

    `CRM_BASE` used to win outright. On a single-business install that is
    correct. On the hosted product it is one environment variable shared by
    every company on the box, so it would have addressed every cleaner at every
    company to `akyehq.com` — a host where their company does not exist. Every
    claim link and every My Day link, for everybody, pointing at the wrong
    place.

    So when this request belongs to a company, that company's own address wins.
    `CRM_BASE` is the answer only when there is no company in play, which is
    exactly the single-business case it was written for.
    """
    company = _tenant_base()
    if company:
        return company

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


def _tenant_base():
    """This company's own address, or '' if we are not inside one.

    Inside a request the host is already right, so it is used as-is. Outside
    one -- a nightly reminder, a scheduled follow-up -- there is no host to
    read, so it is rebuilt from the schema name and the product domain. A text
    sent by a background job has to reach the same place a text sent by a
    click does.
    """
    try:
        import tenancy
        if not tenancy.is_tenant():
            return ''
    except Exception:
        return ''

    try:
        from flask import request, has_request_context
        if has_request_context():
            return request.host_url.rstrip('/')
    except Exception:
        pass

    try:
        import product
        schema = tenancy.current_schema() or ''
        slug = schema[len(tenancy.SCHEMA_PREFIX):] if schema.startswith(
            tenancy.SCHEMA_PREFIX) else ''
        domain = product.domain()
        if slug and domain:
            return f'{product.scheme_for(domain)}://{slug}.{domain}'
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
    """'Springfield, IL' for email footers — blank rather than wrong if unset."""
    city = _setting('city')
    state = _setting('state')
    return ', '.join(p for p in (city, state) if p)


def version():
    """Which build is actually running, so 'did my change deploy?' has an answer.

    Railway sets RAILWAY_GIT_COMMIT_SHA on every GitHub-triggered deploy. Falls
    back to the local checkout when running on a laptop, and to 'dev' when
    neither is available — a missing version must never take a page down.
    """
    sha = (os.environ.get('RAILWAY_GIT_COMMIT_SHA')
           or os.environ.get('SOURCE_COMMIT')
           # Stamped into the customer image at build time. A container has no
           # .git and none of Railway's git variables, so without this every
           # customer instance would report 'dev' and none could be told apart.
           or os.environ.get('RELEASE_SHA') or '').strip()
    if not sha:
        sha = _git('rev-parse', 'HEAD')
    return sha[:7] if sha else 'dev'


def _git(*args):
    try:
        import subprocess
        return subprocess.run(('git',) + args, capture_output=True, text=True,
                              timeout=2,
                              cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
    except Exception:
        return ''


def release_channel():
    """Which branch this instance deploys from — the release channel.

    'stable' is what a customer's instance follows: it only moves when a release
    is promoted deliberately. 'main' is the channel this business runs itself,
    where a change lands the moment it is pushed. Knowing which one an instance
    is on is the first question when it behaves differently from another.
    """
    branch = (os.environ.get('RAILWAY_GIT_BRANCH') or '').strip()
    if not branch:
        # An image has no branch. It was published from a release tag, so by
        # definition it is on the stable channel.
        if os.environ.get('RELEASE_TAG'):
            return 'stable'
        branch = _git('rev-parse', '--abbrev-ref', 'HEAD')
    return branch or 'unknown'


def release_tag():
    """The release this build belongs to, e.g. 'v2026.08.20'.

    Read from the RELEASE file that release.py writes and commits, not from a
    git tag: the build has no tags. Railway clones the branch to run the app,
    not the repository's history, so `git describe` came back empty on every
    deployed instance — which made the release invisible in exactly the place it
    needed to be visible.
    """
    stamped = (os.environ.get('RELEASE_TAG') or '').strip()
    if stamped:
        return stamped
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'RELEASE')
        with open(path) as f:
            return f.readline().strip()
    except OSError:
        return _git('describe', '--tags', '--abbrev=0') or ''
