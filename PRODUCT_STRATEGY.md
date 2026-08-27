# Product Strategy — freemium, naming, mobile, and going multi-vertical

Written 2026-08-26. Builds on `SAAS_ROADMAP.md` (architecture) and
`LAUNCH_BACKLOG.md` (pre-launch work).

---

## 1. Freemium — the honest read, then why it works *for you* anyway

### The general case against it

None of your competitors are freemium. Jobber, ZenMaid, BookingKoala and
Housecall Pro all use **14-day free trials**. That's not an accident, and the
reasons apply to you:

- **Your marginal cost per user is not zero.** Every job notification is an SMS.
  Twilio is roughly a cent per segment plus carrier fees. A free company texting
  200 notifications a month is cash out of your pocket, monthly, forever, from
  someone who has never paid you.
- **Support cost is the real killer.** Field-service software users are not
  self-serve. They call. Free users generate roughly the same ticket volume as
  paying ones.
- **The TAM is small.** Maybe 100–200k US cleaning companies with employees.
  Freemium math needs millions of users to work. Yours doesn't have them.
- **It anchors the price.** "Software for my cleaning business is free" is a hard
  belief to un-teach at renewal.

### Why I'd still say yes, in your specific case

You are not a generic founder. Your audience — *Queen of Side Hustles*, the
course material in this repo, the playbooks — is **people starting service
businesses.** They start solo. They grow. They hire a second person.

That is the single best freemium setup there is: **a free tier that is genuinely
great for one person, and structurally incapable of running a crew.** They don't
hit an arbitrary wall, they hit *the moment their business changes* — and that
moment is exactly where your product's real value (crew assignment, per-job pay,
hiring) begins.

Your free tier isn't a discount. It's a lead magnet you already have the audience
for, and an on-ramp into the paid product at the precise week they need it.

**So: yes to freemium — with two non-negotiable rules.**

1. **No SMS on the free tier. Email only.** This is the one that protects the
   business. Every other limit is a product decision; this one is cash.
2. **No direct support on free.** Docs, videos, and a community. Your time is the
   second thing free users would consume without limit.

And run a **14-day Pro trial on top of it**, so a real company with 6 cleaners can
evaluate the actual product without pretending to be solo.

---

## 2. The tiers

Three tiers. Names matter — they should describe the customer, not the plan size.

### 🆓 Solo — free forever
*For the owner-operator who is still doing the cleaning.*

- 1 owner login
- **Up to 2 field workers** (them plus one helper)
- Unlimited clients
- **20 jobs / month**
- Calendar and scheduling
- The cleaner magic-link job flow
- **1 checklist template**
- Manual payment recording
- **Email notifications only — no SMS**
- "Powered by [Product]" on customer-facing pages
- Docs and community support

### 💼 Pro — $99/mo
*For the owner who has stopped cleaning and started managing. This is the product.*

Everything in Solo, plus:
- **Up to 10 field workers**, unlimited office logins
- Unlimited jobs and clients
- **SMS included** (fair-use cap, e.g. 1,000/mo, then metered)
- **Per-job pay engine, payroll, 1099 and W-9** ← the wedge
- **Hiring funnel** — applications, interviews, offers, onboarding ← the wedge
- SOP library and unlimited checklists
- Recurring jobs and automations
- Card payments via Stripe
- P&L, job economics, reporting
- Online booking widget for their website
- Email support

### 🏢 Scale — $199/mo
*For multi-crew operations and commercial work.*

Everything in Pro, plus:
- **Unlimited field workers**
- Commercial accounts, quotes, and the lead finder
- Multi-brand (residential + commercial identities)
- Remove "Powered by"
- Advanced reporting and data export
- Priority support and onboarding call

### The design principle behind those splits

**Gate on scale and money, never on the core loop.**

A free user must be able to run a real job start to finish — book it, schedule
it, send the cleaner, complete the checklist, get paid. If they can't, they never
learn what the product does and they never convert.

What's gated is what appears *when they start succeeding*: a third worker, the
50th job, paying a crew, hiring, knowing their margin.

Notice what's on the free tier that competitors charge for — the cleaner job flow
and checklists. That's deliberate. It's the part people fall in love with, and
it's the part that costs you almost nothing to give away.

### Two rules that prevent the ugly moments

- **Never delete or hide data on downgrade.** If a Pro customer drops to Solo with
  40 clients, they keep all 40 — they just can't add a 41st, and month-old jobs go
  read-only. Blocking a *new action* is a nudge. Making yesterday's records vanish
  is a betrayal, and it's what people write reviews about.
- **Grandfather the founding customers permanently.** A `grandfathered` flag on
  the organization that survives every future price change. It's the only reason
  an early adopter should move now.

---

## 3. What to build for gating

This is small — days, not weeks — if it's done in one place.

**`entitlements.py` — one module, one source of truth**

```
PLANS = {
  'solo':  {'field_workers': 2,  'jobs_per_month': 20,   'sms': False,
            'checklist_templates': 1, 'features': {...}},
  'pro':   {'field_workers': 10, 'jobs_per_month': None, 'sms': 1000, ...},
  'scale': {'field_workers': None, ...},
}

can(org, 'hiring')          -> bool
limit(org, 'field_workers') -> int | None
usage(org, 'jobs_this_month') -> int
```

Everything else calls into it. No plan checks scattered through 262 routes.

**The pieces:**

1. `plan`, `plan_status`, `trial_ends_at`, `grandfathered` on the `organizations`
   table in the control-plane schema (see `SAAS_ROADMAP.md` §3).
2. A `@requires_plan('pro')` decorator — **server-side, always.** Hiding a menu
   item is not gating. Model it on the existing `@owner_required` in `auth.py`;
   it's the same shape.
3. Extend `navigation.py`. Sections already carry an `owner_only` flag — add a
   `min_plan` alongside it, and render locked items **greyed with a 🔒, not
   hidden.** A feature you can see but can't use sells the upgrade. A feature you
   can't see doesn't exist.
4. Usage counters: active workers, jobs this month, SMS this month. Cheap
   aggregate queries, cached.
5. **An upgrade screen that sells rather than blocks.** When they hit the 20-job
   wall: *"You've scheduled 20 jobs this month — you're growing. Pro removes the
   limit and calculates what every cleaner is owed."* Show the number they just
   hit. It's proof they need it.
6. Stripe Billing checkout, webhooks, and a `past_due` state that locks to a
   "update your card" screen without touching data.
7. **Instrument the walls.** Log every entitlement denial with the org, the
   feature and the date. Which wall people hit before upgrading — and which walls
   they hit and then churn — is the most valuable pricing data you will ever
   have. Most companies don't collect it.

---

## 4. Naming

### Constraints, from everything above

Since you're expanding past cleaning, **the name cannot contain "clean," "maid,"
"tidy," "sparkle," or a broom.** ZenMaid boxed itself in permanently; don't repeat
it. It also shouldn't rhyme with Jobber or read like generic B2B mush.

Your differentiator is **crew** — hire them, schedule them, pay them, hold them to
a standard. Lean the name there. It's true across cleaning, landscaping,
detailing, pressure washing and window cleaning.

### Direction A — crew-forward *(my recommendation)*

| Name | Why |
|---|---|
| **Crewline** | Crew + the lineup / the day's line-up of jobs. Vertical-neutral, says what it does, sounds like a real company. **My top pick.** |
| **CrewKit** | Friendly. Honest about what you actually sell — a kit: hiring funnel, pay engine, SOPs, scheduling. Approachable for a first-time owner, which is your audience. |
| **Crewhaus** | Slightly more premium. Good if you want to price at $149+. |
| **OnCrew** | Short, app-like, easy to say on a phone call. |

### Direction B — operations-forward

| Name | Why |
|---|---|
| **Runsheet** | A runsheet *is* the day's job list — the actual trade word. Distinctive, ops-native, zero vertical lock-in. Most memorable name on this page. |
| **Dayrate** | Nods at per-job pay. Narrower. |
| **Cadence** | Recurring work. Pretty, but vague and widely used. |

### Direction C — brandable / abstract
**Kova · Rove · Sable · Tandem.** Cheapest to trademark, but you'd pay for the
meaning in marketing spend for years. Not where I'd go with a small budget.

### Before you commit — the checklist

1. **USPTO trademark search** (tess2.uspto.gov) in class 42 (SaaS) and class 35.
   Free, and it's the one that can force a rename after launch.
2. `.com` availability. If it's taken but parked, price it — a good `.com` for
   $2–5k is a real asset. **Avoid `.io` and `.ai`** for this market; your
   customers will mistype it into `.com` and land on someone else.
3. Google it with "software" and "cleaning."
4. **The phone test.** Say it out loud: *"We use Crewline to run our cleaning
   business."* If it needs spelling twice, drop it.
5. Instagram, Facebook, TikTok handles — your audience lives there.

Pick the name **before** the multi-tenant build, because it goes into the
subdomain scheme, the emails, the Stripe products and the app-store listing. A
rename after launch is genuinely painful.

---

## 5. App Store — my recommendation is *not yet*, and here's the reasoning

### Why you probably shouldn't build native apps this year

**Your magic links are better than an app for cleaners, and that's a competitive
advantage, not a gap.**

A cleaner hired last Tuesday, on a $40 Android with no free storage, taps a text
and is looking at today's job in two seconds. No download, no account, no
password, no "I can't log in" support ticket. ZenMaid and Jobber both require an
app install and both pay a support tax for it. **Say this out loud in demos.**

**Also:**
- **Apple rejects wrapped websites.** Guideline 4.2 ("minimum functionality") is
  the single most common rejection. A webview around your Flask app gets refused.
  A real native app is a separate codebase and a permanent second thing to
  maintain.
- **Apple's cut.** If the app unlocks paid features, Apple generally wants In-App
  Purchase — 30%, or 15% under the Small Business Program. That's your Pro margin.
  The standard B2B workaround is a **free app you sign into with an existing
  account, with no purchase path in the app at all** (what Jobber and Housecall Pro
  do). Anti-steering rules have been in flux since the US Epic ruling — **verify
  the current guidelines when you actually build**, don't plan around what's true
  today.
- **Google's newer requirements bite too** — new personal developer accounts face
  a closed-testing requirement (roughly 12 testers over 14 days) before production
  release. An organization account has a different path. Check before you assume a
  launch date.

### Do this instead: ship a PWA

Installable to the home screen, works offline, **and iOS supports web push for
home-screen PWAs** (16.4+), which covers most of what you'd want native for. Days
of work, not months, and it uses the app you already have.

### When to go native — the actual triggers

Build it when you can say yes to at least two:
- 100+ paying companies asking for it by name
- You need push notification reliability a PWA can't give you
- You need real offline (cleaners in basements with no signal — this one is real)
- Camera and GPS quality for job photos and arrival verification matters

Then build **one app — the crew app.** Owners work on a laptop; that's where
scheduling and money actually happen. Two apps is two problems.

### When you do submit, these cause most rejections

- Missing **in-app account deletion** — mandatory for any app with signup, and
  constantly missed
- No demo account for the reviewer (login-gated apps must supply working creds)
- Incomplete privacy nutrition labels, or a privacy policy URL that 404s
- Anything that looks like a repackaged website

Budget: $99/yr Apple, $25 one-time Google. Review is usually 1–3 days once you're
past the first approval.

---

## 6. Going multi-vertical — how, and when

### The code is readier than you'd think

Cleaning-specific surface area is small: four columns on `Booking`
(`bedrooms`, `bathrooms`, `sqft`, `extras`) and the bed/bath matrix in
`pricing.py`. **Jobs, crew, assignment, per-job pay, checklists, SOPs, hiring,
messaging, invoicing and the money pages are all already vertical-neutral.**

**The work — do it during the multi-tenant build, it's cheap then and expensive later:**

1. **Replace the four columns with a `job_attributes` JSON field.** Each vertical
   defines its own: cleaning gets beds/baths/sqft, landscaping gets lot size and
   service type, detailing gets vehicle class.
2. **Make pricing pluggable.** Today it's one hardcoded matrix. It needs to be a
   strategy per tenant: `flat` · `per_unit` · `per_hour` · `per_sqft` ·
   `matrix` (what you have) · `quote_only`. Landscaping is per-visit-flat,
   detailing is per-vehicle-class, pressure washing is per-sqft.
3. **Vertical packs.** A bundle of seed content: service list, default prices,
   checklist templates, SOPs, hiring questions, call scripts. Cleaning already
   exists — it's your `_seed_*` functions. Each new vertical is content work, not
   engineering, and **that's the part you can actually do faster than a
   competitor**, because you know how these businesses run.

### But do not market horizontally yet

"Software for service businesses" is Jobber and Housecall Pro. They are
established, funded, and horizontal. Entering as a fifth generic option means
losing on distribution before anyone sees the product.

**Stay "for cleaning companies" until roughly 100 paying customers.** Own the
niche, get the case studies, then expand *one vertical at a time* along the
natural adjacency:

> cleaning → **window cleaning** → **pressure washing** → **carpet cleaning** →
> lawn care → mobile detailing

Those first three are the closest neighbours: crew-based, recurring, residential,
same customer, often literally the same owner adding a service line. Some of your
cleaning customers will *ask* for pressure washing before you offer it. That's
your signal to build the pack.

Build the architecture horizontal. Sell vertical. The name lets you switch for
free — which is why §4 says pick a neutral one.

---

## 7. Where you actually win

| | You | Jobber | ZenMaid | BookingKoala | Housecall Pro |
|---|---|---|---|---|---|
| Cleaning-native | ✅ | ❌ | ✅ | ✅ | ❌ |
| **Hiring funnel** | ✅ **unique** | ❌ | ❌ | ❌ | ❌ |
| **Per-job crew pay** | ✅ **strong** | ❌ | ⚠️ | ⚠️ | ❌ |
| SOPs + photo checklists | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ |
| No-install crew access | ✅ | ❌ | ❌ | ❌ | ❌ |
| Free tier | ✅ | ❌ | ❌ | ❌ | ❌ |
| Online booking widget | ⚠️ *gap* | ✅ | ✅ | ✅ | ✅ |
| QuickBooks sync | ❌ *gap* | ✅ | ✅ | ⚠️ | ✅ |
| Native mobile app | ❌ | ✅ | ✅ | ✅ | ✅ |

**Two gaps worth closing, in order:** the embeddable booking widget (owners ask
for it by name; it's how their website becomes jobs) and QuickBooks sync (loses
deals with bookkeepers, but only after you have bookkeepers to lose).

**The positioning, one line:**

> *Every other tool puts your jobs on a calendar. This one helps you hire the
> crew, pay them per job, and prove the work got done to your standard.*

Nobody else can say it, and you can only say it because you run one.
