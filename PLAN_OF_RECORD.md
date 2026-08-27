# Plan of record

Written 2026-08-27. Reconciles the Agentic AI Implementation Master Plan against
the actual codebase and the work already done.

**This file supersedes the sequencing in `LAUNCH_PLAN.md` and `SAAS_ROADMAP.md`.**
Those remain accurate on architecture and go-to-market; where they disagree with
this file on *order*, this file wins.

---

## Verdict

The master plan is a good document — better organised than anything else written
about this product, and right about three real defects nobody had caught. It was
also written without reading the code, and it shows in four places where
following it would cost months for no gain.

Take its rigour. Do not take its architecture, its role model, its pricing, or
its timeline.

---

## 1. What it caught that we had missed — all three verified in the code

### 🔴 Money is stored as floating point. 19 columns, zero `Numeric`.

```
models.py:85    balance_due     = db.Column(db.Float)
models.py:408   pay_amount      = db.Column(db.Float)
models.py:950   amount          = db.Column(db.Float, nullable=False)   # payroll
```

The plan's rule — *"Use decimal monetary types. Do not use floating-point
arithmetic for currency"* — is correct and this violates it everywhere.

Floats cannot represent most decimal amounts exactly. `0.1 + 0.2` is
`0.30000000000000004`. Individually invisible; across a P&L, a payroll run and a
1099 it compounds into totals that do not reconcile, and the symptom is a cleaner
who says her pay statement is a cent off and cannot be told why.

This is the single most valuable finding in the document. **But do not fix it
yet** — see §2 of the sequence below. It is a data migration across 19 columns
touching every financial calculation, and the plan is right that tests must come
first.

### 🟠 No CSRF protection anywhere. No `flask_wtf`, no tokens.

Every state-changing POST — create booking, correct price, pay a contractor,
delete an expense — accepts a form submission with no proof it came from your
own page.

Modern browsers default cookies to `SameSite=Lax`, which blocks the classic
cross-site form post, so this is a gap rather than an open door. It is still a
gap, and it is about a day's work.

### 🟠 No login rate limiting, and no session cookie hardening.

`SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE` and session lifetime are
unset — Flask's defaults apply rather than a decision. Failed logins are
unthrottled, so the owner login can be attacked at whatever rate the server will
answer.

### Also right, and worth adopting wholesale

- **Idempotent webhook processing**, and *"do not accept a successful browser
  redirect as authoritative payment confirmation."* Both are how people lose
  money at exactly this stage.
- **Audit logging** for financial and authorization changes, with the discipline
  of not logging message bodies or credentials.
- **"Never use production customer data for tests, screenshots or demos."**
  Directly relevant: your local `instance/dazzle.db` holds real client records
  and I read it during the backup drill. It should be anonymised or replaced with
  seeded data.
- **Separate operational facts from derived metrics** — *"never use a dashboard
  total as the source for another dashboard total."* Exactly right.
- **Staged store rollout** and **owner-controlled developer accounts.**
- **The adversarial cross-tenant test list**, which is more thorough than mine.
- **Graceful limit behaviour** — *"never hold customer data hostage."* Already
  how `entitlements.py` works; good to see it independently arrived at.

---

## 2. Where it is wrong for this codebase

Each of these comes from not having read the repository.

### ❌ "Every operational record must carry an immutable `organization_id`"

This is row-level multi-tenancy across 33 models and 262 routes. It is 6–10 weeks
of work in which one forgotten `.filter_by(organization_id=...)` puts one
company's client list on another company's screen — and there are hundreds of
places to forget it.

**You are already isolated.** Every customer has a separate app, separate
Postgres, separate domain (`NEW_CUSTOMER_SETUP.md`). The plan is solving a
problem you do not have, using the riskiest of the three available methods.

**Do schema-per-tenant instead** (`SAAS_ROADMAP.md` §2). One Postgres, one schema
per company, `search_path` set per request. Your models and routes do not change.
Isolation is enforced by the database rather than by remembering a filter, so a
bug returns *no* data instead of *someone else's*. Two to three weeks instead of
six to ten.

Keep the plan's **adversarial test list** — it applies unchanged. Only the
mechanism is different.

### ❌ Nine roles

Owner, Administrator, Dispatcher, Hiring Manager, Accountant, Marketing/VA, Team
Lead, Cleaner/Contractor, Read-only Auditor.

No cleaning company with eight cleaners has a Read-only Auditor. Every one of
those roles is a permission matrix to maintain, test and support, for
distinctions your customers do not make.

**Ship Owner, Manager and Worker.** Add a role when a paying customer asks for
one. The plan's underlying advice — *named permissions, not role-name
comparisons* — is right and should be adopted regardless of how many roles exist.

### ❌ Cleaners get logins

The plan lists Cleaner/Contractor as a role and specifies "Secure login" in the
cleaner mobile experience.

Your cleaners have no accounts. They get texted magic links —
`/claim/<ctoken>/<stoken>`, `/checklist/<token>` — with `secrets.token_urlsafe`
tokens. A cleaner hired last Tuesday taps a text and is looking at today's job in
two seconds. No install, no password, no reset, no support ticket.

That is a competitive advantage over ZenMaid and Jobber, both of which force an
app install and pay the support tax. **Do not replace it with logins.** Adopt the
plan's token hardening — expiry, purpose restriction, revocation, rate limiting —
which is genuinely good and mostly missing today.

### ❌ Five pricing tiers at launch, and a $39 founding price

Free / $39 / $79 / $149 / $249–399 is five ways to be confused before anyone has
paid you once. And the Founding 20 offer — *Growth at $39/month for twelve
months* — sets your best early reference price at half of Growth, locked for a
year, across twenty customers. That is roughly $9,600 of forgone revenue in year
one from precisely the customers most willing to pay.

**Three tiers** (`PRODUCT_STRATEGY.md` §2): Free / Pro $99 / Scale $199. **Ten
founding customers, not twenty**, at $79 locked. Ten is enough to learn from and
few enough to support personally while you are also building.

### ❌ It never requires backups or error monitoring

Both appear in the Phase 0 *inventory* list — things to document — and then never
appear again as things to build. There is no acceptance criterion anywhere in
twelve phases that says a backup must exist.

That is the largest omission in the document. It is also already done: see
`BACKUP.md`.

### ❌ It never mentions `_migrate_db()`

Rule 7 says migrations must be reversible. But `app.py:409` is a hand-written
`ALTER TABLE` script that runs at every boot against live data, with no dry run
and no rollback, and the plan never names it. Under schema-per-tenant it runs
against every schema at once. **Alembic is the real Phase 1 blocker** and the
plan does not know it exists.

### ⚠️ It contradicts itself on order

Phases 9–10 put mobile *before* the Founding 20 in Phase 11. The "Absolute
implementation order" at the end puts Founding 20 at #19 and mobile at #21–23.
Follow the second one — customers before apps.

---

## 3. The part that needs saying plainly: the timeline

Twelve phases and twenty-five sequential steps. Multi-tenancy, RBAC, audit
logging, decimal migration, reconciliation, onboarding, navigation redesign,
entitlements, billing, usage metering for SMS and AI and leads, three "engines,"
an automation engine, two mobile apps, two app store launches, a founding cohort,
and a recommendation engine.

**That is nine to eighteen months of full-time work.** You have three months.

The plan never states a duration, which is what makes it dangerous — it reads as
a checklist you could work down, and it is a multi-year roadmap. Attempted in
three months it produces twelve things at 70% and nothing anyone can pay for.

Its own strategic summary is the right instinct: *"secure the operating system,
make onboarding repeatable, prove paid value, and only then scale."* Steps 1–20
are two of those four. **Cut at step 20.**

---

## 4. What to actually build, in order

Merged. Everything below is either already done, or fits in twelve weeks.

### ✅ Done
- Backups, verified restore, nightly off-site job — `BACKUP.md`
- Entitlement engine, server-side, with usage limits and denial logging —
  `entitlements.py`
- Grandfathering so established instances are never downgraded

### Weeks 1–2 — Security and truth *(the plan's Phase 0 and 2.1, merged)*
1. Move to a feature branch. `main` deploys to your live business on push.
2. Secret scan of git history. Rotate anything found — changing the file is not
   enough once it is in a commit.
3. CSRF protection, login rate limiting, session cookie hardening.
4. Error monitoring, tagged by instance.
5. **Tests around every financial calculation, before touching any of them.**
   Pricing, pay, tips, fees, discounts, commissions, refunds. This is the plan's
   best sequencing instinct and it is non-negotiable.
6. Anonymise or replace the real client data in `instance/dazzle.db`.

### Weeks 3–4 — Money correctness
7. **Migrate the 19 float columns to `Numeric(10,2)`.** Backward-compatible
   migration, tests from step 5 proving nothing moved.
8. Facts versus derived metrics; reconciliation views for Stripe.

### Weeks 5–7 — The platform
9. **Alembic replacing `_migrate_db()`.** The real blocker.
10. Control-plane schema: organizations, memberships, subscriptions.
11. Schema-per-tenant with `search_path` middleware.
12. Migrate the existing business into a schema.
13. The adversarial isolation suite from the plan's §1.2, in CI.
14. Named permissions; three roles.
15. Audit logging for financial and authorization events.

### Weeks 8–10 — The front door
16. Self-service signup, email verification, password reset.
17. Stripe Billing: checkout, trial, **idempotent webhooks**, dunning, grace.
18. Apply `@requires_plan()` across the gated routes; upgrade screen.
19. Activation checklist ending at "schedule your first job."
20. Customer and cleaner CSV importers.
21. Twilio subaccounts; shared sending domain.

### Weeks 11–12 — Prove it
22. Seeded demo tenant. **Never production data.**
23. Ten founding customers at $79 locked.
24. Instrument the funnel: signup → org → worker → customer → booking →
    assignment → completed job → payment → retention.

### Explicitly deferred to after paying customers
Mobile apps and store submission · usage metering for SMS/AI/leads · the
automation engine · the three "engines" · navigation redesign · the
recommendation layer · roles four through nine · multi-location · white label ·
API access.

All of it is good. None of it is what stands between you and the first person
paying.

---

## 5. Rules to adopt verbatim

The plan's governing rules are its strongest section. Adopt all ten, with two
additions:

11. **No backup, no launch.** Verified restore, not just a file.
12. **State the cost in weeks before starting any phase.** The failure mode of a
    plan this thorough is that everything looks mandatory.
