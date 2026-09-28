# Akye Data Lifecycle Policy

Status: approved for first-cohort launch-readiness remediation.

This policy defines the minimum privacy/data-lifecycle contract for Akye's shared multi-tenant PostgreSQL architecture. It does not authorize Production activation or live payments.

## Tenant closure and retention

A tenant closure request enters a 30-day retention window.

At closure:

- application access is revoked immediately and stale authenticated sessions must fail closed;
- the tenant is marked `closed` in the control plane and must not resolve to its tenant schema through ordinary application traffic;
- new jobs, automation, messaging, payment initiation, and other tenant-originated effects are disabled;
- the tenant schema and private media remain recoverable during the retention window;
- closure must not impair neighboring tenants.

The retention window is 30 calendar days from the recorded closure timestamp.

## Pre-purge export

Before permanent purge, an authorized tenant owner may request an export of the tenant's reasonably portable business data. Export authorization and generation must remain tenant scoped. An export is not permission to expose another tenant's records or control-plane data belonging to other organizations.

## Permanent purge

After the 30-day retention window expires, the tenant's customer/business content must be permanently purged from active systems. Purge includes:

- the tenant PostgreSQL schema and its business records;
- tenant-owned private media/object bytes and tenant-scoped derived content where the storage provider supports deletion;
- tenant-scoped secrets/tokens that are no longer required;
- content-bearing control-plane records that exist solely to serve that tenant and are not required for security, billing, fraud, dispute, or legal/audit obligations.

Purge must be explicit, auditable, idempotent, fail closed, and bounded to the intended tenant. A failed or partial purge must not reactivate the tenant and must not affect neighboring tenants.

## Narrow retained records

After purge, Akye may retain only the minimum non-content metadata needed for legitimate security, billing, fraud/dispute, release, and audit purposes. Examples include tenant identifier/slug, closure and purge timestamps, billing transaction/provider identifiers where retention is required, and non-content audit events.

Retained records must not be used to reconstruct ordinary customer CRM content. Product leads, support requests, feedback screenshots, and similar control-plane personal data are not automatically exempt from lifecycle handling merely because they live outside tenant schemas.

## Backups

Akye's encrypted database backups have a 30-day retention period. Permanent purge applies to active systems; immutable or operational backups are not surgically rewritten. Purged data may therefore persist in encrypted backups until those backups age out under the existing retention schedule.

A restore from a backup containing data already purged from active systems must not silently resurrect that tenant into service. Recovery procedures must reconcile post-backup closure/purge state before external traffic is restored.

## Private media

Database backup/restore does not prove lifecycle handling for external object bytes. Before 30-tenant GO, Akye must have evidence that tenant-owned private media can be enumerated and deleted at purge without deleting another tenant's media. If no external object store is used for a media class, its actual storage location must still be covered by the purge boundary.

## Evidence required for PASS

Privacy/data-lifecycle readiness is PASS only when deterministic evidence demonstrates at minimum:

1. closure immediately denies tenant access and invalidates stale sessions;
2. a closed tenant remains recoverable during the 30-day retention window;
3. a neighboring tenant remains operational through closure and purge;
4. purge is unavailable before retention expiry except through a separately authorized exceptional process;
5. eligible purge removes the intended tenant's active business data without cross-tenant deletion;
6. repeated purge is safe/idempotent;
7. pre-purge export remains tenant scoped;
8. control-plane and private-media disposition is defined and tested for the storage classes actually used;
9. backup restore procedures account for purge tombstones/state so expired tenant content is not accidentally reactivated.

Absence of this evidence remains NO-GO for the 30-tenant cohort. A policy document alone does not satisfy the gate.
