"""Brand identities for outgoing commercial quotes/emails.

Two brands share the one CRM:
  - 'lm'     = L & M Commercial Cleaners (offices, daycares, medical, retail…)
  - 'dazzle' = Dazzle & Shine Maids (apartments + property managers)

Each quote is auto-branded by property type, and every quote email uses the
right name, colors, and reply-to so it looks like it came from that brand.
"""
import os

BRANDS = {
    'lm': {
        'key': 'lm',
        'name': 'L & M Commercial Cleaners',
        'tagline': 'Commercial Cleaning Proposal',
        'from_email': 'admin@commercialcleanersorlando.com',
        'reply_to': 'admin@commercialcleanersorlando.com',
        'phone': '',
        'website': 'www.commercialcleanersorlando.com',
        'dark': '#12324a',
        'accent': '#2a89c4',
        'accent_text': '#ffffff',
        # Flip True once commercialcleanersorlando.com is verified in Resend,
        # then quotes will send FROM admin@commercialcleanersorlando.com.
        'domain_verified': False,
    },
    'dazzle': {
        'key': 'dazzle',
        'name': 'Dazzle & Shine Maids',
        'tagline': 'Professional Cleaning Proposal',
        'from_email': 'bookings@dazzleandshinemaids.com',
        'reply_to': 'dazzleandshinemaids@gmail.com',
        'phone': '(689) 999-0194',
        'website': 'www.dazzleandshinemaids.com',
        'dark': '#1f1333',
        'accent': '#d3a84f',
        'accent_text': '#1f1333',
        'domain_verified': True,
    },
}

DEFAULT_BRAND = 'lm'
# Property types that belong to the Dazzle (residential-adjacent) side.
_DAZZLE_KEYS = ('apartment', 'student housing', 'property management')


def brand_for_property(property_type):
    pt = (property_type or '').lower()
    return 'dazzle' if any(k in pt for k in _DAZZLE_KEYS) else 'lm'


def get_brand(key):
    return BRANDS.get(key or DEFAULT_BRAND, BRANDS[DEFAULT_BRAND])


def send_identity(key):
    """(from_name, from_email, reply_to) for send_email. Until a brand's domain
    is verified in Resend we send from the verified default address, but keep the
    brand's display name and reply-to so replies reach the right inbox."""
    b = get_brand(key)
    verified_default = os.environ.get('FROM_EMAIL', 'bookings@dazzleandshinemaids.com')
    from_email = b['from_email'] if b.get('domain_verified') else verified_default
    return b['name'], from_email, b['reply_to']


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
