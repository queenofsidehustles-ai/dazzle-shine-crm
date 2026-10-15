---
name: akye-lifecycle-email
description: Use when adding, changing, or reviewing any email Akye sends to a cleaning-company owner or to a lead about signing up, setting up, the trial, or upgrading (trial_nudges.py, lead_nurture.py, welcome_email.py, email_confirm.py). Covers the trigger and stop rules, voice, format, video links, and tests.
---

# Akye lifecycle emails

The emails Akye (the product) sends to cleaning-company owners and to people
who came close to signing up. Not the emails a cleaning company sends its own
customers. Those are tenant templates and a different system.

Read `SIGNUP_FUNNEL.md` first for the map of every email and when it fires.

## Where each kind lives

| Kind | File | How it is triggered |
|---|---|---|
| Welcome + confirm code | `welcome_email.py`, `email_confirm.py` | signup, once |
| Owner emails on a schedule | `trial_nudges.py` (`due()` + `compose()`) | daily, `/api/trial-nudges` |
| Owner emails on an event | `trial_nudges.send_event()` | the moment it happens |
| Leads who did not sign up | `lead_nurture.py` | daily, `/api/lead-nurture` |
| Catalog, switches, history | `communications.py`, console Communications page | read by every sender |

A new owner email is almost always a new **kind** in `trial_nudges.py`. Do not
start a new module or a new cron for it.

## The facts emails must get right

- The 30-day trial starts when the company has **one active cleaner and one
  customer** (`onboarding.progress()['activated']`). Not "your first job", not
  "assign a job". Any email that states the rule must say this.
- Before that, they have **30 days** to start (`billing.START_WITHIN_DAYS`).
- When the trial ends they drop to the **free plan and keep everything**.
  Nothing is deleted. No card is on file during the trial.
- Every owner link goes to **their own address** (`company_url(org)`, e.g.
  `https://sparkle.akyehq.com/...`), never to `akyehq.com`, which is only the
  marketing site.
- Their public booking page is `{company_url}/book`.

## Rules every owner email follows

1. **One a day, total.** `due()` returns None if `nudge_last_at` is within
   `ONE_A_DAY_HOURS`. Event emails ignore the gate but still set it.
2. **Never twice.** Each kind is written to `nudges_sent` once it goes. Record
   only after a successful send, so a failure retries tomorrow.
3. **Windows, not exact days.** A kind is due for a range of days, e.g.
   `DAY4 = (4, 5)`, so a missed cron day sends late instead of never.
4. **Stop when they act.** Not-activated emails are only checked in the
   `not_started` phase. Once activated, they can never be sent.
5. **Staleness.** Anything keyed to a past event (lapsed, activated) has a
   short window. The first run against a real database must not email
   history.
6. **Who never gets one:** paying (`trial_state` is None), `is_test`,
   `is_demo`, `nudges_opted_out`, suspended or closing or closed, no owner
   email.
7. **Sent as the product**, never as the cleaning company: `from_name =
   product.name()`, `from_email = product.from_email()`, the product's Resend
   key. See `_send()`.
8. **Footer** says reply to reach a person, and how to turn the emails off
   (Billing page). `wrap()` already does this, so always use `wrap()`.

Lead (nurture) emails follow `lead_nurture.py`'s own rules: never uploaded
lists (`source == 'console upload'`), never anybody who owns a company,
unsubscribed, or `contacted_at` set; `FRESH_DAYS` on the first email; footer
with unsubscribe and postal address via `lead_outreach.email_html`.

## Voice

Monica's rules, and they apply to every word:

- **Short.** Text-message length where possible. Two or three short
  paragraphs. Cut any sentence that does not change what they do next.
- **Humble, not flex-y.** No "game-changer," no "you'll love," no "I built
  this." Akye is introduced as something that helps, by people who run
  cleaning businesses too.
- **One ask per email.** One button. The button says what happens
  ("Add a cleaner"), not "Click here."
- **Their words, not ours.** "Customers" and "cleaners," not "clients" and
  "staff" or "CRM objects." "Booking page," not "widget."
- **Plain punctuation.** No em-dash pileups. Contractions are fine.
- Always capitalize "God" if it ever appears.

## How the emails persuade (and where the line is)

Every email follows the same shape: **the pain, the fix, one small ask.**

1. **Open on a moment they have lived.** Not "manage your schedule" but
   "a cleaner texting 'which house again?' at 8am." Pain points we use: the
   schedule living in your head and phone, addresses screenshotted into a
   group chat, a price request that booked someone else before you replied,
   quotes and follow-ups waiting for a free evening, a job cleaned and never
   billed, the customer list living on one phone, pay day as a memory test.
2. **Show the fix in Akye, concretely.** Name the feature by what it does
   for them that day.
3. **Make the ask small.** "About two minutes," "one cleaner and one
   customer." Remove the risk they are guarding against ("your 30 days do
   not start until you do").
4. **Loss over gain, with real stakes only.** When a trial ends, list exactly
   what switches off (`LOSES` in `compose()`), from `entitlements.PLANS`.
5. **Picture next week** after a win (activated, first booking).

Never: invented deadlines or scarcity, made-up testimonials or numbers
("owners save 10 hours"), guilt, or claims a free-plan user cannot get. If a
claim depends on a paid feature, it only goes in emails sent during the trial.

## Videos

Never embed a player in an email. Call `funnel_videos.email_block(key)`; it
returns a still with a play button that links out, or `''` if that video is not
recorded yet. Never write an email that only makes sense with the video.
Video keys and their Railway variables are listed in `funnel_videos.py`. The
scripts are in `LOOM_SCRIPTS.md`.

## Adding a new owner email, step by step

1. Add the key to `ALL` (and to `EVENTS` if it fires on an event).
2. Add a window constant if it is scheduled.
3. Add it to `due()` in the right phase, in the right priority order
   (earliest-due first within a phase).
4. Add its copy to `compose()` using `wrap(heading, body, cta, href)`.
5. If it is an event, call `trial_nudges.send_event(slug, kind)` where it
   happens. It never raises, so it is safe inside a request.
6. Tests: add `due()` cases to `tests/test_signup_funnel.py` (due, not due,
   sent once, blocked for paying, test, opted out), and confirm the
   `compose()` loop in `tests/test_trial_nudges.py` still passes for every
   kind (names them, links to their own address).
7. Add it to `communications.CATALOG` so it appears on the console's
   Communications page with its own switch and preview.
8. Update the table in `SIGNUP_FUNNEL.md`.

## Before you finish

Run:

```bash
TEST_POSTGRES_URL=postgresql://... python3 tests/test_trial_nudges.py
TEST_POSTGRES_URL=postgresql://... python3 tests/test_signup_funnel.py
python3 -m pytest -q tests/test_scheduler_product_jobs.py
```

Then render the email you changed and read it as the owner would, on a phone.
