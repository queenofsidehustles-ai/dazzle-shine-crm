# Akye affiliate program: strategy and action plan

Written 2026-10-15. Companion to `GETTING_CUSTOMERS.md` (hand-picked first ten)
and `SIGNUP_FUNNEL.md` (what happens after the click). This document is about the
channel that comes after the first ten: other people who already have the ear of
cleaning-company owners, paid only when an owner actually pays.

---

## 1. The short version

- **Two programs, not one.** (a) *Customer referral*: an Akye company invites
  another owner and both get a month of credit. (b) *Affiliate partners*:
  coaches, creators, community owners, bookkeepers and VAs who serve cleaning
  companies earn **30% of the subscription for 12 months**.
- **Pay only for money received.** Commission accrues on a paid Stripe invoice,
  after a hold, never on a signup or a trial. This is the same rule as the
  Lead Specialist agreement ("closed means the customer has paid").
- **Start by hand, automate on proof.** Five affiliates, a spreadsheet ledger
  and manual payouts for the first 60 days. Build the engine once there is a
  paid referral worth paying.
- **Most of the tracking already exists.** `attribution.py` stores a signed
  90-day first-touch cookie, `/r/<slug>` records a referrer, and
  `control_plane.referred_by` plus the Funnel's referrals table show who sent
  whom. What is missing is a *reward*: nothing pays or credits anyone yet.
- **Gate:** do not open the program publicly until the first design-partner
  cohort is live and activation is proven (see section 8). Affiliates amplify a
  funnel; they do not repair one.

---

## 2. Fit: why affiliate suits this product

| Fact about Akye | Consequence |
|---|---|
| Buyer is a small cleaning-company owner (3 to 10 cleaners) who trusts peers over ads | Referral beats paid ads. A recommendation from someone they follow does the vetting. |
| Pro is **$79/mo**, Scale **$249/mo**, Solo is free, 14-day full Pro trial | Recurring revenue supports a recurring commission. Free Solo means a click is cheap to try, so affiliates can promise "no card needed" honestly. |
| Existing channels cost real money (the home page cites about $80 per bought commercial lead; Thumbtack leads run $15 to $40) | A 12-month commission is only paid on customers who stay, so cost tracks retention instead of clicks. |
| Founder runs a cleaning company ("the unfair advantage" in `GETTING_CUSTOMERS.md`) | Authenticity is the pitch. Affiliates are handed the founder story and the demo, not a banner. |
| Stripe Connect is already integrated (`stripe_connect.py`, `create_transfer`) | Payouts to affiliates reuse the contractor-payout plumbing. |
| Product-wide principle: failure should never take a customer's data hostage | Affiliate rules must never touch a customer's plan or access. Commission problems are settled between Akye and the affiliate only. |

---

## 3. Program design

### 3.1 Customer referral (the cheap, fast one)

Every Akye company already has a link: `akyehq.com/r/<company-address>`.

- **Reward:** referrer gets **one month of Pro credit** when the referred company
  makes its first paid invoice. The referred company gets **an extra 14 days of
  trial** (or the first month at half price, whichever is simpler in Stripe).
- **Cap:** 12 free months per company per year, so it cannot become a way to
  never pay.
- **Where it shows up:** Settings, plus a line in the day-30 and day-60 owner
  digest ("Know another owner? Here is your link"). Credit, not cash, because
  cash makes customers into affiliates with tax paperwork.
- **Already built:** link, cookie, validation that the referrer exists and is not
  the new company (`control_plane._signup_attribution`). **Not built:** the credit.

### 3.2 Affiliate partners (the scalable one)

| Term | Setting | Reasoning |
|---|---|---|
| Commission | **30% of subscription revenue received, for 12 months** | $23.70/mo on Pro, $74.70/mo on Scale. Meaningful for the affiliate, still leaves Akye the larger share after SMS, Nana and lead-search costs (these are real per-account costs). Revisit after real margins are known. |
| Cookie | **90 days** (matches `attribution.MAX_AGE`) | Owners decide slowly. |
| Attribution | Affiliate code beats UTM tags; a customer referral beats nothing; otherwise first touch wins | Mirrors the existing rule: a personal invitation is the fact worth crediting. |
| Qualifying event | A paid Stripe invoice, net of refunds | Never a signup, never a trial. |
| Hold | **30 days** from the invoice before it becomes payable | Covers refunds and chargebacks. |
| Payout | Monthly, **$50 minimum**, balance rolls over | Avoids a pile of tiny transfers. |
| Clawback | Refunded or charged-back invoices reverse their commission | Stated in the terms up front. |
| Self-referral | Not allowed (same owner email, same Stripe customer, same payment card fingerprint) | Review flagged cases by hand. |
| Free plan | No commission on Solo. The affiliate earns when the company pays. | |
| Bonus (optional, month 3+) | $100 when an affiliate lands **5 paying companies in a calendar month** | Same shape as the existing $100 momentum bonus. |

Do **not** pay for leads, signups or trials, offer two-tier (sub-affiliate)
commissions, or allow paid search on the Akye brand name. All three attract the
traffic that churns.

### 3.3 Who to recruit (in this order)

1. **Cleaning-business coaches and course creators.** They already sell to your
   buyer and have a "tools I use" list. Highest intent, highest conversion.
2. **Owners of cleaning-business Facebook groups and online communities.** The
   playbook already says to read these; the step up is a partnership with the
   admin. Offer a group-specific link and a live demo for members.
3. **Bookkeepers, tax preparers and insurance/bonding agents who serve cleaning
   companies.** Akye handles 1099s, W-9s and crew pay, so the pitch to them is
   less work at tax time.
4. **YouTube and podcast creators in the cleaning-business niche.** Higher
   volume, lower conversion. Give them a demo company and a video script.
5. **Virtual assistants and operations consultants** who set up tools for cleaning
   owners. They are a *implementation partner*: they earn the commission and
   are the person who sets Akye up. (Distinct from the Lead Specialist
   commission-only role in `VA_COMMISSION_AGREEMENT.md`, which is for Dazzle &
   Shine's own cleaning sales. Keep the two programs separate in the paperwork.)
6. **Supply vendors and trade associations.** Slow to close, large reach. Worth a
   conversation in the second quarter, not the first.

Name real people only from your own research and conversations; this plan does
not assume any in particular.

### 3.4 What an affiliate gets

- A **dashboard link by email** (no password): clicks, signups, paying
  companies, accrued, payable, paid.
- A **demo company** to screen-share (the demo tenant already exists via
  `demo_company.py` and `DEMO.md`).
- The **Loom scripts** in `LOOM_SCRIPTS.md` adapted for a third party, the
  trial-to-paid email sequence summary, and a one-page "what it replaces" sheet.
- A **monthly email** with what converted and what objections owners raised.

---

## 4. Messaging

The angle is the product's: *"You stopped cleaning and started managing. This is
what keeps the Friday payout straight."*

- **For owners:** the founder story, a true claim only ("built for my own
  company"), 14-day full trial, free Solo tier, no card to start.
- **For affiliates:** recurring income from a product their audience already
  needs, and a founder who answers messages.
- **Proof points to use** (all already true in the repo): per-job crew pay and
  1099/W-9 flow, async video interviews, open-job board, booking page,
  Stripe Connect payouts, Nana assistant.
- **Rules for affiliates:** disclose the relationship clearly on every post
  (FTC endorsement rules), no income claims, no promises about features that
  are not live, no spam, and no bidding on "Akye" in paid search.

---

## 5. Economics

Assumptions are marked; replace with real numbers after the first cohort.

| | Pro ($79) | Scale ($249) |
|---|---|---|
| Commission at 30% for 12 months | $284 total | $896 total |
| Monthly commission | $23.70 | $74.70 |
| Akye keeps per month (before cost of SMS, Nana, lead search, Stripe fees) | $55.30 | $174.30 |
| Break-even vs. a $40 bought lead | 2 months of revenue | 1 month |

Because commission only follows revenue, **an affiliate's customer who cancels in
month 3 costs about $71 on Pro, not a fixed acquisition fee.** The exposure is
bounded by the customer's actual payments.

Guardrails: model gross margin per plan once 60 days of SMS and Nana usage are
in; if the margin on Pro is under about 60%, lower the rate for new affiliates
rather than changing terms on existing ones (grandfather existing rates for the
12 months they were promised).

---

## 6. Measurement

Everything keys off the Funnel page (`funnel.py`), which already breaks signups,
activation and paying by channel and lists referrals per referrer.

| Metric | Source | Why |
|---|---|---|
| Clicks per affiliate | New: count at `/r/<code>` | Top of funnel |
| Signups per affiliate | `signup_source` / `referred_by` | Conversion from click |
| Activation rate per affiliate | `activated_at` | Quality of traffic. A channel with signups and no activations is a leak. |
| Paying companies per affiliate | Stripe subscription status | The real outcome |
| 90-day retention per affiliate | Stripe | Decides who to keep investing in |
| Commission as % of revenue from the channel | Ledger vs. invoices | Program cost |
| Time to first paid invoice | Funnel | Cash timing |

Review weekly for the first 8 weeks and monthly after. **Cut or coach** any
affiliate with 20+ signups and under 10% activation.

---

## 7. Implementation (what to build, in order)

### Built so far (October 2026)

| Step | Status | Where |
|---|---|---|
| A. Data model | **Built** | `control_plane.py`: `affiliates`, `affiliate_logins`, `affiliate_clicks`, `affiliate_commissions`, `affiliate_payouts`, plus `organizations.affiliate_code` |
| B. Attribution | **Built** | `attribution.py` (`aff` field, `?aff=`), `/p/<code>` in `blueprints/marketing.py`, `control_plane._signup_attribution` |
| C. Accrue and reverse | **Built** | `billing.apply_event` (`invoice.paid`, `charge.refunded`), `affiliates.accrue` / `reverse` |
| D. Payout | **Recorded by hand** | `affiliates.record_payout` writes the payout down. It does not move money; the Stripe Connect transfer is still to do. |
| E. Console | **Built** | `/console/affiliates` (add, status, sign-in link, payout, reverse) |
| F. Partner page | **Built** | `/partners` (`blueprints/partners.py`, `templates/partners/`) |
| G. Terms and apply page | Not built | |
| H. Customer referral credit | Not built | |

Decisions made while building:

- **Partner codes use `/p/<code>` and their own cookie field**, not `/r/`. A company address and a partner code can then never collide.
- **A partner outranks a customer referral** as the Funnel channel, because only the partner earns commission. Both are still recorded.
- **Credit is dropped** for an inactive partner, an unknown code, or a signup using the partner's own mailbox, however it is dressed up (`+tags` anywhere, dots on Gmail, case).
- **A shared business domain is credited but held for review.** The partner and the owner at the same non-free-mail domain could be colleagues or the partner's own company, and software cannot tell. The company works normally; only that commission is held ("being checked by us" on the partner page) until staff press *It is a real introduction* in the console. Free-mail domains (gmail, yahoo and so on) never trigger it. Not yet checked: a Stripe card shared with the partner, the strongest signal, which needs the card fingerprint from Stripe.
- **One trial, one clock.** The trial is 30 days from signup (`entitlements.TRIAL_DAYS`, read by `billing`). Setting up a cleaner and a customer is a tracked milestone (`activated_at`) but no longer starts or moves the trial, so no email says a trial "has not started". The old start-by window is gone.
- **The Stripe webhook must send `charge.refunded`** as well as the invoice events, or refunds will not reverse a commission. Disputes are not handled automatically: reverse by hand in the console.
- **Payouts under $50 roll over** (`affiliates.MIN_PAYOUT_CENTS`). The 12-month term is exclusive: the payment a year after the first is the thirteenth and earns nothing. A refund that arrives before its payment leaves a zero reversed row, so the payment earns nothing. A ledger error raises, so Stripe retries the webhook.
- **Commission is on the invoice total before tax**, and a partial refund is left for a person.

### Original plan

Everything runs in the control plane (public schema), consistent with the rule in
`entitlements.py` that billing state lives where a tenant cannot write to it.

### Step A: Data model (migration)
- `affiliates`: id, name, email, code (same character set as `attribution.clean_ref`),
  rate (default 0.30), duration_months (12), status (pending / active / paused),
  terms_accepted_at, payout_account_id (Stripe Connect), tax_info_collected,
  created_at.
- `organizations.affiliate_id` (nullable), alongside the existing `referred_by`.
- `commission_entries`: id, affiliate_id, organization slug, **stripe_invoice_id
  (unique)**, gross_cents, commission_cents, status (accrued / payable / paid /
  reversed), payable_at, paid_at, payout_ref.

### Step B: Attribute (small change to code that exists)
- `/r/<ref>` (`blueprints/marketing.py:495`) resolves the code as either a
  company address or an affiliate code. Store the affiliate code in the signed
  cookie (`attribution.FIELDS`) so it cannot be edited.
- `control_plane._signup_attribution` validates an affiliate code the way it
  validates a company address today (exists, active, not self) and writes
  `affiliate_id`.
- Confirm **early-access leads and the abandoned-signup capture also carry the
  cookie**, so an affiliate who sends someone to a gated page still gets credit
  when signups open.

### Step C: Accrue and reverse (billing webhook)
- In the `invoice.paid` branch of `billing.py` (line 377), insert a
  `commission_entries` row for the company's affiliate if it is inside its
  12-month window.
- The unique `stripe_invoice_id` makes it safe when Stripe delivers the same
  event twice, which is the rule `billing.py` is already built around ("state a
  fact, do not increment").
- Handle `charge.refunded` and `charge.dispute.created` by marking the entry
  reversed. Commission is computed from the amount actually paid, after discounts.

### Step D: Payout
- A monthly job selects entries past their hold, groups by affiliate, skips
  totals under $50, and pays via `stripe_connect.create_transfer` with an
  idempotency key like `aff-<affiliate>-<yyyymm>`.
- Collect a W-9 before the first payout. US affiliates paid $600 or more in a
  calendar year need a 1099-NEC; the platform already collects W-9s for crews,
  so reuse that flow. Confirm current thresholds with your accountant.

### Step E: Console pages (staff)
- `console` section for affiliates: list, approve, pause, adjust rate, see
  ledger, mark payouts, export CSV. A failed or flagged payout must never touch
  the referred company's plan.

### Step F: Affiliate portal
- Magic-link dashboard (reuse the `LoginToken` pattern from signup) with stats and
  statement history, plus copyable links with campaign tags
  (`?ref=<code>&utm_campaign=<where>`).

### Step G: Terms and apply page
- `/partners` page: how it works, rate, hold, disclosure rules, apply form.
- Short **Affiliate Terms** (independent contractor, not employment; disclosure;
  no spam; clawback; Akye may change terms with 30 days notice and cannot cut
  rates retroactively on customers already referred). **Have a lawyer review
  before publishing.**

### Step H: Customer referral credit
- On the referred company's first `invoice.paid`, apply a Stripe customer
  balance credit (or a coupon) to the referrer; cap at 12 per year.

**Not worth building yet:** automatic tiering, sub-affiliates, a creative library,
cookie-less tracking, a third-party affiliate network. Revisit past 25 active
affiliates.

---

## 8. Timeline

Today is 2026-10-15. Dates move with the cohort; the gates are what matter.

| Window | What happens | Gate to move on |
|---|---|---|
| **Weeks 1 to 2** | Decide the rate and terms. Draft the one-page terms. Build the tracking sheet. Confirm early-access leads keep attribution (Step B check). Fix the trial-length inconsistency below. | Terms drafted; rate decided |
| **Weeks 3 to 8: Pilot** | Recruit **5 affiliates** by hand (coaches and community owners first). Give each a code via the existing `?ref=` / UTM tags and track in a sheet and the Funnel's channel table. Pay manually after the hold. | At least 1 paid referral, or a clear read on why not |
| **Weeks 9 to 14** | Build Steps A to D (data, attribution, accrual, payout) behind the existing release controls. Migrate the sheet into the ledger and reconcile once against Stripe. | Reconciliation matches to the cent |
| **Weeks 15 to 20** | Steps E to G: console, portal, `/partners`. Open applications. Ship customer-referral credit (H). | 10 active affiliates, first monthly payout run clean |
| **Month 6+** | Review margin and retention by channel. Adjust rate for new affiliates only. Add vendors and associations. | |

**Launch gate (do not skip):** at least the first design-partner cohort live, an
activation rate you are happy to scale, and Stripe billing verified in live mode.
Affiliates will send people to whatever funnel exists; if it leaks, they will
make that expensive and public.

---

## 9. Targets (planning numbers, not forecasts)

These are assumptions to be overwritten, chosen to size the work rather than
predict it.

| By end of | Active affiliates | Paying companies from affiliates | Monthly commission cost |
|---|---|---|---|
| Pilot (week 8) | 5 | 1 to 3 | under $100 |
| Month 6 | 10 to 15 | 8 to 15 | about $200 to $400 |
| Month 12 | 25 | 30 to 50 | about $700 to $1,200 |

Success is not the count of affiliates. It is **paying companies that stay**
at a commission cost lower than the other channels cost per customer.

---

## 10. Risks and open items

| Risk | Response |
|---|---|
| Low-quality traffic (signups that never activate) | Pay only on paid invoices; weekly activation by affiliate; cut weak ones. |
| Misleading claims by an affiliate | Written disclosure and claim rules; pause on first breach; claim-review for large audiences. |
| Self-referral and fake accounts | Same email, customer, or card fingerprint blocks accrual; manual review of flagged. |
| Chargebacks after payout | 30-day hold, clawback in terms, carry negative balance forward. |
| Tax and legal | W-9 before payout, 1099-NEC, lawyer review of terms, FTC disclosure. |
| Margin shrinks as SMS and Nana usage grows | Rate set on measured margin; grandfather the promised 12 months. |
| Channel conflict with the Lead Specialist program | Separate agreements; Lead Specialists sell Dazzle & Shine cleaning, affiliates promote the Akye product. Make that explicit in both. |
| ~~Trial length inconsistent~~ | **Resolved.** The trial is now 30 days everywhere (`billing.TRIAL_DAYS`, `entitlements.TRIAL_DAYS`, emails, banner, tests), matching the Scale plan trial. Note the earlier reading was only half right: the code had a 30-day *start-by* window and a 14-day trial after activation. The trial is now one clock: 30 days from signup. |
| Signups can be shut (`SIGNUPS_OPEN=0`) during hand onboarding | Affiliate links land on early access; confirm the cookie survives the early-access form, and tell affiliates the current state. |

---

## 11. First ten actions

1. Decide the rate (30% for 12 months) and the hold (30 days). Write them in two lines.
2. ~~Resolve the 14 versus 30 day trial discrepancy.~~ Done: 30 days everywhere.
3. Draft the one-page affiliate terms and the disclosure rules; book a lawyer review.
4. List 20 candidate affiliates from your own research (coaches, group admins, bookkeepers, VAs), ranked by audience fit.
5. Verify the early-access and abandoned-signup paths store attribution from the cookie.
6. Create the tracking sheet (affiliate, code, link, signups, activated, paying, commission accrued, paid).
7. Personally invite the top 5, with a demo-company walkthrough, in the founder voice.
8. Send each their tagged link (`?ref=<code>&utm_campaign=<channel>`) and the claim rules.
9. Review the Funnel channels table weekly; note activation per affiliate.
10. At week 8, decide: build the engine (Steps A to D), change the terms, or stop.
