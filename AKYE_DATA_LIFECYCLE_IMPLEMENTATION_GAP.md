# Akye Data Lifecycle — Residual Evidence Gate

> **Status: SUPERSEDED AS AN IMPLEMENTATION INVENTORY.**
>
> This file originally described the pre-remediation lifecycle implementation gap. It is retained as historical evidence, but statements that `closed_at` / `purged_at` do not exist are obsolete. Current launch authority is `AKYE_FINAL_LAUNCH_HARDENING.md` together with `AKYE_DATA_LIFECYCLE_POLICY.md` and the exact-SHA stable certification workflow.

Decision: 30-day tenant retention approved.

## Current verdict

**P1 RESIDUAL EVIDENCE GATE — do not represent destructive purge as launch-proven until the evidence below passes.**

Implemented lifecycle schema/access controls and PostgreSQL boundary tests are distinct from proof of the complete destructive lifecycle. The remaining evidence contract is:

- prove operator-authorized purge refuses execution before `closed_at + 30 days`;
- prove only the intended tenant schema/content is destroyed after eligibility checks;
- preserve a non-content purge tombstone/audit record;
- prove purge is idempotent and the tenant remains non-resolvable after partial/repeated execution;
- enumerate and delete tenant-owned private media without cross-tenant deletion;
- document disposition for tenant-related control-plane content including feedback screenshots and support/lead records where applicable;
- prove backup/restore reconciles closure/purge tombstones before restored content can become externally reachable;
- run PostgreSQL falsification for retained-before-deadline, purged-after-deadline, neighbor survival, repeated purge, and restore/non-resurrection;
- add the completed destructive-lifecycle falsification to `.github/workflows/launch-readiness-stable.yml` as a mandatory release gate.

Do not satisfy this gate by broadening tenant permissions, bypassing lifecycle checks, or deleting records at closure time. Closure is immediate access containment; purge is a separate destructive operation after the approved retention window.
