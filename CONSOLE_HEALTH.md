# The console's Health page

Written 2026-10-18. What each section means, what has to be in place for it to
fill in, and what to do when it turns red.

`/console/health`. The **Health** tab carries a count of what needs a look:
backups, background jobs, Stripe and platform errors. Usage is on the page but
not in the count, because reading it means looking inside every company.

## What reports in, and how

| Section | Reported by | When |
|---|---|---|
| Backups | the **Nightly backup** GitHub Action, one line per database | after each run, pass or fail |
| Scheduler, hourly / daily | `scheduler.py` (the **Automations** Action) | after each run |
| Trial emails, emails to leads | `/api/trial-nudges`, `/api/lead-nurture` | every real run (a dry run is not recorded) |
| Stripe's webhook | `/api/stripe/webhook` | every event, success or failure |

Reports land in `platform_runs` in the control plane. Backups and the scheduler
post to `/api/platform-run` with the same `REMINDER_API_KEY` the scheduler
already uses, and only those two kinds are accepted from outside.

## The four states

| State | Means |
|---|---|
| ok | reported success recently |
| stale | its last success is too old: backups 36 hours, hourly scheduler 3 hours, daily jobs 30 hours |
| failed | its most recent run said it failed |
| not reported yet | it has never reported |

**Not reported yet is not an alarm.** On a fresh deployment nothing has
reported, and a page that cried wolf on day one would be ignored on day thirty.
If it stays that way after a night, the reporter is not wired up: check the
`REMINDER_API_KEY` secret on the Action, and that the deployed product has
`/api/platform-run` (the backup job checks out `akye-stable`, so the code has to
be promoted there first).

## Before this works in production

1. **Promote this change to `akye-stable`** (and so the deployed product), so
   `/api/platform-run` exists. Until then the backup step prints a warning and
   changes nothing.
2. **`REMINDER_API_KEY` must be a secret on the Nightly backup workflow too.**
   It already is for Automations; the same value.
3. Wait for one night, or run the workflow by hand (**Actions → Nightly backup →
   Run workflow**).

## Platform errors

Faults outside any company's CRM: the product's own pages, the console, and
Stripe's webhook. A company's own errors stay on its page. **Looked at** means
somebody has read it; a fault that comes back reopens itself.

## Usage this month

Counts, not dollars, against each company's monthly limit: texts (plan limit),
Nana questions and setup-chat messages (`ASSISTANT_MONTHLY_LIMIT`,
`SETUP_ASSISTANT_MONTHLY_LIMIT`), lead searches (plan limit). Amber is past 80%,
red is at the limit. What each call costs is on the provider's dashboard
(Twilio, Anthropic, Google); it is not recorded here.

## Switches

Emergency controls for the whole product, flipped from the page and written to
the Record. Everything is on unless turned off, and an unreadable database means
**on**: a kill switch that fails closed would take the product down when the
database blinked.

| Switch | Off means |
|---|---|
| New signups | nobody can open an account. `SIGNUPS_OPEN=0` still wins: the console cannot reopen it |
| AI features | Nana, the setup chat, drafted content and translation behave as if no Claude key were set |
| Texting | every text from every company stops, **including job and reminder texts**. For a runaway bill or abuse, not routine use |
| Partner payouts | no partner can be paid; commissions keep accruing. Unlike the others this one fails closed: if the switch cannot be read, nobody is paid. `PARTNER_PAYOUTS_OPEN=0` also stops it whatever the console says. A retry of a payout over a day old first asks Stripe whether it was already sent |

A switch takes effect immediately in the worker that handled the click and within
about 8 seconds everywhere else.

## When something is red

- **Backup failed or stale:** open the run in GitHub (Actions → Nightly backup),
  read the failed step, fix it, run it by hand. `BACKUP.md` has the restore drill.
- **Scheduler stale:** the schedule stopped. Check the Automations workflow in
  GitHub is enabled (scheduled workflows are disabled after 60 days of repository
  inactivity) and that its `AKYE_DATABASE_URL` and `REMINDER_API_KEY` secrets are set.
- **Stripe's webhook failed:** somebody paid and may not have been upgraded. Open the
  event in Stripe (Developers → Webhooks), read the error, and resend it once fixed;
  handling is safe to repeat.
- **Platform error:** the row names the page and the exception.
