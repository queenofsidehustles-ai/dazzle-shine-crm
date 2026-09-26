# The demo company — BrightNest Cleaning Co.

BrightNest is a fictional house-cleaning business in Austin, Texas, owned by
Sarah Mitchell, that has been running on Akye for about six months. It exists
so Akye can be shown working — to a prospect, in a Product Hunt launch, in a
Supademo recording — with a business that looks lived-in and adds up, and
without anybody real ever being contacted.

It is built by `demo_company.py` and kept safe by `demo_guard.py`. Tests:
`tests/test_demo_company.py`.

---

## Build it, rebuild it, check it

Run inside the app on Railway, where `DATABASE_URL` reaches the database:

```
railway ssh
/opt/venv/bin/python demo_company.py --dry-run   # what it would do; writes nothing
/opt/venv/bin/python demo_company.py             # build, or rebuild fresh
/opt/venv/bin/python demo_company.py --verify    # does the live demo still add up?
/opt/venv/bin/python demo_company.py --reset     # the same as a plain run
```

(`railway run` from a laptop cannot reach `postgres.railway.internal`; that is
why it is run over `railway ssh`, with the app's own Python.)

| Setting | What it does |
|---|---|
| `DEMO_OWNER_PASSWORD` | Sarah's password (`sarah@brightnest.example`, owner). |
| `DEMO_OPS_PASSWORD` | Priya's password (`priya@brightnest.example`, dispatcher). |
| `DEMO_SLUG` | The company's address. Defaults to `brightnest`. |

Set the two passwords as Railway variables. If they are not set, a rebuild
makes one-off passwords and prints them once — they are never written to the
repository, and they change on every rebuild.

Sign in at `https://brightnest.<your domain>/login`.

### Rebuild it every day

Every date in the demo is worked out from the day it is built: the jobs on
"today", the cleaner who clocked in at 8:04, the leads that came in yesterday.
The next day those are yesterday's, still marked as not done. **Rebuild it
daily** (and before any recording or launch). The dashboard reads "today" from
the server's clock, which on Railway is UTC, so the cleanest time is just after
00:00 UTC (7 PM in Austin in summer). No schedule for this is set up yet — see
*Remaining* below.

A rebuild signs out anyone signed in to the demo (the passwords are set afresh).

### What a rebuild touches

Only two schemas: `tenant_brightnest` and its staging copy
`tenant_brightnest__next`, plus the company's own row in `organizations`.
Nothing is truncated; no other company is read or written.

1. Refuses if a company that is **not** marked as the demo holds the address.
2. Refuses if another rebuild is already running (a PostgreSQL advisory lock).
3. Builds the whole company in the staging schema, through the app's own
   services — pricing, quoting, payments, invoicing, recurring series,
   cleaner pay.
4. Runs every check in `verify()` against the staging copy.
5. Only if all of them pass, swaps it in for the live one in a single
   transaction (`DROP SCHEMA live; ALTER SCHEMA staging RENAME TO live`).

If any step fails, the staging schema is dropped and the demo people are
already using is left exactly as it was. The command says which stage failed.

### What `--verify` checks (28 checks)

Integrity (every job has a customer, a real status, a price; no crew row points
anywhere else; nothing finished is in the future or unfinished in the past; no
cleaner in two places at once), money (every paid job is settled in full;
revenue on Reports equals the money collected; what is owed equals price less
collected; exactly the intended invoices are overdue; cleaner pay matches each
job, some paid and some still waiting; five months of revenue, none empty and
not all the same), and the story (no empty weekday in the last three weeks; two
jobs waiting on confirmation; reviews average what they say; five jobs today
with four cleaners out; one job open to claim; one job tomorrow with nobody on
it; one customer yet to confirm; two new leads since yesterday; the journey
customer went from quote to review; setup shows 100%; an owner and an office
login).

Run it after people have used the demo: failures show what they changed.

---

## What is in it

| | |
|---|---|
| Team | 6 cleaners, all hourly at the company rate: Maria Lopez, Jasmine Carter, Alicia Brooks, Daniel Reyes, Nicole Grant, Tasha Williams |
| Logins | Sarah Mitchell (owner), Priya Shah (dispatcher) |
| Customers | 52: weekly, bi-weekly and monthly plans, occasional, one-time, four brand new, three gone quiet, two who owe money |
| Jobs | 188: about 156 completed over five months, 5 today, 24 upcoming |
| Money | 156 invoices, 2 overdue; card, Zelle, cash and check payments with tips; monthly card fees; recurring and one-off expenses |
| Pay | Cleaner pay goes out on the Friday after each job; anything since last Friday is still waiting |
| Pipeline | 22 leads (new, contacted, won, lost), 2 commercial accounts, 3 commercial quotes |
| Reviews | 20, averaging 4.7 |
| Messages | 3 text threads, one unread |
| Automations | On, with the last few days' run history — but never run (see Safety) |

The numbers are the same on every rebuild (a fixed random seed); only the
dates move with the day.

### This morning at BrightNest

- **Today:** Marcus Castillo 8:00 (Maria, clocked in at 8:04), Derek Nguyen 9:00
  (Jasmine), Owen Pruitt's deep clean 10:30 (Alicia and Daniel), Bianca Fenwick's
  move-out 1:00 (Maria — a brand-new customer), and Leticia Ashford 2:30,
  **open for any cleaner to claim**.
- **Tomorrow:** Imani Moreau 8:00 **still has to confirm**; Hannah Whitaker 9:00
  (Tasha); **Caleb Lindqvist 10:30 has nobody on it**; Priscilla Okafor moved to
  1:00 by text, with Nicole.
- **Yesterday:** Andre Quintero's deep clean is done and invoiced, **not yet
  paid**; Megan Ellison paid and left a review this morning.
- **Owed:** Ivan Maddox and Joanna Novak are **overdue**.
- **New:** Rebecca Tate asked about a deep clean on the website this morning,
  and her text is **unread**; Jordan Ellis came in from Google yesterday.
- **The whole journey, one customer:** Olivia Harlow came in as a lead, was
  quoted a deep clean with oven and fridge, booked, paid a deposit, was cleaned
  by Alicia and Daniel, paid the balance, and left five stars.

---

## Safety — what it can and cannot do

The demo login may be handed to many people, and any of them can press every
button. So the limits are enforced on the server, at the few places everything
goes through — not by hiding buttons. The company is marked `is_demo` (and
`is_test`) in `organizations`; `demo_guard.active()` answers "is this the demo's
work?" from the request's company, the database schema in use, or the seed
asking explicitly.

| | Where | What happens |
|---|---|---|
| Stripe, Twilio, Resend keys | `integrations.get()` | Always blank for the demo — including the platform's environment keys, which a company with none of its own would otherwise fall back to. |
| Email, texts, marketing texts, MailerLite | `notifications.send_*` | Refused, even with a key handed in directly, and written to the **Sent Log** as "Demo company — not sent". The page says "nothing was actually sent". |
| Akye's own subscription | `billing.checkout_session` / `portal_session` | Refused: "Plans cannot be changed and no card is ever taken." |
| Customers paying | Stripe keys are blank | Payment pages cannot take a card. |
| Stripe webhook | `blueprints/api.py` | Refused without a secret, which the demo never has, so a forged "payment succeeded" cannot be accepted. |
| Daily automations | `scheduler.companies()` | Never run for the demo, so nothing is sent and its state does not drift. |
| Password, two-factor, connection keys | `blueprints/account.py`, `settings.py` | Cannot be changed, so one visitor cannot lock out the next or leave real keys behind. |
| Funnel and Sales numbers | `is_test` | Left out. A demo company stays a test account even if the console is asked otherwise. |
| Contact details | the seed | `@example.com` / `@brightnest.example` addresses and 555-01xx numbers, reserved for fiction — they reach nobody. |

**The one exception:** email to Akye's own support inbox (a crash alert or a
feedback notice from somebody using the demo) still goes out. Nobody fictional
is contacted, and a prospect hitting a bug is exactly what Akye wants to hear.

**Paid API cost boundary:** demo visitors cannot spend Akye's provider credits.
Nana receives no OpenRouter key; voice falls back to the browser speech engine;
translation returns the source text; and Find Leads uses its local fictional
Places fixtures. These guards are server-side and apply even when platform keys
are configured.

---

## Showing it

### Product Hunt, 60–90 seconds

1. Sign in as Sarah → **Dashboard**: five jobs today in time order, four cleaners
   out, Maria already clocked in, one job open to claim, tomorrow's job with
   nobody on it, and what customers still owe.
2. Tap tomorrow's **Caleb Lindqvist** (nobody on it) → add Alicia → "sent to her"
   (the page also says nothing really left).
3. **Invoices → Overdue**: Ivan and Joanna. Open Ivan → mark paid by Zelle.
4. **Money**: five months of revenue, costs, card fees, profit.
5. End on the **Calendar** — a full, real-looking month.

### A fuller tour, 3–5 minutes

1. Dashboard, as above.
2. **Clients → Olivia Harlow**: the whole story of one customer, lead to review.
3. **Leads**: Rebecca Tate from this morning; **Messages**: her unread text —
   reply, and see it land in the **Sent Log** as not sent.
4. **Commercial**: two accounts and three quotes.
5. **Team**: six cleaners, onboarding done; **Payroll**: paid through last
   Friday, the latest jobs waiting; **Timesheets**.
6. **Reports**: revenue by month and service, leads converting.
7. **Automations**: which reminders run, with history.
8. The public **booking page** (`/book`) a customer would use.

### Recording (Supademo and the like)

- Rebuild first, the same day, so "today" is today.
- Record at 1440 wide for desktop or 390 for phone; every page fits both
  without sideways scrolling.
- Every name, email and phone number on screen is fictional; nothing needs
  blurring.
- Rebuild again afterwards — a recording changes things (and `--verify` will
  list what).

---

## Troubleshooting

| Symptom | Cause, and what to do |
|---|---|
| "A company that is not the demo already uses 'brightnest'" | A real company holds the address. Nothing was touched. Set `DEMO_SLUG` to another address. |
| "Another rebuild of the demo company is running" | Wait for it; the lock lets go by itself if that process died. |
| `Stopped at "<stage>"` | That stage failed; the live demo was not touched. The message says why. |
| `--verify` shows failures | Somebody used the demo. Rebuild. |
| Today's jobs look like yesterday's | It was not rebuilt today. Rebuild. |
| Signed out after a rebuild | Expected — passwords are set afresh. |
| "The demo company needs PostgreSQL" | Run it where `DATABASE_URL` is the Postgres (over `railway ssh`). |
| Could not connect to `postgres.railway.internal` | Run it over `railway ssh`, not `railway run`. |

---

## Decision register

| # | Decision | Why | Instead of |
|---|---|---|---|
| D1 | The demo is a real company with its own schema, built with the app's own code. | Every page, number and rule shown is the product's, not a mock-up; it cannot drift from the real app. | A read-only fake, or screenshots. |
| D2 | A separate `is_demo` flag, which also sets `is_test`. | "Leave out of numbers" and "must never contact anyone" are different promises; the demo needs both. | Reusing `is_test` alone. |
| D3 | The kill switch lives on the server at the outbound chokepoints. | A hidden button can be found; a missing key cannot be used. Holds for every page, including future ones. | Hiding buttons in templates. |
| D4 | Blocked messages are written to the Sent Log, and the page says so once. | The demo still shows what Akye *would* have sent — and never claims a send that did not happen. | Silently dropping them. |
| D5 | Email to Akye's own support inbox still goes. | Crash alerts and feedback from prospects are the point of a launch; they contact nobody fictional. | Blocking all email. |
| D6 | Staging schema, verify, then one-transaction swap; advisory lock. | A rebuild is all-or-nothing and there is never a moment without a demo; two at once cannot collide. | Deleting rows in place. |
| D7 | Refuse if the address belongs to a company not marked as the demo. | The rebuild drops a schema; it must never be pointed at a real one. | Trusting the operator. |
| D8 | Dates relative to the day of the build, using the same "today" as the dashboard. | Always "this morning", whenever it is built. Costs a daily rebuild. | Fixed dates, which age instantly. |
| D9 | A fixed random seed. | The same company every time; tests can compare rebuilds exactly. | Fresh randomness per build. |
| D10 | Built through pricing, quoting, payments, invoicing, recurring and pay services where they exist; `verify()` checks the rest. | Money and pay follow the app's own rules, so Reports, P&L and Payroll agree. | Writing every table by hand. |
| D11 | All cleaners hourly at the company's labor rate. | Payroll, job pay and timesheets line up on every page. | A mix of hourly and percentage pay. |
| D12 | Only reserved fictional contact details (example.com, `.example`, 555-01xx). | Nothing can reach a real person even if every guard failed. | Realistic-looking real domains. |
| D13 | Passwords from Railway variables; one-off ones printed if unset. | No credential in the repository. | A known password in code. |
| D14 | Password, two-factor and connection keys are fixed for the demo. | A shared login must not be lockable, or left holding a visitor's real keys. | Trusting visitors. |
| D15 | Automations are on but never run. | The settings show what Akye does; running them would change the demo's state (and could only fail to send). History is seeded instead. | Turning automations off. |
| D16 | Stripe, email and texting show as "not connected". | True — and the reason no card is taken. | Faking a connected state. |
| D17 | The demo is on the top plan, active, with no Stripe customer. | Every feature is visible; there is nothing to bill. | A trial that expires. |
| D18 | Paid AI/lookup providers are blocked for demo companies, with local/free fallbacks where possible. | A public launch must not turn shared credentials into an unbounded cost surface. | Letting anonymous demo traffic spend platform credits. |
| D19 | Small app fixes found while building it are in the same change (see the PR). | They were real bugs that any company would see; the demo made them visible. | Leaving them for later. |

---

## Remaining

- **No daily rebuild is scheduled.** Adding one writes to production, so it is
  left for an explicit decision (a Railway cron running
  `/opt/venv/bin/python demo_company.py`, just after 00:00 UTC).
- **The dashboard's "today" is the server's date (UTC)**, not Austin's — for
  every company, not just the demo. Between 7 PM and midnight in Austin it
  already shows tomorrow.
- **Message times in the inbox show in UTC**, for every company.
- **Pages that say "Sent" whatever happened.** Several pages report a send
  from having asked rather than from the answer — for real companies too. The
  demo now says nothing was sent; real companies still see "Sent" when, say,
  email is not connected. The Sent Log is always right.
