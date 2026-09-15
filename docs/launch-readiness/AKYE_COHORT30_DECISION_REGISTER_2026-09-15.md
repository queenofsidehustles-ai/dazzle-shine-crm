# AkyeHQ Cohort-30 Decision Register — 2026-09-15

Status: ACTIVE
Release posture: NO-GO
Production activation: WITHHELD
Live funds: UNAUTHORIZED
Merge to `akye-stable`: WITHHELD

This register records material remediation decisions made while continuing launch-readiness work. Default rule: when evidence is incomplete or alternatives differ in risk, choose the fail-closed, reversible, least-destructive option and preserve the current NO-GO posture.

| ID | Decision | Conservative rationale | Revisit |
|---|---|---|---|
| DR-001 | Keep `akye-launch-readiness/cohort-30` isolated; do not merge or activate Production while P0/P1 gates remain. | Prevents unproven remediation from becoming stable/Production behavior. | Final launch gate. |
| DR-002 | Treat the 30-day tenant-retention boundary as mandatory. Operator convenience must not bypass it. | Destructive deletion is irreversible; closure is reversible and preserves recovery options. | Policy review after cohort evidence. |
| DR-003 | A broad whole-file rewrite of `provisioning.py` was rejected and immediately reverted. No unrelated cleanup/refactoring will be accepted as part of the lifecycle fix. | Minimizes regression surface and preserves unrelated operational behavior. | Do not revisit during cohort remediation. |
| DR-004 | Current privacy-lifecycle failure remains a release blocker until the actual operator destroy path is routed through the lifecycle boundary and the exact-head falsification workflow is green. | A passing test without removal of the destructive bypass would be false assurance. | After targeted fix + CI evidence. |
| DR-005 | Do not weaken or bypass `test_tenant_data_lifecycle_no_bypass.py` merely to obtain green CI. | The test represents the intended safety invariant; implementation must conform to it. | Only if retention policy itself is formally changed. |

## Current evidence

- Privacy lifecycle workflow reaches the policy contract successfully.
- `No destructive retention bypass` fails because `provisioning.py` still contains a direct `drop_schema(...)` and direct organization deletion in the `destroy` operator path.
- Downstream tenant-bounded media purge and PostgreSQL retention/purge falsification are therefore not yet accepted as exact-head evidence.

## Morning discussion queue

1. Review the final targeted destroy/close operator UX after the implementation is proven.
2. Review whether permanent purge should remain a separate privileged operation rather than be exposed through `provisioning.py`.
3. Review final rollback/containment evidence before any cohort invitation or merge decision.
