# Akye Final Launch Hardening

This document is the authoritative reconciliation note for final cohort launch hardening.

## Release gate

Akye customer releases originate from `akye-stable`. Every exact candidate SHA must pass the `Akye Stable Launch Certification` workflow (`.github/workflows/launch-readiness-stable.yml`). The older cohort remediation workflow is historical evidence and is not the stable release authority.

A green CI run is necessary but not sufficient: the cohort release record must also capture deployed `/version`, backup status, rollback target, incident owner, provider modes, admitted tenant count, and runtime journey evidence.

## Lifecycle reconciliation

The historical `AKYE_DATA_LIFECYCLE_IMPLEMENTATION_GAP.md` predates the implementation of `closed_at` / `purged_at` lifecycle schema work and subsequent PostgreSQL lifecycle tests. Treat that document as historical gap evidence, not current implementation truth.

Before 30-tenant expansion, destructive purge remains subject to explicit evidence for: 30-day eligibility, tenant-only schema/media deletion, idempotency, tombstone preservation, neighbor survival, and restore non-resurrection. If any of those are not demonstrated, record the residual as P1 with owner and expiry rather than representing it as closed.

## Golden runtime journeys

For each promoted release, execute at minimum:

1. New owner signup and tenant provisioning.
2. Owner sign-in and correct tenant routing.
3. First customer creation.
4. First job/work-order creation and scheduling.
5. Worker invitation/access and role denial checks.
6. Job completion.
7. Invoice creation and payment in the authorized provider mode.
8. Logout/session invalidation.
9. Two-tenant cross-object/media/export denial falsification.
10. Tenant suspension/reactivation without neighbor impact.

Record PASS/FAIL against the exact deployed SHA. Any cross-tenant disclosure, unauthorized financial action, broad authentication bypass, destructive data loss, or failure to resolve the correct tenant is P0.

## Media continuity

Database backup does not prove uploaded-object recovery. Before claiming complete disaster recovery, record the object-storage provider, retention/versioning policy, tenant-object namespace, restore procedure, deletion/purge behavior, and a successful sample restore. Until that evidence exists, database recovery is GREEN but complete media disaster recovery is NOT PROVEN.

## Provider degradation

SMS-dependent workflows must expose a truthful degraded state when Twilio/SMS is unavailable. They must not report an SMS as sent unless the provider accepted it. Email fallback may be used only where the product explicitly represents that fallback.

## Documentation authority

Akye platform release, tenancy, lifecycle, security, backup, and cohort documents govern the shared multi-tenant SaaS. Legacy Dazzle/Cleaning-Wonder documents describe tenant/business behavior only and must not be used as authority for Akye deployment topology or release governance.

## Repository control

`akye-stable` should be protected in GitHub so the stable certification check cannot be bypassed by an unreviewed direct update. If repository administration permissions are unavailable to the automation connection, this remains an external repository-setting action and must be verified in the release record.
