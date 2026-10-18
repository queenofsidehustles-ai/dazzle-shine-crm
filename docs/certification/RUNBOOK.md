# Quotation release gate: how to produce the evidence

This runbook goes with the GREEN remediation plan (2026-10-16). Each gate has:
- a command to run;
- the file it produces;
- what a pass looks like.

Production commands go through Railway (`railway run …`), so the database password never leaves Railway and is never pasted anywhere. Keep every output file in the evidence archive. Each file holds ids, hashes and counts, and no customer data.

| Gate | Command | Pass |
|---|---|---|
| G0 Deployment | Railway dashboard: deployment SHA, replicas, Postgres health (screenshot) | SHA = the `akye-stable` commit being certified |
| G1 Schema | `railway run python3 certify.py schema --out g1-schema.json` | exit 0 |
| G1/G5 Evidence | `railway run python3 certify.py evidence --out g1-evidence.json` | exit 0 |
| G2 Journey | `railway run python3 certify.py journey --company <demo slug> --out g2-journey.json` | exit 0 |
| G3 Concurrency, auth | CI: `test_quote_failure_modes`, `test_quote_integrity`, `test_quote_certification` on the certified SHA | green |
| G4 Mail provider | Manual steps (below) | every step ticked |
| G5 Restore | Nightly backup run (Actions → Nightly backup), plus `certify.py compare` | job green; exit 0 |
| G6 Sign-off | This table filled in, the files archived, approvals recorded | — |

## G1: schema and guards
`certify.py schema` runs in a read-only transaction. It:
- lists every company schema;
- reconciles that list with the company list, so a company with no schema, or a stray schema, is a problem;
- checks every schema is on the code's migration head;
- checks every table and column from migrations 0028–0031 is present;
- checks every guard trigger is present and **switched on**;
- checks both unique indexes are present.

It also reports which database login it ran as, and whether that login owns the tables. **On Railway it does.** The owner can switch guards off, so the guards stop mistakes, not the owner.

What does show an owner's change:
- the audit chain;
- the record the backup keeps outside the database.

Both are checked below.

`certify.py evidence` (also read-only) works through every company. It checks that:
- every revision's terms still hash to its stored hash;
- every answer and agreement names its revision's hash;
- every accepted quote has its answer and account. A quote accepted before answers were recorded (migration 0029) kept only a status and a time; it is listed as an *exception* when no terms were ever frozen for it and it was accepted before the company's first revision or answer. Otherwise it is a problem;
- every quote accepted since agreements began also has its agreement. Older ones are listed as *exceptions*, not problems: their answer is their record;
- there is at most one accepted amendment per quote;
- every company's audit chain recomputes from its rows.

## G2: the journey, on the demo company
`certify.py journey` refuses to run unless both are true:
- the company is marked `is_demo`;
- the database is already on this code's migration head. So deploy first; the journey never migrates anything.

**What it does:**
1. Creates a certification proposal.
2. Sends it, which freezes a revision and binds the link to it.
3. Checks the customer's link shows exactly that revision's hash.
4. Accepts it with a typed name.
5. Checks there is exactly one answer, one agreement and the account link, and that the trail has created, sent, viewed, accepted and agreement executed.
6. Tries a second acceptance, an edit and a delete. Each must change nothing.
7. Runs `UPDATE` and `DELETE` straight at the evidence tables, in transactions that are always rolled back. Each must be refused.
8. Amends the agreement, sends and accepts the amendment, and checks that:
   - the original agreement is unchanged;
   - the new agreement names the original;
   - the original link says it was replaced.
9. Reconciles everything it made.

**Email:** a demo company never sends email, so the two sends go to a recording stub. The output says `transport: certification stub`, and each message gets a `cert-…` id. Real delivery through Resend is G4's to prove. The records it makes stay on the demo company until the demo is next rebuilt.

## G4: Resend (manual, in the Resend dashboard)
1. **Webhook:** Webhooks → Add endpoint `https://<platform host>/api/email-events`. Select the events `email.delivered`, `email.bounced`, `email.complained` and `email.delivery_delayed`.
2. **Secret:** copy its signing secret into Railway as `RESEND_EVENTS_WEBHOOK_SECRET`, then redeploy.
3. **Delivered:** from a real company you control, send a proposal to an inbox you control. On its review page, the delivery should turn to ✅ Delivered, with the Resend message id. Screenshot it.
4. **Bounced:** send one to `bounced@resend.dev`, Resend's bounce test address. You should see ⛔ Bounced with the reason.
5. **Replay:** use "Resend" on one event in the dashboard. Nothing should change: it's recorded once.
6. **Alerts:** a wrong secret, or an event that can't be saved, appears on the console's errors page and emails the platform owner. Their kinds are `SignatureRefused` and `EventNotSaved`. To prove the alert, temporarily set a wrong secret on a non-production service and watch for the alert.

## G5: restore
**Nightly backup:** the nightly backup (`.github/workflows/backup.yml`) does all of this. A green run is the G5 evidence:
- it dumps every company in one snapshot;
- it writes into the manifest each company's audit chain head and every evidence hash. The manifest lives on GitHub, outside the database;
- it restores the dump into a scratch database and checks that:
  - every row came back;
  - the restored evidence matches the manifest exactly;
  - every audit chain recomputes;
  - every guard is back on.

**Comparing later:** to hold the live database against any earlier manifest, run `railway run python3 certify.py compare backup-<date>.manifest.json --out g5-compare.json`. It passes if everything written down then is still there, unchanged, and the audit chain has only grown by appending.

**A backup fails loudly**, keeping the file and naming the rows, in either case:
- an audit chain doesn't recompute;
- a hash doesn't match.

## When something fails
**Every problem names its company schema and the record id.** None of these commands changes anything. Investigate before acting.

**Tampering versus a loose end:**
- **Tampering:** a broken chain or a hash mismatch is a change to evidence, not a loose end. Treat it as an incident and compare against the latest manifest that passed.
- **Loose end:** a reconciliation problem, such as an accepted quote with no account, needs a person who knows what happened.

This is engineering GREEN only. Legal review of the contract terms and of signatory authority is a separate business gate (plan §9).
