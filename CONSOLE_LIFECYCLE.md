# Closing, exporting and purging a company from the console

Written 2026-10-19. Where it is, who can do what, and what stops a mistake.
The rules (30-day retention, what purge removes) are in
`AKYE_DATA_LIFECYCLE_POLICY.md` and enforced by `tenant_data_lifecycle.py`; this
only describes the controls on top of them.

**Console → Companies → a company → Lifecycle.**

## What each control does

| Control | Who | Does |
|---|---|---|
| Export their data | manager or owner | Downloads a zip of CSVs: customers, jobs, workers, payments to workers, expenses. |
| Close this company | console owner | Ends everyone's access now (their address stops answering, sessions are cleared) and starts the 30-day retention. The data is kept. |
| Reopen | console owner | Takes a closure back while the data exists. The company comes back **suspended**, not active: nobody can sign in until you press Reactivate. A later closure starts a fresh 30 days. |
| Permanently purge | console owner | Deletes the company's schema, private photos and linked feedback, once the 30 days have passed. Leaves a minimal record (address, dates, billing ids). |

Health → *Closed, in retention* lists every closed company and flags the ones
whose retention has ended ("ready to purge").

## What stops a mistake

These used to be terminal-only. The friction moved with them, and there is more
of it, because an open browser tab is easier to misuse than a typed command.

- **Close, reopen and purge are the console owner's alone.** A manager can export, nothing else.
- **Your password again** on every action (and your authenticator code if two-factor is on). Wrong attempts count toward the same lockout as a wrong sign-in, so the form cannot be used to guess a password.
- **A written reason**, which goes in the Record.
- **The company's address typed out** to close or purge.
- **Purge also needs a tick** that the owner has been offered their data.
- **Purge is refused before the 30 days are up**, whatever the form says. The check is in the library, not the page, and there is no override.
- **A company with a live Stripe subscription cannot be closed**: they would keep being billed for a workspace nobody can open. Cancel the subscription in Stripe first. The demo company cannot be closed either.
- **A failed purge leaves the company closed** and changes nothing else; it is safe to try again. Repeating a purge that worked is harmless.

## The export

Explicit columns, never a blind dump. In it: customers, jobs, workers (name,
contact, pay type and rate), payments to workers, expenses. **Not** in it: sign-in
accounts and password hashes, two-factor secrets, card details, payment-provider
ids, portal and agreement tokens, private documents (W-9s, IDs), message history,
keys for connected services, anything belonging to another company. The README in
the zip says so.

It holds personal information about the company's customers and workers. Send it
only to the owner, privately. Text beginning with `=`, `+`, `-` or `@` gets an
apostrophe in front so a spreadsheet does not run it as a formula. Every download
is written to the Record with the reason.

After a company is closed its owner cannot sign in to download their own data,
which is why staff make the export.

## When a customer asks to leave

1. Cancel their Stripe subscription, if they have one.
2. Export their data and send it to the owner, privately.
3. Close the company. Tell the owner the date their data will be kept until.
4. After that date, purge, ticking that they were offered a copy.

## Backups

Purge applies to live systems. Encrypted backups are not rewritten, so purged
data can persist there until they age out (30 days). A restore from before the
purge must not bring the company back: `restored_closed_tenants_requiring_repurge`
finds closed companies whose restored data has to be purged again.

## Not done here

- Closing or purging from the terminal still works (`tenant_lifecycle_cli.py`).
- The owner is not emailed when their company is closed. Tell them yourself.
- Other personal data about a company outside its own schema (early-access
  leads, support requests) is not removed by purge; that is existing behavior.
