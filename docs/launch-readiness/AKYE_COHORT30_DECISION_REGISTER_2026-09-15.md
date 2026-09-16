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
| DR-005 | Do not weaken or bypass lifecycle no-bypass tests merely to obtain green CI. | The tests represent intended safety invariants; implementation must conform to them. | Only if retention policy itself is formally changed. |
| DR-006 | Preserve `drop_schema()` as a failed-provisioning/test helper, but remove it from the registered-tenant operator path. `destroy` performs lifecycle closure only; permanent purge remains a separate privileged lifecycle operation after retention eligibility. | Removes the bypass with the smallest blast radius while preserving a legitimate recovery/test primitive. | Review operator wording after exact-head CI is green. |
| DR-007 | Do not perform a whole-file operational-code replacement unless the complete current file is verified first. | The connector write primitive replaces the complete file; partial/truncated retrieval risks destructive loss of unrelated behavior. | Revisit when a patch-capable write path is available. |
| DR-008 | Treat Launch Readiness test-manifest drift as an evidence defect, not a reason to weaken the fail-closed aggregator. | Suppressing diagnostics would hide missing coverage. | Revisit only on new workflow drift. |
| DR-009 | Preserve profitability and efficiency optimizations behind security, privacy, accounting integrity, tenant isolation, auditability, and reversible operations. | Reduces operating cost and dispute/liability exposure without creating hidden customer or security risk. | Review against cohort metrics after the 3–5 tenant stage. |
| DR-010 | Do not interpret a grouped `continue-on-error` gate as product failure until the failing subtest is identified. | Prevents unnecessary production-code changes and permission/security regressions. | Revisit when exact failing assertions are available. |
| DR-011 | Reuse existing tenant export, dispute-evidence, onboarding, and Playwright surfaces instead of creating parallel implementations. | Duplicate implementations increase support cost and regression surface. | Revisit only if an existing surface cannot satisfy a documented requirement. |
| DR-012 | Treat newer exact-head CI as authoritative over superseded grouped-failure assumptions. | Avoids unnecessary runtime changes while retaining fail-closed release control. | Reopen on later exact-head regression or new falsification evidence. |
| DR-013 | Keep operational backup execution separate from code-level restore containment. | Code-level restore tests do not prove scheduled backup/RPO/RTO operations. | Final recovery rehearsal. |
| DR-014 | Treat mobile/accessibility as a distinct launch-evidence surface and extend the existing Playwright framework. | Minimizes maintenance cost and prevents desktop functional tests from being misrepresented as mobile/accessibility evidence. | Expand when new critical journeys are identified. |
| DR-015 | Golden Journey browser falsification covers 360px, 390px and desktop critical owner surfaces; write-oriented browser evidence must not target Production. | Keeps customer data and providers outside the test blast radius. | Extend to cleaner-role critical journeys. |
| DR-016 | Earlier exact-head backend GREEN evidence remains historical evidence, not a substitute for current-head CI. | Every material remediation commit must earn its own exact-head evidence. | Current candidate. |
| DR-017 | Central RBAC enforcement applies only to endpoints deliberately classified in `ENDPOINT_PERMISSIONS`; unclassified routes preserve their existing route-local authorization for canonical roles. Unknown/missing roles still fail closed. | Denying every unclassified route locked legitimate admin/dispatcher/cleaner/limited users out of large portions of the product. Broadly granting permissions would be equally unsafe. This restores the intended layered boundary without expanding classified permissions. | Expand classification deliberately, route family by route family, with real-route tests. |
| DR-018 | Tenant purge CLI must have a non-mutating eligibility preflight and still require explicit confirmation; destructive `purge_tenant()` independently re-checks retention under its transaction. | Prevents broken operator tooling without allowing preflight state to authorize irreversible deletion. | Revisit after exact-head CLI contract evidence. |
| DR-019 | A stale RBAC test that required all unclassified routes to 403 is a test-contract defect after DR-017, not a reason to reintroduce the application-wide lockout. | The test contradicted the intended classified-route architecture and the real-route availability requirement. Updated tests preserve unknown-role fail-closed behavior and all explicit sensitive-route permissions. | Reopen only if RBAC architecture is formally changed. |

## Current evidence

- Registered-tenant `destroy` routes through lifecycle closure; permanent purge remains retention-gated and separate.
- `tenant_lifecycle_cli.py purge` now has a callable, non-mutating `purge_eligible()` preflight, while destructive purge retains its own retention/schema/lifecycle re-checks and confirmation boundary.
- `tests/test_tenant_lifecycle_cli_contract.py` falsifies API existence, ineligible no-delete behavior, and mandatory human confirmation for eligible purge.
- The RBAC runtime was corrected so central enforcement applies only to deliberately classified endpoint/method pairs; canonical-role access to unclassified routes falls back to route-local authorization. Explicit owner-only decorators and classified permission checks remain intact.
- Exact-head Launch Readiness on `5068c45958179ac09636ed08d786691e2d198199` reached PAY-01, PAY-02, tenant HTTP/media/lifecycle, PostgreSQL tenancy, concurrent 30-tenant isolation, backup/restore, scheduler/cron/provider, CSRF and other critical gates successfully. The remaining role/session failure was traced to a stale test asserting the superseded global-unclassified-403 behavior, not to a need to broaden classified permissions.
- Commit `ead94a134ae5f0adc84221e29a793656445e3e1a` aligns the RBAC test contract with DR-017: canonical roles retain route-local authority on unclassified routes; unknown/missing roles remain denied; sensitive classified routes retain explicit least-privilege behavior.
- Mobile/accessibility Golden Journey has previously produced exact-head GREEN CI evidence; the earlier register statement that it had never passed CI was stale and is withdrawn.
- A scheduled Akye backup run previously completed with scratch PostgreSQL restore proof, encryption, uploaded backup artifact and manifest; RTO/release-rehearsal evidence remains separately reviewable.
- Restore anti-resurrection detection exists in lifecycle code and PostgreSQL falsification, but the actual `backup.py restore()` path still needs a bounded detection/containment integration before recovery authorization can be treated as complete. Automatic deletion during restore is not authorized.
- Private media is authenticated and tenant-bounded. Job-photo immutability currently fails closed, though its domain policy remains coupled into the generic private-media module and should be separated after higher-priority release gates.
- No Production activation, merge, live-funds authorization, permission broadening, credential mutation, or customer-data deletion was performed.

## Active autonomous queue

1. Obtain exact-head CI after the RBAC test-contract correction; fix only demonstrated current-head failures.
2. Integrate post-restore closed-tenant detection/containment into the real restore path without automatic purge, then falsify it.
3. Consolidate operational rollback/RTO and private-media recovery evidence.
4. Extend Golden Journey coverage to cleaner-role critical mobile/accessibility journeys where the existing harness can do so safely.
5. Falsify provider degraded modes and realistic 30-tenant application workload beyond database-context isolation.
6. Extend onboarding into measurable low-support activation milestones and capture profitability/support-cost instrumentation without weakening security/privacy/accounting/audit boundaries.
7. Assemble immutable release evidence and recommend, but do not perform, the first 3–5 design-partner release decision.

## Discussion queue

1. Review final operator closure/purge UX after exact-head lifecycle evidence remains green.
2. Review first 3–5 design-partner admission criteria after the integrated candidate is green.
3. Review final rollback/containment and operational backup evidence before any cohort invitation or merge decision.
