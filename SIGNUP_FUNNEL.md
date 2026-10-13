# Akye signup funnel

Everything that happens between a Meta ad click and a cleaning company using
Akye, and every email along the way.

## The path

1. **Ad → `/signup`.** Attribution tags are kept (attribution.py). If the
   overview video is set, it plays above the form.
2. **Email typed → lead saved.** When the email box loses focus,
   `/signup/started` writes a `product_leads` row tagged `abandoned_signup`.
   If they finish, that row is deleted.
3. **Signup → straight in.** No gate. The welcome email carries their web
   address **and** a 6-digit confirm code with a "Yes, this is me" link.
4. **Soft banner** on the dashboard until the email is confirmed, with a way
   to fix a mistyped address (`/confirm-email`).
5. **First week emails** push them to add one cleaner and one customer.
6. **Activated** (one cleaner + one customer) starts the 14 days and sends a
   note at that moment.
7. **First online booking** sends a note at that moment.
8. **Trial ending / ended / win-back** as below.

## Every email

### To the owner (trial_nudges.py, sent as Akye)

| Key | When | Who | Says |
|---|---|---|---|
| welcome | at signup | everyone | your address, sign-in email, confirm code |
| `day1` | day 1–2 | not activated | two things, two minutes |
| `day2` | day 2–4 | everyone on trial | your booking page is already live |
| `day4` | day 4–5 | not activated | where people get stuck |
| `day5` | day 5–6 | not activated | bring your list over |
| `start_7` | day 7–13 | not activated | your 14 days haven't started |
| `start_21` | day 21–29 | not activated | X days left to start |
| `activated` | at the moment, or within 3 days | just activated | your 14 days just started |
| `first_booking` | at the moment | first online booking | somebody booked you |
| `feature` | trial day 8–10 | a setup step still undone | one thing worth trying |
| `ending` | 3 days left | running | X days left of everything |
| `ended` | 0–3 days after | lapsed | finished, everything is still here |
| `winback` | 7–10 days after | lapsed after using it | here's what you'd get back |

Never more than one a day. Never the same one twice. Never to paying, test,
demo, opted-out or closed companies.

### To leads who didn't sign up (lead_nurture.py)

| Step | Day | Subject |
|---|---|---|
| 1 | 1 | What it actually costs to start a cleaning business |
| 2 | 4 | How to price a cleaning job |
| 3 | 8 | The decision that gets new cleaning owners fined |
| 4 | 13 | Want to try Akye with your real business? |

Only for people who came to us (half-finished signup, early access). Never
uploaded prospect lists. Stops if they sign up, unsubscribe, or the console
marks them contacted. Each has an unsubscribe link and the postal address.

## Setup after merging

1. **Deploy.** New columns are added automatically on boot
   (`control_plane.ensure_columns`).
2. **Scheduler.** The GitHub Actions scheduler already runs product jobs
   daily; `lead-nurture` is now in `scheduler.PRODUCT_JOBS` next to
   `trial-nudges`. Nothing to add.
3. **Videos.** Record the six Looms in `LOOM_SCRIPTS.md`, then set these on
   Railway: `AKYE_VIDEO_OVERVIEW`, `AKYE_VIDEO_SIGNUP`,
   `AKYE_VIDEO_TEAM_AND_CUSTOMER`, `AKYE_VIDEO_BOOKING_PAGE`,
   `AKYE_VIDEO_BOOK_JOB`, `AKYE_VIDEO_MIGRATION`. Unset ones simply don't show.
4. **Check a dry run** before the first real day:
   `POST /api/trial-nudges?dry_run=1` and `POST /api/lead-nurture?dry_run=1`
   with the `X-Api-Key` header.

## Changing an email

Use the `akye-lifecycle-email` skill (`.claude/skills/akye-lifecycle-email`).
It has the rules, the voice and the test steps.
