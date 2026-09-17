# Akye launch-readiness decision/evidence register

This register records conservative launch decisions made on
`akye-launch-readiness/cohort-30`. It does not authorize merge, Production,
customer traffic, live Paystack/live funds, permission broadening, secret
exposure, or irreversible deletion of real customer data.

## Active decisions

### RECOVERY-03 — restored closed-tenant data fails readiness

Status: IMPLEMENTATION BOUNDARY ADDED; REAL BACKUP INTEGRATION OPEN.

A restore can legitimately resurrect data captured while a tenant was inside the
30-day retention window. Recovery must consult
`restored_closed_tenants_requiring_repurge()` and withhold readiness when such
data requires containment. Recovery must never auto-call `purge_tenant()`.

Evidence:
- `tenant_data_lifecycle.py` contains the non-destructive detector.
- `recovery_lifecycle.py` provides the fail-closed readiness boundary.
- `tests/test_recovery_lifecycle_boundary.py` falsifies allow/deny behavior.
- `tests/test_backup_lifecycle_containment_contract.py` remains intentionally
  RED until `backup.py` calls the boundary in its real restore/verify path.

Liability/profitability implication: prevents a disaster-recovery event from
silently re-exposing data for a closed or previously purged customer, reducing
privacy, contractual, support, and remediation exposure without adding deletion
automation or normal request-path overhead.

### CI-EVIDENCE-03 — PostgreSQL isolation must be substantive

Status: INFRASTRUCTURE REMEDIATION COMMITTED; EXACT-HEAD ISOLATION RESULT STILL
UNRESOLVED.

Commit `521602290468216bec7c34fce1a414adffab3839` provisions PostgreSQL 16 for the
launch-isolation lane and supplies `TEST_POSTGRES_URL`, removing the known
architecture in which PostgreSQL-dependent tests could skip for lack of a test
server. Do not call the 30-tenant boundary PASS until the exact-head isolation
job and its PostgreSQL-dependent steps are inspectable and successful.

### MOBILE-A11Y-01 — critical mobile/accessibility journeys

Status: PASS at `521602290468216bec7c34fce1a414adffab3839`.

Exact-head Actions run `35169115356`, job `105036705976`, completed successfully.
The job checked out and verified the exact candidate revision, started a
disposable CRM, installed Chromium, and completed the mobile/accessibility
golden journeys. The failure-log step was skipped because the journey passed.

Implication: preserves usable critical journeys for field/mobile users and
reduces avoidable onboarding/support friction while P0/P1 backend gates remain
fail-closed.

### RELEASE-01 — launch posture

Status: NO-GO.

Do not merge or activate Production/customer traffic until P0/P1 gates and
operational rollback/containment evidence are green. Live Paystack/live funds
remain unauthorized.
