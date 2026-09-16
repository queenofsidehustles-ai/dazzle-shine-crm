"""Recovery/lifecycle containment contract.

A database restore is a recovery operation, never implicit authorization to
reactivate retention-bound tenant data or to perform irreversible deletion.
These tests keep that boundary executable while the restore integration is
completed.
"""
from pathlib import Path

import tenant_data_lifecycle as lifecycle


ROOT = Path(__file__).resolve().parents[1]
BACKUP_SOURCE = (ROOT / "backup.py").read_text(encoding="utf-8")


def test_lifecycle_exposes_non_destructive_post_restore_detector():
    detector = getattr(lifecycle, "restored_closed_tenants_requiring_repurge", None)
    assert callable(detector), (
        "Recovery must have a non-destructive detector for closed tenants whose "
        "retention state requires explicit remediation after restore."
    )


def test_restore_does_not_implicitly_purge_tenants():
    """Fail closed against turning restore into an irreversible-delete path."""
    restore_start = BACKUP_SOURCE.index("def restore(")
    restore_tail = BACKUP_SOURCE[restore_start:]
    assert "purge_tenant(" not in restore_tail
    assert "purge_eligible(" not in restore_tail


def test_backup_restore_integration_must_reconcile_lifecycle_before_release():
    """Executable release gate for the currently open P1 recovery gap.

    This intentionally remains red until backup.restore invokes the detector
    (or an equivalent bounded reconciliation helper) before declaring recovery
    successful.  The eventual integration must detect/contain only; deletion
    remains an explicit operator action behind the lifecycle CLI confirmation.
    """
    restore_start = BACKUP_SOURCE.index("def restore(")
    restore_tail = BACKUP_SOURCE[restore_start:]
    assert "restored_closed_tenants_requiring_repurge" in restore_tail, (
        "P1 RECOVERY GAP: backup.restore must reconcile restored closed tenants "
        "before recovery can be treated as traffic-ready. Do not auto-purge."
    )
