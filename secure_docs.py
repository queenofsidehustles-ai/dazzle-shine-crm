"""Encrypted storage for the documents that would hurt if they leaked.

A driver's licence, a W-9 and a background check are the three things this CRM
holds that a thief would actually want: a government ID number, a social
security number, and someone's criminal history. Everything else uploaded here —
job photos, expense receipts — goes to Cloudinary through an unsigned preset,
which returns a long random URL that is nonetheless *public*. Anyone who obtains
that URL can open the file forever, with no login. For a before-and-after photo
of a kitchen that is a fair trade. For an SSN it is not.

So these three never leave the application. The bytes are encrypted and written
to the database, and the only way back out is a route behind the owner's login.
No public URL for them is ever created, which means there is none to leak,
forward, or find in a browser history.

The key is derived from SECRET_KEY. That has two consequences worth knowing:
rotating SECRET_KEY makes existing documents unreadable, and a deployment whose
SECRET_KEY is the development default is not meaningfully encrypted. is_ready()
reports the second case so the UI can say so out loud rather than implying a
protection that isn't there.
"""
import base64
import hashlib
import os

_DEV_DEFAULT = 'dev-secret-change-me'

# One document should never be big enough to need this much room. The cap is
# here so a bad or hostile upload can't fill the database.
MAX_BYTES = 8 * 1024 * 1024

ALLOWED_TYPES = {
    'application/pdf': 'pdf',
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/heic': 'heic',
    'image/heif': 'heif',
    'image/webp': 'webp',
}


def _secret():
    return os.environ.get('SECRET_KEY', _DEV_DEFAULT)


def is_ready():
    """False when SECRET_KEY is missing or still the shipped default, which
    would make the encryption theatre rather than protection."""
    s = _secret()
    return bool(s) and s != _DEV_DEFAULT


def _fernet():
    from cryptography.fernet import Fernet
    # Fernet wants 32 url-safe base64 bytes; SECRET_KEY is an arbitrary string.
    digest = hashlib.sha256(_secret().encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(raw: bytes) -> bytes:
    return _fernet().encrypt(raw)


def decrypt(blob: bytes) -> bytes:
    """Plaintext, or None if this blob can't be read with the current key —
    which is what a rotated SECRET_KEY looks like from here."""
    try:
        return _fernet().decrypt(blob)
    except Exception:
        return None


def check_upload(file_storage):
    """(ok, error_message, content_type, raw_bytes) for an incoming file.

    Reads it fully to measure it: Content-Length on a multipart part is a claim
    by the sender, and the point of the cap is to not trust that."""
    if file_storage is None or not getattr(file_storage, 'filename', ''):
        return False, 'Please choose a file first.', None, None

    raw = file_storage.read()
    if not raw:
        return False, 'That file came through empty — please try again.', None, None
    if len(raw) > MAX_BYTES:
        mb = MAX_BYTES // (1024 * 1024)
        return False, f'That file is larger than {mb}MB. Please send a smaller photo or PDF.', None, None

    ctype = (file_storage.mimetype or '').lower().split(';')[0]
    if ctype not in ALLOWED_TYPES:
        return False, 'Please send a PDF or a photo (JPG, PNG or HEIC).', None, None

    return True, None, ctype, raw
