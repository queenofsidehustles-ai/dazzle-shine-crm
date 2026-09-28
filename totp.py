"""TOTP two-factor authentication (RFC 6238), from the standard library only.

No new dependency for this: TOTP is HMAC-SHA1 over a 30-second time counter,
which hashlib/hmac already do, and the payload every authenticator app
expects (SHA1, 6 digits, 30-second step) is deliberately the least capable
option here, not the weakest choice made carelessly -- it is what Google
Authenticator, Authy and 1Password all actually implement, and a "stronger"
hash nobody's app supports protects nothing.

Backup codes exist because a lost phone must not be a locked-out account:
generated once at setup, shown once, and usable one time each -- hashed the
same way a password is, never stored or logged in the clear.
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
import urllib.parse

from werkzeug.security import generate_password_hash, check_password_hash

STEP_SECONDS = 30
DIGITS = 6
BACKUP_CODE_COUNT = 8


def generate_secret():
    """A new random TOTP secret, base32-encoded -- the format every
    authenticator app expects to scan or type in."""
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii')


def _code_at(secret, counter):
    padded = secret.upper() + '=' * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded)
    msg = struct.pack('>Q', counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** DIGITS)).zfill(DIGITS)


def verify_totp(secret, code, window=1):
    """True if `code` matches the secret at the current 30-second step, or
    one step either side (window=1) -- ordinary clock drift between this
    server and the phone that generated it, not a security relaxation: the
    window is one step, not an open-ended allowance.
    """
    code = (code or '').strip().replace(' ', '')
    if not secret or not code or not code.isdigit() or len(code) != DIGITS:
        return False
    counter = int(time.time() // STEP_SECONDS)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_code_at(secret, counter + offset), code):
            return True
    return False


def provisioning_uri(secret, username, issuer='Akye'):
    """otpauth:// URI for an authenticator app to add this account -- tap it
    on the phone doing the setup, or type the secret in by hand. No QR image
    generated here; that would need a new dependency for a step every
    authenticator app already supports without one."""
    label = urllib.parse.quote(f'{issuer}:{username}')
    params = urllib.parse.urlencode({
        'secret': secret, 'issuer': issuer, 'algorithm': 'SHA1',
        'digits': DIGITS, 'period': STEP_SECONDS,
    })
    return f'otpauth://totp/{label}?{params}'


def format_secret(secret):
    """Grouped in 4s for a human typing it in by hand: 'ABCD EFGH ...'."""
    return ' '.join(secret[i:i + 4] for i in range(0, len(secret), 4))


def generate_backup_codes():
    """BACKUP_CODE_COUNT fresh codes, plain text -- shown to the user exactly
    once, at generation time, by the caller. Never returned again after this."""
    return [f'{secrets.randbelow(10**8):08d}' for _ in range(BACKUP_CODE_COUNT)]


def hash_backup_codes(codes):
    """JSON-encoded list of hashes, for User.totp_backup_codes. Same hashing
    as a password -- these ARE a password, usable exactly once each."""
    return json.dumps([generate_password_hash(c, method='pbkdf2:sha256') for c in codes])


def consume_backup_code(stored_json, code):
    """If `code` matches one of the stored hashes, return the remaining set
    (that one removed) to save back -- the caller commits it. Returns None if
    no match, meaning nothing should be changed."""
    code = (code or '').strip().replace(' ', '').replace('-', '')
    if not stored_json or not code:
        return None
    try:
        hashes = json.loads(stored_json)
    except (TypeError, ValueError):
        return None
    for h in hashes:
        if check_password_hash(h, code):
            remaining = [x for x in hashes if x != h]
            return json.dumps(remaining)
    return None
