# Setting up the CRM for a new cleaning company

Every company gets **its own deployment**: its own app, its own database, its own
domain, its own Stripe account. Nothing is shared. One company's bad day cannot
touch another's, and there is no way for their data to mix.

Work through this in order. Budget about two hours for the first one.

---

## Before you start — what to collect from them

Ask for all of this up front. Chasing it halfway through is what makes setup drag.

| What | Why you need it | Blocker? |
|---|---|---|
| Business name, phone, address | Goes on every email, invoice and page | **Yes** |
| The email address they want customers to reply to | Where their replies land | **Yes** |
| **Their own Stripe account** | Their customers' money must reach *them* | **Yes** |
| A domain (or use a free `.up.railway.app` one to start) | Their cleaners' job links | No |
| Their prices per service and per bedroom count | The quoting engine | **Yes** |
| Their cleaner pay rate ($/hour) | Payroll and the floor-price guard | **Yes** |
| Logo and brand colours | Email headers | No |
| Google review link | The review button after a 5-star rating | No |

> **The Stripe one is non-negotiable.** If their instance ends up pointed at your
> Stripe keys, their customers' payments land in *your* bank account. Check this
> twice.

---

## 1. Create their app on Railway

1. Railway → **New Project** → **Deploy from GitHub repo** → this repo.
2. Add a **Postgres** database to the project. Railway sets `DATABASE_URL` itself.
3. Deploy. It will boot with placeholder branding — that's expected.

## 2. Set their environment variables

In Railway → their project → **Variables**:

| Variable | Value | Notes |
|---|---|---|
| `CRM_BASE` | `https://their-app.up.railway.app` | **The important one.** Every link texted to their cleaners and customers is built from this. Wrong here and their cleaners land on someone else's CRM. No trailing slash. |
| `SECRET_KEY` | a long random string | Generate a fresh one per company. Never reuse. |
| `ADMIN_USER` / `ADMIN_PASS` | their login | Let them choose the password; you shouldn't know it. |
| `STRIPE_SECRET_KEY` | **their** `sk_live_…` | From *their* Stripe account. |
| `STRIPE_PUBLISHABLE_KEY` | **their** `pk_live_…` | Same account. |
| `FROM_EMAIL` | e.g. `bookings@theirdomain.com` | Must be a domain verified with the email provider — see step 4. |
| `TWILIO_ACCOUNT_SID` | theirs | Texting. Without it, texts are logged as "not connected" rather than sent. |
| `TWILIO_AUTH_TOKEN` | theirs | |
| `TWILIO_PHONE` | their sending number | |
| `RESEND_API_KEY` | theirs | Email sending. |

Redeploy after saving.

**Sanity check before going further:** open
`https://their-app.up.railway.app/login` and log in. If that works, the app and
database are wired up correctly.

## 3. Fill in Settings → Business

Log in as them and work down the page. This is where the CRM learns who it
belongs to — the name entered here appears on every page and every email.

- **Business Info** — name, phone, email, address, city, state, website.
- **Business Model** — contractor vs employee, and who answers the phone.
- **Branding** — tagline, colours, Google review link.
  Leave the review link blank if they haven't got one; the button hides itself
  rather than sending their happy customer to review the wrong company.
- **Commercial Brand** — *leave entirely blank* unless they sell commercial work
  under a different trading name. Blank means all quotes go out under their one
  name, which is what most businesses want.
- **Customer Terms** — read these with them. The default terms include the
  non-refundable and scope-change clauses. They are the ones on the hook for
  what these say, so they should approve the wording.

Then **Settings → Pricing** for their price matrix, and their cleaner hourly rate.

## 4. Get their email sending properly

Until their domain is verified, email goes out from the deployment's default
address with their name on it. That works, but it looks better once verified.

1. In Resend, add their domain and add the DNS records it gives you.
2. Once it shows verified, set `FROM_EMAIL` to an address on that domain.
3. In **Settings → Business → Branding**, switch **Send Email From Your Own
   Domain** to *Yes*.

> Don't switch that on before the domain verifies — their emails will stop
> arriving and it is not obvious why.

## 5. Test it end to end before they touch it

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

## 6. Hand over

Give them: the URL, their login, and a walk-through. Nothing else — they never
need access to your Railway project, your database, or your Stripe.

---

## When you change the code

Both deployments track this repo. Pushing to `main` deploys to **every**
instance, theirs included. So:

- A bug you ship at 9pm is a bug in their business too.
- Test locally first. `tests/local-e2e.spec.js` runs the whole flow against a
  throwaway database in about twelve seconds.
- Their pricing, branding and settings live in *their* database, so a deploy
  never overwrites what they've configured.

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
