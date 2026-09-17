"""TEN-07 contract for checklist before/after photos.

These static assertions prevent the public work-order page from regressing to
browser-direct Cloudinary uploads or accepting arbitrary provider URLs as
stored authorization-bearing media. Runtime tenant/token/object tests are added
with the server-side implementation.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKORDERS = (ROOT / 'blueprints' / 'workorders.py').read_text()
CHECKLIST = (ROOT / 'templates' / 'public' / 'checklist.html').read_text()


def test_checklist_template_does_not_upload_directly_to_cloudinary():
    assert 'api.cloudinary.com' not in CHECKLIST
    assert 'UPLOAD_PRESET' not in CHECKLIST
    assert 'CLOUD_NAME' not in CHECKLIST


def test_checklist_template_does_not_render_stored_media_refs_directly():
    assert "'<img src=\"' + url + '\" />'" not in CHECKLIST
    assert 'cloud.secure_url' not in CHECKLIST


def test_add_photo_does_not_accept_client_supplied_url():
    assert "data.get('url')" not in WORKORDERS
    assert "data.get(\"url\")" not in WORKORDERS
    assert "request.files.get('photo')" in WORKORDERS


def test_job_photos_use_private_media_boundary():
    assert 'private_media.upload_image' in WORKORDERS
    assert "kind='job-photo'" in WORKORDERS
    assert 'private_media.fetch_image' in WORKORDERS
    assert 'Cache-Control' in WORKORDERS
    assert 'private, no-store' in WORKORDERS
