# AkyeHQ Application Use-Case and Truth Catalog v1.0

**Purpose:** Canonical behavioral reference for product design, acceptance testing, regression testing, launch-readiness review, and future feature changes.

**Evidence baseline:** Repository state at `ec3ffeec3ba0e190b1f316ee18130b56f160f931` on `akye-launch-readiness/cohort-30`, including current blueprints, templates, tests, launch-readiness controls, tenancy, payment, lifecycle, backup, security, onboarding, commercial, hiring, messaging, and finance surfaces.

## 1. How to use this catalog

A **truth** is an invariant the application must preserve. A **use case** describes a user/business outcome and the observable behavior required to satisfy it. Tests should falsify truths, not merely confirm that pages load.

For each use case, test at least: happy path, invalid input, unauthorized role, wrong tenant, stale/replayed token where applicable, provider failure where applicable, duplicate/retry behavior, mobile viewport, and persistence after a new request/process.

### Truth precedence

1. Security, tenant isolation, privacy/data lifecycle, payment/accounting integrity, auditability, and release controls.
2. Explicit product/business rules in this catalog.
3. Current documented workflow and UX behavior.
4. Implementation details.

If implementation conflicts with a higher-order truth, the implementation is defective; the truth is not automatically rewritten to match the code.

### Truth states

- **MUST** - release-blocking invariant.
- **SHOULD** - expected product behavior; deviation requires documented rationale.
- **MAY** - supported variation.
- **PROPOSED** - desired behavior not yet established as current application truth.

## 2. System identity and actors

AkyeHQ is a white-label, shared multi-tenant operations platform for service businesses, initially optimized for cleaning businesses. It combines CRM, quoting, bookings, scheduling, payments, communications, field-team workflows, hiring/onboarding, contractor pay, financial reporting, automations, commercial sales, and business administration.

Primary actors:

- **Business Owner/Admin** - controls the tenant, business settings, money, customers, jobs, team, hiring, integrations, reporting, and privileged actions.
- **Office/Operations Staff** - operates CRM, bookings, communications, scheduling and permitted administrative workflows according to role.
- **Cleaner/Contractor/Field Worker** - views eligible work, claims/accepts work where enabled, manages availability, performs assigned jobs, follows checklists, records time/evidence, and sees permitted pay information.
- **Customer/Client** - requests/receives quotes, books, confirms, pays, views portal/invoices, communicates, and rates service.
- **Applicant** - applies, interviews, supplies required onboarding/background documentation, accepts agreements and progresses through hiring.
- **Platform Operator** - manages the SaaS control plane and tenant lifecycle without crossing tenant data boundaries.
- **Automation/Provider** - scheduled jobs and external providers perform bounded actions only for the correct tenant and authenticated event.

## 3. Constitutional application truths

**T-001 Tenant isolation - MUST.** A user, token, webhook, scheduled task, object identifier, export, document, media reference, database session, or connection belonging to Tenant A must never disclose, mutate, authorize, or execute against Tenant B.

**T-002 Shared architecture - MUST.** AkyeHQ remains a shared multi-tenant PostgreSQL application; correctness must not depend on one deployment or database per customer.

**T-003 Fail closed - MUST.** Missing/ambiguous tenant context, invalid authorization, invalid provider authenticity, invalid role, invalid payment evidence, invalid secret transport, or unsafe host context must deny the operation rather than guess.

**T-004 Least authority - MUST.** Roles receive only the capabilities required for their operational duties. Removing an error by broadening permissions is not acceptable.

**T-005 Money integrity - MUST.** Monetary values, collected amounts, deposits, tips, discounts, fees, contractor pay, invoices, receipts, and P&L must remain exact, internally consistent, tenant-scoped, and auditable.

**T-006 Payment evidence - MUST.** A booking/order cannot become paid/confirmed merely because the browser says payment succeeded. Server-side provider evidence must match amount, currency, customer/tenant, purpose, and transaction binding.

**T-007 Paid-history immutability - MUST.** Later price changes must not silently rewrite the economic truth of an already-paid transaction or receipt.

**T-008 Idempotency - MUST.** Provider retries, webhook redelivery, repeated confirmation, repeated automation execution, and user refresh/retry must not double-charge, double-pay, duplicate irreversible records, or corrupt state.

**T-009 Private evidence - MUST.** Job photos, receipts, applicant/customer documents and other private evidence must not become public URLs or cross-tenant replayable references.

**T-010 Evidence preservation - MUST.** Job/dispute evidence that is intended to prove what happened must not be silently replaced or mutated after the relevant event.

**T-011 Data lifecycle - MUST.** Tenant closure, retention, purge and restore behavior must follow the canonical lifecycle policy. Restore must not resurrect a closed tenant into active service, and eligible re-purge must remain possible.

**T-012 Backup/restore containment - MUST.** Backup and restore must preserve tenant boundaries and produce recoverable evidence; recovery of one tenant must not expose or corrupt another.

**T-013 Provider boundaries - MUST.** Webhooks, cron jobs and integrations authenticate through their intended boundary and execute in the correct tenant context.

**T-014 Host integrity - MUST.** Forwarded/canonical host handling must not permit a forged host to select or impersonate another tenant.

**T-015 Session integrity - MUST.** Logout, credential/session invalidation and privilege changes must terminate authority as designed; stale sessions must not retain forbidden access.

**T-016 CSRF/state-change integrity - MUST.** Browser-originated state-changing operations must preserve the application's CSRF/API security boundary.

**T-017 Mobile operability - MUST for cohort launch.** Critical owner/admin journeys must work at 360px and 390px widths without destructive horizontal overflow or inaccessible required controls.

**T-018 Accessible control names - MUST for critical journeys.** Visible enabled form controls in critical journeys must have usable accessible names and keyboard focus must move predictably.

**T-019 Auditability - MUST.** Material business changes affecting money, authorization, customer commitments, evidence, or lifecycle must be reconstructable from durable records where the feature requires an audit trail.

**T-020 No production-by-accident - MUST.** Tests, diagnostics, preview workflows and automated evidence collection must not activate production traffic, live funds, or irreversible customer actions unless explicitly authorized.

## 4. Use-case catalog

### A. Tenant creation, signup and onboarding

**UC-001 Create a new business workspace.** Actor: prospective owner. Outcome: a unique tenant/workspace is provisioned with its own business identity and owner authority. Truths: T-001, T-002, T-003, T-004. Acceptance: duplicate/conflicting identifiers fail safely; partial provisioning does not leave an ambiguously active tenant.

**UC-002 First owner login.** Actor: owner. Outcome: authenticated owner reaches only their workspace and is guided to first-run setup. Acceptance: another tenant's hostname/session cannot redirect authority across tenants.

**UC-003 Configure business profile.** Actor: owner/admin. Outcome: business name, contact details, service area and operational settings are saved tenant-locally and appear consistently in white-label/customer surfaces.

**UC-004 Configure services and pricing.** Actor: owner/admin. Outcome: services, prices, deposits, discounts, upsells and commercial settings become the tenant's quoting/booking rules. Acceptance: changes affect future calculations without rewriting historical paid truth.

**UC-005 Configure provider connections.** Actor: owner/admin. Outcome: supported payment/messaging/email connections can be configured without exposing secret values to ordinary users or other tenants.

**UC-006 Trial/plan entitlement enforcement.** Actor: owner/admin. Outcome: features follow plan/trial entitlements. Acceptance: expired/unauthorized entitlement denies the gated capability without data loss or privilege escalation.

### B. CRM, leads and prospecting

**UC-010 Capture a lead.** Actor: owner/staff/automation. Outcome: prospect identity, source, contact details, notes and status are stored in the correct tenant.

**UC-011 Import or work Local Services Ads leads.** Actor: owner/staff. Outcome: LSA leads can be imported/reviewed, quoted and followed up without duplication or cross-tenant leakage.

**UC-012 Find commercial prospects.** Actor: owner/sales staff. Outcome: prospecting/places-finder tools help identify businesses and create tenant-owned prospects; external lookup results do not become customer truth until deliberately captured.

**UC-013 Follow up a missed/unreached contact.** Actor: staff/automation. Outcome: missed contacts remain actionable and follow-up history is visible, without duplicate uncontrolled outreach.

**UC-014 Convert lead to customer/booking/quote.** Actor: staff. Outcome: conversion preserves the prospect's identity/history and produces the intended downstream record once.

**UC-015 Maintain customer record.** Actor: authorized staff. Outcome: contact/address/history can be updated; edits remain tenant-scoped and do not rewrite unrelated historical transaction evidence.

**UC-016 Recover a dormant client.** Actor: owner/staff. Outcome: recover-client workflow identifies and contacts eligible prior customers according to tenant rules and communication permissions.

### C. Quoting and pricing

**UC-020 Create residential quote.** Actor: owner/staff. Outcome: quote price derives from configured service/pricing inputs and produces a customer-readable offer.

**UC-021 Apply discount.** Actor: authorized staff. Outcome: discount is explicit, bounded by policy/role, and recorded so gross price, discount and final price reconcile.

**UC-022 Add upsell/debris/extra-service pricing.** Actor: staff. Outcome: additions change quote economics transparently and consistently.

**UC-023 Create commercial estimate.** Actor: owner/staff. Outcome: commercial calculator accounts for configured labor/productivity/drive-time/economic assumptions and can create a commercial opportunity/quote.

**UC-024 Send quote.** Actor: staff. Outcome: correct customer receives a tenant-branded quote link/message; send history is recorded where supported.

**UC-025 Customer views quote.** Actor: customer. Outcome: tokenized/public quote access reveals only the intended quote/customer context.

**UC-026 Customer accepts/declines quote.** Actor: customer. Outcome: response is durable, token/tenant scoped and cannot mutate another quote.

**UC-027 Convert accepted quote to booking.** Actor: staff/system. Outcome: accepted commercial/residential terms become a booking without silently changing the accepted economic terms.

### D. Booking and scheduling

**UC-030 Customer self-books.** Actor: customer. Outcome: customer selects eligible service/date/options and receives a valid booking request/booking according to tenant settings.

**UC-031 Staff creates booking.** Actor: owner/staff. Outcome: staff can create a booking for a customer with date, service, price, notes and assignment state.

**UC-032 Hold a booking.** Actor: staff. Outcome: a tentative/held booking remains distinguishable from confirmed work and follows hold rules.

**UC-033 Confirm booking.** Actor: customer/staff/system as permitted. Outcome: confirmation changes only the intended booking and honors payment/deposit requirements.

**UC-034 Reschedule booking.** Actor: authorized staff/customer workflow. Outcome: date/time changes preserve history and do not duplicate the job or payment obligation.

**UC-035 Change service address.** Actor: authorized staff. Outcome: future job execution uses the updated address while historical evidence remains understandable.

**UC-036 Calendar view.** Actor: owner/staff. Outcome: scheduled work is represented consistently by date/status/team and tenant.

**UC-037 Recurring service.** Actor: owner/staff. Outcome: recurring rules generate/manage the intended series without uncontrolled duplicates; changes can distinguish one occurrence from the series.

**UC-038 Flag unassigned work.** Actor: owner/dispatcher. Outcome: upcoming jobs lacking required assignment are visible as operational exceptions.

### E. Payment, deposits, invoices and receipts

**UC-040 Collect booking deposit.** Actor: customer/system. Outcome: deposit is accepted only after provider-verified tenant-bound payment evidence; booking/deposit state and amount reconcile. Truths: T-005-T-008.

**UC-041 Pay by payment link.** Actor: customer. Outcome: payment link is bound to the correct tenant/customer/purpose/amount and cannot be replayed for another object.

**UC-042 Take payment on site.** Actor: authorized worker/staff/customer. Outcome: QR/on-site flow records the correct charge against the correct booking and customer.

**UC-043 Morning-of invoice/balance request.** Actor: automation. Outcome: eligible customer receives the correct balance request once according to timing rules.

**UC-044 Confirm provider payment.** Actor: system/webhook. Outcome: browser/client assertions are insufficient; server verifies provider transaction identity, status, amount, currency, customer/tenant and purpose.

**UC-045 Generate paid receipt.** Actor: system/staff/customer. Outcome: receipt reflects durable paid economics and private receipt access is tenant/object scoped.

**UC-046 Correct a price after payment.** Actor: privileged admin. Outcome: correction does not rewrite the original paid evidence invisibly; adjustments remain reconstructable.

**UC-047 Record tip.** Actor: customer/staff/system. Outcome: tip is separate from base service economics, attributed correctly and included in downstream accounting/pay logic only as policy requires.

**UC-048 Prevent duplicate charge.** Actor: system. Outcome: retries, refreshes and webhook redelivery cannot produce a second unintended charge.

**UC-049 Payment provider unavailable.** Actor: customer/staff/system. Outcome: application fails safely, does not mark unpaid work paid, and presents a recoverable state.

### F. Dispatch, claims and field execution

**UC-050 Broadcast open job.** Actor: dispatcher/system. Outcome: eligible team members can be notified of available work without exposing customer/job details beyond authorized recipients.

**UC-051 Claim open job.** Actor: eligible contractor/cleaner. Outcome: first valid claim assigns work atomically; concurrent claim attempts cannot create multiple authoritative assignees.

**UC-052 View My Day.** Actor: field worker. Outcome: worker sees only their permitted jobs, schedule, customer/job instructions and permitted money information.

**UC-053 Record availability.** Actor: field worker. Outcome: availability affects scheduling/dispatch for the correct worker and tenant.

**UC-054 Execute job checklist.** Actor: field worker. Outcome: required checklist items and promised service scope guide execution; completion state is durable.

**UC-055 Upload job photo/evidence.** Actor: field worker. Outcome: evidence is private, tenant/object bound and protected from silent replacement where immutability is required. Truths: T-009, T-010.

**UC-056 Record time/crew hours.** Actor: field worker/manager. Outcome: time entries are attributable, tenant-scoped and feed permitted pay/economic calculations.

**UC-057 Complete job.** Actor: field worker/manager. Outcome: completion status, checklist/evidence, money state and downstream follow-ups remain coherent.

### G. Customer communication and portal

**UC-060 Two-way customer messaging.** Actor: staff/customer. Outcome: SMS/email conversation is associated with the correct customer and tenant; provider failure is visible/retryable without duplicate uncontrolled sends.

**UC-061 Use message templates.** Actor: staff/admin. Outcome: tenant templates can be edited/used without leaking another tenant's content.

**UC-062 Automated reminders/follow-ups.** Actor: scheduler. Outcome: only eligible records are contacted, at intended times, once per idempotency rule, within the correct tenant.

**UC-063 Customer portal invite/login.** Actor: customer. Outcome: invitation/verification grants access only to that customer's intended tenant-scoped portal data.

**UC-064 Customer views invoice/history.** Actor: customer. Outcome: portal exposes only permitted customer records and correct money truth.

**UC-065 Customer books again.** Actor: returning customer. Outcome: prior information may streamline booking but cannot cause stale price/address/payment assumptions to be silently reused incorrectly.

**UC-066 Customer rates service.** Actor: customer. Outcome: rating is tied to the intended completed service and cannot be used to mutate another customer's/job's record.

### H. Hiring, contractor onboarding and compliance

**UC-070 Public applicant applies.** Actor: applicant. Outcome: application is captured for the intended company/tenant and does not expose internal hiring data.

**UC-071 Async interview.** Actor: applicant. Outcome: applicant completes guided interview; responses/media remain private and associated with the correct application.

**UC-072 Review applicant.** Actor: authorized manager. Outcome: manager sees only tenant applicants and can advance/reject according to role.

**UC-073 Upload background/compliance documents.** Actor: applicant/contractor. Outcome: documents are private, tenant/applicant scoped and retrievable only by authorized actors.

**UC-074 Contractor agreement/signature.** Actor: contractor. Outcome: agreement acceptance is attributable and preserved as evidence.

**UC-075 Onboarding hub.** Actor: accepted contractor. Outcome: required forms, training, documents, orientation and start-date steps are sequenced and progress is durable.

**UC-076 Insurance expiry tracking.** Actor: owner/admin. Outcome: expiring/missing compliance evidence becomes visible before it creates operational risk.

**UC-077 Training/SOP access.** Actor: worker. Outcome: worker can access permitted current procedures without gaining administrative authority.

### I. Team, roles and access

**UC-080 Add team member.** Actor: owner/admin. Outcome: member is added to the current tenant with explicit role; no accidental cross-tenant identity binding.

**UC-081 Team login.** Actor: staff/worker. Outcome: authenticated identity receives only current role capabilities.

**UC-082 Change role.** Actor: privileged admin. Outcome: new authority takes effect predictably and stale sessions do not preserve removed privilege.

**UC-083 Remove/deactivate team access.** Actor: privileged admin. Outcome: access terminates without deleting business records that must remain attributable.

**UC-084 Role-denied operation.** Actor: insufficiently privileged user. Outcome: state does not change; denial is safe and does not reveal sensitive object existence across tenants.

### J. Contractor pay, payroll and commissions

**UC-090 Calculate cleaner/contractor pay.** Actor: owner/payroll staff/system. Outcome: pay derives from documented job/pay policy, completed work and applicable tips/adjustments.

**UC-091 Flat crew pay.** Actor: payroll staff. Outcome: flat-pay rules are applied consistently and do not double-count time-based compensation.

**UC-092 Generate pay statement.** Actor: payroll staff/contractor. Outcome: statement reconciles source jobs, adjustments and total payable amount.

**UC-093 Record payout.** Actor: authorized payroll/system. Outcome: payout state is durable and retries cannot create duplicate authoritative payouts.

**UC-094 Stripe Connect payout/split.** Actor: system. Outcome: connected-account action is tenant/contractor bound and provider result is verified before marking payout complete.

**UC-095 Sales/VA commission.** Actor: owner/admin. Outcome: commission rules and resulting amounts are transparent, tenant-scoped and auditable.

### K. Finance and business intelligence

**UC-100 P&L view.** Actor: owner/authorized manager. Outcome: revenue, collected money, expenses, contractor/labor costs and profit reconcile to underlying tenant records for the selected period.

**UC-101 Record expense.** Actor: authorized staff. Outcome: expense is categorized, dated, tenant-scoped and reflected once in reporting.

**UC-102 Job economics.** Actor: owner/manager. Outcome: job-level revenue/cost/pay/margin analysis uses consistent money definitions and does not confuse quoted, collected and paid amounts.

**UC-103 Period/month boundary reporting.** Actor: owner. Outcome: date boundaries/time periods are deterministic so the same transaction is not omitted or double-counted across periods.

**UC-104 Reports/export.** Actor: authorized user. Outcome: export contains only the current tenant's authorized data and preserves usable business meaning.

### L. Automations and assistant

**UC-110 Scheduled operational automation.** Actor: scheduler. Outcome: reminders, balance requests, follow-ups and other jobs run only for eligible tenant records and are safe to retry.

**UC-111 Tenant-safe cron execution.** Actor: scheduler. Outcome: cron secret and tenant host/context are validated; forged host/context fails closed.

**UC-112 AI/assistant asks for information.** Actor: owner/staff. Outcome: assistant may analyze permitted tenant context but must not invent completed actions or access another tenant.

**UC-113 Assistant proposes an action.** Actor: assistant + human. Outcome: proposal is distinguishable from execution; high-impact actions require the application's intended authorization/human control.

**UC-114 Assistant executes an authorized action.** Actor: authorized user/assistant. Outcome: execution uses the same tenant, role, validation and audit constraints as manual execution.

### M. Commercial sales and growth

**UC-120 Commercial lead workflow.** Actor: owner/sales staff. Outcome: commercial prospects can move from discovery to estimate/quote/customer while preserving source/history.

**UC-121 Commercial pricing calculator.** Actor: owner/sales staff. Outcome: price/margin inputs produce reproducible economics; configured drive-time/productivity assumptions are not silently ignored.

**UC-122 LSA follow-up campaign.** Actor: staff/automation. Outcome: lead follow-up cadence is bounded, tenant-specific and avoids duplicate sends.

**UC-123 Content/call scripts/SOP management.** Actor: owner/admin. Outcome: tenant can maintain operational/sales content without modifying another tenant's content.

### N. White-label and SaaS control plane

**UC-130 Render tenant brand.** Actor: any tenant user/customer. Outcome: hostname/workspace renders correct tenant name/brand/contact information without data/branding bleed.

**UC-131 Platform operator lists/manages companies.** Actor: platform operator. Outcome: control-plane functions do not confer routine access to tenant-private operational data beyond explicitly authorized support/administration boundaries.

**UC-132 Tenant lifecycle closure.** Actor: authorized platform/tenant process. Outcome: closed tenant becomes inaccessible for normal service while retention state is preserved.

**UC-133 Retention-gated purge.** Actor: privileged lifecycle operator. Outcome: purge before policy eligibility is refused; eligible purge is tenant-bounded and idempotent.

**UC-134 Restore after closure.** Actor: recovery operator. Outcome: restore does not silently reactivate a closed tenant; restored closed tenant is identified for required re-purge/containment.

**UC-135 30-tenant cohort concurrency.** Actor: system. Outcome: concurrent operations across at least 30 tenant contexts preserve database/search-path/pool/session isolation.

### O. Backup, recovery and operational continuity

**UC-140 Nightly database backup.** Actor: automation/operator. Outcome: backup is produced, verified, encrypted before upload where required, and accompanied by durable manifest/evidence.

**UC-141 Scratch restore verification.** Actor: automation/operator. Outcome: backup can restore into a disposable environment and tenant containment remains intact.

**UC-142 Restore one service environment.** Actor: recovery operator. Outcome: recovery procedure can reconstruct service state without crossing tenant boundaries or accidentally activating unsafe provider behavior.

**UC-143 Private-media recovery.** Actor: recovery operator. Outcome: database recovery and private external-media recovery together preserve required customer/job/applicant evidence; missing binary evidence is surfaced rather than silently treated as recovered. **Status: truth required; full operational proof remains a release-readiness workstream.**

**UC-144 Rollback bad release.** Actor: operator. Outcome: application can return to a known-good release while preserving compatible customer data and avoiding duplicate provider actions.

### P. Security, privacy and abuse cases

**UC-150 Cross-tenant object-ID attack.** Actor: malicious/accidental user. Expected truth: request is denied/not found without leaking Tenant B data.

**UC-151 Cross-tenant public-token replay.** Actor: attacker. Expected truth: quote, portal, receipt, media, claim or document token for Tenant A cannot be replayed in Tenant B.

**UC-152 Forged webhook.** Actor: attacker. Expected truth: invalid signature/authenticity is rejected and no money/business state changes.

**UC-153 Forged forwarded host.** Actor: attacker. Expected truth: host manipulation cannot select another tenant.

**UC-154 Missing tenant context.** Actor: system/request. Expected truth: operation fails closed rather than defaulting to a customer tenant.

**UC-155 Stale session after privilege removal.** Actor: former privileged user. Expected truth: removed authority is not retained.

**UC-156 CSRF attempt.** Actor: attacker. Expected truth: unauthorized browser-originated state change is rejected.

**UC-157 Public-media URL substitution.** Actor: attacker/user. Expected truth: unsigned/public/wrong-folder media reference is rejected.

**UC-158 Payment amount/currency/customer tampering.** Actor: attacker/customer. Expected truth: payment confirmation fails and booking remains economically unchanged.

**UC-159 Duplicate provider event.** Actor: provider retry. Expected truth: state remains correct and irreversible side effect occurs at most once.

**UC-160 Premature tenant purge.** Actor: operator/error. Expected truth: retention policy prevents purge before eligibility.

### Q. Mobile, accessibility and usability truths

**UC-170 Owner dashboard on phone.** Actor: owner. Outcome: dashboard is usable at 360/390px without destructive horizontal overflow.

**UC-171 Booking list/new booking on phone.** Actor: owner/staff. Outcome: booking navigation and required controls are operable, labeled and keyboard-focusable.

**UC-172 P&L on phone.** Actor: owner. Outcome: critical financial information remains readable/usable without losing money meaning.

**UC-173 Keyboard-only critical form.** Actor: keyboard user. Outcome: focus moves from body into interactive controls and required controls have accessible names.

### R. Failure and degraded-mode use cases

**UC-180 Email provider unavailable.** Expected truth: business record remains correct; send failure is observable/retryable and not falsely marked successful.

**UC-181 SMS provider unavailable.** Expected truth: no duplicate or fabricated success; alternate/manual workflow remains possible where product permits.

**UC-182 Payment provider timeout.** Expected truth: uncertain payment is not converted into authoritative paid state without verification.

**UC-183 Database transaction failure.** Expected truth: partial multi-record business operation rolls back or is left in a deliberately recoverable state, not silently half-complete.

**UC-184 Concurrent claim/update.** Expected truth: one authoritative result wins according to business rule; no duplicate ownership or money effect.

**UC-185 Automation rerun after crash.** Expected truth: retry is idempotent and tenant-bounded.

## 5. Cross-cutting test matrix

Every release-critical use case should be mapped against these dimensions where applicable:

| Dimension | Required falsification question |
|---|---|
| Tenant | Can Tenant A read/write/trigger Tenant B? |
| Role | Can a lower role perform a higher-role action? |
| Identity/session | Does stale/invalid identity retain authority? |
| Object binding | Can changing an ID/token target another object? |
| Money | Do displayed, charged, collected, paid and reported values reconcile? |
| Retry/idempotency | What happens if the same request/event runs twice? |
| Provider authenticity | Can a forged callback change state? |
| Provider outage | Does failure preserve truthful state? |
| Concurrency | Can simultaneous actions create two authoritative outcomes? |
| Persistence | Is truth still correct in a fresh process/request? |
| Privacy/media | Can private evidence become public or cross-tenant? |
| Lifecycle | What happens after tenant closure/retention/restore/purge? |
| Mobile | Does the critical journey work at 360/390px? |
| Accessibility | Are controls named, focusable and operable? |
| Audit | Can a material decision/transaction be reconstructed? |
| Recovery | Does backup/restore preserve the same truth? |

## 6. Truth-to-test policy

1. Each MUST truth should have at least one automated falsification test; high-risk truths should have unit/integration plus end-to-end or runtime evidence.
2. A green page-load test does not prove a business truth.
3. Tests should assert durable state, not only HTTP status or rendered text, for money, authorization, lifecycle and evidence workflows.
4. Tenant tests must use adversarial cross-tenant identifiers/tokens, not merely two happy-path tenants.
5. Cohort reliability evidence must include realistic concurrent execution across the 30-tenant target, not a single-tenant benchmark multiplied by 30.
6. Payment tests must verify provider-bound server evidence and replay/idempotency behavior.
7. Recovery tests must prove restored business truth, not merely that a backup file exists.
8. When a truth changes intentionally, update this catalog first or in the same reviewed change, state the business reason, identify affected tests, and preserve higher-order constitutional truths.
9. A test that contradicts a current approved truth is a test defect; implementation should not be changed merely to satisfy a stale test.
10. Production activation remains a separate explicit authorization decision; green truth tests are necessary evidence, not automatic authorization.

## 7. Release-critical Golden Truth journeys

The minimum integrated journeys for cohort release are:

**GT-01 Tenant bootstrap:** signup -> provision tenant -> owner login -> configure business/pricing -> invite team member; prove no neighboring tenant effect.

**GT-02 Lead-to-cash:** capture lead -> quote -> customer accepts -> booking -> verified deposit/payment -> job -> receipt -> P&L; prove exact money reconciliation and no duplicate effects on retry.

**GT-03 Field-service execution:** schedule/broadcast -> valid worker claims/assigned -> My Day -> checklist -> private job evidence -> completion -> pay calculation; prove role and tenant boundaries.

**GT-04 Customer lifecycle:** portal invite -> verify -> view own booking/invoice -> communicate -> pay -> rate -> book again; prove token/object isolation.

**GT-05 Hiring-to-work:** applicant -> interview -> private documents -> review -> agreement -> onboarding -> role/login -> availability -> eligible job; prove applicant privacy and least authority.

**GT-06 Commercial:** discover commercial prospect -> calculator -> quote -> acceptance -> booking/work order -> invoice/payment -> job economics; prove pricing reproducibility.

**GT-07 30-tenant concurrency:** simultaneous tenant sessions/queries/jobs/automations across 30 workspaces; prove connection/search-path/session restoration and zero cross-tenant leakage.

**GT-08 Failure recovery:** provider failure + retry, webhook redelivery, automation rerun, application restart; prove truthful/idempotent state.

**GT-09 Backup/restore:** produce verified backup -> scratch restore -> validate tenant counts/key business records -> validate closed-tenant state -> validate private-media continuity -> demonstrate bounded recovery procedure.

**GT-10 Mobile owner day:** 360px/390px owner login -> dashboard -> bookings -> create/edit booking -> money/P&L -> logout; prove accessibility and no critical layout obstruction.

## 8. Governance

This file is intended to become the canonical product-truth catalog. It should be versioned with the application. New features should add or amend use cases and truths before their tests are considered complete. Bug fixes should identify which truth/use case was violated. Release reviews should report coverage by truth/use-case ID rather than only by test-file name.
