"""P1 privacy/data-lifecycle policy must remain explicit and fail closed.

This is deliberately a policy-contract test, not evidence that destructive purge
implementation exists. The 30-tenant gate remains NO-GO until implementation
and PostgreSQL/media falsification are added.
"""
from pathlib import Path

POLICY = Path(__file__).resolve().parents[1] / 'AKYE_DATA_LIFECYCLE_POLICY.md'


def _policy():
    return POLICY.read_text(encoding='utf-8').lower()


def test_policy_fixes_retention_at_30_days_and_immediate_access_revocation():
    text = _policy()
    assert '30 calendar days' in text
    assert 'application access is revoked immediately' in text
    assert 'marked `closed`' in text
    assert 'must not resolve to its tenant schema' in text


def test_policy_requires_export_before_purge_and_tenant_scope():
    text = _policy()
    assert 'pre-purge export' in text
    assert 'authorized tenant owner' in text
    assert 'export authorization and generation must remain tenant scoped' in text


def test_policy_requires_active_system_purge_but_backup_age_out():
    text = _policy()
    assert 'permanently purged from active systems' in text
    assert 'backups are not surgically rewritten' in text
    assert 'until those backups age out' in text
    assert 'must not silently resurrect that tenant into service' in text


def test_policy_covers_control_plane_private_media_and_neighbor_safety():
    text = _policy()
    assert 'control-plane personal data' in text
    assert 'private media' in text
    assert "without deleting another tenant's media" in text
    assert 'neighboring tenant remains operational' in text


def test_policy_refuses_to_claim_pass_from_documentation_alone():
    text = _policy()
    assert 'a policy document alone does not satisfy the gate' in text
    assert 'absence of this evidence remains no-go' in text
