# Akye Cohort Release Control

Release-control contract for the first external cohort. This document closes the operator-facing boundary between a green candidate and permission to expose businesses to it. It does **not** authorize live funds or an automatic 30-tenant launch.

## Release posture

Akye ships from `akye-stable`. The working/remediation branch must never be a customer deployment source. A candidate may be promoted only after the exact candidate revision passes `.github/workflows/launch-readiness-stable.yml` and the operator records the evidence below. The stable certification runs on pull requests targeting `akye-stable` and again after a push/merge to `akye-stable`; the older `.github/workflows/launch-readiness.yml` is remediation/history evidence and is not the authoritative stable release gate.

Expansion is staged: internal/synthetic tenants -> 3-5 design partners -> 10 tenants -> 30 tenants. Each expansion is a new release decision; success at one stage does not authorize the next.

## Required evidence before each expansion

Record:

- candidate commit SHA and Akye Stable Launch Certification run ID;
- deployed `/version` release/channel response;
- number and identities of tenants being admitted;
- named release operator and incident owner;
- backup status and latest successful Akye backup run;
- support intake channel and current known limitations;
- payment and provider modes authorized for this stage;
- rollback/containment decision and approver.

No stage may proceed while a P0 is open. A P1 requires either PASS evidence or explicit written, time-bounded risk acceptance.

## Cohort kill switches

Containment is deliberately narrower than deletion. Prefer the smallest boundary that stops the harm.

### One tenant

Suspend the affected organization in the control plane. A suspended tenant must fail closed while neighboring tenants remain available. Reactivate only after the incident owner verifies the tenant's data and current release.

### New cohort admissions

Set `SIGNUPS_OPEN=0`. This stops new self-service signup without altering existing tenant data.

### Payments

Do not authorize live Stripe/customer charging merely because the application is releasable. Keep provider credentials/test mode bounded to the approved stage. If payment integrity is in doubt, withhold new payment initiation and investigate provider events before re-enabling.

### Messaging / provider automation

If a provider or automation is producing unsafe or duplicate effects, disable that provider/automation at the narrowest available configuration boundary. Do not delete tenant records to stop delivery. Record the provider, tenant scope, timestamp, and reason.

### Whole cohort

If isolation, authentication, payment integrity, destructive migration, or broad data corruption is suspected, stop cohort expansion immediately and pause the application/deployment write path. Preserve logs and take a backup of the affected database before destructive remediation.

## Code rollback

Akye customer deployments follow `akye-stable`. Rollback changes code, not customer data.

1. Freeze cohort expansion and record the current `/version` output.
2. Preserve incident evidence and determine whether database writes must also be paused.
3. Use the Akye release line to return `akye-stable` to the prior Akye release. Never roll Akye onto a CRM/Dazzle release tag.
4. Verify `/version` reports `channel: akye-stable` and the expected previous Akye release.
5. Run smoke checks on an internal/synthetic tenant before restoring external traffic.
6. Release forward after the defect is corrected; do not treat rollback as the permanent fix.

Rollback is unsafe if the newer release performed a destructive schema change that old code cannot understand. Akye migrations must therefore remain backward-compatible/additive across the rollback window.

## Data recovery contract

The Akye database is backed up nightly by `.github/workflows/backup.yml`, encrypted before artifact upload, retained for 30 days, and restored into scratch PostgreSQL during verification.

Operational targets for the first cohort:

- **RPO:** 24 hours maximum from the scheduled database backup. Take an additional verified backup before migrations, bulk edits, or other high-risk operations.
- **RTO target:** 4 hours for database recovery and application validation during the first cohort. This is an operating target, not a provider SLA; measure every rehearsal/incident and revise it from evidence.
- **Retention:** 30 days for encrypted backup artifacts; manifests may be retained longer because they contain row counts rather than customer records.

Recovery procedure:

1. Stop writes to the damaged database.
2. Take a backup of the damaged state for evidence/reconciliation.
3. Decrypt and verify the selected known-good backup.
4. Restore into a **fresh PostgreSQL database**, never over the only damaged copy.
5. Verify tenant registry, sampled tenant schemas, critical business rows, and isolation before cutover.
6. Point the application at the recovered database only after verification.
7. Reconcile the RPO window using provider records and operational communications.

The database backup does not itself preserve external object bytes. Private media/object-storage recovery remains a separate provider-level continuity responsibility and must be verified before claiming complete disaster recovery for uploaded files.

## Stage gates

### Internal / synthetic

Required: exact-SHA Akye Stable Launch Certification GREEN; no open P0; rollback path reviewed; database restore proof GREEN. Live funds remain unauthorized.

### 3-5 design partners

In addition: named support/incident owner, backup job operational for the Akye database, `/version` on `akye-stable`, known-limitations communication, and provider modes explicitly approved. Run critical owner and cleaner journeys on mobile and desktop.

### 10 tenants

In addition: review incidents and failed jobs from the design-partner stage; demonstrate one-tenant suspension/reactivation without neighbor impact; confirm backup age is within RPO; verify support response process and rollback drill evidence.

### 30 tenants

In addition: cohort-scale concurrency/load evidence, privacy/data-lifecycle readiness, accessibility/responsive critical-journey review, success metrics and support burden reviewed, and every remaining P1 either PASS or explicitly risk-accepted with owner and expiry.

## Incident minimum

For every severity-1 or severity-2 incident record: start time, affected tenant(s), release SHA/version, provider(s), containment action, evidence preserved, customer communication decision, recovery/rollback action, end time, data-loss assessment, and follow-up owner.

Severity 1 includes suspected cross-tenant disclosure, unauthorized financial action, broad authentication bypass, or destructive data loss. Freeze cohort expansion immediately.

Severity 2 includes a tenant-critical workflow unavailable or materially incorrect without confirmed cross-tenant disclosure. Contain the tenant/provider/feature and evaluate rollback.

## Final release record

A final cohort release record must answer all of the following before GO:

- exact candidate SHA and Akye Stable Launch Certification run;
- all P0 PASS;
- all P1 PASS or written risk acceptance with expiry;
- `akye-stable` is the deployment channel;
- latest Akye encrypted backup is successful and within RPO;
- rollback target is known and compatible;
- incident/support owner is available;
- cohort stage and admitted tenant count are explicit;
- live-payment authorization is separately recorded if applicable.

Absence of evidence is NO-GO. A green CI run is necessary but not sufficient for external cohort expansion.
