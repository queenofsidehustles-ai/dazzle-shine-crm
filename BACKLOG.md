# Dazzle & Shine — Build-Later Backlog

Ideas we agreed to build later (not urgent). Newest at top.

## White-labeling (parked 2026-08-01 — do before a second customer touches the CRM)

The CRM is being built to resell to other cleaning companies. It isn't tenant-safe
yet. Audit findings, worst first:

- [ ] **Hardcoded production URL — this one is a real bug, not cosmetic.**
      `CRM_BASE = 'https://dazzle-shine-crm-production.up.railway.app'` appears in
      `lifecycle.py:12`, `blueprints/messages.py:17`, `blueprints/claims.py:14`, and
      `audit.py:8`. Another company's cleaners would get job-claim links pointing at
      **our** server — they'd tap "Claim this job" and land in someone else's CRM.
      Fix: derive the base URL from the request host or a per-tenant setting.
- [ ] **~150 hardcoded "Dazzle & Shine" strings across 25+ files** — emails, page
      titles, templates. `BusinessSetting` already exists and is the right mechanism;
      it's just used inconsistently. Heaviest offenders: `blueprints/contractors.py`
      (31), `blueprints/interviews.py` (18), `blueprints/bookings.py` (17).
- [ ] **Outgoing email defaults to our addresses.** `notifications.py:132` falls back
      to `bookings@dazzleandshinemaids.com`, `:140` to the gmail. `payment_service.py`
      does the same in two places.
- [ ] **`brands.py` is two hardcoded brand dicts**, not a per-tenant layer. Fine for
      the L&M / Dazzle split it was built for; won't carry a third company.
- [ ] **Regression guard:** `tests/local-e2e.spec.js` test 14 already asserts the
      brand can't leak into the P&L CSV. Extend that idea — a test that boots a
      blank instance and fails if "Dazzle" appears anywhere user-facing.

## Contractor pay
- [ ] **Auto-flag 55% raise candidates.** When a contractor hits the top-performer
      bar (15+ completed jobs AND 4.5★+ average AND reliable), show a badge/alert on
      their Team profile (e.g. "⭐ Eligible for 55% raise") so Monica doesn't have to
      track it by hand. The actual raise stays a manual one-click bump (she decides
      who's earned it). See CONTRACTOR_PAY_POLICY.md for the criteria.

## Client acquisition (from GROWTH_PLAYBOOK.md)
- [ ] **Review Flywheel** — auto text+email after each completed job asking for a
      rating; 4-5★ → Google review page, 1-3★ → private feedback form. Build once
      there are ~10 real completed jobs to run it on.
- [ ] **Referral program** — happy clients get a code; friend gets $25 off first
      clean, referrer gets $25 off next. Builds on the existing discounts engine.
- [ ] **Reactivation campaign** — "we miss you" offer to clients who haven't booked
      in 60-90 days.

## Notes
- Twilio (texting) must be connected in Railway for the SMS parts of Speed-to-Lead
  and the Review Flywheel to actually send. Until then, email still fires.
