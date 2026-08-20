# Setting up the CRM for a new cleaning company

Every company gets **its own deployment**: its own app, its own database, its own
domain, its own Stripe account. Nothing is shared. One company's bad day cannot
touch another's, and there is no way for their data to mix.

Work through this in order. Budget about two hours for the first one.

---

## What you do, and what they do

Keep this split. It's what stops you becoming the bottleneck as this grows.

| You | They |
|---|---|
| Create the Railway project and database | Everything else |
| Set `CRM_BASE`, `SECRET_KEY`, `ADMIN_USER`, `ADMIN_PASS` | Their Stripe, Twilio and email keys |
| Hand over a URL and a login | Their business details, prices, terms, branding |

**You never need their Stripe credentials.** They paste their own keys into
Settings → Connections, encrypted, and can rotate them without telling you. If
you find yourself logging into a customer's Stripe, something has gone wrong with
the process.

Send them **CUSTOMER_ONBOARDING.md**. It walks them through the rest, and the CRM
shows them a Setup checklist tracking what's left.

> **The one thing to verify yourself:** that their instance is not pointed at
> *your* Stripe keys. Their Connections page names the business a key belongs to
> — check it says theirs before they take a real booking.

---

## 1. Create their app on Railway

1. Railway → **New Project** → **Deploy from GitHub repo** → this repo.
2. **Set the branch to `stable`**, not `main`. `main` is this business's own
   channel and changes on every push; `stable` only moves when a release is
   promoted deliberately. See **RELEASING.md**. This is the single easiest thing
   to get wrong and the most expensive: an instance on `main` takes every change
   the moment it is pushed, untested, into someone's live business.
3. Add a **Postgres** database to the project. Railway sets `DATABASE_URL` itself.
4. Deploy. It will boot with placeholder branding — that's expected. Check
   `/version` reports `"channel": "stable"` before going any further.

## 2. Set their environment variables

In Railway → their project → **Variables**:

| Variable | Value | Notes |
|---|---|---|
| `CRM_BASE` | `https://their-app.up.railway.app` | **The important one.** Every link texted to their cleaners and customers is built from this. Wrong here and their cleaners land on someone else's CRM. No trailing slash. |
| `SECRET_KEY` | a long random string | Generate a fresh one per company. Never reuse. |
| `ADMIN_USER` / `ADMIN_PASS` | their login | Let them choose the password; you shouldn't know it. |
| `FROM_EMAIL` | e.g. `bookings@theirdomain.com` | Optional. They can set this themselves later once their domain verifies. |

That's all you set. **Stripe, Twilio and email keys are theirs to enter** in
Settings → Connections — they're stored encrypted in their own database and you
never handle them.

> `SECRET_KEY` also encrypts their saved keys. Changing it later means they have
> to paste their keys in again, so generate it once and leave it alone.

Redeploy after saving.

**Sanity check before going further:** open
`https://their-app.up.railway.app/login` and log in. If that works, the app and
database are wired up correctly.

## 3. Hand it over

Give them the URL, their login, and **CUSTOMER_ONBOARDING.md**.

From here it's theirs. They log in, see a Setup checklist, and work down it:
business details, prices, terms, branding, and their own Stripe/Twilio/email
keys. You don't have to do any of it, and you shouldn't — a customer who can't
change their own prices without messaging you is a customer you'll be supporting
forever.

Stay available for questions. Don't take the keyboard.

## 4. Watch for the one expensive mistake

Before they take a real booking, have them press **Settings → Connections → Test
Stripe connection**. It names the business the money would reach.

If that name isn't theirs, stop and fix it. Everything else on this list is
recoverable; money landing in the wrong bank account is the one that isn't.

## 5. Test it end to end before they go live

Do this on their instance, with their keys, using Stripe **test mode** first if
they'll let you.

- [ ] Log in.
- [ ] Add a cleaner. Send them a test text — does it arrive from *their* number?
- [ ] Create a booking. Does the confirmation email arrive with *their* name on it?
- [ ] Open the payment link. Does the page show *their* business?
- [ ] Take a $1 test payment. Does it appear in *their* Stripe dashboard? **Check
      this specifically. It is the single most expensive thing to get wrong.**
- [ ] Assign the job to the cleaner and send the offer. Tap the link on a phone —
      does it open *their* CRM, not yours?
- [ ] Mark the job complete and check the rating link.
- [ ] Open the P&L. Does the revenue show up?

Anything that lands on your CRM instead of theirs means `CRM_BASE` is wrong or
unset on their deployment.

## 6. Keep your hands off

They never need access to your Railway project, your database, or your Stripe —
and you never need access to theirs.

---

## How updates reach them

**Code is shared. Data is not.** That split is the whole thing:

| | Where it lives | What a deploy does to it |
|---|---|---|
| Bug fixes, new features | This repo — one copy | Reaches every instance |
| Their prices, branding, terms | *Their* database | Never touched |
| Their customers, bookings, cleaners, payments | *Their* database | Never touched |

So fixing a bug once fixes it for everyone. You don't repeat the work per
customer. The flip side is that shipping a bug ships it to everyone too — a bad
push at 9pm is a bad push in his business, in front of his customers.

### Give yourself a release you control

Don't point his instance at `main`. Point it at a `stable` branch you merge into
when you're ready:

```
main     ← you work here; your CRM deploys from this
  │
  └──▶ stable   ← his CRM deploys from this. You merge when you're confident.
```

Set it up once, in Railway → his project → **Settings → Source → Branch** →
`stable`. Then:

```bash
# You've shipped something to your own CRM, used it for a few days, and it's good:
git checkout stable
git merge main
git push origin stable      # now his instance updates
git checkout main
```

Why bother: **you become his staging environment.** Every change runs in your
real business first, on your real jobs and your real money, before it reaches
anyone else. That's a genuinely good safety net and it costs you one extra
command.

If you'd rather keep it simple to begin with, both instances can track `main` —
just know that every push is live in his business the moment you make it.

### Either way

- Test locally first. `tests/local-e2e.spec.js` runs the whole flow against a
  throwaway database in about twelve seconds.
- `python3 tests/test_whitelabel.py` fails if any of your branding leaks back in.
- Tell him before a change he'll notice. "Your invoices look different today"
  should never be a surprise.

---

## Things that are still shared, and shouldn't be forever

Worth knowing before this grows past a couple of customers:

- **One repo, one deploy button.** Fine for two or three companies. Past that,
  you want a release you promote deliberately rather than every push going live
  everywhere at once.
- **No staging.** There is nowhere to try a change before customers see it.
  This was worth having when it was just your business. With someone else's
  livelihood on it, it matters more.
- **The admin UI colour scheme** is still gold-and-purple in the CSS. Emails and
  all customer-facing text are fully themeable; the admin screens they log into
  aren't yet. Cosmetic, and only they ever see it.
