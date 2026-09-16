"""P1 recovery contract: a verified restore must not silently resurrect closed tenants.

This is deliberately non-destructive.  It freezes the recovery boundary while the
operational restore hook is integrated: backup verification must consult the
lifecycle reconciliation detector, and any due tenant must withhold readiness
rather than being auto-purged.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKUP = (ROOT / "backup.py").read_text(encoding="utf-8")
LIFECYCLE = (ROOT / "tenant_data_lifecycle.py").read_text(encoding="utf-8")


def test_lifecycle_exposes_non_destructive_restore_reconciliation_detector():
    assert "def restored_closed_tenants_requiring_repurge(" in LIFECYCLE


def test_backup_restore_must_integrate_lifecycle_reconciliation_before_release():
    """Fail until backup.py's real restore/verify path checks the detector.

    The fix must *not* call purge_tenant automatically.  Recovery should detect
    and withhold readiness, leaving irreversible deletion behind the explicit
    retention-gated operator command.
    """
    assert "restored_closed_tenants_requiring_repurge" in BACKUP, (
        "backup.py restore/verify path does not yet reconcile restored closed "
        "tenants; a successful restore could be treated as traffic-ready before "
        "retention-bound data is contained"
    )


def test_backup_does_not_auto_purge_during_restore():
    # Importing the lifecycle module is acceptable; irreversible purge must not
    # be wired directly into recovery.  This guards the conservative decision.
    assert "purge_tenant(" not in BACKUP
