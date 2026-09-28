"""No operator path may bypass the approved 30-day retention boundary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVISIONING = (ROOT / 'provisioning.py').read_text(encoding='utf-8')


def test_provisioning_destroy_command_cannot_directly_drop_registered_tenant():
    destroy = PROVISIONING.split("elif args.action == 'destroy':", 1)[1]
    destroy = destroy.split('return 0', 1)[0]
    assert 'drop_schema(' not in destroy
    assert 'DELETE FROM public.organizations' not in destroy
    assert 'tenant_data_lifecycle' in destroy


def test_permanent_purge_has_no_pre_retention_force_flag():
    lifecycle = (ROOT / 'tenant_data_lifecycle.py').read_text(encoding='utf-8')
    assert 'force=' not in lifecycle
    assert 'RetentionNotExpired' in lifecycle
    assert 'RETENTION_DAYS = 30' in lifecycle
