# Turning this into a real SaaS

Written 2026-08-24. Supersedes the architecture sections of `LAUNCH_PLAN.md`
if — and only if — the goal is self-service subscription SaaS in the mould of
Jobber, ZenMaid and BookingKoala.

---

## 0. First: three different businesses, one product

These keep getting used interchangeably. They need different code, different
prices and different sales motions. Pick one to lead with.

| | **A. Private deployment** | **B. Multi-tenant SaaS** | **C. True white label / reseller** |
|---|---|---|---|
| What they buy | Their own instance, set up for them | A login at `theirname.yourcrm.com` | Your product under *their* brand, resold to *their* network |
| Who they are | One cleaning company | Hundreds of cleaning companies | Franchise groups, cleaning coaches, consultants |
| Signup | You, 2 hours of setup | Credit card, 60 seconds, 3am, no human | Contract |
| Price | $300–500/mo | $79–149/mo | $500–2,000/mo + per-seat |
| Ceiling | ~20 customers before you drown | Thousands | ~10 partners, but each is worth 20 customers |
| Architecture | **What you have today** | Needs the work below | Multi-tenant + custom domains + branding |
| Time to first dollar | Now | 2–3 months | Now-ish, but long sales cycles |

**You said "white label," you built A, and the outside analysis assumed B.** That's
the whole source of the confusion. Answering your question directly: yes — if the
goal is B, that analysis's Phase 2 becomes correct in *principle*. But it's still
wrong in *method* and wrong in *timing*, and both matter more than the principle.

---

## 1. What the outside analysis gets right and wrong, re-scored for SaaS

| Its advice | Verdict for a real SaaS |
|---|---|
| Phase 1 — freeze MVP scope | ✅ Still right |
| Phase 2 — "add `tenant_id` to every table" | ⚠️ **Right goal, wrong method.** See §2 — `tenant_id` is the most expensive and most dangerous of the three ways to do this. |
| Phase 3 — three roles | ⚠️ Partly. Owner/manager split yes. **Field workers still should not have logins** — your texted magic links are better and the market agrees (ZenMaid's cleaner app is the weak point in their product). |
| Phase 4 — onboarding wizard | 🔼 **Much more important now.** With no human in the loop, the wizard *is* the salesperson. |
| Phase 5 — "skip self-service billing" | ❌ **Now wrong.** Billing isn't a nice-to-have in a SaaS, it's the product's front door. It's also 1–2 weeks with Stripe Billing, not the two-week disaster it implies. |
| Phase 6 — one offer, $79 | ⚠️ One offer yes. See §5 — the price is decided by economics you haven't measured. |
| Phases 7–16 — demo tenant, golden demo, manual onboarding, prospecting, support, instrumentation, 30-day test | ✅ **All still right.** This is the strongest part of that document and none of it changes. |

The sequencing mistake is the important one. **Do not stop selling in order to
rewrite.** See §6.

---

## 2. The architecture decision — and it isn't `tenant_id`

Three ways to run many companies on one product. This is the single highest-stakes
technical decision in the whole plan.

### Option 1 — Row-level (`org_id` on every table). What the analysis proposed.
One database, one set of tables, every row tagged.

- **Cheapest to run.** What Jobber and Salesforce do at scale.
- **Brutal to retrofit.** 33 models, 262 routes. Every query, every `.get()`, every
  report needs a filter added.
- **One missed filter leaks a customer's client list into another's screen.** There
  are hundreds of places to miss it and no compiler to catch you.
- Realistic effort here: **6–10 weeks**, with a long tail of leaks found in production.

### Option 2 — Schema-per-tenant. ✅ **My recommendation.**
One Postgres database. Each company gets its own **schema** — its own copy of all
33 tables. A request to `acme.yourcrm.com` sets `search_path = tenant_acme` and
every existing query in the codebase then reads Acme's tables. Untouched.

- **Your models don't change. Your 262 routes don't change.** `Booking.query.all()`
  already returns only the current tenant's bookings, because Postgres — not your
  code — decides which tables that means.
- **Isolation is enforced by the database**, not by remembering a filter. A bug
  gives you *no* data, not *someone else's* data. That failure mode is survivable;
  the row-level one is not.
- **The migration path from where you are today is nearly trivial.** Each customer
  currently has a separate database with exactly these tables. `pg_dump` it,
  restore into a schema. Your existing instances become tenants without a rewrite.
- **`create_app()` already contains the provisioning routine.** `db.create_all()`
  plus twelve `_seed_*` functions (`app.py:200`) run at boot today. Point them at a
  new schema and that's your signup flow — the hard part is written.
- Realistic effort: **2–3 weeks.**

Costs of choosing it: migrations must loop over every schema (which forces the
Alembic fix you need anyway); cross-tenant reporting takes deliberate work; and
Postgres gets unhappy somewhere in the low thousands of schemas. That last one is
a problem worth having, and Option 1 is still available then — from a codebase
that by that point has paying customers funding the work.

### Option 3 — Container-per-tenant. What you have.
- Perfect isolation, zero code change.
- **Cost doesn't compress and provisioning can't be instant enough for self-serve.**
  See §5. This is why it can't be the SaaS answer, and it's the only reason.

### Decision

**Schema-per-tenant.** It buys you 90% of row-level's economics for 25% of the
work and a fraction of the risk, on a codebase that was never written with tenancy
in mind. Revisit at ~500 paying companies.

---

## 3. What SaaS needs beyond tenancy

Tenancy is maybe 30% of the job. This is the rest.

### The control plane — a new shared `public` schema
Everything today lives inside a company. You now need things that live *above* one:

- `organizations` — name, subdomain, plan, status, `trial_ends_at`, `created_at`
- `accounts` — a person's login, mapped to an org (a login must resolve to a
  tenant *before* any tenant query runs)
- `subscriptions` — Stripe customer, subscription, status, current period end
- `signup_events` / product analytics

This is new code, and it's the part with no equivalent in the current app.

### Tenant resolution
Subdomain (`acme.yourcrm.com`) via wildcard DNS and a wildcard TLS certificate.
Middleware resolves subdomain → org → `SET search_path`, before the request
touches a blueprint. Custom domains later, and only for Model C.

### Alembic — non-negotiable now
`app.py::_migrate_db()` hand-writes `ALTER TABLE`s at boot. Against 200 schemas
that is not a maintenance problem, it's an outage. Alembic, with a migration
runner that iterates schemas and reports which succeeded. **Do this before the
first outside tenant, not after.**

### Stripe Billing — your subscriptions
Checkout, trial, webhooks (`invoice.paid`, `payment_failed`, `subscription.deleted`),
dunning emails, and a `past_due` state that locks the app to a "update your card"
screen without deleting anything. 1–2 weeks.

### Stripe Connect — their payment processing
Today tenants paste their secret key into Settings (`integrations.py`). That's
well built — encrypted at rest, sensible precedence — but for self-serve it's both
a conversion killer and the source of the wrong-account footgun.

**Switch tenant onboarding to Stripe Connect (Standard).** They click "Connect
Stripe," OAuth, done. You never hold a secret key, the account can't be the wrong
one, and if you ever want a platform fee the rails are there. You already know the
Connect API from `stripe_connect.py`.

### Messaging at scale — this is where multi-tenant *beats* your current model
Today every new company needs its own Twilio account and its own A2P 10DLC
registration: days to weeks, and it can be rejected. Under multi-tenant you run
**Twilio subaccounts** under your master account and register as an ISV. A new
tenant gets a working number in minutes.

Same for email: send from your verified domain with the tenant's name and
reply-to, and let them verify their own domain later as an upgrade.

**Onboarding goes from three weeks to three minutes.** That is a better product
for the customer, not just a cheaper one for you — and it's a genuine argument for
doing this properly rather than a concession.

### Self-serve onboarding
`onboarding.py`'s checklist is a good foundation but assumes someone explained the
product first. Add a real first-run wizard ending in **"schedule your first job"**,
plus the option to load the demo tenant's data so a trial account is never empty.

### Back office
List every org, usage, plan, last login, jobs this week. Impersonate a tenant for
support (logged). Suspend. Export and delete on cancellation. Without this you
cannot support 50 customers, and you cannot legally promise deletion.

### Also required
Self-serve password reset and email verification · rate limiting and signup abuse
controls · backups of the one database, with a **tested per-schema restore** ·
error monitoring tagged by tenant · terms, privacy, DPA, and the
not-a-payroll-provider clause.

---

## 4. Feature gaps against the competition

You are strong where they're weak, and that should shape the roadmap. But two
gaps will come up in demos and one of them will cost you deals.

| | You | Jobber | ZenMaid | BookingKoala |
|---|---|---|---|---|
| Cleaning-specific | ✅ | ❌ generic trades | ✅ | ✅ |
| Per-job contractor pay | ✅ **strong** | ❌ | ⚠️ weak | ⚠️ |
| Hiring / interview funnel | ✅ **unique** | ❌ | ❌ | ❌ |
| SOPs + checklists w/ photos | ✅ **strong** | ⚠️ | ⚠️ | ✅ |
| Online booking widget for *their* website | ⚠️ partial | ✅ | ✅ | ✅ **their strength** |
| Native mobile app for cleaners | ❌ magic links | ✅ | ✅ | ✅ |
| QuickBooks sync | ❌ | ✅ | ✅ | ⚠️ |
| Route optimisation | ❌ | ✅ | ⚠️ | ❌ |

**Defend the magic links.** Cleaners don't install apps, and support tickets for
"I can't log in" are the tax competitors pay. Say that out loud in demos.

**Build the embeddable booking widget.** It's the one real gap. Every competitor
has it, owners ask for it by name, and it's how their website turns into jobs.
Post-launch, but early post-launch.

**QuickBooks sync** loses deals with bookkeepers. Note it, defer it.

---

## 5. The economics — this is what actually decides the architecture

Rough monthly infrastructure per paying company:

| Model | Marginal cost / customer | Gross margin at $99 |
|---|---|---|
| Container-per-tenant (today) | ~$25–45 | **~55–75%** and it doesn't improve |
| Schema-per-tenant | ~$1–3 once you're past ~20 tenants | **~95%** |

SaaS businesses need 80%+ gross margin to survive paid acquisition and support.
The current model can't get there — not because it's badly built, but because
container-per-tenant costs are linear and subscription revenue at $99 is thin.
**That, not security, is the real reason to do this work.**

Two more numbers to hold onto:

- **CAC.** At $99/mo with 3% monthly churn, average lifetime revenue is roughly
  $3,000. You can afford maybe $600–900 to acquire a customer and still build a
  business. Paid ads against Jobber's budget will not come in under that. Your
  first 20–30 customers will be founder-sold regardless of how self-serve the
  product is. **Build for self-serve, sell like an agency, for the first year.**
- **Price.** $79 is under-priced for what this does. ZenMaid starts around $58
  and climbs with cleaners; Jobber runs $29–$169+. You bundle a hiring funnel, a
  pay engine and an SOP library that none of them have. **Launch at $99, with
  $149 for 10+ cleaners.** Founding customers get their price locked — that's the
  urgency, not a lower number.

---

## 6. The plan — do not stop selling to rewrite

The trap is disappearing for three months to build tenancy, and emerging with a
beautiful multi-tenant platform and zero evidence anyone wants it.

### Phase 0 — now, in parallel with everything else: sell 3 companies on today's architecture
Instance-per-customer is invisible to the customer. They get a URL and a login and
never know. Price it at **$149/mo founding, hosting included** — hand-onboarded,
because you'll be doing the setup yourself anyway.

Three paying companies gets you: proof people pay, cash to fund the build, and —
most valuable — three months of watching real cleaning companies use it, which is
the only reliable source of what the SaaS version must do. They migrate into the
platform later as schemas, cleanly.

Ship the P0 tickets from `LAUNCH_BACKLOG.md` (T-01 backups, T-02 monitoring, T-03
password reset, T-04 Stripe guard, T-05 isolation tests) to make that safe. Those
five carry over to the SaaS build unchanged. **Nothing in Phase 0 is throwaway.**

### Phase 1 — weeks 1–3: tenancy foundation
Alembic replacing `_migrate_db()` · `public` schema with `organizations` /
`accounts` / `subscriptions` · subdomain middleware and `search_path` ·
provisioning function reusing the existing `_seed_*` routines · a migration script
that folds an existing customer database into a schema · a test suite that proves
tenant A's session cannot reach tenant B's schema.

### Phase 2 — weeks 4–6: the front door
Marketing page and signup · email verification and password reset · Stripe Billing
with a 14-day trial, no card up front · dunning and `past_due` lockout · the
first-run wizard ending at "schedule your first job" · demo-data option for trials.

### Phase 3 — weeks 7–9: self-serve operations
Twilio subaccount provisioning and ISV 10DLC · shared sending domain with
per-tenant reply-to · Stripe Connect replacing pasted keys · back office with
impersonation, suspend, export, delete · product analytics and a weekly digest ·
in-app support channel.

### Phase 4 — weeks 10–12: migrate and open
Move the Phase 0 customers in, one at a time, with their consent and a rollback ·
load-test 50 tenants on one database · penetration-test tenant isolation, ideally
with someone who isn't you · open signups to a waitlist first, not the world.

**Realistic total: 3 months of focused work**, and only if scope stays frozen. The
schedule dies the first time a prospect asks for route optimisation and it gets
built.

---

## 7. The honest risks

**The market is crowded and well funded.** Jobber, ZenMaid, BookingKoala, Launch27
and a dozen others are established, and cleaning-company owners are hard to reach
cheaply. A generic "CRM for cleaners" loses this fight on distribution alone.

**So don't enter as a CRM.** Enter as the thing none of them have:

> *The only platform that helps you **hire** cleaners, **pay** them per job, and
> hold them to **your** standard — not just put jobs on a calendar.*

The hiring funnel and the per-job pay engine are the wedge. Scheduling is table
stakes you happen to already have.

**Your unfair advantage is that you run a cleaning company.** Every competitor is
software people who interviewed cleaning companies. You have the call scripts, the
pay policy, the hiring messages, the SOPs and the growth playbook because you
needed them. That content is a marketing engine and an onboarding asset, and it is
not something a competitor ships next quarter.

**The biggest risk isn't technical.** It's spending three months on a platform for
customers you haven't met. Phase 0 exists specifically to stop that.
