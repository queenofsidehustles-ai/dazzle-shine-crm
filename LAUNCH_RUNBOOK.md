# Standing the product up

Written 2026-08-28. Everything from picking a name to the first outside company
paying you.

Follow it in order. Each step is finished when its **Check** passes — if a check
fails, stop there rather than carrying on, because everything after it assumes
that one worked.

**Nothing in here touches Dazzle & Shine.** Your CRM keeps running exactly as it
does now, on its own database, throughout. The product is a second deployment.

---

## Before anything

**Your business stays live and untouched.** The whole SaaS is a separate Railway
service with a separate database. If everything below went wrong, your cleaning
company would not notice.

**You will need:** the name, a card for the domain (~£12/year) and Railway
(~$20/month to start), and about half a day.

---

## Step 1 — The name and the domain

Nothing else can start until this is decided, because the name goes into the web
addresses, the emails, the Stripe products and the app listing. Renaming later
means migrating all of it plus every bookmark your customers have.

1. Pick from `NAMING.md`, or pick your own.
2. **Search it at tmsearch.uspto.gov** — classes 42 and 35. A live mark in
   either kills it. Do this first; it is the one thing that can force a rename
   after launch.
3. Buy the `.com` at Namecheap, Cloudflare or Porkbun. If the bare word is
   taken, `getNAME.com` or `NAMEhq.com` are completely respectable — Mailchimp,
   Basecamp and Hubspot are all compound words.
4. Avoid `.io` and `.ai`. Cleaning-company owners type `.com` by reflex and will
   land on a stranger's website.

**Check:** you own the domain and can log into the registrar's DNS page.

---

## Step 2 — Two Stripe products

This is your own Stripe account for subscription income — **not** the Stripe
keys a cleaning company enters to charge its own customers. Those are separate
accounts and separate money, and confusing them would bill subscriptions to a
customer's own processor.

In the Stripe dashboard, in **test mode** first:

1. **Products → Add product** → name it **Pro**, price **$99**, *Recurring,
   monthly*. Save.
2. Same again for **Scale** at **$199**.
3. On each product, copy the **price ID** — it starts `price_`. Not the product
   ID. Keep both somewhere.
4. **Developers → API keys** → copy the **Secret key** (`sk_test_…`).

**Check:** you have two IDs starting `price_` and one key starting `sk_test_`.

---

## Step 3 — The product's own deployment

A new Railway project, separate from the one your CRM lives in.

1. Railway → **New Project** → **Deploy from GitHub repo** → this repository.
2. Set the branch to **`main`**.
3. **+ New → Database → Add PostgreSQL.** Railway wires `DATABASE_URL` itself.
4. Turn **auto-deploy off** for now (Settings → Source), so nothing goes live
   before it is configured.

**Check:** the service exists and the database is Online.

---

## Step 4 — The settings

Railway → the app service → **Variables**. These are the ones that matter:

| Variable | Value | What it does |
|---|---|---|
| `BASE_DOMAIN` | `akyehq.com` | **The switch.** Without it there is no multi-tenancy and no signup at all. |
| `SIGNUPS_OPEN` | `0` | Door shut while you test. `1` opens it. |
| `SECRET_KEY` | a long random string | Signs sessions and encrypts saved keys. Generate once, never change. |
| `CRM_BASE` | `https://akyehq.com` | Every link in every email and text is built from this. |
| `STRIPE_PLATFORM_SECRET_KEY` | `sk_test_…` | Your subscription income. |
| `STRIPE_PLATFORM_WEBHOOK_SECRET` | `whsec_…` | From step 6. Leave blank for now. |
| `STRIPE_PRICE_PRO` | `price_…` | From step 2. |
| `STRIPE_PRICE_SCALE` | `price_…` | From step 2. |
| `FROM_EMAIL` | `support@akyehq.com` | Must be on a domain your email provider has verified. |
| `SENTRY_DSN` | *(optional)* | Errors also go to Sentry if set. They are recorded either way. |

Generate the secret key with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

> **Do not set `ADMIN_USER` or `ADMIN_PASS`.** Those are the single-business
> login. On the product every account is a real user record, created by signup.

**Check:** Variables shows `BASE_DOMAIN` and `SIGNUPS_OPEN=0`.

---

## Step 5 — DNS, and the wildcard

Every company gets its own address — `acme.akyehq.com`. That needs a
**wildcard** record, so one entry covers every company you will ever have.

1. Railway → your service → **Settings → Networking → Custom Domain**.
2. Add `akyehq.com`, then add `*.akyehq.com`. Railway gives you a target
   for each.
3. At your registrar's DNS page:

```
Type    Name    Value
CNAME   @       <the target Railway gave you>
CNAME   *       <the target Railway gave you>
```

Some registrars will not allow a CNAME on the root. If so, use their **ALIAS**
or **ANAME** record type for `@`, or Cloudflare, which handles it.

4. Wait. DNS takes minutes usually, and occasionally hours.

**Check:** `https://akyehq.com` loads, and so does `https://anything.akyehq.com`.
Both may show an error page at this stage — what matters is that they *resolve*
and the padlock is there.

---

## Step 6 — Tell Stripe where to send its messages

This is the part that actually changes what a customer is entitled to. A
browser redirect never does.

1. Stripe → **Developers → Webhooks → Add endpoint**.
2. URL: `https://akyehq.com/api/stripe/webhook`
3. Select these events:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_failed`
4. Save, then copy the **Signing secret** (`whsec_…`).
5. Put it in Railway as `STRIPE_PLATFORM_WEBHOOK_SECRET`. Redeploy.

**Check:** Stripe's webhook page shows the endpoint, and **Send test webhook**
returns `200`.

---

## Step 7 — Prove it works, with signups still shut

Set `SIGNUPS_OPEN=1` **temporarily**, and make one company that is yours.

1. Go to `https://akyehq.com/signup`.
2. Sign up as **Test Cleaning Co**, address `testco`.
3. You should land at `https://testco.akyehq.com`, signed in, with your
   business name on the dashboard and a *Getting started* banner.

Then walk the whole thing:

- [ ] Add a cleaner, a customer, and book a job
- [ ] Assign the job — the *Getting started* banner should disappear
- [ ] Open the cleaner's job link on a **real phone**. Tap **Navigate**.
- [ ] Complete the checklist, clock in and out
- [ ] Check payroll shows what you set, not something else
- [ ] Try to reach **Hiring** — it should send you to the upgrade page
- [ ] Upgrade to Pro with Stripe's test card `4242 4242 4242 4242`
- [ ] Hiring should now open. **This is the moment billing is proven.**

Then set `SIGNUPS_OPEN=0` again.

**Check:** every box above. If the upgrade did not unlock Hiring, the webhook is
not arriving — check its delivery log in Stripe before going further.

---

## Step 8 — The isolation test, by hand

Automated tests cover this on every run, but do it once yourself. It is the one
failure that would end the product.

1. Sign up a **second** company, `testtwo`.
2. Put a customer in it called `SECOND COMPANY ONLY`.
3. Go back to `testco.akyehq.com` and look at the customer list.

**Check:** `SECOND COMPANY ONLY` is nowhere. If you can see it, **stop
everything** and tell me.

---

## Step 9 — Backups for the product database

The SaaS database holds every customer's business, not just yours. It needs the
same protection your CRM already has.

1. In the backup workflow's GitHub secrets, add the **product** database URL
   (Railway → the new Postgres → `DATABASE_PUBLIC_URL`).
2. Run the workflow by hand and check it goes green.
3. Restore it into a scratch database once, and log in. **An untested backup is
   not a backup.**

**Check:** a green run, and a restore you have personally opened.

---

## Step 10 — The legal minimum

You will be holding, on your servers, other companies': customer names and home
addresses, house access notes, employee W-9s, background checks and pay records.

Before a single outside company puts real data in:

- [ ] **Terms of service**, with a liability cap
- [ ] **Privacy policy** covering data you process for them
- [ ] **An explicit line that you are a record-keeping tool** — not a payroll
      provider, and not an advisor on whether somebody is an employee or a
      contractor. Your software computes contractor pay and produces 1099
      figures. If a customer misclassifies someone, you do not want to be the
      one who "told them to."
- [ ] **What happens to their data if they cancel** — export, and deletion.

Have a lawyer read them. It is a few hundred pounds and it is not optional once
somebody else's employee records are on your server.

**Check:** all four exist and are linked from the signup page.

---

## Step 11 — Go live

1. Stripe → switch to **live mode**. Recreate the two products, take the live
   `sk_live_…` key and a new webhook secret.
2. Update the Railway variables to the live values.
3. Delete `testco` and `testtwo`:
   `python3 provisioning.py destroy testco`
4. `SIGNUPS_OPEN=1`.

**Check:** `/version` responds, `/signup` loads, and a real card works.

---

## Step 12 — The first ten, by hand

Do not advertise. From `LAUNCH_PLAN.md`:

- Thirty cleaning companies in your area, screened on: 3–10 cleaners, evidence
  of a team, the owner still doing the scheduling, **and how they pay their
  cleaners** — per-job or percentage fits this product; hourly W-2 does not.
- Founder-led outreach with discovery questions, not a pitch.
- Ten founding customers at $79 locked, hand-onboarded — you import their
  clients, cleaners, prices and upcoming jobs so they log in and find their
  business already there.

**The number to watch is not signups.** It is **jobs run through the platform
per week**. A company with 60 jobs putting 5 into your software has not adopted
it, whatever the login count says.

---

## When something goes wrong

```bash
python3 release.py --rollback      # put the code back
python3 migrate.py status          # where the database is
python3 migrate.py sql             # what a pending change would do
python3 backup.py --list           # what backups exist
```

Every instance reports what it is running at `/version`, without logging in.
Two instances behaving differently is almost always two different releases.

**Errors report themselves.** Settings → Errors, and an email the first time
each fault happens. If a customer says something is broken, look there first —
it is probably already recorded.

---

## Roughly what it costs

| | |
|---|---|
| Domain | ~£12/year |
| Railway (app + database) | ~$20/month to start |
| Stripe | 2.9% + 30¢ per payment |
| Sentry | free tier is plenty |
| **Per extra customer** | **~$1–3/month** |

At $99/month that is about 95% gross margin, which is the whole reason for one
database with a schema per company rather than a separate deployment each.
