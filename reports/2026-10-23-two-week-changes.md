# Akye: Improvements and Changes, 9–23 Oct 2026

**Scope:** 114 non-merge commits, 13–23 Oct (320 files, about +37,300 / −2,200 lines). Release `akye-v2026.10.23` was cut on 23 Oct.
Source: `git log --since="2 weeks ago"`.

## Highlights
1. Quotes became a legally trackable record. A sent offer is frozen, acceptance is all-or-nothing, and the audit trail has a hash chain.
2. Nana, the AI assistant, now runs on Claude API credits and has a setup chat, a help guide and voice.
3. A 30-day trial, an affiliate program and Stripe partner payouts shipped.
4. The release process changed: `main` is the working branch, `akye-stable` is the release channel, and releases are gated on the commit's checks.
5. The Health console and backups are much stronger.

## 1. Quotes and commercial integrity
- A sent offer is never rewritten, and acceptance is all-or-nothing (audit F1–F4, #90).
- Sent quotes are frozen, the acceptor is recorded, and accounts are linked by key (F5–F8, #91).
- Agreements, amendments, delivery outcomes and an audit trail (#93).
- Accepted terms are locked, and non-finite inputs are rejected.
- Quote editor:
  - "Duplicate as a new draft" action.
  - Flag when Settings rates have moved since a quote was priced.
  - Custom lines are priced as qty × rate.
  - One $/sq ft formatting rule shared by the page and the email.
  - Shows other quotes written for the same account.
- Release-gate evidence: audit hash chain, `certify.py` and restore checks (#97).
  - Pre-0029 acceptances are listed as exceptions, not failures (#106).
  - Evidence guards survive a company schema rename (0032, #107).
  - `certify.py` zone check: a live company it can't read is now a finding, not a pass.
  - Stored time zones are audited, and Lewiston is now correctly Pacific.

## 2. Growth: trial, funnel, affiliates, sales
- **Trial:** one 30-day clock from signup (#130). Copy no longer says "not started".
- **Signup funnel:** email confirmation, abandoned-signup capture, first-week and moment emails, and lead nurture. Funnel emails were rewritten around owners' real pain points.
- **Console Communications:** every automated email in one place.
- **Funnel follow-up lists:** newest first, with a label that says what the list is now. Repeat requests are sorted by last ask.
- **Affiliates:**
  - Partner page, attribution and 30-day trial.
  - Commissions on shared-domain signups are held for review.
  - A commission refunded after the partner was paid is taken back, including partial refunds.
  - Stripe transfer payouts, which fail closed if the switch is unreadable, reconcile aged retries with Stripe, and never accept a reversed transfer.
  - The console can link a company to its Stripe customer and subscription.
  - Affiliate marketing strategy and action plan documented.
- **Sales reps:** daily call targets, an owner's Team page, and "My numbers" (#73).
- **BrightNest demo:** price list lifted 12%, for about +40% net profit (#108, #129).

## 3. Nana, AI and onboarding
- **Claude API credits:** Nana, drafts, translation and content (#100). The setup chat on Getting started also uses them (#99).
- **Nana features:** help guide, welcome pop-up and voice (#101). Nana asks a model that exists and says so when it can't (#111).
- **Deposit messages:** these now use the business's own Pricing amount, not a fixed $50 (#102, #103).
- **Setup flow:**
  - No dead ends between steps (#105).
  - Setup asks for what you can't trade without (#115).
  - Setup can be walked end to end, and a refused signup can be explained (#120).
  - The step number matches the meter, and terms are editable (#122).
  - Finishing setup and connecting payments read as one line (#123).
  - Balance is one question on one card, and payments are asked once (#138).
- **Other UI changes:** "One card for one question: who is doing this job" (#82). "Four moments and a drawer, instead of eleven boxes" (#86). Help tips on hover, focus and tap, with dots on unopened features and one suggestion per sign-in (#80, #81). The deposit request is back where it can be seen (#79). "How many cleaners" is now a decision (Monica Lewis).
- **Surveys and videos:** survey of existing businesses, with Nana answering two questions (#118). Three onboarding video scripts mapped to Getting started, and an overview video showing a job going out to the team and being claimed.

## 4. Jobs and bookings
- **Photos and close-out:** photos are optional to close a job, with a manual "Mark complete". Clock-in and checklist are enforced server-side on close-out. Held jobs block one-click complete. Photo checklist wording is migrated per company (0033).
- **Book again:** repeat a completed booking as a one-off, linked to the original.
  - It enforces the job limit and carries the accepted checklist.
  - It handles crew jobs and picks the last clean by completion date.
  - It is classified in the role matrix.
- **Review fixes (21 Oct):**
  - City switch.
  - Interview uploads.
  - Backup anchor.
  - Trial end.
  - Terms window.
  - ZIP zones, including mixed ZIP prefixes.
  - Rollback per line.
- **Console:** companies are listed newest first, with search and archive. Close, export and purge controls were ported to `akye-stable`.

## 5. Reliability, Health and operations
- **Health upgrade:** backups, background jobs, platform errors, usage and switches (#109).
  - Review fixes: server errors stay pending, unmapped refunds retry, and every backup target is listed.
  - Nana failures are two rows, not one with the message overwritten (#114).
  - The button no longer looks like a question box, and flashes have a colour (#113).
  - The errors page records database crashes and keeps no customer values (#110).
- **Backups:**
  - A restore is held to evidence only where the source had an audit chain.
  - The backup name for the "-1" run was fixed.
  - The `test_backup` timing flake was fixed.
- **Database:** one connection pool per process (`provisioning._engine()` reuses its engine). A post-0031 schema without its chain is refused.
- **Security:** a rogue-code and loose-ends review (#95). The cron-key check was hardened, and the Stripe payout confirm dialog now escapes the partner name and amount.
- **Loose ends (#98):** flaky crew-hours check fixed, dependencies pinned, stale cards removed, Node 24 actions.

## 6. Release process
- `main` is Akye's working branch and `akye-stable` is its release channel. CI, nightly backup and `release.py` follow `main`.
- A release gates on the commit's checks, and production runs the release.
- The release tag records its checks, migration head and way back.
- A by-hand release needs run links and a second person.
- Fixes were ported between `main` and `akye-stable`: affiliates, Health, payouts and migration IDs.
- White-label sweep: no business name in the source. `release.py` is exempt because it names git branches.
- Remediation report of 19 Oct (#128) and a 22 Oct report.

## Follow-ups seen in the log
- Two ports left photo-wording migration 0021 as a no-op, so stamped databases keep resolving. Keep that in mind before renumbering migrations.
- Manual releases need a second person, so schedule that into release days.
