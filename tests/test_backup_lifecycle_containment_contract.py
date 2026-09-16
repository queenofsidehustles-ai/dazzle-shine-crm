"""P1 recovery contract: a verified restore must not silently resurrect closed tenants.

This is deliberately non-destructive. Recovery must consult the lifecycle
reconciliation detector and withhold readiness rather than auto-purging data.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKUP = (ROOT / "backup.py").read_text(encoding="utf-8")
LIFECYCLE = (ROOT / "tenant_data_lifecycle.py").read_text(encoding="utf-8")
RECOVERY = (ROOT / "recovery_lifecycle.py").read_text(encoding="utf-8")


def test_lifecycle_exposes_non_destructive_restore_reconciliation_detector():
    assert "def restored_closed_tenants_requiring_repurge(" in LIFECYCLE


def test_recovery_boundary_integrates_lifecycle_reconciliation_detector():
    assert "restored_closed_tenants_requiring_repurge" in RECOVERY
    assert "assert_restore_ready" in RECOVERY


def test_backup_restore_must_integrate_recovery_boundary_before_release():
    """Fail until backup.py's real restore/verify path checks the boundary."""
    assert "assert_restore_ready" in BACKUP, (
        "backup.py restore/verify path does not yet enforce lifecycle recovery "
        "containment before traffic readiness"
    )


def test_recovery_does_not_auto_purge_during_restore():
    assert "purge_tenant(" not in BACKUP
    assert "purge_tenant(" not in RECOVERY
