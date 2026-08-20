# Dazzle & Shine — Build-Later Backlog

Ideas we agreed to build later (not urgent). Newest at top.

## White-labeling — DONE 2026-08-08

Every item below is finished. Setting up a new company is now a config job, not a
code job: see **NEW_CUSTOMER_SETUP.md**.

- [x] **Hardcoded production URL.** Gone from all 11 places. Every texted link is
      built from `branding.crm_base()`, which reads the `CRM_BASE` environment
      variable and falls back to the live request's own host — so a misconfigured
      instance links to itself rather than to somebody else's CRM.
- [x] **217 hardcoded brand strings across 90 files.** All resolve through
      `branding.py` (code) or the `BIZ` template variable injected by the context
      processor in `app.py`.
- [x] **Outgoing email defaults.** `branding.from_email()` / `owner_email()` /
      `reply_to()`. Settings first so the owner can change them without a redeploy;
      the *sending* address stays an env var because it must match a verified domain.
- [x] **`brands.py` rebuilt.** Both identities come from Settings. A business with
      one trading name leaves the commercial fields blank and its commercial quotes
      fall back to its single name. Legacy `lm` / `dazzle` keys on saved quotes still
      resolve, so no history was rewritten.
- [x] **Google review link no longer defaults to ours** — this was the sharpest
      leak. Unset means the button hides rather than sending a delighted customer to
      review the wrong company.
- [x] **Regression guard.** `test_whitelabel.py` boots a blank instance and fails if
      any trace of another company appears on 17 admin pages, the payment page, quote
      emails, the training guide or the interview questions. `test_whitelabel_existing.py`
      proves the existing business's name, colours, L&M brand and review link all
      survived the move into Settings.

Still open, and worth doing before this grows past a couple of customers:

- [ ] **Admin UI theming.** Emails and customer-facing pages are fully themeable;
      the admin CSS is still gold-and-purple. Only the owner sees it.
- [x] **A release you promote deliberately.** Done 2026-08-20. Customers deploy
      from `stable`, which only moves when `release.py --go` runs — and it runs
      every test suite before it will. `/version` reports the release each
      instance is on, and `--rollback` puts them back. See **RELEASING.md**.
- [x] **Staging.** Done 2026-08-20, by using this business's own instance as the
      canary rather than standing up a second environment nobody would look at.
      `main` is live here immediately; customers only see a change once it has
      been promoted.

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
