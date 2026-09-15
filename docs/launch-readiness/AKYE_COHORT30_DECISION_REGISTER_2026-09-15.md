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
| DR-004 | Privacy lifecycle remains a release gate until the registered-tenant operator path and exact-head falsification evidence conform to the approved retention boundary. | A passing test without removal of a destructive bypass would be false assurance. | Re-evaluate only against exact-head CI evidence. |
| DR-005 | Do not weaken or bypass `test_tenant_data_lifecycle_no_bypass.py` merely to obtain green CI. | The test represents the intended safety invariant; implementation must conform to it. | Only if retention policy itself is formally changed. |
| DR-006 | Preserve `drop_schema()` as a failed-provisioning/test helper, but remove it from the registered-tenant operator path. `destroy` performs lifecycle closure only; permanent purge remains a separate privileged lifecycle operation after retention eligibility. | Removes the bypass with the smallest blast radius while preserving a legitimate recovery/test primitive. | Review operator wording after exact-head CI is green. |
| DR-007 | Do not perform a whole-file operational-code replacement unless the complete current file is verified first. | The connector write primitive replaces the complete file; partial/truncated retrieval risks destructive loss of unrelated behavior. | Revisit when a patch-capable write path is available. |
| DR-008 | Treat Launch Readiness test-manifest drift as a real evidence defect, not as a diagnostic-step defect. Align PAY-02 and tenant HTTP/media gates to current, existing security tests while preserving `continue-on-error` plus the fail-closed final aggregator. | The latest red run exposed stale workflow references to test files that no longer exist. Suppressing diagnostics or weakening the aggregator would hide missing coverage. Repointing gates to current equivalent and stronger tests restores executable evidence without relaxing the boundary. | Revisit after the exact-head replacement workflow run completes. |
| DR-009 | Preserve profitability and efficiency optimizations behind security, privacy, accounting integrity, tenant isolation, auditability, and reversible operations. Prefer self-service defaults, explicit state transitions, bounded automation, and measurable support reduction. | Reduces operating cost and dispute/liability exposure without creating hidden customer or security risk. | Review against cohort metrics after the 3–5 tenant stage. |

## Current evidence

- The registered-tenant `destroy` operator path has been routed through lifecycle closure; permanent purge remains retention-gated and separate.
- Privacy lifecycle falsification has subsequently reached GREEN on the remediation branch; it remains subject to exact-head revalidation after material lifecycle changes.
- Launch Readiness run `34978648730` on head `5eab945c29784e8e5a2693a5dff22bfb05c50c15` completed FAILURE.
- Inspection showed the PAY-02 and tenant HTTP/media steps had `continue-on-error: true`: their displayed step conclusions were `success`, while their underlying outcomes were failures, correctly triggering diagnostics and the final fail-closed aggregator.
- The workflow referenced stale/nonexistent test paths including `tests/test_payment_integrity.py`, `tests/test_payment_redelivery.py`, `tests/test_payment_state_regressions.py`, `tests/test_payment_attempt_isolation.py`, `tests/test_tenant_session_binding.py`, `tests/test_tenant_direct_object_isolation.py`, `tests/test_tenant_documents.py`, `tests/test_tenant_private_media.py`, and `tests/test_private_media_signature.py`.
- Commit `a2c167beb1f6cc878c320b5411772d214b9c9516` aligns those two gates with current repository tests covering booking payment-intent integrity, payment confirmation, charge behavior/timing, paid receipts, post-payment price integrity, Stripe webhook tenant isolation, tenant session/object isolation, HTTP object isolation, secure documents, export isolation, private-media/receipt boundaries, and immutable private job-photo contracts.
- No Production activation, merge, live-funds authorization, permission broadening, or customer-data deletion was performed.

## Active autonomous queue

1. Falsify commit `a2c167b...` through exact-head Launch Readiness and Privacy Lifecycle runs; remediate real failures rather than suppressing them.
2. Complete tenant data-portability and restore anti-resurrection evidence.
3. Falsify mobile/accessibility Golden Journeys and correct launch-blocking defects.
4. Convert existing onboarding documentation into measurable, low-support activation behavior rather than adding another setup document.
5. Add cohort control/support instrumentation and explicit consequential-state auditability where gaps remain.
6. Falsify provider degraded modes and realistic 30-tenant application workload beyond database-context isolation.
7. Prove operational backup/recovery evidence and capture profitability/support-cost instrumentation.
8. Assemble immutable release evidence and recommend, but do not perform, the first 3–5 design-partner release decision.

## Discussion queue

1. Review final operator closure/purge UX after exact-head lifecycle evidence remains green.
2. Review the first 3–5 design-partner admission criteria after the integrated candidate is green.
3. Review final rollback/containment evidence before any cohort invitation or merge decision.
