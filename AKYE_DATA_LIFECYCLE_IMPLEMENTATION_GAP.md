# Akye Data Lifecycle Implementation Gap

Decision: 30-day tenant retention approved.

Current verdict: **P1 OPEN / NO-GO for 30-tenant expansion.**

Existing evidence proves tenant lifecycle access denial and tenant-scoped financial CSV export, but it does not prove the approved destructive lifecycle. The following implementation work is required before this P1 can close:

- record an immutable `closed_at` timestamp (current control-plane organization state records `suspended_at` but no closure/purge timestamps);
- implement an operator-authorized purge path that refuses purge before `closed_at + 30 days`;
- drop only the intended tenant schema after eligibility checks and preserve a non-content purge tombstone/audit record;
- make purge idempotent and keep the tenant non-resolvable after partial/repeated execution;
- enumerate and delete tenant-owned private media without cross-tenant deletion;
- define disposition for tenant-related control-plane content including feedback screenshots and support/lead records where applicable;
- ensure backup restore reconciles closure/purge tombstones before restored data can become externally reachable;
- add real PostgreSQL falsification covering retained-before-deadline, purged-after-deadline, neighbor survival, repeated purge, and restore/non-resurrection behavior;
- integrate the completed implementation test into `.github/workflows/launch-readiness.yml` as a mandatory gate.

Do not satisfy this gap by broadening tenant permissions, bypassing lifecycle checks, or deleting records at closure time. Closure is immediate access containment; purge is a separate destructive operation after the approved retention window.
