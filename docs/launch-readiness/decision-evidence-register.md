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

### POOL-01 — connection-leak and noisy-neighbor falsification for the 30-tenant
cohort

Status: IMPLEMENTED AND VERIFIED at `a9c30923e133f0d4a28c412b12f1e638136af8b7`
(test-only; no production code changed).

The existing cohort-concurrency suite proved `search_path` never bleeds across
pooled connections under 30-tenant concurrent load, but never asserted the
pool's own connection accounting, and never modeled one tenant exhausting
shared pool capacity — both explicitly asked for by the launch-readiness
plan's Priority 4. Four new tests added to
`tests/test_cohort_concurrency_postgres.py`, all against real PostgreSQL:

- `test_no_connection_leak_after_concurrent_cohort_load` — `pool.checkedout()`
  returns to 0 after 600 concurrent reads across 30 tenants.
- `test_no_connection_leak_when_half_of_concurrent_reads_fail` — same, with
  half of all reads forced to raise mid-transaction, exercising the error
  path specifically.
- `test_noisy_neighbor_queues_without_cross_tenant_bleed` — one tenant
  holding every connection in a 2-connection pool makes a neighbor queue,
  not read the wrong tenant's row, once a connection frees.
- `test_noisy_neighbor_pool_exhaustion_fails_loudly_not_with_stale_tenant_data`
  — a neighbor that cannot wait long enough gets a clean `TimeoutError`,
  never a connection still pointed at someone else's schema.

Falsified by hand before committing, both probes reverted before the real
commit: widening the exhaustion test's `pool_timeout` past the noisy
tenant's hold time reproduced `Failed: DID NOT RAISE`; separately, injecting
a real unreturned connection (kept alive outside the pool rather than
relying on GC) on the forced-failure path reliably drove the shared pool
into cascading 30-second-per-checkout stalls under the existing 200-read
workload — confirming a genuine leak here is not just an assertion failure
but the exact platform-wide degradation these tests exist to catch.

Production carries no explicit pool sizing (`SQLALCHEMY_ENGINE_OPTIONS` is
unset), so it runs on SQLAlchemy's unconfigured default (`pool_size=5`,
`max_overflow=10` — 15 total) shared across every company on the platform.
Worth a deliberate sizing decision as tenant count grows, but out of scope
here: this round adds falsifying tests, not a production config change.

Evidence: CI `Concurrent 30-tenant pool isolation` step green in "Launch
Readiness" run `35220858874` at exact head `a9c3092`, immediately following
the local real-PostgreSQL run (6/6 passed) and the hand-falsification above.

### SCHED-01 — stale scheduler-workflow test contradicted the deliberate
triggering-ref fix

Status: RESOLVED at `fde4a12954845e0ecffe9ecd371e20df0d2122bd` (test-only;
no production code changed).

While investigating scheduler/background cross-talk (also Priority 4),
found `tests/test_scheduler.py` asserting `automations.yml` hardcodes
`ref: akye-stable`, directly contradicted by
`tests/test_tenant_scheduler_isolation.py`'s own
`test_automation_workflow_uses_triggering_revision_not_hardcoded_branch`,
which asserts the opposite. Running `tests/test_scheduler.py` directly
confirmed it currently exits 1 on this one check.

Root cause: commit `200251e` ("Run automation workflow from triggering
release ref") deliberately removed the hardcoded ref on this branch for the
same reason as CI-SCHEDULE-01 — a hardcoded ref does not protect a
*scheduled* run at all (GitHub always resolves that from the default
branch's copy of the file, regardless), so it only matters for
`workflow_dispatch`, where it should run the release that triggered it
rather than an implicit second one. `tests/test_scheduler.py` was never
updated to match.

Confirmed safe before touching anything: `main`'s own copy of
`automations.yml` is unchanged and still correctly pinned to
`ref: akye-stable`, so the real nightly automations run (schedule-triggered,
sourced from `main`) was never affected — this was purely a same-file test
left stale on the candidate branch, not a live incident. Also confirmed
`.github/workflows/lsa-followups.yml` (Google Ads follow-ups) has no
checkout step at all — it calls the production CRM's own HTTP endpoint
directly — so it carries none of this risk class.

Not wired into any CI gate (`launch-readiness.yml` never references
`test_scheduler.py`), so this was silent, stale test debt rather than a live
red signal. Updated the assertion to match the current, deliberate,
now-consistent invariant.

Evidence: `python tests/test_scheduler.py` — exit 0 locally (was exit 1, one
check failing); `tests/test_tenant_scheduler_isolation.py` — 4/4 passing,
unaffected. CI: "Launch Readiness" run `35221110963` and "Launch Readiness
Isolation" run `35221110933`, both `conclusion: success` at exact head
`fde4a12`, including the `Tenant scheduler isolation` step.

### BILL-01 — platform Stripe webhook was permanently unreachable behind a
mistaken tenant-host gate

Status: IMPLEMENTED AND VERIFIED at `837b514f7e3825dea938aba75319624986917e87`
(user-authorized before running the verifying test; the harness flagged the
change as a security-test edit and correctly asked first).

Found starting the Priority 5 (profitability/support hardening) pass:
`tests/test_billing.py` failed against real PostgreSQL because
`/api/stripe/webhook` returned 404 for every request, including a correctly
signed one.

Root cause: `security.PROVIDER_WEBHOOK_PATHS` grouped `/api/stripe/webhook`
with `/messages/incoming` under `require_tenant_for_machine_route()`, which
requires the request to resolve to a tenant subdomain before the route is
even reached. Correct for Twilio (each company connects its own
number/token, looked up by tenant); wrong for the platform billing webhook,
confirmed from four independent angles: `billing.stripe_key()`/
`webhook_secret()` read `STRIPE_PLATFORM_SECRET_KEY`/
`STRIPE_PLATFORM_WEBHOOK_SECRET` (one Stripe account for every company's
Akye plan, explicitly distinguished in the code's own docstring from "a
business's own Stripe account"); `billing.apply_event()` resolves the
company from the event payload against the control plane, never from the
request host; `DEPLOY_STEPS.md`/`LAUNCH_RUNBOOK.md` both instruct the
operator to configure Stripe's endpoint as the bare `BASE_DOMAIN`; and
`SECURITY.md` already documents this route as signature-authenticated, not
host-bound.

Net effect if unfixed: every subscription checkout, cancellation, and
failed-payment event would silently never apply once this branch's
`security.py` reached production. Confirmed candidate-branch-only
(introduced during the TEN-06/07 host-boundary hardening work) — does not
exist on `akye-stable`, so there was no live incident.

Masked from CI because `tests/test_provider_webhook_boundary.py` had been
written to assert the broken behavior as correct. Corrected both files to
match the documented, payload-authenticated design; the route's Stripe
signature verification itself is untouched — this removes a mistaken
orthogonal host gate, it does not weaken the actual authentication.

Evidence: `tests/test_billing.py` — full pass against real PostgreSQL
(was failing at "an unsigned payload is refused"), including the complete
checkout → subscribe → fail → recover → cancel lifecycle.
`tests/test_provider_webhook_boundary.py` — 7/7 passing (2 corrected).
No regressions: `test_cron_tenant_host_boundary.py`, `test_csrf_api_boundary.py`
(38/38 combined with the above), `test_stripe_webhook_tenant_isolation.py`
(the separate, genuinely tenant-scoped Stripe Connect webhook — unaffected).
CI: "Launch Readiness" run `35222604585` and "Launch Readiness Isolation"
run `35222604465`, both `conclusion: success` at exact head `837b514`,
including the `Provider webhook boundary` step; reconfirmed green on both
workflows at head `fcbb7dc` after this entry's own commit.

Liability/profitability implication: this was the most consequential
finding of the launch-readiness effort so far — unfixed, it would have made
Akye's own subscription revenue permanently unrecognized by the application
the moment this branch shipped, regardless of how correctly every other
billing safeguard (PAY-01, PAY-02, signature verification, idempotent event
handling) worked.

### RELEASE-GATE-01 — release.py's test runner silently skipped most
pytest-style suites

Status: IMPLEMENTED AND VERIFIED at `cc6b9f7ae109eeee02f66975d24abcd2a8d6b2b1`
(user-authorized before implementation, given the shared, cross-branch
sensitivity). Fixed on this branch only; NOT pushed to `main` or
`akye-stable` — separate explicit authorization would be needed for that,
per the same reasoning as CI-SCHEDULE-01.

`release.py --go` / `--akye --go` is the documented, real command
(`RELEASING.md`) for promoting code to `stable`/`akye-stable` — every real
cleaning company on Akye. Its `run_tests()` ran every `tests/test_*.py` via
plain `python <file>` and treated exit 0 as pass. Correct for this repo's
older script-style suites (checks execute at import time); wrong for
genuine pytest suites (`def test_*(fixture):`), which only run if
something calls them — `python file.py` just defines the functions and
exits 0, having verified nothing.

Confirmed empirically: of 37 pure-pytest-style files in `tests/`, **19
exit 0 silently** under this invocation, including
`test_tenancy_cohort_30.py`, `test_cohort_30_tenant_isolation.py`,
`test_cohort_concurrency_postgres.py`,
`test_tenant_session_and_object_isolation.py`,
`test_tenant_http_object_isolation.py`,
`test_tenant_secure_document_isolation.py`, `test_tenant_export_isolation.py`,
`test_backup_lifecycle_containment_contract.py`, and 11 more — effectively
the entire tenant-isolation and recovery evidence built during this
launch-readiness effort. `release.py` is byte-identical across `main`,
`akye-stable`, and this branch — this predates the branch and is not
something introduced here.

Fix: `_is_pytest_style()`, an AST check for "has `def test_*` functions and
no top-level executable statement" (module docstring excluded).
`run_tests()` now routes pytest-style files through
`python -m pytest -q <file>` and leaves script-style files on plain
`python <file>` — self-maintaining (AST-detected, not a hardcoded list)
since new suites are added constantly; a hardcoded list would rot exactly
like the PAY-02-INVOKE bug it otherwise mirrors.

Evidence: ran the actual patched `run_tests()` against the full 142-file
suite on a fresh Python 3.12 venv (matching `check_python()`'s own
production-version requirement) with real PostgreSQL — not just the
classifier in isolation. All 19 previously-silent files now execute for
real, confirmed by `test_rbac_matrix.py` correctly reporting "9 failed, 16
passed" (a known, pre-existing failure, reported earlier this session and
confirmed via `git stash` to predate all of this session's changes) rather
than a silent pass. `tests/test_release.py` (asserts `run_tests()` gates on
failure) still passes in full — zero regressions from this change.

**Separate, unresolved finding surfaced by the same full run — not caused
by this fix and not triaged here:** 19 further pre-existing failures in
script-style suites, unaffected by this change (their invocation is
unchanged) and apparently never run end-to-end via `release.py`'s actual
mechanism before. Spot-checked two, both look like genuine pre-existing
issues rather than sandbox artifacts: `test_first_run.py`'s "/book
responds (503)"; `test_whitelabel.py` sets a placeholder 4-character
`SECRET_KEY` alongside an `https://` `CRM_BASE`, which now correctly trips
`validate_secret()`'s production-detection heuristic (the FIXTURE-01
pattern again — a test predating a later security hardening pass). The
other 17 (`test_booking_page.py`, `test_booking_payment_intent_integrity.py`,
`test_canonical_host.py`, `test_confirm_request.py`, `test_early_access.py`,
`test_legal.py`, `test_login_security.py`, `test_lsa_followup.py`,
`test_marketing.py`, `test_portal_invite.py`, `test_security.py`,
`test_security_page.py`, `test_seo.py`, `test_tenant_links.py`,
`test_tip_after_job.py`, `test_upsell_pricing.py`,
`test_whitelabel_existing.py`) were not individually diagnosed. These are
general CRM feature tests, not launch-readiness-gated and largely not
Akye-multi-tenancy-specific, so triaging all 19 is a separate, unbounded
piece of work outside this session's scope — flagged for the user's team
to prioritize, or for an explicit follow-up request.

### RELEASE-GATE-01-TRIAGE — the 19 script-style failures surfaced by
RELEASE-GATE-01, resolved

Status: 8 of 19 fully fixed at `1ffb4ec`, root cause identified for 6 more,
5 remain genuinely open and untriaged (one — `test_rbac_matrix.py` — was
already known and reported before this session's work, out of scope; four
are new and unexplained). Test-only; no production change.

**Fully fixed (8 files, `1ffb4ec`):** `test_canonical_host.py`,
`test_confirm_request.py`, `test_portal_invite.py` (this one root cause
only — see below), `test_tip_after_job.py`, `test_upsell_pricing.py`,
`test_whitelabel.py`, `test_whitelabel_existing.py`,
`test_booking_payment_intent_integrity.py`. Two distinct root causes:

- Seven set a realistic `https://` `CRM_BASE` alongside a 4-character
  placeholder `SECRET_KEY` — a combination that predates
  `security.validate_secret()`'s production-detection heuristic
  (`CRM_BASE.startswith('https://')` is one of its signals) and now
  correctly refuses to start with a guessable secret rather than silently
  signing owner sessions with one. Bumped each to a 32+ character
  placeholder, matching how the rest of the suite already does it.
- `test_booking_payment_intent_integrity.py` was a distinct, unrelated bug:
  no `sys.path.insert`, so it only ever worked when pytest's own import
  machinery found it — which is how both CI and `release.py`'s new
  pytest-style routing already run it, so this was invisible until run as
  a bare script. Added the missing line.

**Root cause identified, not yet fixed (6 files sharing one cause):**
`test_seo.py` (remaining piece after its `SECRET_KEY` fix),
`test_first_run.py`, `test_early_access.py`, `test_legal.py`,
`test_marketing.py`, `test_security_page.py`. All use SQLite
(`DATABASE_URL=sqlite:///...`) and set `BASE_DOMAIN`, then make a request
to a fake `*.<BASE_DOMAIN>` host to assert that company/marketing/legal
content does not leak onto a tenant subdomain. `tenancy._enforce_request_lifecycle()`
now unconditionally calls `control_plane.find()` for any resolved slug —
and `control_plane.find()` queries the schema-qualified `public.organizations`
table, a PostgreSQL-only construct. On SQLite this raises
`OperationalError: no such table: public.organizations`, caught by
`_enforce_request_lifecycle`'s generic exception handler and reported as
503 ("Tenant lifecycle could not be verified") instead of the 404/redirect
these tests expect from "no such company." Confirmed by direct
reproduction, not just log reading. Not a production defect — production
always runs PostgreSQL — but a real architectural mismatch between an
older single-business-era test style (SQLite, for speed) and control-plane
enforcement added later in the tenant-lifecycle hardening work. Fixing it
requires a judgment call (move affected tests to real PostgreSQL, teach
`control_plane`/`_enforce_request_lifecycle` to degrade gracefully on a
non-PostgreSQL dialect, or adjust each test's expected status) — deferred
rather than decided unilaterally.

**Genuinely distinct, unexplained (4 files, need individual investigation):**
- `test_login_security.py`: `auth.authenticate()` now calls
  `bind_session_to_current_tenant()`, which writes to Flask's `session` —
  requiring an active request context. This test calls `authenticate()`
  directly outside one. Likely another old-test-vs-newer-hardening
  collision (session-tenant binding), but not confirmed to the same
  standard as the SQLite pattern above.
- `test_security.py`: "only the first entry in X-Forwarded-For is
  trusted" — `security.client_ip()` returns something other than the
  expected `1.2.3.4`. Not yet root-caused. Worth flagging as
  security-relevant rather than assumed benign.
- `test_lsa_followup.py`: "the number is on the do-not-text list" — a
  `SmsOptOut` record expected after a STOP reply is not found. Not yet
  root-caused. Worth flagging as compliance-relevant (STOP handling)
  rather than assumed benign.
- `test_tenant_links.py`: "the embed script frames that company's own
  booking page" fails on one of six sections; the other five (including
  the security-relevant ones — a link built with no request in flight, and
  the request host winning inside one) pass. Not yet root-caused.

Evidence: each fix in the "fully fixed" group re-run individually to exit
0; `test_whitelabel.py` and `test_whitelabel_existing.py` additionally
confirmed to complete their full assertion sequence, not just their first
previously-failing check. The four unexplained files and the six
SQLite-pattern files were run to capture their exact tracebacks/assertions
(recorded above) but not further diagnosed or fixed.

### RELEASE-GATE-01-TRIAGE — the two security/compliance-flagged items,
resolved

Status: both root-caused and fixed at `0540e9e` and `423b78c`. Neither was
a real regression; both were test fixtures predating later, legitimate
hardening. Test-only; no production code changed in either fix.

**X-Forwarded-For (`test_security.py`):** the test used
`app.test_request_context()`, which builds a request object directly and
never invokes `app.wsgi_app` — so ProxyFix (`x_for=1`, installed in
`create_app()`) never ran, and the check was passing or failing by
accident regardless of what `security.client_ip()` actually does on a
real request. Its expected value was also backwards: with `x_for=1`,
Railway (the one trusted proxy) appends the address it saw as the *last*
entry in `X-Forwarded-For`; trusting the *first* entry, as the test
asserted, would mean trusting whatever an attacker claims for itself —
the exact forgery the section's own title warns about. Verified both
facts by direct reproduction against the real WSGI stack: `client_ip()`
correctly returns `'5.6.7.8'` (the proxy-appended value), not `'1.2.3.4'`
(the client-claimed one). Production behavior was already correct; only
the test was fixed, routed through a real request via the test client.

While re-running this file to completion, a genuine, pre-existing,
three-way disagreement about `/api/stripe-webhook` (the per-tenant Stripe
Connect webhook) and CSRF exemption surfaced: `test_csrf_api_boundary.py`
(2026-09-12) explicitly names it a "stale alias" that must stay
origin-checked; `test_stripe_webhook_tenant_isolation.py` (2026-09-13, one
day later) exercises it as a real, currently-used, tenant-scoped route
(though without an `Origin` header, so it never actually settles the CSRF
question either way); `test_security.py` itself (unmodified since
2026-08-25, i.e. written before either) had assumed all along it was
CSRF-exempt like its siblings. A fix was drafted (adding the exemption to
`security.CSRF_EXEMPT_PATHS`, mirroring BILL-01's already-approved
reasoning for the sibling platform webhook) and **reverted immediately**
on finding the more specific, deliberately-named test asserting the
opposite — picking a side here is not something to do unilaterally.
`security.py` is unchanged; `test_security.py` no longer asserts either
answer for this route and documents the disagreement in place for whoever
resolves it next.

**SMS STOP/opt-out (`test_lsa_followup.py`):** `security.validate_twilio_webhook()`
now requires a valid Twilio signature on `/messages/incoming` before
acting on anything, added after this test was written. An unsigned STOP
(or any unsigned inbound text) is refused at the door with a bare 403,
before ever reaching the opt-out logic — confirmed by direct reproduction
(403, no signature provided) before concluding this, not assumed. The
STOP-handling code itself is untouched and, once actually reached, works
exactly as intended. Fixed by signing both inbound-message requests in
this file with `twilio.request_validator.RequestValidator`, matching the
pattern `test_provider_webhook_boundary.py` already established.

Evidence: both files pass in full end to end (not just past their
previous failure point) — `test_security.py` 12/12 sections,
`test_lsa_followup.py` 17/17 sections. No regressions:
`test_csrf_api_boundary.py` (15/15), `test_provider_webhook_boundary.py`,
`test_stripe_webhook_tenant_isolation.py`, `test_billing.py` (full
lifecycle) all still pass against real PostgreSQL.

**Net effect on the remaining open list:** all 4 "genuinely distinct,
unexplained" items are now down to 2 (`test_login_security.py`'s
session-context dependency, `test_tenant_links.py`'s embed-domain
mismatch), plus the still-undecided `/api/stripe-webhook` CSRF question
above, plus the 6 SQLite/control-plane files and `test_rbac_matrix.py`,
unchanged from the prior entry.

### JOURNEY-01 — acceptance-test findings from the 40-journey pass, three fixed

Status: fixed at `e2f700d` on `fix/journey-test-findings`, opened as
[PR #6](https://github.com/queenofsidehustles-ai/dazzle-shine-crm/pull/6)
against `akye-stable`, **not merged**. Live `akyehq.com` was unreachable
from this sandbox (proxy egress allowlist), so all fixes were built and
verified against a local server running the exact `akye-stable` code,
against a real PostgreSQL database, driven by Playwright.

**Journey #1 (P0) — brand-new signup logged owners out immediately.**
`blueprints/signup.py`'s `welcome()` built the post-signup session by hand
(`session['logged_in']`, `['role']`, `['user_id']`, `['user_name']`) but
never set `session['auth_fingerprint']`.
`auth.session_matches_current_user()` requires that fingerprint on every
`login_required` request and fails closed (clears the session, redirects
to `/login`) when it's missing — exactly what happened on the very next
page load. Every brand-new signup was silently logged back out right
after finishing signup, with no explanation, and had to sign in again
manually with the password just set. Fixed by setting
`session['auth_fingerprint'] = auth._auth_fingerprint(user.password_hash)`,
matching what the normal password-login path already does
(`auth.py` line 179). Verified on a genuinely fresh tenant (not the
already-signed-up one used for the first pass, to rule out a stale-data
confound): signup lands signed in, and — the actual regression — the
immediate follow-up page load stays signed in instead of bouncing to
`/login`.

**Journey #27 — no way to search Clients, Bookings, or Team.** Each list
page had no search once it grew past a glance. Added a `q` query-param
search box to all three (`blueprints/bookings.py`'s `clients()` and
`index()`, `blueprints/contractors.py`'s `team()`, plus
`templates/admin/clients.html`, `bookings.html`, `team.html`), filtering
on name/email/phone (and address for bookings) via `ilike`, with a
distinct "no matches" state kept separate from the genuine empty-list
state. Verified against seeded fixture records on all three pages: a
partial-name query finds the target row; a query with no matches shows
the new empty-search state, not the generic "no records yet" one.

**Journey #35 — no self-serve way to get your own data out.** Settings
had no general export; the closest things were the Money → P&L export and
a separate commercial-leads CSV, neither of which covers customers, jobs,
or the team roster. Added `Settings → Export data`
(`blueprints/settings.py`, `templates/admin/export.html`, a new tab in
`navigation.py`), with CSV downloads for customers, jobs, and workers.
Payment tokens (`portal_token`, `stripe_customer_id`,
`stripe_payment_method_id`) and login/payout credentials
(`agreement_token`, `stripe_account_id`) are deliberately excluded from
every export — confirmed by asserting their absence from each CSV's
header row, not just eyeballing the route code. Verified all three
downloads return `200`, `text/csv`, `Content-Disposition: attachment`,
contain the expected seeded row, and that the export tab is reachable
from the Settings nav.

**Journey #12 caveat (Team Logins/Staff disconnection) — not addressed
here.** The original pass recorded this as PASS-with-caveat, not a
failure, and flagged it as a deeper architectural gap (a worker login and
its Staff card can drift apart) rather than a simple bug fix. Left open;
worth a dedicated look before launch but out of scope for this pass.

**Re-running the full 8-phase local suite (not just these three fixes)
surfaced unrelated failures** (reschedule, worker daily workflow, mobile
viewport, job reassignment, address-correction persistence, password
reset, deletion/privacy, bad-network retry) in code none of these fixes
touch. Investigated enough to be confident these are stale-state
artifacts of re-running the suite's later phases against a test tenant
that had already accumulated data from the original full pass (hardcoded
booking/client IDs and element assumptions no longer matching), not new
product regressions — but that is inference from the pattern, not
independently reproduced the way the three fixes above were. A fresh
full-suite run against a clean database is recommended before launch if a
firm answer is wanted on any of those eight.

### IAM-02 — contractor-pay authorization gap, found by policy review of
RBAC-02, fixed

Status: fixed at `3b985fd` on `fix/journey-test-findings`, pushed to
[PR #6](https://github.com/queenofsidehustles-ai/dazzle-shine-crm/pull/6)
against `akye-stable`, **not merged**. Live on `akye-stable` before this
fix — RBAC-02's own decision above predates it and never touched these
routes, so this was not introduced by launch-readiness work.

Asked to audit the application's policies for internal consistency
(distinct from a specific bug report), found four routes that let any
authenticated role move or view a worker's money with no role check,
directly contradicting `rbac.py`'s own stated design
(`ROLE_OPTIONS`: *"Admin — operations, no finance/pay"*) and inconsistent
with every sibling route:

- `contractors.pay_contractor` (`POST /team/<id>/pay`) — a real Stripe
  Connect transfer (`stripe_connect.create_transfer`). Was
  `@login_required` only; the function body has no role check either.
- `contractors.pay_manual` (`POST /team/<id>/pay-manual`) — records a
  cash/Venmo/Zelle payment as paid. Same gap.
- `contractors.staff_detail`'s POST handler (`section=pay`) — sets
  `pay_type`/`pay_rate` directly on any worker's `Staff` row, gated by
  *nothing*, not even a decorator (the route is shared with the
  legitimately-open profile-edit fields). The same page's "Pay Settings"
  card — rate inputs plus a working "Update Pay" submit button — and a
  separate "Earnings" card (earned/paid/still-owed totals, itemized
  per-job pay) both rendered unconditionally to any logged-in role,
  found while checking the fix for a template-only issue and turning out
  to be materially worse: read-and-write, not just read.
- `contractors.pay_statement` (`GET /payroll/statement/<id>`) — every
  other `/payroll/*` route is `@owner_required`; this was the one
  exception, showing any worker's itemized earnings history to anyone
  signed in.

Fixed: the first two and `pay_statement` switched to `@owner_required`,
matching their siblings exactly. `staff_detail`'s pay section gets a
direct `auth.is_owner_session()` check (the route can't be blanket
owner-only — it also serves the profile fields every role legitimately
edits). Both sensitive cards in `contractor_detail.html` now sit behind
the same `{% if session.role == 'owner' %}` gate `team.html` already uses
for `pay_label()` on the roster. All four also added to `rbac.OWNER_ONLY_ENDPOINTS`
as the same regression safety net RBAC-02 used for staff/hiring/
commercial — belt-and-suspenders against a future decorator downgrade,
not the live protection (the decorator/inline check is).

**Reconciled, without changing behavior, while auditing the same
surfaces:**
- `auth.py` gained `bind_authenticated_session(user)`, the one shared
  helper for starting a session outside the password-checked
  `authenticate()` path. `signup.welcome()` now calls it instead of
  hand-assembling session keys — `authenticate()` already did the
  equivalent internally; checked every other hand-rolled
  `session['user_id'] = ...` site in the codebase (`blueprints/admin.py`
  is the only other one, and it correctly calls `authenticate()` first) —
  so this closes the *pattern* behind JOURNEY-01's signup bug, not just
  that one instance of it.
- `/api/stripe-webhook` (`blueprints/api.py`, a tenant's own Stripe
  account) and `/api/stripe/webhook` (`blueprints/billing_routes.py`,
  Akye's platform billing account) — one character apart, already
  mistaken for each other by three different tests per the
  RELEASE-GATE-01-TRIAGE entry above — now cross-reference each other in
  comments naming exactly which is which. The actual CSRF-exemption
  disagreement for the tenant route stays open on purpose, per that
  entry's own reasoning: not something to resolve unilaterally.
- `entitlements.py`'s module docstring stopped claiming multi-tenancy is
  a future change ("Later: a column on the organization, once the app is
  multi-tenant") the app has in fact already made everywhere else, and
  now names the real gap plainly: plan/subscription state lives in the
  tenant's own schema (`BusinessSetting`), unlike every other
  authoritative tenant fact (`control_plane.organizations`, which a
  tenant's own session can never write to). Verified today's only write
  path (`settings.business()`) is a hardcoded field allowlist that
  happens to omit `'plan'`, not a structural boundary — so there is no
  live self-upgrade exploit, but the trust tier is still architecturally
  inconsistent with where every other authoritative fact lives. Not
  restructured here; that is a real migration, not a doc fix.

Evidence: against real PostgreSQL, a seeded dispatcher-role session
(`ROLE_PERMISSIONS['dispatcher']` has no `pay.manage`/`finance.manage`)
gets a 302 (owner-only redirect) or 403 on all four routes, confirmed by
direct query against `contractor_payment` that zero rows were written by
the blocked attempts; sees neither the Pay Settings nor Earnings card on
the staff detail page; and is bounced off the pay statement. An owner
session re-run immediately after confirmed unaffected on every one of the
same checks (successful pay-manual, both cards visible, statement loads).
The full prior journey-fix suite (signup auth_fingerprint, Clients/
Bookings/Team search, data export) was re-run in full afterward with no
regressions.

Liability implication: this was a live authorization gap on `akye-stable`
allowing any authenticated non-owner role (a `dispatcher` login, for
instance) to both trigger a real Stripe payout to a contractor and view
every worker's itemized earnings — found and closed by treating RBAC-02's
own stated policy as a specification to audit the rest of the codebase
against, rather than a one-time fix.

### IDOR-01 — My Day clock-in/out trusted a client-submitted booking_id, fixed;
one further scan pass, two items flagged rather than fixed

Status: fixed at `1d2a1d3` on `fix/journey-test-findings`, pushed to
[PR #6](https://github.com/queenofsidehustles-ai/dazzle-shine-crm/pull/6)
against `akye-stable`, **not merged**. Live on `akye-stable` before this
fix, same as IAM-02.

Asked to scan again after IAM-02, for the same class of gap in different
territory: `blueprints/contractors.py`'s `clock_in`/`clock_out`
(`/my-day/<token>/clock-in|clock-out/<int:booking_id>`) identify the
worker from their personal `agreement_token` but took `booking_id`
straight from the URL with no check that the two are related.
`my_day()` itself already computes exactly this relationship (solo
assignment by name, or a `BookingCrew` row) to decide which jobs even get
a clock button — `clock_in`/`clock_out` never repeated that check
server-side, so a request crafted by hand naming any `booking_id` in the
tenant clocked (paid) hours against a job that worker was never assigned
to. Checked every other route in the codebase shaped like this (a token
plus a separate integer ID: `grep`'d for the pattern across all
blueprints) — `ratings.<token>/<int:stars>` and
`workorders.get_photo(token, phase, photo_index)` are the only other two,
and both are safe (`stars` is a value, not a foreign key;
`get_photo`'s `photo_index` is bounds-checked against that same token's
own checklist, confirmed by reading the route). This was the one genuine
instance, not a pattern repeated elsewhere.

Fixed: `_staff_is_on_booking(s, b)`, the same test `my_day()` uses,
called at the top of both routes before touching any `TimeEntry`.

Evidence: against real PostgreSQL, a worker's own token still clocks
in/out cleanly on their assigned job (302, a `TimeEntry` row written,
confirmed by direct query); the identical token against a different,
unassigned booking gets 403 with zero `TimeEntry` rows written for that
attempt (confirmed by direct query, not inferred from the status code
alone). Full prior fix suite (signup, search, export, IAM-02's
contractor-pay checks) re-run clean afterward.

**Two further items surfaced by the same scan, flagged rather than fixed
— both are behavior-change judgment calls, unlike the unambiguous
money/fraud fixes above:**

- `staff_detail`'s *profile* fields (name, phone, emergency contact,
  notes, active/inactive toggle) and `staff_toggle_active` remain open to
  any logged-in role, including `cleaner` (`ROLE_PERMISSIONS['cleaner']`
  is `{'assigned_work.use'}` only). So hiring a new worker is owner-only
  (`staff.index`/`staff.edit`, RBAC-02), but editing an existing worker's
  contact info or deactivating them — stopping them from receiving any
  further job assignments — is not gated at all beyond being logged in.
  Whether `admin`/`dispatcher` should manage this (plausible — it looks
  like ordinary team administration) while `cleaner` should not
  (`assigned_work.use` reads as intentionally narrower) is a product
  decision this pass didn't make unilaterally.
- Residual data-integrity question from the same fix: any `TimeEntry`
  rows created *before* this fix, by a worker clocked into a job they
  were not assigned to, are not identified or touched here. Not
  fabricated — no evidence any exist on `akye-stable`'s real data — but
  worth a one-time audit query before launch if the team wants certainty
  (`TimeEntry` joined against `Booking`/`BookingCrew` for a mismatch) --
  correcting or removing any found is a payroll-affecting action outside
  this pass's authorization to take alone.

### IDOR-01-AUDIT — the pre-fix TimeEntry audit IDOR-01 flagged, run

Status: tool built and verified at `a9a950c`; **could not be run against
real `akye-stable` production data** from this sandbox (no network path
to `akyehq.com` or its database, and no production credentials were ever
provided to this session). `audit_time_entry_assignment.py` is ready for
the team to run directly, with `DATABASE_URL` set to production.

`--slug` scopes to one tenant; unknown slug and an unmigrated schema are
both handled without crashing the run (a schema missing `time_entry` or
`booking_crew` is skipped with a note, not treated as zero mismatches).

Run against this session's own QA database (the only PostgreSQL this
sandbox can reach): 11 seeded tenant schemas, **0 mismatches** on the
real data in them. To prove the tool actually catches the case it exists
for, not just that it stays quiet, a synthetic mismatched row was
inserted by hand (a staff member clocked into a booking assigned to
nobody, with no crew row for them either) — the audit reported it
correctly, by name, booking, and timestamps; the row was then removed
and a re-run confirmed zero mismatches again. This demonstrates
correctness, not an absence of the real thing on production — that
still needs an actual run there.

**Two further, smaller items surfaced while reviewing the surrounding
code for this audit, neither acted on:**
- `TimeEntry.note` and `TimeEntry.edited_by` are declared on the model
  ("who changed it, if anybody") but nothing in the codebase ever writes
  to either — there is no route to edit a `TimeEntry` at all once
  created, only to open (`clock_in`) or close (`clock_out`) one. A
  mismatch this audit finds cannot currently be corrected from the admin
  UI, even by the owner; fixing one requires direct database access. Not
  fixed here — building a correction UI is real feature work, not a
  finding to silently act on.
- `audit.py` (the repo's separate UI-completeness checker, unrelated to
  this new script despite the similar name) logs in via
  `ADMIN_USER`/`ADMIN_PASS`, which `auth.env_login_configured()`
  deliberately disables on hosted multi-tenant Akye. As written, this
  script cannot log in to a real hosted tenant at all and predates the
  multi-tenant architecture, the same way `entitlements.py`'s docstring
  did before IAM-02. Not fixed or removed here; flagged as likely-dead
  tooling for whoever next reaches for it.

### PRODUCT-01 — first batch of user-reported product fixes (group 1 of a
13-item punch list)

Status: fixed at `343507b`/`d2314ee` on `fix/journey-test-findings`, pushed
to [PR #6](https://github.com/queenofsidehustles-ai/dazzle-shine-crm/pull/6)
against `akye-stable`, **not merged**. Test-only verification (not a
security review) -- these five items were reviewed against the actual
code before implementation and the reminders fix was exercised live; the
other four are copy/config changes.

The user supplied a 13-item list of requested changes. Reviewed each
against the real code first rather than taking the description at face
value -- two turned out not to be what they looked like, and one turned
out to be a real, previously-undiagnosed bug the description didn't
name. Implemented the five lowest-risk, no-open-questions items now;
the remaining eight (2FA, persistent tenant login, a migration toolbox,
menu reorganization, market/state selection, setup-step rollback,
address autocomplete) need product decisions or larger design work and
are deferred pending the user's answers.

- **Cleaner day-before reminders bug (real fix).** Traced "check sending
  of auto reminders for cleaner recurring jobs": the reminder logic
  itself was correct for both one-time and recurring bookings, but it
  lived inside the "Follow-ups and win-backs" automation (customer
  win-back nudges) with no disclosure that toggle also controlled
  cleaner reminders. Split into its own function, wired into the
  existing "Day-before reminders" automation instead (same daily cron,
  no new scheduled trigger needed), and fixed a second bug found along
  the way -- it computed "tomorrow" from naive UTC rather than the
  business's local date, the same class of bug the customer-facing
  reminder route was already fixed for. Verified live: with win-back
  nudges off, the cleaner reminder still fires; with day-before
  reminders off, it correctly doesn't.
- **Cleaner-pay label (clarity, not a bug).** Traced "cleaner pay cannot
  be right" through `pricing.py`: `client_price` and `contractor_earnings`
  are computed independently; `labor_rate` never reaches the customer's
  price. Confirmed correct, relabeled for clarity anyway since the
  question itself shows the old label invited exactly this misreading.
- **PWA install name** (`static/manifest.json`: "Dazzle & Shine CRM" →
  "Akye App"). Flagged, not resolved: `base_admin.html`'s
  `apple-mobile-web-app-title` is already dynamic per tenant (`{{ BIZ }}
  CRM`) — iOS and the install manifest will now say different things
  until someone decides whether both should say "Akye" or both should be
  tenant-branded.
- **Sign-up button copy** ("Get early access" → "Sign up", "Request
  early access" → "Complete sign up"). Checked `early_access()`'s own
  routing before changing anything: it already redirects straight to the
  real self-serve `/signup` once `SIGNUPS_OPEN` is true, and its
  confirmation copy already sets honest hand-onboarding expectations for
  the closed-signups case — so the new wording is accurate in both
  states, not just the eventual self-serve one.
- **Support email** (`akyecrm@gmail.com` → `support@akyehq.com`):
  searched the entire repository, no occurrence anywhere.
  `product.py`'s `support_email()` already defaults to
  `support@akyehq.com` and is only overridden by a `PRODUCT_SUPPORT_EMAIL`
  environment variable — nothing to change in code. Flagged for the user
  to check Railway's env vars / connected email account instead.

Evidence: manifest and label changes confirmed by direct render against
the local QA server; the sign-up-copy change confirmed in both the
open- and closed-signups branches (`SIGNUPS_OPEN` toggled); the reminder
fix confirmed by seeding a real booking for the business's local
"tomorrow," toggling each automation independently, and checking both
the live JSON response and `Staff.schedule_reminder_date` directly in
the database, not just trusting the response body. Full 17-check prior
regression suite (JOURNEY-01, IAM-02, IDOR-01) re-run clean.

### PRODUCT-02 — Phase A of the group-2/3 punch list (#5)

Status: fixed at `0ad9f2d` on `fix/journey-test-findings`, pushed to
[PR #6](https://github.com/queenofsidehustles-ai/dazzle-shine-crm/pull/6)
against `akye-stable`, **not merged**.

Decisions for the remaining group-2/3 items (#1 2FA, #2 persistent
tenant login, #3 Migration Toolbox, #7 market/state) were settled with
the user first: TOTP-only 2FA (Google-Authenticator-compatible), opt-in,
no role enforced; tenant login persistence via a root-domain cookie plus
an email-lookup fallback (needs a new control-plane email→tenant index,
flagged to the user before building); Migration Toolbox's team import
creates a Staff record per CSV row and emails each contractor an invite
link to set up their own login and finish their own profile — fixes the
Journey #12 Staff/login disconnection by construction rather than
deepening it; market/state is compliance-copy-only, not booking-
functional, and ships with the existing default terms as every state's
fallback since correct per-state legal wording needs the user's own (or
counsel's) input, not code. #4 (menu reorganization) explicitly deferred
by the user. Full plan given to the user before any of this phase's
code was written.

**#5 (setup rollback), the only item ready with no open questions,
implemented and verified this pass** — see `templates/admin/
getting_started.html`'s fix, evidence in the commit itself (link-per-
step confirmed present and resolving to a real, loading settings page,
full regression suite re-run clean).

**#8 (address autocomplete) is next and is blocked on the user**: it
needs a second Google Places API key, restricted by HTTP referrer, since
the existing server-side key (used in `places_finder.py`) is IP-
restricted and unsafe to expose in browser JavaScript. Cannot be created
by this session — requires the user's Google Cloud Console access.

### PRODUCT-03 — Phase C of the group-2/3 punch list (#7, Markets)

Status: fixed at `b8862ba` on `fix/journey-test-findings`, pushed to
[PR #6](https://github.com/queenofsidehustles-ai/dazzle-shine-crm/pull/6)
against `akye-stable`, **not merged**.

Built per the decided scope (compliance-copy-only, not booking-
functional): a "Markets" multi-select on Business Info, next to Time
Zone, plus an optional per-state note appended to `customer_terms` for
each selected market. Deliberately additive rather than a per-customer
swap — traced `Client`/`Booking` first and confirmed neither stores a
customer's state (only city and zip), so there is no reliable way to
target a note at one specific customer; a business's markets are a fact
about the business, and every customer sees every note the business has
written for its selected markets, erring toward more disclosure rather
than risking silently missing required disclosure for someone. Wired
into `customer_terms.get_terms()`, the single function every existing
surface (confirmation emails, payment page, invoices, terms-acceptance
snapshotting) already reads through, so nothing else needed to change to
reach all of them. Ships with the existing default terms as every
state's fallback; explicitly not legal advice, matching the base terms'
own existing disclaimer.

Evidence: selected FL and GA as markets against real PostgreSQL, wrote a
note for FL only, and confirmed both `get_terms()` and `as_html()`
correctly append the FL note under its own bold heading (the same
markup convention the rest of the terms already use) while GA — selected
but left blank — does not appear at all, proving the "only if written"
behavior rather than just that saving works. Full 17-check prior
regression suite re-run clean.

### PRODUCT-04 — Phase D of the group-2/3 punch list (#2, persistent tenant
login), corrected mid-build

Status: fixed at `86477f1` on `fix/journey-test-findings`, pushed to
[PR #6](https://github.com/queenofsidehustles-ai/dazzle-shine-crm/pull/6)
against `akye-stable`, **not merged**.

**Recorded transparently because the first attempt was wrong, not just
because the second one worked.** Built the decided design (a cross-
subdomain cookie plus an email-lookup fallback) from scratch — a new
`auth.py` cookie helper, an `app.py` `after_request` hook, a new root-
domain branch in `admin.login()`, a new template — before discovering
`marketing.workspace()` already does most of this job: a cookie-backed
one-click "welcome back, continue to X" return path, deliberately never
confirming whether a typed address is real (anti-enumeration by
design), and already wired in *ahead of* `admin.login()` by
`marketing.install()`'s `_front_door()` `before_request` hook, which
intercepts `/login` on the product's root domain unconditionally. That
hook would have short-circuited every request before the new code in
`admin.py` ever ran — confirmed directly (a curl request to root
`/login` landed on `/workspace`, not the new code), not assumed. All of
the parallel-mechanism code was reverted rather than shipped as dead
weight beside a working one; the local diff on `auth.py`/`app.py`
returned to empty, confirmed before committing.

**What was actually missing, added instead:** a route in for someone on
a browser the `workspace` cookie has never seen (new device, cleared
cookie) who also does not remember their exact subdomain. A second,
collapsed-by-default form on `marketing/workspace.html`, "Don't know
your address? We'll email it to you," backed by a new control-plane
index (`tenant_logins`, written once at account creation in
`signup.py` and `team_logins.py` — checked and confirmed those are the
only two places a `User` row is created today) and a matching
`login_lookup_requests` throttle table. Deliberately the same shape as
`account.forgot_password`: identical response whether an account was
found, an email was sent, or the address was already asked for too
recently, and the matching address(es) are emailed rather than ever
displayed on the page.

Evidence: against real PostgreSQL, a fresh signup correctly writes its
(email, slug) pair to the index; looking that email up returns the same
"check your inbox" response as a made-up email, but the outbound
notification log confirms only the real one actually queued a send —
proving the no-enumeration property holds, not just that the happy path
works. A second lookup for the same email inside the cooldown window
sends nothing (log unchanged). The pre-existing `workspace` slug flow
(both the remembered-cookie one-click redirect and a fresh-slug
redirect) re-verified unaffected by the changes around it. Full
21-check prior regression suite re-run clean.

**Unrelated but significant finding surfaced while reading
`control_plane.py` for this work, not yet acted on:** `organizations`
already declares `plan`, `subscription_status`, `trial_ends_at` and
`grandfathered` columns, with its own docstring explaining exactly why
billing state belongs in the control plane and not a tenant's own
schema ("A business must not be able to edit the record of what it is
paying"). This directly confirms IAM-02's `entitlements.py` finding
above — but is a stronger statement of it than that entry made: the
*correct* location already exists as live schema, and `entitlements.py`
simply does not read from it, reading `BusinessSetting` in the tenant's
own schema instead. Not touched here — moving `entitlements.state()`
onto `organizations` is a real migration (every existing tenant's plan
data would need to move, and `billing_routes.py`'s webhook handler would
need to write to the new location instead) and deserves its own pass
with the user's sign-off, not a fix folded into an unrelated feature.

### RELEASE-01 — launch posture

Status: NO-GO.

Do not merge or activate Production/customer traffic until P0/P1 gates and
operational rollback/containment evidence are green. Live Paystack/live funds
remain unauthorized.
