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
| DR-008 | Treat Launch Readiness test-manifest drift as a real evidence defect, not as a diagnostic-step defect. Align PAY-02 and tenant HTTP/media gates to current, existing security tests while preserving `continue-on-error` plus the fail-closed final aggregator. | The red run exposed stale workflow references to test files that no longer exist. Suppressing diagnostics or weakening the aggregator would hide missing coverage. Repointing gates to current equivalent and stronger tests restores executable evidence without relaxing the boundary. | Revisit after exact-head replacement workflow evidence is green. |
| DR-009 | Preserve profitability and efficiency optimizations behind security, privacy, accounting integrity, tenant isolation, auditability, and reversible operations. Prefer self-service defaults, explicit state transitions, bounded automation, and measurable support reduction. | Reduces operating cost and dispute/liability exposure without creating hidden customer or security risk. | Review against cohort metrics after the 3–5 tenant stage. |
| DR-010 | Do not interpret a grouped `continue-on-error` gate as product failure until the failing subtest is identified. Preserve the red aggregate, but distinguish workflow-manifest, test-harness, and implementation failures before changing runtime code. | Prevents unnecessary production-code changes and permission/security regressions while keeping release evidence fail-closed. | Revisit when exact failing assertions are available. |
| DR-011 | Reuse existing tenant export, dispute-evidence, onboarding, and Playwright surfaces instead of creating parallel implementations. Extend only proven gaps. | Duplicate implementations increase support cost, regression surface, inconsistent semantics, and future maintenance burden. | Revisit only if existing surface cannot satisfy a documented launch requirement. |
| DR-012 | Treat exact-head CI as authoritative over prior grouped-failure assumptions. When a newer exact-head Launch Readiness run is GREEN, close the prior PAY-02/tenant-HTTP grouped blocker rather than modifying runtime code to solve a superseded failure. | Avoids unnecessary security/payment changes and preserves the evidence-first rule. | Reopen only on a later exact-head regression or a new falsification finding. |
| DR-013 | Close restore anti-resurrection as an implementation/falsification backlog item because the PostgreSQL lifecycle suite already proves restored closed tenants are detected for re-purge and remain non-reactivated. Keep operational backup execution as a separate P1 requiring real backup-run/RPO evidence. | Prevents duplicate recovery code while avoiding the unsafe inference that code-level restore tests prove the scheduled backup is operational. | Reopen only if restore/lifecycle tests regress or operational rehearsal contradicts the invariant. |
| DR-014 | Treat mobile/accessibility as a distinct launch-evidence gap: existing Playwright suites exercise functional flows but currently contain no dedicated accessibility assertions or viewport matrix. Extend the existing Playwright surface rather than adding a second browser framework. | Reuses proven infrastructure, minimizes maintenance cost, and prevents functional desktop tests from being misrepresented as accessibility/mobile evidence. | Revisit after Golden Journey evidence is executable and reviewed. |
| DR-015 | Add local-only Golden Journey browser falsification at 360px, 390px and 1280px for dashboard, bookings, new-booking and money surfaces; require no document-level horizontal overflow, accessible names on visible critical controls, and keyboard focus entry. Do not run write-oriented browser evidence against Production. | Converts the mobile/accessibility requirement into executable, repeatable evidence while keeping customer data and external providers outside the test blast radius. | Expand after demonstrated failures identify additional critical routes or cleaner-role journeys. |

## Current evidence

- The registered-tenant `destroy` operator path has been routed through lifecycle closure; permanent purge remains retention-gated and separate.
- Privacy lifecycle falsification is GREEN on exact head `45769f361aa15668cf5b97092bf74e6751ee4615` (run `34992676766`).
- Launch Readiness is GREEN on exact head `45769f361aa15668cf5b97092bf74e6751ee4615` (run `34992676186`).
- The exact-head Launch Readiness job completed all critical launch-gate steps successfully, including PAY-01, PAY-02, tenant HTTP/object/document/export/media isolation, lifecycle, PostgreSQL tenant/pool isolation, concurrent 30-tenant isolation, backup/restore containment, scheduler isolation, cron/provider boundaries, CSRF, role/session fail-closed behavior, signup provisioning safety, forwarded-host isolation, and the final fail-closed aggregator.
- The earlier PAY-02 and tenant HTTP/media grouped blocker is therefore closed by newer exact-head evidence; no runtime-code relaxation is warranted.
- The workflow references current repository tests for payment integrity and tenant HTTP/media boundaries.
- Repository inspection confirms `tests/test_tenant_export_isolation.py`, `tests/test_dispute_evidence.py`, `templates/admin/dispute_evidence.html`, `onboarding.py`, `templates/admin/getting_started.html`, and Playwright suites already exist. These workstreams will be extended rather than duplicated.
- Restore anti-resurrection is already covered by the PostgreSQL lifecycle falsification: restoration of a retention-period backup recreates the schema while the organization remains closed, the restored tenant is identified as requiring re-purge, and re-purge is safe/idempotent. This is implementation evidence, not operational backup-run evidence.
- Existing Playwright configuration deliberately separates local write-flow tests from production read-only tests and serializes shared-database browser work.
- `tests/mobile-accessibility-golden.spec.js` now adds executable local-only viewport/accessibility falsification for critical owner journeys. It has not yet been claimed PASS: exact execution evidence is still required.
- Current private media is authenticated image storage under tenant-bounded `akye-private/{tenant_slug}/{kind}` paths; lifecycle purge remains bounded to the resource type actually stored.
- No Production activation, merge, live-funds authorization, permission broadening, credential mutation, or customer-data deletion was performed.

## Active autonomous queue

1. Execute the new mobile/accessibility Golden Journey evidence and correct only launch-blocking defects demonstrated by it; extend to cleaner-role critical journeys where the existing local harness can do so safely.
2. Prove operational backup execution separately from code-level restore containment: latest successful Akye backup, encryption/artifact evidence, backup age within RPO, and scratch-restore rehearsal before external admission.
3. Extend existing onboarding behavior into measurable low-support activation milestones rather than adding another setup implementation.
4. Add cohort control/support instrumentation only where existing operational/dispute surfaces leave measurable gaps.
5. Falsify provider degraded modes and realistic 30-tenant application workload beyond database-context isolation.
6. Capture profitability/support-cost instrumentation without weakening security, privacy, accounting integrity, tenant isolation, or auditability.
7. Assemble immutable release evidence and recommend, but do not perform, the first 3–5 design-partner release decision.

## Discussion queue

1. Review final operator closure/purge UX after exact-head lifecycle evidence remains green.
2. Review the first 3–5 design-partner admission criteria after the integrated candidate is green.
3. Review final rollback/containment and operational backup evidence before any cohort invitation or merge decision.