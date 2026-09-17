# Akye launch-readiness decision/evidence register

This register records conservative launch decisions made on
`akye-launch-readiness/cohort-30`. It does not authorize merge, Production,
customer traffic, live Paystack/live funds, permission broadening, secret
exposure, or irreversible deletion of real customer data.

## Active decisions

### RECOVERY-03 — restored closed-tenant data fails readiness

Status: IMPLEMENTED AND VERIFIED at `530fc372fc45dc35722ba6460df9cd50e779bcef`.

A restore can legitimately resurrect data captured while a tenant was inside the
30-day retention window. Recovery must consult
`restored_closed_tenants_requiring_repurge()` and withhold readiness when such
data requires containment. Recovery must never auto-call `purge_tenant()`.

`backup.py`'s real `verify()` path now calls
`recovery_lifecycle.assert_restore_ready()` against the just-restored scratch
database and raises `BackupFailed` if it finds a closed tenant whose retention
has expired or that was already purged. No `purge_tenant()` call anywhere in
this path — containment only.

A prerequisite fix was required first: `control_plane.py`'s `organizations`
table never declared `closed_at`/`purged_at` as real SQLAlchemy columns (only
a raw `ALTER TABLE` added them), so `backup.py`'s restore — which inserts
through the declared Table object, not the live database's actual columns, by
design — silently dropped both values on every restore. The lifecycle check
would have had nothing to read. Both columns are now declared on the Table
object; `tenant_data_lifecycle.ensure_columns()` remains the ALTER-TABLE
backfill for a pre-existing database.

Evidence:
- `tests/test_backup_lifecycle_containment_contract.py` — 4/4 passing (was
  intentionally red on `test_backup_restore_must_integrate_recovery_boundary_before_release`).
- End-to-end smoke test against real PostgreSQL (not just the string-presence
  contract): a `create()` + `verify()` round trip (a) raises `BackupFailed`
  naming the tenant's slug when the backup contains a tenant closed 40 days
  ago, and (b) succeeds normally for a tenant closed moments ago, still
  inside retention.
- CI: `RECOVERY lifecycle containment contract` step green in "Launch
  Readiness Isolation" run `35216588938`.
- No regression: `tests/test_backup_tenants.py` (7 sections) and the
  PostgreSQL tenancy suite (45 tests: `test_tenancy_cohort_30`,
  `test_signup_provisioning_safety`, `test_forwarded_host_tenant_boundary`,
  `test_cohort_concurrency_postgres`, `test_tenant_pool_reuse_postgres`,
  `test_tenant_context_restoration`, `test_tenant_search_path_fail_closed`,
  `test_cron_tenant_host_boundary`) stay green.

Liability/profitability implication: prevents a disaster-recovery event from
silently re-exposing data for a closed or previously purged customer, reducing
privacy, contractual, support, and remediation exposure without adding deletion
automation or normal request-path overhead.

### RBAC-02 — unclassified routes must not default-allow a missing/unknown role,
and pay/hiring/commercial surfaces stay owner-only

Status: IMPLEMENTED AND VERIFIED at `530fc372fc45dc35722ba6460df9cd50e779bcef`.

`rbac.enforce_current_request()`'s prior fix for locking non-owner roles out of
unrelated product surfaces (deferring an unclassified route to route-local
authority) went one step too far: it deferred for *any* recognised role,
including a missing or unrecognised one, and it had no way to keep specific
unclassified-but-sensitive surfaces (staff/hiring pay rates, commercial
accounts, quotes, invoices, deleting a lead, re-requesting a background check)
owner-only. Both gaps meant `admin`/`dispatcher`/any authenticated non-owner
role could reach them.

Two changes:
- `enforce_current_request()` now fails closed (403) for a missing or
  unrecognised role even on an unclassified route; a recognised role is still
  deferred to route-local authority.
- A new `rbac.OWNER_ONLY_ENDPOINTS` set marks the specific sensitive
  unclassified surfaces above as owner-only. Their real blueprint routes
  (`blueprints/staff.py`, `commercial.py`, `quotes.py`, `invoices.py`, plus
  `leads.delete` and `messages.request_bgcheck`) were also switched from
  `@login_required` to `@owner_required`, so the boundary holds even if the
  rbac matrix is ever bypassed.

Evidence: `tests/test_role_fail_closed.py` and `tests/test_operational_role_matrix.py`
— 173/173 passing (was 13 failing). CI: `Role and session fail closed` step
green in "Launch Readiness" run `35216588981`.

Liability implication: closes a live authorization gap — any authenticated
non-owner account could reach pay/hiring/commercial administration before this
fix.

### FIXTURE-01 — stale isolation-test fixtures against credential revalidation

Status: RESOLVED at `530fc372fc45dc35722ba6460df9cd50e779bcef` (no production
change).

`auth.session_matches_current_user()` re-checks a live `User` row and an
`auth_fingerprint` derived from its current `password_hash` on every request
(prior session-invalidation work). Four TEN isolation test fixtures pre-date
that check and hand-assembled a session with either a fabricated `user_id`
naming no real `User` row, or a real `user_id` with no `auth_fingerprint` —
both now correctly rejected as stale, which was turning a same-tenant sanity
check into an unexpected redirect to `/login` before the test ever reached
the cross-tenant behavior it meant to exercise. Each fixture now provisions a
real owner `User` per tenant and signs the session with that user's own
`auth_fingerprint`, exactly as `auth.authenticate()` does on a genuine login.

Evidence: `test_tenant_session_and_object_isolation.py`,
`test_tenant_http_object_isolation.py`, `test_tenant_secure_document_isolation.py`,
`test_tenant_export_isolation.py` — all green against real PostgreSQL (was 8
failing assertions). CI: `Tenant session, object, document, export and media
isolation` step green in "Launch Readiness" run `35216588981`.

### PAY-02-INVOKE — script-style payment tests were being run through pytest

Status: RESOLVED at `1eed9a1b8fa4bd2ed5ba5cfbf6ff541a83526cdf` (workflow-only
change).

`tests/test_charge.py`, `test_charge_timing.py`, `test_paid_receipt.py`,
`test_price_raised_after_paid.py` and `test_payment_confirmation_integrity.py`
are standalone scripts that assert at import time — none define a
pytest-collectible `test_*` function. `launch-readiness.yml`'s PAY-02 step ran
all seven files in that lane through `python -m pytest`, which collects 0
items and exits 5 on each of the five, failing real money-integrity coverage
that in fact never executed. Both the primary PAY-02 step and its
diagnose-on-failure twin now run the five scripts directly (`python
<file>`) and keep the two genuine pytest modules
(`test_booking_payment_intent_integrity.py`, `test_stripe_webhook_tenant_isolation.py`)
on pytest.

Evidence: all five scripts exit 0 standalone; both pytest modules pass (one
against SQLite, both against real PostgreSQL). CI: `PAY-02 payment integrity`
step green in "Launch Readiness" run `35215956973` (and remained green through
subsequent runs).

### CI-EVIDENCE-03 — PostgreSQL isolation must be substantive

Status: RESOLVED. Exact-head isolation result is now inspectable and green.

Commit `521602290468216bec7c34fce1a414adffab3839` provisions PostgreSQL 16 for the
launch-isolation lane and supplies `TEST_POSTGRES_URL`, removing the known
architecture in which PostgreSQL-dependent tests could skip for lack of a test
server. At `530fc372fc45dc35722ba6460df9cd50e779bcef` both "Launch Readiness"
(run `35216588981`) and "Launch Readiness Isolation" (run `35216588938`) are
green end to end, including `PostgreSQL tenant and pool isolation` and
`Concurrent 30-tenant pool isolation`, with no skip observed in either job's
step list.

### MOBILE-A11Y-01 — critical mobile/accessibility journeys

Status: PASS at `521602290468216bec7c34fce1a414adffab3839`.

Exact-head Actions run `35169115356`, job `105036705976`, completed successfully.
The job checked out and verified the exact candidate revision, started a
disposable CRM, installed Chromium, and completed the mobile/accessibility
golden journeys. The failure-log step was skipped because the journey passed.

Implication: preserves usable critical journeys for field/mobile users and
reduces avoidable onboarding/support friction while P0/P1 backend gates remain
fail-closed.

### CI-SCHEDULE-01 — the automatic nightly backup drill does not exercise the
candidate branch

Status: RESOLVED at `main@d4afe5a` (workflow-only change, user-authorized).

`.github/workflows/backup.yml` on `akye-launch-readiness/cohort-30` correctly
points the `akye` matrix job's checkout at
`ref: akye-launch-readiness/cohort-30` (fixed alongside RECOVERY-03, so the
drill restores through this branch's `backup.py`, not `akye-stable`'s).
Verified directly: a manual `workflow_dispatch` run against this branch
(`35218489753`, head `0bfb11717689cf31c0e36452402545aa970375cb`) checked out
the candidate branch, ran `python3 backup.py --dir backups --verify` — the
same call path RECOVERY-03 is wired into — and both the `akye` and `dazzle`
matrix jobs completed successfully end to end (checkout → backup → restore
→ RECOVERY-03 lifecycle check → encrypt → upload), proving the mechanism
works when dispatched against candidate code.

However, GitHub Actions resolves a `schedule`-triggered run's workflow
*definition* — not just its checkout targets — from the repository's default
branch (`main`), regardless of any `ref:` fields inside the job/matrix body.
`main`'s own copy of `backup.yml` (verified directly, SHA
`4c61c6f93b84155e2287c693c9f5652b584a815f`) still pins the `akye` matrix job
to `ref: akye-stable` and predates the RECOVERY-03 targeting fix. The two most
recent scheduled runs (#27, #28) both show `head_branch: main`, confirming
this in practice. Net effect: the automatic 08:00 UTC nightly drill does not
run against this candidate branch and does not exercise the RECOVERY-03 fix
at all — only an explicit manual `workflow_dispatch` with `ref:
akye-launch-readiness/cohort-30` does, and only for that one run.

This is a GitHub Actions platform behavior interacting with the explicit
constraint against merging this branch into `main`/stable/release. Flagged
for an explicit go/no-go decision rather than acted on unilaterally, since
the only fix touches the default/production branch: user authorized a
narrow, workflow-only edit to `main`'s `backup.yml` — only the `ref:
akye-stable` value in the `akye` matrix entry, changed to `ref:
akye-launch-readiness/cohort-30`, with a comment explaining why and a note to
revert once the candidate branch ships or stops being authoritative. No
application code, funds, secrets, or permissions touched; the candidate
branch itself is not merged. Pushed directly to `main` at `d4afe5a`
("Point nightly backup's akye job at the launch-readiness candidate, not
akye-stable").

Net effect: the next scheduled 08:00 UTC run (and any future one, until
reverted) will resolve its workflow definition from this updated `main`
copy, checkout the candidate branch for the `akye` job, and exercise
RECOVERY-03 automatically. The mechanism itself was already proven correct
via the manual `workflow_dispatch` run (`35218489753`) before this change
was made.

### RELEASE-01 — launch posture

Status: NO-GO.

Do not merge or activate Production/customer traffic until P0/P1 gates and
operational rollback/containment evidence are green. Live Paystack/live funds
remain unauthorized.
