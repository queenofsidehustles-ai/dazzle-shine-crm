"""Brand identities for outgoing quotes and emails.

A cleaning company often sells under more than one name — a residential brand
for homes and apartments, a commercial one for offices, daycares and medical.
Each quote is branded by property type so the email looks like it came from the
right side of the business.

Both identities are read from Settings, not baked into this file. That is what
lets one deployment serve one company and another deployment serve a different
company with no code change. A business with only one name never has to fill in
the commercial fields — the commercial brand quietly falls back to the primary
one, so its quotes simply go out under the single name it actually uses.

The stored keys 'lm' and 'dazzle' predate this and still exist on old Quote
rows, so they are kept as aliases rather than rewritten in the database.
"""
import os

PRIMARY = 'primary'
COMMERCIAL = 'commercial'

# Historic keys still present on saved quotes.
_ALIASES = {'dazzle': PRIMARY, 'lm': COMMERCIAL}

DEFAULT_BRAND = COMMERCIAL

# Property types that belong to the residential/primary side of the business.
_PRIMARY_KEYS = ('apartment', 'student housing', 'property management')

# Fallback palette for email headers when nothing is set. Deliberately neutral —
# a new business sees a plain, professional email rather than someone else's colours.
_DEFAULT_DARK = '#1f2937'
_DEFAULT_ACCENT = '#2563eb'
_DEFAULT_ACCENT_TEXT = '#ffffff'


def _setting(key, default=''):
    try:
        from models import BusinessSetting
        return (BusinessSetting.get(key) or '').strip() or default
    except Exception:
        return default


def normalize(key):
    """Map any stored or passed-in brand key onto a current one."""
    key = (key or DEFAULT_BRAND).strip().lower()
    return _ALIASES.get(key, key if key in (PRIMARY, COMMERCIAL) else DEFAULT_BRAND)


def brand_for_property(property_type):
    pt = (property_type or '').lower()
    return PRIMARY if any(k in pt for k in _PRIMARY_KEYS) else COMMERCIAL


def get_brand(key):
    """Build a brand's identity from Settings, every time it's asked for, so a
    change on the Settings page takes effect on the next email sent."""
    import branding
    key = normalize(key)

    name = branding.biz_name()
    identity = {
        'key': key,
        'name': name,
        'tagline': _setting('brand_tagline', 'Professional Cleaning Proposal'),
        'from_email': branding.from_email(),
        'reply_to': branding.reply_to(),
        'phone': branding.phone(),
        'website': branding.website(),
        'dark': _setting('brand_dark', _DEFAULT_DARK),
        'accent': _setting('brand_accent', _DEFAULT_ACCENT),
        'accent_text': _setting('brand_accent_text', _DEFAULT_ACCENT_TEXT),
        'domain_verified': _setting('brand_domain_verified', '') == '1',
    }

    if key == COMMERCIAL:
        # Only override what the commercial side actually has its own version of;
        # anything left blank keeps the primary business's details.
        overrides = {
            'name': _setting('commercial_name'),
            'tagline': _setting('commercial_tagline'),
            'from_email': _setting('commercial_from_email'),
            'reply_to': _setting('commercial_reply_to'),
            'phone': _setting('commercial_phone'),
            'website': _setting('commercial_website'),
            'dark': _setting('commercial_dark'),
            'accent': _setting('commercial_accent'),
            'accent_text': _setting('commercial_accent_text'),
        }
        identity.update({k: v for k, v in overrides.items() if v})
        identity['domain_verified'] = _setting('commercial_domain_verified', '') == '1'

    return identity


def brand_choices():
    """(key, label) pairs for the quote form's brand picker."""
    return [(PRIMARY, get_brand(PRIMARY)['name']),
            (COMMERCIAL, get_brand(COMMERCIAL)['name'])]


# ── Which side of the business a record belongs to ────────────────────────────
#
# Split on the TYPE OF WORK, not the type of customer. A property management
# company is a business, but the work it buys is cleaning a home between
# tenants — that is residential, and it stays with the primary brand. The
# commercial brand is offices, medical, retail, post-construction, janitorial.
#
# Turnover and make-ready are deliberately primary. They were the case that
# decided the rule: sold to a business, but residential work.

_COMMERCIAL_SERVICES = ('commercial',)
_COMMERCIAL_CATEGORIES = ('medical_office', 'general_contractor', 'office', 'daycare')


def _field(record, name):
    """Read a field off a model row or off a plain dict of search results."""
    if isinstance(record, dict):
        return (record.get(name) or '').lower()
    return (getattr(record, name, '') or '').lower()


def brand_for_lead(lead):
    """Which brand an inbound lead belongs to.

    Anything not positively commercial is primary. Misfiling a commercial lead
    as residential costs one wrong script; the reverse mails a house cleaning
    quote to a facility manager.
    """
    return COMMERCIAL if _field(lead, 'service_type') in _COMMERCIAL_SERVICES else PRIMARY


def brand_for_prospect(prospect):
    """Which brand a cold-call prospect belongs to.

    Property managers, realtors and short-term-rental hosts look commercial and
    are not: what they buy is turnover cleaning. That mistake has already been
    made once by hand, which is why it is written down here.
    """
    return COMMERCIAL if _field(prospect, 'category') in _COMMERCIAL_CATEGORIES else PRIMARY


def backfill(record, derive):
    """Give a record a brand if it predates the split. True if one was set.

    Written once, on the first read after deploy, rather than guessed forever:
    the derived answer becomes a real stored value that can then be corrected
    by hand. Callers commit.
    """
    if getattr(record, 'brand', None):
        return False
    record.brand = derive(record)
    return True


# ── The brand lens: which side of the business is on screen ───────────────────
#
# Held in the session rather than a column, because it is a view preference and
# not a fact about anything. Defaults to ALL so a first load after deploy shows
# the whole CRM — a switcher that starts filtered looks like data loss.

ALL = 'all'


def active():
    """The brand currently being viewed, or ALL."""
    try:
        from flask import session
        key = (session.get('crm_brand') or ALL).strip().lower()
    except Exception:
        return ALL   # outside a request (cron, shell) nothing is filtered
    return key if key in (PRIMARY, COMMERCIAL, ALL) else ALL


def set_active(key):
    from flask import session
    key = normalize_lens(key)
    session['crm_brand'] = key
    return key


def normalize_lens(key):
    key = (key or ALL).strip().lower()
    key = _ALIASES.get(key, key)
    return key if key in (PRIMARY, COMMERCIAL, ALL) else ALL


def lens_choices():
    """(key, label) for the switcher, All first."""
    return [(ALL, 'All brands'),
            (PRIMARY, get_brand(PRIMARY)['name']),
            (COMMERCIAL, get_brand(COMMERCIAL)['name'])]


def in_lens(record, derive, key=None):
    """Does one record belong on screen right now?"""
    key = key or active()
    if key == ALL:
        return True
    return (getattr(record, 'brand', None) or derive(record)) == key


def filter_rows(rows, derive, key=None):
    """Keep the rows belonging to the active brand. ALL keeps everything."""
    key = key or active()
    if key == ALL:
        return list(rows)
    return [r for r in rows if in_lens(r, derive, key)]


def send_identity(key):
    """(from_name, from_email, reply_to) for send_email.

    Mail may only be sent from a domain verified with the email provider. Until
    a brand's own domain is verified we send from the deployment's verified
    default address but keep the brand's display name and reply-to, so the email
    still reads as that brand and replies still reach the right inbox."""
    import branding
    b = get_brand(key)
    verified_default = branding.from_email()
    from_addr = b['from_email'] if b.get('domain_verified') else verified_default
    return b['name'], from_addr, b['reply_to']


def email_shell(key, heading, inner_html, cta_text=None, cta_url=None, footer_note=None):
    """Branded HTML email wrapper used by quote sends and nurture follow-ups."""
    b = get_brand(key)
    cta = ''
    if cta_text and cta_url:
        cta = (f'<div style="text-align:center;margin:24px 0">'
               f'<a href="{cta_url}" style="background:{b["accent"]};color:{b["accent_text"]};'
               f'padding:14px 32px;border-radius:999px;text-decoration:none;font-weight:700;'
               f'font-size:1rem;display:inline-block">{cta_text}</a></div>')
    contact = b['name'] + (' · ' + b['phone'] if b.get('phone') else '')
    foot = footer_note or 'Questions? Just reply to this email.'
    head_html = f'<h2 style="color:{b["accent"]};margin:0 0 14px">{heading}</h2>' if heading else ''
    return f"""
<div style="font-family:Inter,Arial,sans-serif;max-width:600px;margin:0 auto;color:#1f1333">
  <div style="background:{b['dark']};padding:24px;text-align:center;border-radius:12px 12px 0 0">
    <div style="color:#fff;font-size:1.4rem;font-weight:800;margin:0">{b['name']}</div>
    <div style="color:rgba(255,255,255,0.65);margin-top:4px;font-size:0.75rem;letter-spacing:0.14em;text-transform:uppercase">{b['tagline']}</div>
  </div>
  <div style="padding:30px;background:#fff;border:1px solid #e4dfef;border-top:none;border-radius:0 0 12px 12px">
    {head_html}
    {inner_html}
    {cta}
    <hr style="border:none;border-top:1px solid #e4dfef;margin:22px 0">
    <p style="font-size:0.8rem;color:#9a95ad;margin:0">{foot}<br>{contact}</p>
  </div>
</div>"""

def normalise_hex(value, fallback=''):
    """'2563EB', '#25f', ' #2563eb ' -> '#2563eb'. Anything else -> fallback."""
    import re
    v = (value or '').strip().lstrip('#').lower()
    if re.fullmatch(r'[0-9a-f]{3}', v):
        v = ''.join(ch * 2 for ch in v)
    return f'#{v}' if re.fullmatch(r'[0-9a-f]{6}', v) else fallback


def readable_on(background, fallback='#ffffff'):
    """Black or white, whichever a person can actually read on that colour.

    Asked as a third form field this was answered wrong often enough to matter:
    a business picks a soft yellow for its buttons, leaves the text white, and
    ships a booking page whose only button is invisible. Computed with the WCAG
    relative-luminance formula rather than by eyeballing the hex, because a mid
    yellow and a mid blue look nothing alike to an eye even when their numbers
    look similar.
    """
    hexv = normalise_hex(background)
    if not hexv:
        return fallback

    def channel(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = channel(hexv[1:3]), channel(hexv[3:5]), channel(hexv[5:7])
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    on_white = 1.05 / (lum + 0.05)
    on_black = (lum + 0.05) / 0.05
    return '#ffffff' if on_white >= on_black else '#111827'

