"""TEN-07: private media references are cryptographically tenant- and object-scoped."""
import base64
import hashlib
import hmac
import json

import private_media

_SIGNING_SECRET = "test-private-media-signing-secret"


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _ref(**overrides):
    payload = {
        "v": 1,
        "tenant": "alpha",
        "kind": "job-photo",
        "scope": "42",
        "public_id": "akye-private/alpha/job-photo/abc123",
        "version": 1234567890,
        "format": "jpg",
        "resource_type": "image",
    }
    payload.update(overrides)
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_SIGNING_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
    return "akye-media:v1:" + _b64(raw) + "." + _b64(signature)


def _set_signing_key(monkeypatch):
    monkeypatch.setenv("CLOUDINARY_API_SECRET", _SIGNING_SECRET)


def test_private_media_ref_accepts_exact_tenant_kind_and_scope(monkeypatch):
    _set_signing_key(monkeypatch)
    parsed = private_media.parse_ref(
        _ref(), tenant_slug="alpha", kind="job-photo", scope_id=42)
    assert parsed is not None
    assert parsed["public_id"].endswith("abc123")


def test_private_media_ref_rejects_cross_tenant_replay(monkeypatch):
    _set_signing_key(monkeypatch)
    assert private_media.parse_ref(
        _ref(), tenant_slug="beta", kind="job-photo", scope_id=42) is None


def test_private_media_ref_rejects_cross_object_replay(monkeypatch):
    _set_signing_key(monkeypatch)
    assert private_media.parse_ref(
        _ref(), tenant_slug="alpha", kind="job-photo", scope_id=99) is None


def test_private_media_ref_rejects_kind_confusion(monkeypatch):
    _set_signing_key(monkeypatch)
    assert private_media.parse_ref(
        _ref(), tenant_slug="alpha", kind="receipt", scope_id=42) is None


def test_private_media_ref_rejects_payload_tampering(monkeypatch):
    _set_signing_key(monkeypatch)
    ref = _ref()
    prefix, token = ref.rsplit(":", 1)
    encoded_payload, signature = token.split(".", 1)
    padding = "=" * (-len(encoded_payload) % 4)
    payload = json.loads(base64.urlsafe_b64decode((encoded_payload + padding).encode("ascii")))
    payload["public_id"] = "akye-private/alpha/job-photo/other-secret-asset"
    tampered_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    tampered = prefix + ":" + _b64(tampered_raw) + "." + signature
    assert private_media.parse_ref(
        tampered, tenant_slug="alpha", kind="job-photo", scope_id=42) is None


def test_private_media_ref_rejects_asset_outside_bound_folder(monkeypatch):
    _set_signing_key(monkeypatch)
    assert private_media.parse_ref(
        _ref(public_id="akye-private/beta/job-photo/abc123"),
        tenant_slug="alpha", kind="job-photo", scope_id=42) is None


def test_public_cloudinary_url_is_not_a_private_media_ref(monkeypatch):
    _set_signing_key(monkeypatch)
    assert not private_media.is_private_ref(
        "https://res.cloudinary.com/example/image/upload/v1/receipt.jpg")
    assert private_media.parse_ref(
        "https://res.cloudinary.com/example/image/upload/v1/receipt.jpg",
        tenant_slug="alpha") is None


def test_unsigned_legacy_ref_fails_closed(monkeypatch):
    _set_signing_key(monkeypatch)
    payload = {
        "v": 1,
        "tenant": "alpha",
        "kind": "job-photo",
        "scope": "42",
        "public_id": "akye-private/alpha/job-photo/abc123",
        "version": 1,
        "format": "jpg",
        "resource_type": "image",
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    unsigned = "akye-media:v1:" + _b64(raw)
    assert private_media.parse_ref(unsigned, tenant_slug="alpha") is None


def test_missing_signing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("CLOUDINARY_API_SECRET", raising=False)
    assert private_media.parse_ref(
        _ref(), tenant_slug="alpha", kind="job-photo", scope_id=42) is None


def test_malformed_ref_fails_closed(monkeypatch):
    _set_signing_key(monkeypatch)
    assert private_media.parse_ref("akye-media:v1:not-base64", tenant_slug="alpha") is None
