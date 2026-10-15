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
6. **Activated** (one cleaner + one customer) is a milestone inside the trial,
   not what starts it: the 30 days run from signup. It sends a "you are set up"
   note at that moment.
7. **First online booking** sends a note at that moment.
8. **Trial ending / ended / win-back** as below.

## Every email

### To the owner (trial_nudges.py, sent as Akye)

| Key | When | Who | Says |
|---|---|---|---|
| welcome | at signup | everyone | your address, sign-in email, confirm code |
| `day1` | day 1–2 | not activated | get the schedule out of your head |
| `day2` | day 2–4 | everyone on trial | the jobs you lose while you're cleaning |
| `day4` | day 4–5 | not activated | what usually gets in the way |
| `day5` | day 5–6 | not activated | your customer list is one lost phone from gone |
| `start_7` | day 7–13 | not activated | two minutes to see it work |
| `start_21` | day 21–25 | not activated | X days left, and nothing set up yet |
| `activated` | at the moment, or within 3 days | just activated | you are set up, and everything is on |
| `first_booking` | at the moment | first online booking | somebody booked you |
| `feature` | 8–10 days after they set up | a setup step still undone | before your trial ends, try this |
| `ending` | 3 days left | everyone on a trial | X days left of everything |
| `ended` | 0–3 days after | lapsed | finished, everything is still here |
| `winback` | 7–10 days after | lapsed after using it | still doing it the hard way? |

Never more than one a day. Never the same one twice. Never to paying, test,
demo, opted-out or closed companies.

### To leads who didn't sign up (lead_nurture.py)

| Step | Day | Subject |
|---|---|---|
| 1 | 1 | What it actually costs to start a cleaning business |
| 2 | 4 | How to price a cleaning job (and stop undercharging) |
| 3 | 8 | The decision that gets new cleaning owners fined |
| 4 | 13 | Last one from us |

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

## Managing it day to day: Console → Communications

One page for every automated email to owners and leads:

- **Due today**: who gets what at 6pm Eastern, with buttons to send now.
- **Every automated email**: what it is, when it goes, how many went out in
  30 days, a preview, and an on/off switch (managers and the owner only).
  A switch that is off holds the email; it is not marked sent. The welcome
  email is always on.
- **Recently sent**, and a search box for one person's or company's full
  email history. Each company's console page lists its emails too.

Leads stop getting automatic emails when they sign up, unsubscribe, reply,
or get a signup invite from the Leads page.

## Changing an email

Use the `akye-lifecycle-email` skill (`.claude/skills/akye-lifecycle-email`).
It has the rules, the voice and the test steps.
