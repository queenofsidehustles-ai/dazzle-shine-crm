from types import SimpleNamespace

import pytest

import recovery_lifecycle


def test_restore_ready_when_reconciliation_is_empty(monkeypatch):
    monkeypatch.setattr(
        recovery_lifecycle,
        'restored_tenants_requiring_containment',
        lambda engine, now=None: [],
    )
    assert recovery_lifecycle.assert_restore_ready(SimpleNamespace()) is True


def test_restore_withholds_readiness_for_resurrected_closed_tenant(monkeypatch):
    monkeypatch.setattr(
        recovery_lifecycle,
        'restored_tenants_requiring_containment',
        lambda engine, now=None: [{'slug': 'closed-shop'}],
    )
    with pytest.raises(RuntimeError, match='lifecycle containment'):
        recovery_lifecycle.assert_restore_ready(SimpleNamespace())
