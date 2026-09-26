# Recovery lifecycle integration gate

Decision: fail closed when a restored database contains closed-tenant data that
requires lifecycle containment.

## Evidence boundary

`tenant_data_lifecycle.restored_closed_tenants_requiring_repurge()` is the
source-of-truth detector. `recovery_lifecycle.assert_restore_ready()` converts
that detector into a readiness gate without deleting data.

The remaining integration step is deliberately blocked until `backup.py` can be
patched safely: after restore verification and before declaring the restored
database ready, call `assert_restore_ready()` with the restored database engine.
A non-empty result must fail verification/readiness.

## Safety constraints

- Recovery must never call `purge_tenant()` automatically.
- Retention eligibility remains authoritative.
- A closed tenant stays closed after restore.
- Previously purged/retention-expired restored data withholds traffic readiness
  until an explicit operator lifecycle action reconciles it.
- No real customer data is deleted by this gate.

## Release posture

NO-GO until the real backup restore/verify path enforces this boundary and the
contract executes green in CI.
