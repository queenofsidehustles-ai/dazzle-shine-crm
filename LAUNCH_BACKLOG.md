# Launch Backlog — the exact work before Customer #1

Companion to `LAUNCH_PLAN.md`. Audit performed 2026-08-24 against `v2026.08.19.4`.

Classifications:
**SHIP** — good enough for a paying customer as-is ·
**FIX** — must change before Customer #1 ·
**HIDE** — works, but confuses a new owner; hide until asked for ·
**LATER** — post-launch

---

## Part A — Module audit

Every section of `navigation.py`, judged against one question: *does this help
Customer #1 run jobs and pay cleaners?*

### Jobs & Schedule — the core. Mostly ready.

| Module | Verdict | Note |
|---|---|---|
| Dashboard | **SHIP** | Never demo it empty — see the seed script, T-06. |
| Bookings / All jobs | **SHIP** | Detail, edit, price correction, dispute evidence all present. |
| Invoices | **SHIP** | |
| Calendar | **SHIP** | Grid + series collapse are tested. |
| Clients | **SHIP** | Needs a CSV importer for onboarding — T-07. |
| Messages (inbox, sent log, templates) | **SHIP** | Blocked by Twilio 10DLC per customer — T-12. |
| Recurring jobs | **SHIP** | `recurring.py` is solid and it's a real differentiator. |
| **Cleaner job flow** (claim → on-the-way → clock-in → checklist → photos → signature → complete) | **SHIP** | This is the best thing in the product. It *is* the demo. |

### Money — the second-strongest area

| Module | Verdict | Note |
|---|---|---|
| Payroll / contractor pay | **SHIP** | Per-job percentage pay is the differentiator. |
| Job economics | **SHIP** | Show this in the demo. Owners have never seen it before. |
| Profit & Loss, Expenses, Trends | **SHIP** | |
| 1099 & W-9 | **SHIP** | Add the not-a-payroll-provider disclaimer — T-10. |
| Stripe payments / deposits / tips | **FIX** | Live/test guard, T-04. |
| VA commissions | **HIDE** | Very specific to how you run *your* business. Confusing on day one. |

### My Team

| Module | Verdict | Note |
|---|---|---|
| Team / Cleaners | **SHIP** | |
| Availability, Broadcast | **SHIP** | |
| Hiring: applications, interviews, offers, onboarding, agreements | **SHIP** | Genuinely rare in this category. Demo it *second*, after the job flow. |
| Background checks / secure docs | **SHIP** | Covered by legal work, T-10. |

### Get Customers

| Module | Verdict | Note |
|---|---|---|
| Leads | **SHIP** | |
| Discounts | **SHIP** | |
| Commercial: Find leads / Accounts / Quotes | **HIDE** | Needs their own Google Places key. Excellent upsell later; on day one it's a second product bolted to the first. Show it only if the prospect asks about commercial work. |

### Toolkit

| Module | Verdict | Note |
|---|---|---|
| Checklists | **SHIP** | Required. Half the value of the cleaner flow. |
| SOP Library | **SHIP** | Pre-load it with your SOPs — that's part of what they're buying. |
| Email templates, Call scripts, Text templates | **SHIP** | Pre-load. Same reason. |
| Content Studio | **HIDE** | Needs an OpenRouter key. Off-mission for Customer #1. |

### Setup

| Module | Verdict | Note |
|---|---|---|
| Setup checklist (`onboarding.py`) | **SHIP** | Better than the wizard the outside analysis asked you to build. Don't rebuild it — extend it (T-08). |
| Settings: Pricing, Business, Connections, Automations | **SHIP** | |
| Team logins | **FIX** | No self-serve password reset, T-03. |
| Commercial brand | **HIDE** | Only if Commercial is hidden. |

**Nothing needs to be built. Three things need to be hidden, five need to be
fixed, and the platform underneath needs to become safe to trust.**

---

## Part B — Tickets, in build order

### 🔴 P0 — the launch gate. Nothing ships to a customer until these are done.

**T-01 · Automated backups, with a restore you have actually run**
Daily `pg_dump` of each customer instance to storage you control, 30-day
retention, off Railway. Then **restore one into a scratch database and log in to
it.** An untested backup is not a backup. Document it in `NEW_CUSTOMER_SETUP.md`
as a per-instance step.
*Why P0: their client list and job history is their company.*

**T-02 · Error monitoring**
Sentry (free tier) in `app.py`, with the instance name as a tag so you can tell
whose CRM threw. Plus a `/health` endpoint next to the existing `/version`
(`blueprints/admin.py:14`) returning app + DB status.
*Why P0: with N instances you currently learn about outages by phone call.*

**T-03 · Self-serve password reset**
Today the owner login is `ADMIN_USER`/`ADMIN_PASS` in Railway env vars
(`auth.py`). A customer who forgets their password can only be rescued by you
editing their environment. That is a support call per customer, forever.
- Emailed reset token for `User` accounts, expiring, single-use
- On first login, force the env-var owner to create a real `User` account and
  then stop honouring the env login for that instance
- Keep the env login as break-glass only

**T-04 · Stripe live/test mismatch guard**
`settings/connections` already has a test that names the business a key belongs
to. Promote it from a checklist item to a hard block: refuse to generate a
customer-facing payment link when the connected Stripe account's business name
doesn't match `BusinessSetting('business_name')`. Show the mismatch loudly.
*Why P0: `NEW_CUSTOMER_SETUP.md` calls this "the one expensive mistake." Money in
the wrong bank account is the only unrecoverable failure on the list.*

**T-05 · Adversarial access tests**
A new `tests/test_isolation.py`:
- Cleaner A's `claim_token` / `checklist` token cannot open cleaner B's job
- A completed or released job's token stops working
- A `team`-role session gets 403/redirect on **every** owner-only endpoint by
  direct URL — enumerate them from `navigation.py`, don't hand-list them
- `portal_token` for client A cannot read client B
- Every token-guarded route rejects a truncated or altered token

This is the version of "Phase 2" that actually applies to this architecture, and
it's a day rather than a month.

### 🟠 P1 — needed for the demo and the first onboarding

**T-06 · Demo seed script — `seed_demo.py`**
One command builds *Sparkle Cleaning Services*: 12 clients, 6 cleaners, 3 teams,
25 jobs across past and future, 4 recurring series, 1 commercial account, 1 deep
clean, 1 cancellation, 1 unavailable cleaner, mixed pay structures, completed
checklists with photos, message history, a month of P&L. Refuses to run against a
database that already has real data.
*Never demo an empty dashboard.*

**T-07 · Client + cleaner CSV import**
Upload → column mapping → preview → commit, with duplicate detection. This is how
Customer #1's business is already in there when they first log in, and it's the
difference between a great first impression and homework.

**T-08 · Extend the Setup checklist to first job**
`onboarding.py` is good. Add a percentage-complete indicator and make the final
item **"Schedule your first job"** — the activation event. The checklist stays
visible on the dashboard until that item is done.

**T-09 · Product analytics**
Log these events to a table, with a weekly digest emailed to you:
`org_created, user_invited, staff_created, client_created, job_created,
job_scheduled, crew_assigned, checklist_started, job_completed,
job_pay_calculated, login, payment_received`.
The one number that matters: **jobs run through the platform per week.**

**T-10 · Legal**
Terms of service with a liability cap · privacy policy covering processed data ·
an explicit not-a-payroll-provider / not-a-classification-advisor clause on the
1099 and payroll pages · a written data export + deletion commitment on cancel.
Have a lawyer read them.

**T-11 · Hide the three off-mission modules**
A `BusinessSetting` feature flag per module — Commercial, Content Studio, VA
Commissions — default off on a new instance, switchable in Settings. Nothing gets
deleted; your own instance keeps all three on.

**T-12 · Per-customer messaging runbook**
Write the Twilio 10DLC brand + campaign registration steps and the Resend DNS
steps into `NEW_CUSTOMER_SETUP.md`, flagged as **start on day one — carrier
approval takes days to weeks and can be rejected.**

### 🟡 P2 — before customer #3

**T-13 · Make `_migrate_db()` survivable**
`app.py:409` runs hand-written `ALTER TABLE`s against live customer data at boot.
Minimum: a dry-run mode that logs what it would do, a per-instance record of
which migrations have run, and a documented rollback. Alembic is the real answer;
this is the cheap one.

**T-14 · Fleet dashboard**
One page on your own instance that pings each customer's `/version` and
`/health`: release, up/down, last error, jobs this week. You cannot support
instances you cannot see.

**T-15 · Provisioning script**
Only after you've done #1 and #2 by hand and know where the two hours actually
go. Automating a process you haven't run twice bakes in the wrong process.

**T-16 · Middle role**
When a customer asks for an office manager who sees job costs but not payroll.
Not before.

### 🟢 LATER — explicitly deferred

Multi-tenancy · self-service signup · Stripe subscription billing · admin UI
theming · route optimisation · AI crew optimisation · advanced analytics ·
custom domains per customer.

---

## Part C — The golden demo script

Ten minutes. One scenario. Run it on the seeded *Sparkle Cleaning Services*.

> *"Mrs. Johnson wants a deep clean Thursday at 10."*

1. Find Mrs. Johnson in Clients — she's already a repeat customer. **(20s)**
2. Book a $280 deep clean, Thursday 10am. **(60s)**
3. Calendar — there it is, next to Thursday's other work. **(20s)**
4. Assign Maria and Jennifer. **(30s)**
5. **Pick up your phone.** Open the link Maria just got. Job, address, access
   notes, checklist, on-the-way, clock-in. **(2 min — this is the demo)**
6. Walk the checklist. Add a photo. Sign. Submit complete. **(90s)**
7. Back on the laptop: the job is done, and Maria's pay is already calculated.
   **(60s)**
8. Payroll — what Maria gets paid Friday, no spreadsheet. **(60s)**
9. Job economics — what the owner kept on that $280. **(60s)**

Then stop. You've shown the whole loop: customer → revenue → job → labour →
execution → pay → profit.

If they lean forward, show hiring second. Nothing else. Do not open Settings.

---

## Part D — Prospect screen

30 companies. Qualify on all five:

1. **3–10 cleaners.** A solo cleaner has no team pain. A 100-person company drags
   you into enterprise work.
2. **Evidence of a team** — a "our team" page, hiring ads, multiple vans, high
   review counts.
3. **The owner still does the scheduling herself.**
4. **Recurring residential clients.** 50–200 is the sweet spot.
5. **Cleaners paid a percentage or per job — not hourly W-2.** ← *the filter the
   outside analysis missed.* The pay engine, 1099s and W-9 flow are all built
   around per-job contractor pay. An hourly W-2 shop will fight the product.

Open with discovery, not a pitch:
*"How are you assigning cleaners to tomorrow's jobs?"* ·
*"How do they know where they're going?"* ·
*"How do you work out what each cleaner gets paid?"* ·
*"How do you know your standard was followed?"* ·
*"What happens when someone calls out?"*

Their answers tell you which two minutes of the demo to spend five on.

---

## Part E — The offer

**Founding Operator — first 10 companies only**

Everything: scheduling, calendar, clients, recurring work, team assignment,
per-job pay, checklists, SOP library, hiring funnel, messaging. Unlimited office
users, up to 10 cleaners. Hosting included. Direct founder onboarding — *we load
your clients, cleaners, prices and upcoming jobs for you.* Priority support. No
setup fee. No contract. Cancel anytime. **Your price is locked for as long as you
stay subscribed.**

**Price: decide after you've measured one month of real hosting cost on a second
instance.** $79 is the number in the outside analysis; it did not account for you
absorbing Railway Pro, a service and a Postgres per customer. If the margin is
thin, launch at $99–$129 — you are selling a hiring funnel and a pay engine that
ZenMaid doesn't have, not a discount calendar. A price you have frozen forever is
not a place to be optimistic.

Invoice #1 manually. Stripe subscriptions can wait.
