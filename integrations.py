"""The keys that connect this CRM to Stripe, Twilio and the email service.

These used to be readable only from environment variables, which meant only
somebody with access to the hosting dashboard could connect a business's payment
processor. That does not scale: the person selling the CRM would end up holding
every customer's Stripe credentials, and would be a required step in every
setup, every key rotation and every outage at 6am on a Saturday.

So an owner can now enter her own keys in Settings → Connections and never hand
them to anybody. Environment variables still work and are still the better place
for them if you have dashboard access — they are simply no longer the only way.

Order of precedence: a key saved in Settings wins over the environment. That way
what an owner types always takes effect; a setting that silently did nothing
because of an environment variable she cannot see would be far worse than the
alternative.

Stored keys are encrypted with a key derived from SECRET_KEY, so a leaked
database backup does not hand over a live payment processor.
"""
import base64
import hashlib
import os

# name -> (environment variable, label, is_secret)
FIELDS = {
    'stripe_secret_key':      ('STRIPE_SECRET_KEY', 'Stripe secret key', True),
    'stripe_publishable_key': ('STRIPE_PUBLISHABLE_KEY', 'Stripe publishable key', False),
    'twilio_account_sid':     ('TWILIO_ACCOUNT_SID', 'Twilio account SID', False),
    'twilio_auth_token':      ('TWILIO_AUTH_TOKEN', 'Twilio auth token', True),
    'twilio_phone':           ('TWILIO_PHONE', 'Twilio phone number', False),
    'resend_api_key':         ('RESEND_API_KEY', 'Resend API key', True),
    'stripe_webhook_secret':  ('STRIPE_WEBHOOK_SECRET', 'Stripe webhook signing secret', True),
}

_PREFIX = 'int_'
_ENC = 'enc:'


def _cipher():
    """A Fernet cipher keyed off SECRET_KEY.

    Changing SECRET_KEY makes previously saved keys unreadable — they are not
    lost data, just credentials that have to be pasted in again."""
    from cryptography.fernet import Fernet
    seed = (os.environ.get('SECRET_KEY') or 'insecure-dev-key').encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed).digest()))


def _stored(name):
    """The raw value saved in Settings, decrypted. Empty if unset or unreadable."""
    try:
        from models import BusinessSetting
        raw = (BusinessSetting.get(_PREFIX + name) or '').strip()
    except Exception:
        return ''
    if not raw:
        return ''
    if not raw.startswith(_ENC):
        return raw                       # saved before encryption existed
    try:
        return _cipher().decrypt(raw[len(_ENC):].encode()).decode()
    except Exception:
        # Wrong SECRET_KEY, or a corrupted value. Report as unset rather than
        # crashing a payment page.
        return ''


def get(name):
    """The key this CRM should actually use. Settings first, environment second."""
    env_var = FIELDS.get(name, (None,))[0]
    return _stored(name) or (os.environ.get(env_var, '') if env_var else '') or ''


def source(name):
    """Where the value in use came from — for showing the owner what's what."""
    if _stored(name):
        return 'settings'
    env_var = FIELDS.get(name, (None,))[0]
    if env_var and os.environ.get(env_var):
        return 'environment'
    return None


def set(name, value):
    """Save a key. An empty value clears it and falls back to the environment."""
    from models import BusinessSetting
    from extensions import db
    value = (value or '').strip()
    if not value:
        BusinessSetting.set(_PREFIX + name, '')
    else:
        BusinessSetting.set(_PREFIX + name, _ENC + _cipher().encrypt(value.encode()).decode())
    db.session.commit()


def masked(name):
    """'sk_live_…4242' — enough to recognise a key, not enough to use it.

    A saved secret is never sent back to the browser in full. Someone who gets
    at an admin session should not walk away with a live payment key."""
    value = get(name)
    if not value:
        return ''
    if not FIELDS.get(name, (None, None, True))[2]:
        return value                     # publishable / SID / phone aren't secret
    return f'{value[:7]}…{value[-4:]}' if len(value) > 14 else '•' * 8


# ── Named accessors, so call sites read plainly ───────────────────────────────

def stripe_secret_key():      return get('stripe_secret_key')
def stripe_publishable_key(): return get('stripe_publishable_key')
def twilio_account_sid():     return get('twilio_account_sid')
def twilio_auth_token():      return get('twilio_auth_token')
def twilio_phone():           return get('twilio_phone')
def resend_api_key():         return get('resend_api_key')
def stripe_webhook_secret():  return get('stripe_webhook_secret')


def stripe_ready():
    return bool(stripe_secret_key())


def texting_ready():
    return all((twilio_account_sid(), twilio_auth_token(), twilio_phone()))


def email_ready():
    return bool(resend_api_key())


def stripe_mode():
    """'live', 'test' or None — worth showing an owner prominently, because
    taking real bookings against test keys collects no money at all."""
    key = stripe_secret_key()
    if not key:
        return None
    return 'live' if key.startswith('sk_live') else 'test'


def missing_for(area):
    """Which fields are still blank for one integration, by label."""
    groups = {
        'stripe': ['stripe_secret_key', 'stripe_publishable_key'],
        'texting': ['twilio_account_sid', 'twilio_auth_token', 'twilio_phone'],
        'email': ['resend_api_key'],
    }
    return [FIELDS[n][1] for n in groups.get(area, []) if not get(n)]


def status():
    """A plain-language readiness summary for the setup checklist."""
    return {
        'stripe': {'ready': stripe_ready(), 'mode': stripe_mode(),
                   'missing': missing_for('stripe')},
        'texting': {'ready': texting_ready(), 'missing': missing_for('texting')},
        'email': {'ready': email_ready(), 'missing': missing_for('email')},
    }
