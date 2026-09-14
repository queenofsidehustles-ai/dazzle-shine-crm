"""TEN-07: private media references are tenant- and object-scoped."""
import base64
import json

import private_media


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
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return "akye-media:v1:" + token


def test_private_media_ref_accepts_exact_tenant_kind_and_scope():
    parsed = private_media.parse_ref(
        _ref(), tenant_slug="alpha", kind="job-photo", scope_id=42)
    assert parsed is not None
    assert parsed["public_id"].endswith("abc123")


def test_private_media_ref_rejects_cross_tenant_replay():
    assert private_media.parse_ref(
        _ref(), tenant_slug="beta", kind="job-photo", scope_id=42) is None


def test_private_media_ref_rejects_cross_object_replay():
    assert private_media.parse_ref(
        _ref(), tenant_slug="alpha", kind="job-photo", scope_id=99) is None


def test_private_media_ref_rejects_kind_confusion():
    assert private_media.parse_ref(
        _ref(), tenant_slug="alpha", kind="receipt", scope_id=42) is None


def test_public_cloudinary_url_is_not_a_private_media_ref():
    assert not private_media.is_private_ref(
        "https://res.cloudinary.com/example/image/upload/v1/receipt.jpg")
    assert private_media.parse_ref(
        "https://res.cloudinary.com/example/image/upload/v1/receipt.jpg",
        tenant_slug="alpha") is None


def test_malformed_ref_fails_closed():
    assert private_media.parse_ref("akye-media:v1:not-base64", tenant_slug="alpha") is None
