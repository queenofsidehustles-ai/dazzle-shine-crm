# Launch Plan — Customer #1

Written 2026-08-24, after reading the code at `v2026.08.19.4`.

This responds to the outside 30-day analysis. Most of it is good. One piece of it
is wrong for this application, one piece is missing, and the risk list is aimed
at the wrong risks. Everything below is what I'd actually do.

---

## The headline

**You are much closer to a first paying customer than that analysis assumed, and
much further from being able to support ten of them.**

The analysis's biggest recommendation — "add `tenant_id` to every table, make
multi-tenancy bulletproof, Days 1–7" — describes a rewrite you should not do.
The five real blockers are smaller, and none of them are in the product's
feature set.

---

## 1. Skip Phase 2 entirely. You are not multi-tenant and you shouldn't be.

The analysis assumed a shared database where Company A and Company B are rows
apart, and correctly said that's the highest-risk thing in such a design.

That is not this application. `NEW_CUSTOMER_SETUP.md` and `branding.py` already
commit to **instance-per-customer**: separate app, separate Postgres, separate
domain, separate Stripe. There is no `tenant_id` in `models.py` because there is
nothing to disambiguate. Company A cannot read Company B's data by changing a URL
because Company B's data is in a different database on a different server.

That is *stronger* isolation than `tenant_id`, not weaker. Retrofitting tenancy
across 33 models and 262 routes is 4–8 weeks that buys you nothing until roughly
customer #15, and it introduces exactly the class of bug — one missing
`.filter_by(org_id=...)` — that instance-per-customer makes structurally
impossible.

**Decision: stay instance-per-customer through customer #15. Revisit at #10.**

### But instance-per-customer has its own risks, and those *are* your launch gate

The analysis never covers these because it didn't know the architecture. These
are the real Days 1–7 list:

| Risk | Status in the code | Severity |
|---|---|---|
| **No backups** | Zero. No `pg_dump`, no backup policy, nothing in any doc. | 🔴 Blocker |
| **No error monitoring** | Zero. No Sentry, no logging config. | 🔴 Blocker |
| **Schema migrations are hand-rolled** | `app.py::_migrate_db()` — a manual `ALTER TABLE` script that runs on every boot. | 🔴 Blocker |
| **No cross-instance visibility** | You cannot answer "is customer #3 using it?" without logging into their box. | 🟠 Day 30 |
| **Provisioning is 2 hours of manual Railway work** | Documented, not scripted. | 🟢 Fine at #1 |

On one instance — yours — no backups is untidy. On somebody else's instance it is
the end of the relationship and possibly the end of their business. A cleaning
company's client list and job history *is* the company.

`_migrate_db()` deserves special attention. Right now a model change reaches a
customer's live database as a hand-written `ALTER TABLE` that runs at boot,
against their real data, with no dry run and no rollback. It has worked because
you've been the only one it could hurt. That changes the day someone else's
payroll is in it.

---

## 2. Skip Phase 3 too. Two roles is right, and field workers shouldn't have logins.

The analysis wants three roles: Owner / Manager / Field Worker.

You have two (`owner`, `team` — `models.py:1361`), and cleaners have **no login at
all**. They get tokenised magic links: `/claim/<ctoken>/<stoken>`,
`/checklist/<token>`, clock-in, clock-out, photos, signature, submit-complete.

That is a better design for this workforce, not a worse one. A cleaner standing
at a front door at 8am with wet hands does not want to remember a password. A
texted link that opens straight to today's job is the correct product. Do not
replace it with accounts.

The tokens themselves are sound — `secrets.token_urlsafe(24)` and `(32)`, which
is not guessable.

**What to test instead of building a third role:** whether one cleaner's token
can reach another cleaner's job or pay. That's the real adversarial test for this
architecture, and it's a half-day of work, not a week.

**One gap that is real:** `owner` vs `team` is a blunt split. A customer with an
office manager who *should* see job costs but *not* payroll has nowhere to put
her. Note it, don't build it — wait for a customer to ask.

---

## 3. The billing gap is worse than the analysis says, and it's commercial, not technical

There is no subscription billing in the codebase. The analysis said "invoice
Customer #1 manually" — correct, do that.

But it missed the actual problem. Per `NEW_CUSTOMER_SETUP.md`, the customer
creates their **own Railway account**, on Railway's **Pro plan**, to pull a
private registry image. So the sales conversation is currently:

> "It's $79/month. Also, please create a Railway account, upgrade it to Pro,
> paste in this GitHub token, and add a Postgres database."

A cleaning company owner who runs her schedule on WhatsApp will not do this. It
is not a pricing objection, it's a wall.

**Fix: you own the Railway project. $79 includes hosting.** They get a URL and a
login and never hear the word Railway. That also removes the private-registry
problem — it's your workspace, your token.

**Check the margin before you commit to $79.** Railway Pro plus a service plus a
Postgres per customer is real recurring cost against $79. Run the numbers on one
instance for a month before you promise anyone "$79 locked in forever." I'd
rather you launch at $99 or $129 than discover at customer #8 that hosting eats
half the revenue and the price is contractually frozen.

---

## 4. What the analysis got right — keep all of this

- **The objective.** One real outside company, paying, running real jobs, paying
  again in month two. That is the right bar.
- **`FIRST_JOB_SCHEDULED` as the activation event**, not account creation.
- **The 10-minute golden demo** built on one scenario end to end. Yours writes
  itself: create client → book $280 deep clean → calendar → assign two cleaners →
  *show the texted link on a real phone* → checklist → clock out → complete →
  pay statement → owner's P&L. The phone step is the demo. Lead with it.
- **Manual white-glove onboarding for #1.** Import their client list yourself.
  You already have `Cleaning Customers.csv` shaped data to model the importer on.
- **The discovery questions**, especially *"how do you calculate what each cleaner
  gets paid?"* — that one maps directly onto your strongest feature.
- **"Would you use it today without Feature X?"** before building anything custom.
- **Don't make it free.** Agreed completely.
- **Get customers #2–#5 before scaling.** Agreed.

---

## 5. What the analysis missed entirely

### a) You are selling an opinion, not a CRM — and that's the moat

Look at what's in this repo that isn't software: `CONTRACTOR_PAY_POLICY.md`,
`HIRING_MESSAGES.md`, `GROWTH_PLAYBOOK.md`, `VA_TRAINING_PLAN.md`,
`call_scripts.py` (22KB of actual scripts), the SOP library, the interview
funnel, pay-the-job-not-the-hour computed everywhere.

ZenMaid, Jobber and BookingKoala give a cleaning company an empty scheduling
tool. You are giving them **a way to run a cleaning company that already works**,
with the software wrapped around it. That is the thing worth $79, and it's the
thing a competitor can't ship next quarter.

**So don't sell "CRM."** Sell: *"the operating system for a cleaning company that
pays cleaners per job — hiring funnel, pay math, SOPs and schedule in one place,
built by someone running one."*

### b) That same opinion is your qualification filter

The product assumes contractors paid a **percentage of the job**. `Staff.pay_type`
defaults to `'percent'` at 50%. Pay, 1099s, W-9 collection, the raise policy — all
built around it.

A company paying W-2 hourly with a time clock will fight the product the whole
way. **Add to the prospect screen: "how do you pay your cleaners?"** Percentage or
per-job → ideal. Hourly W-2 → politely pass for now. This one question will save
you two wasted demos out of every ten.

### c) Twilio 10DLC will blow up the 30-day timeline if you start it on Day 22

Every new company needs its own Twilio number and its own **A2P 10DLC brand and
campaign registration** before it can text cleaners at volume. That's a carrier
approval process measured in days to weeks and it can be rejected. Same story for
Resend domain verification and its DNS records.

The texted job link is your entire field-worker experience. If it can't send,
there is no product.

**Start Twilio registration and email DNS on Day 1 of that customer's onboarding,
in parallel with everything else.** Not on Day 22. This is the single most likely
reason a 30-day plan becomes a 50-day plan.

### d) Legal exposure is not "terms/privacy basics"

You will be holding, on your infrastructure, another company's: client names and
home addresses, house access notes, employee W-9s, background checks
(`secure_docs.py`, `ContractorDocument`), and pay records.

That is not a marketing site's privacy policy. You need:

1. **Terms of service** with a clear liability cap.
2. **A privacy policy** covering data you process on their behalf.
3. **An explicit line that you are a record-keeping tool, not a payroll provider
   or an employment-classification advisor.** Your product computes contractor
   pay and generates 1099 data. If a customer misclassifies an employee as a
   contractor, you do not want to be the one who "told them to."
4. **A written data-deletion and export commitment** — what happens to their data
   when they cancel.

Get these reviewed. It is a few hundred dollars and it is not optional once
someone else's employee records are on your server.

### e) The Stripe test/live footgun should be code, not a checklist item

`NEW_CUSTOMER_SETUP.md` calls it "the one expensive mistake" and then handles it
with a checkbox. Money landing in the wrong account is unrecoverable and it
happens exactly once before you lose the customer. Make the app refuse to send a
real payment link while the connected Stripe account's business name doesn't
match the configured business name. Ten lines. Do it.

---

## 6. The corrected 30-day sequence

Assumes you are shipping the audit list in `LAUNCH_BACKLOG.md` alongside this.

**Days 1–5 — Make it safe to hold someone else's business**
Backups. Error monitoring. Password reset. The Stripe guard. Cleaner-token
isolation test. Freeze features — nothing new gets added from here.

**Days 6–8 — Make it demoable**
Seed script that builds "Sparkle Cleaning Services" with 12 clients, 6 cleaners,
3 teams, 25 jobs, recurring work, a commercial account, a cancellation, completed
checklists. Run the golden demo end to end on an iPhone, an Android and a laptop
until it's boring.

**Days 6–8, in parallel — Commercial setup**
Founding offer written down. Terms and privacy drafted. Decide the final price
after you've measured one month of real hosting cost.

**Days 9–14 — Find the room**
30 qualified cleaning companies. Screen on: 3–10 cleaners, evidence of a team,
and *how they pay*. Founder outreach with discovery questions, not a pitch.

**Days 15–21 — Demos**
5–10 of them. Target: one signature at your chosen price.

**Day 21 — The day they say yes, before anything else**
Start their Twilio 10DLC registration and their email DNS. Same hour. This is the
long pole.

**Days 22–24 — White-glove migration**
Their clients, cleaners, services, prices, recurring jobs, pay rates. They log in
and their business is already there.

**Days 25–26 — Training**
Owner, then cleaners. Watch where they hesitate — that's your onboarding backlog.

**Days 27–30 — Run it live**
Fix P0/P1 only. Log everything else. Count **jobs run through the platform per
week** — that number, not logins, tells you whether it took.

**Day 30 — The three questions**
"If I turned it off tomorrow, what would you go back to?" / "What would you miss
most?" / "What makes you hesitate about month two?" Then charge month two.

---

## 7. The launch gate

Do not take a paying customer's operational data until every one of these is
true. The rewritten list, aimed at this architecture:

- [ ] Automated daily Postgres backup, and **a restore you have actually performed**
- [ ] Error monitoring reporting to somewhere you look
- [ ] Owner can reset their own password without you touching Railway
- [ ] Cleaner token A cannot reach cleaner B's job or pay
- [ ] `team` role cannot reach any money page by typing the URL
- [ ] Stripe live/test guard blocks a mismatched payment link
- [ ] Full job lifecycle passes on iPhone, Android and desktop
- [ ] `_migrate_db()` has a dry-run and a documented rollback
- [ ] Terms, privacy and the not-a-payroll-provider clause exist
- [ ] `test_whitelabel.py` passes on a blank instance

Everything else can evolve after they're paying.

---

## 8. What I'd deliberately not do yet

- Multi-tenancy
- Self-service signup and Stripe subscription billing
- A third role
- Admin UI theming (they're the only ones who see it)
- Route optimisation, AI crew optimisation, advanced analytics
- Customers #6 through #1,000

Get one company running real jobs. Then four more. Then look at what all five did
the same way, and automate *that*.
