"""TEN-07: submitted checklist photo evidence is immutable."""
from types import ModuleType, SimpleNamespace
import sys

import pytest
from werkzeug.exceptions import Conflict

import private_media


class _UnreadablePhoto:
    filename = "after.jpg"
    mimetype = "image/jpeg"

    def read(self):
        raise AssertionError("finalized evidence must be rejected before reading file bytes")


def test_finalized_checklist_rejects_photo_before_media_write(monkeypatch):
    """A stale public checklist token cannot mutate evidence after submission."""
    fake_models = ModuleType("models")

    class _Query:
        @staticmethod
        def get(checklist_id):
            assert checklist_id == 42
            return SimpleNamespace(photos_submitted_at=object())

    fake_models.JobChecklist = SimpleNamespace(query=_Query())
    monkeypatch.setitem(sys.modules, "models", fake_models)

    configure_calls = []
    monkeypatch.setattr(private_media, "_configure", lambda: configure_calls.append(True))

    with pytest.raises(Conflict) as exc_info:
        private_media.upload_image(
            _UnreadablePhoto(),
            tenant_slug="alpha",
            kind="job-photo",
            scope_id="42:after",
        )

    assert exc_info.value.code == 409
    assert configure_calls == []


def test_job_photo_scope_fails_closed_when_malformed(monkeypatch):
    """Do not permit job-photo writes that are detached from checklist phase scope."""
    fake_models = ModuleType("models")
    monkeypatch.setitem(sys.modules, "models", fake_models)

    with pytest.raises(ValueError, match="Invalid job-photo scope"):
        private_media.upload_image(
            _UnreadablePhoto(),
            tenant_slug="alpha",
            kind="job-photo",
            scope_id="42",
        )
