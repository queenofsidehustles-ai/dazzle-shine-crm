"""Private media boundary for tenant-sensitive receipts and job photos.

Cloudinary HTTPS URLs are not authorization. This module uploads sensitive
images as ``authenticated`` Cloudinary assets and stores only an opaque,
HMAC-authenticated Akye reference. Callers must supply the current tenant and,
for public-token flows, the exact object scope before a reference can be
resolved.

The signed Cloudinary delivery URL is used only server-to-server and is never
returned to the browser. If Cloudinary signing credentials are unavailable,
operations fail closed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
from typing import Any

import requests
from werkzeug.exceptions import Conflict

_PREFIX = "akye-media:v1:"
_MAX_BYTES = 10 * 1024 * 1024
_ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}


def is_ready() -> bool:
    import integrations
    return integrations.photos_ready()


def _signing_key() -> bytes:
    import integrations
    secret = integrations.cloudinary_api_secret()
    if not secret:
        raise RuntimeError("Private media signing is not configured")
    return secret.encode("utf-8")


def _configure():
    import integrations
    if not is_ready():
        raise RuntimeError("Private media storage is not configured")
    import cloudinary
    cloudinary.config(
        cloud_name=integrations.cloudinary_cloud_name(),
        api_key=integrations.cloudinary_api_key(),
        api_secret=integrations.cloudinary_api_secret(),
        secure=True,
    )


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(token: str) -> bytes:
    token += "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token.encode("ascii"))


def _encode(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_signing_key(), raw, hashlib.sha256).digest()
    return _PREFIX + _b64encode(raw) + "." + _b64encode(signature)


def parse_ref(ref: str, *, tenant_slug: str, kind: str | None = None,
              scope_id: int | str | None = None) -> dict[str, Any] | None:
    """Return a validated reference payload, or ``None`` on any mismatch.

    The reference is authenticated before any tenant, kind, scope or asset
    metadata is trusted. A copied or edited token therefore cannot make Akye
    sign delivery for a different Cloudinary authenticated asset.
    """
    if not isinstance(ref, str) or not ref.startswith(_PREFIX):
        return None
    try:
        token = ref[len(_PREFIX):]
        encoded_payload, encoded_signature = token.split(".", 1)
        raw = _b64decode(encoded_payload)
        supplied_signature = _b64decode(encoded_signature)
        expected_signature = hmac.new(_signing_key(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        payload = json.loads(raw)
    except Exception:
        return None

    if payload.get("v") != 1 or payload.get("tenant") != tenant_slug:
        return None
    if kind is not None and payload.get("kind") != kind:
        return None
    if scope_id is not None and str(payload.get("scope")) != str(scope_id):
        return None

    required = ("public_id", "version", "format", "resource_type")
    if any(not payload.get(k) for k in required):
        return None

    expected_folder = f"akye-private/{tenant_slug}/{payload.get('kind')}/"
    if not str(payload["public_id"]).startswith(expected_folder):
        return None

    return payload


def _assert_job_photo_mutable(kind: str, scope_id: int | str | None) -> None:
    """Reject checklist evidence mutation after the cleaner submits the photo set.

    Job-photo scopes are created by the work-order route as ``<checklist>:<phase>``.
    The tenant schema has already been selected from the trusted request host, so
    this lookup is tenant-local. The check deliberately runs before file bytes
    are read or Cloudinary is configured, ensuring a stale public checklist token
    cannot add evidence after review/payment state has begun.
    """
    if kind != "job-photo":
        return

    scope = "" if scope_id is None else str(scope_id)
    checklist_id, separator, phase = scope.partition(":")
    if not separator or phase not in ("before", "after") or not checklist_id.isdigit():
        raise ValueError("Invalid job-photo scope")

    from models import JobChecklist
    checklist = JobChecklist.query.get(int(checklist_id))
    if checklist is None:
        raise ValueError("Checklist scope not found")
    if checklist.photos_submitted_at:
        raise Conflict(description="Submitted checklist photo evidence is immutable")


def upload_image(file_storage, *, tenant_slug: str, kind: str,
                 scope_id: int | str | None = None) -> str:
    """Upload one image as a Cloudinary authenticated asset and return its ref."""
    if not tenant_slug or not kind:
        raise ValueError("tenant_slug and kind are required")
    if file_storage is None or not getattr(file_storage, "filename", ""):
        raise ValueError("Choose an image first")

    _assert_job_photo_mutable(kind, scope_id)

    raw = file_storage.read()
    if not raw:
        raise ValueError("The image is empty")
    if len(raw) > _MAX_BYTES:
        raise ValueError("The image is larger than 10MB")
    ctype = (getattr(file_storage, "mimetype", "") or "").lower().split(";")[0]
    if ctype not in _ALLOWED_TYPES:
        raise ValueError("Upload a JPG, PNG, WEBP or HEIC image")

    _configure()
    import cloudinary.uploader
    folder = f"akye-private/{tenant_slug}/{kind}"
    result = cloudinary.uploader.upload(
        io.BytesIO(raw),
        resource_type="image",
        type="authenticated",
        folder=folder,
        use_filename=False,
        unique_filename=True,
        overwrite=False,
    )
    payload = {
        "v": 1,
        "tenant": tenant_slug,
        "kind": kind,
        "scope": None if scope_id is None else str(scope_id),
        "public_id": result["public_id"],
        "version": result["version"],
        "format": result["format"],
        "resource_type": result.get("resource_type", "image"),
    }
    return _encode(payload)


def fetch_image(ref: str, *, tenant_slug: str, kind: str | None = None,
                scope_id: int | str | None = None) -> tuple[bytes, str] | None:
    """Fetch an authenticated asset server-to-server after scope validation."""
    payload = parse_ref(ref, tenant_slug=tenant_slug, kind=kind, scope_id=scope_id)
    if not payload:
        return None
    _configure()
    import cloudinary.utils
    url, _options = cloudinary.utils.cloudinary_url(
        payload["public_id"],
        resource_type=payload["resource_type"],
        type="authenticated",
        version=payload["version"],
        format=payload["format"],
        secure=True,
        sign_url=True,
    )
    response = requests.get(url, timeout=15)
    if response.status_code != 200:
        return None
    content_type = response.headers.get("Content-Type") or "application/octet-stream"
    return response.content, content_type


def upload_params(*, tenant_slug: str, kind: str,
                  resource_type: str = "video") -> dict[str, Any]:
    """Signed parameters for an upload the browser makes directly.

    A video is recorded in the applicant's browser and is far too large to post
    through this server, so it goes straight to Cloudinary. That used to mean an
    unsigned preset, with the browser naming its own folder -- which is why every
    recording landed in a flat `interviews/` with no tenant in the path, and why
    any client could have named any other path it liked.

    Signing fixes both. The folder and the delivery type are inside the
    signature, so a client that edits them is rejected by Cloudinary rather than
    by us noticing later.
    """
    import time
    import integrations
    _configure()
    import cloudinary.utils
    folder = f"akye-private/{tenant_slug}/{kind}"
    params = {"folder": folder, "type": "authenticated",
              "timestamp": int(time.time())}
    signature = cloudinary.utils.api_sign_request(
        params, integrations.cloudinary_api_secret())
    return {
        "url": f"https://api.cloudinary.com/v1_1/"
               f"{integrations.cloudinary_cloud_name()}/{resource_type}/upload",
        "api_key": integrations.cloudinary_api_key(),
        "folder": folder,
        "type": "authenticated",
        "timestamp": params["timestamp"],
        "signature": signature,
    }


def ref_from_upload(result: dict[str, Any], *, tenant_slug: str, kind: str,
                    scope_id: int | str | None = None) -> str | None:
    """Turn Cloudinary's own upload reply into a signed reference, or None.

    The reply is relayed by the browser, so it is not trusted. The public_id has
    to sit inside this tenant's folder before a reference is minted for it --
    otherwise a client could hand back somebody else's asset and have this
    server sign delivery for it.
    """
    public_id = str(result.get("public_id") or "")
    expected_folder = f"akye-private/{tenant_slug}/{kind}/"
    if not public_id.startswith(expected_folder):
        return None
    version = result.get("version")
    fmt = result.get("format")
    resource_type = result.get("resource_type")
    if not all((version, fmt, resource_type)):
        return None
    payload = {
        "v": 1, "tenant": tenant_slug, "kind": kind,
        "scope": None if scope_id is None else str(scope_id),
        "public_id": public_id, "version": str(version),
        "format": str(fmt), "resource_type": str(resource_type),
    }
    return _encode(payload)


def signed_url(ref: str, *, tenant_slug: str, kind: str | None = None,
               scope_id: int | str | None = None) -> str | None:
    """A signed delivery URL for an authenticated asset, or None.

    Video is served by redirecting the browser here rather than by this server
    fetching the bytes as it does for a photo: a recording is tens of megabytes
    and needs range requests, and proxying it would put the whole file through
    a worker for every scrub of the timeline.
    """
    payload = parse_ref(ref, tenant_slug=tenant_slug, kind=kind, scope_id=scope_id)
    if not payload:
        return None
    # A provider that is not configured should cost this one video, not the
    # whole review page. Without this, a missing cloud name raises while the
    # URL is assembled and the owner gets a 500 instead of an applicant.
    try:
        _configure()
        import cloudinary.utils
        url, _options = cloudinary.utils.cloudinary_url(
            payload["public_id"],
            resource_type=payload["resource_type"],
            type="authenticated",
            version=payload["version"],
            format=payload["format"],
            secure=True,
            sign_url=True,
        )
    except Exception:
        return None
    return url or None


def is_private_ref(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)
