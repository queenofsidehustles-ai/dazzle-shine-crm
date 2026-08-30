# Putting Akye online — click by click

Written 2026-08-30. Follow it in order. Do not skip ahead, because each step
assumes the one before it worked.

**Time:** about half a day, most of it waiting for DNS.

---

## Read this bit first

**Your cleaning company is not involved in any of this.**

You already have a Railway project running Dazzle & Shine. We are making a
**second, separate** Railway project, with its own separate database. They
never touch. If everything below went wrong, your cleaning business would keep
running and your cleaners would not notice a thing.

Two rules that matter more than anything else on this page:

1. **Never paste a database URL into a chat, an email, or a screenshot.** Not
   to me, not to anyone. When a step says to copy one, copy it straight from
   Railway into the box it belongs in, and nowhere else.
2. **Do not set `ADMIN_USER` or `ADMIN_PASS` on the new project.** Those are
   for a single-business CRM. On the product, every account is a real user
   created by signing up. Setting them would create a back door.

If a step does not look like what I describe, **stop and tell me** rather than
clicking the nearest thing. Screenshots are fine — just crop out anything that
looks like a password or a long web address with a password in it.

---

## Step 1 — Make the two Stripe products

This is **your own** Stripe account, for the money other cleaning companies pay
you. It is not the Stripe keys a cleaning company enters to charge its own
customers. Different accounts, different money. Do not mix them up.

1. Go to **dashboard.stripe.com** and sign in.
2. Top right, find the toggle that says **Test mode**. **Turn it ON.**
   Everything in this step is pretend money until we say otherwise.
3. Left sidebar → **Product catalogue** (older accounts say **Products**).
4. Click **+ Add product**.
5. Name: `Pro`
6. Price: `79.00`, currency **USD**.
7. Under it, choose **Recurring**, and set the billing period to **Monthly**.
8. Click **Add product** to save.
9. Do steps 4–8 again, but name it `Scale` and price it `149.00`.

Now collect three things. Keep them in a note on your computer — not in a
message to me.

10. Open the **Pro** product. Under **Pricing** there is a row with the price.
    On the right of that row is an ID starting with **`price_`**. Copy it.
    ⚠️ It is **not** the one starting `prod_`. That is the product ID and it
    will not work.
11. Do the same for **Scale**.
12. Left sidebar → **Developers** → **API keys**. Find **Secret key**. Click
    **Reveal test key**. Copy it. It starts `sk_test_`.

**✅ Done when:** you have two IDs starting `price_` and one key starting
`sk_test_`.

---

## Step 2 — Make a long random password for the app

The app needs one secret string to lock its cookies with. Generate it once and
never change it — changing it later signs everybody out and makes saved keys
unreadable.

1. Open **Terminal** on your Mac.
2. Paste this and press return:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

3. Copy the line it prints into the same note. It is long and looks like
   nonsense. That is correct.

**✅ Done when:** you have a long random line saved.

---

## Step 3 — Make the new Railway project

1. Go to **railway.app** and sign in.
2. You will see your existing project — the one running your cleaning company.
   **Do not open it.** We are not touching it.
3. Click **New Project** (top right).
4. Choose **Deploy from GitHub repo**.
5. Pick this repository from the list.
6. Railway will start building. Let it.
7. When it appears, click on the service (the box with the repo name).
8. Go to the **Settings** tab.
9. Find **Source**. Set the branch to **`main`**.
10. Still in Settings, find **Networking**. We come back here in Step 6.

Now give it a database:

11. Back on the project canvas, click **+ New**.
12. Choose **Database** → **Add PostgreSQL**.
13. Wait until it says **Online**.

Railway connects the database to the app by itself. You do not have to copy
anything.

⚠️ You will see a **Remove** option near the database. That deletes it. You do
not need it at any point.

**✅ Done when:** the project shows two boxes — your app and a Postgres
database — and the database says **Online**.

---

## Step 4 — Type in the settings

1. Click your **app** service (not the database).
2. Go to the **Variables** tab.
3. Click **+ New Variable** and add each of these, one at a time.

| Name | Value | What it does |
|---|---|---|
| `BASE_DOMAIN` | `akyehq.com` | **The main switch.** Without it there is no multi-company mode and no signup at all. |
| `SIGNUPS_OPEN` | `0` | Keeps the door shut while you test. |
| `SECRET_KEY` | the long random line from Step 2 | Locks the cookies. |
| `CRM_BASE` | `https://akyehq.com` | The product's own address. |
| `STRIPE_PLATFORM_SECRET_KEY` | your `sk_test_…` key | Takes subscription money. |
| `STRIPE_PRICE_PRO` | the Pro `price_…` ID | |
| `STRIPE_PRICE_SCALE` | the Scale `price_…` ID | |
| `FROM_EMAIL` | `support@akyehq.com` | The address emails come from. |

Leave `STRIPE_PLATFORM_WEBHOOK_SECRET` out for now — it does not exist yet. We
add it in Step 7.

⚠️ **Do not add `ADMIN_USER` or `ADMIN_PASS`.** See the rules at the top.

4. Railway will redeploy on its own after you save. That is fine.

**✅ Done when:** the Variables list shows `BASE_DOMAIN` and `SIGNUPS_OPEN`
set to `0`.

---

## Step 5 — Check it started

1. Go to the **Deployments** tab.
2. The newest one should say **Success**. If it says **Failed**, click it, copy
   the last twenty lines of the log, and send me those. Do not retry blindly.
3. Click the deployment, then find the address Railway gave you. It looks like
   `something.up.railway.app`.
4. Open `something.up.railway.app/version` in your browser.

You should see a small block of text with a version in it. That means the app
is alive.

**✅ Done when:** `/version` shows you something instead of an error.

---

## Step 6 — Point the domain at it

Every company gets its own address, like `acme.akyehq.com`. That needs a
**wildcard** record — one entry that covers every company you will ever have.

**In Railway:**

1. Your app service → **Settings** → **Networking** → **Custom Domain**.
2. Type `akyehq.com` and add it. Railway shows you a target address to point at.
   Copy it.
3. Click **+ Custom Domain** again. Type `*.akyehq.com` and add it. Copy that
   target too. (It is usually the same one.)

**At your domain registrar** (wherever you bought akyehq.com):

4. Find the **DNS** page.
5. ⚠️ **Careful here.** You already have an **MX** record pointing at Microsoft
   for `support@akyehq.com`. **Do not delete or change it.** We are only adding
   records, not removing any.
6. Add these two:

```
Type    Name    Value
CNAME   @       <the target Railway gave you>
CNAME   *       <the same target>
```

Some registrars refuse a CNAME on `@`. If yours does, look for **ALIAS** or
**ANAME** and use that for `@` instead. The `*` one is a normal CNAME either way.

7. Save, and wait. Usually a few minutes. Sometimes a few hours.

**✅ Done when:** `https://akyehq.com` loads the Akye website with a padlock in
the address bar, **and** `https://testco.akyehq.com` also loads something. It
does not matter what the second one shows yet — what matters is that it
resolves and has a padlock.

If the padlock is missing or you get a certificate warning, wait longer before
telling me it is broken. Certificates can take a while after DNS moves.

---

## Step 7 — Tell Stripe where to send its messages

This is the part that actually changes what a customer is allowed to use.
Someone's browser landing back on your site after paying proves nothing — this
is the proof.

1. Stripe → **Developers** → **Webhooks** → **+ Add endpoint**.
2. Endpoint URL: `https://akyehq.com/api/stripe/webhook`
3. Under **Select events**, tick exactly these seven:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
4. Click **Add endpoint**.
5. On the page that appears, find **Signing secret** and click to reveal it. It
   starts `whsec_`. Copy it.
6. Back in Railway → app service → **Variables** → add:

| Name | Value |
|---|---|
| `STRIPE_PLATFORM_WEBHOOK_SECRET` | the `whsec_…` you just copied |

7. Let it redeploy.

**✅ Done when:** on Stripe's webhook page, **Send test webhook** comes back
with a **200**.

---

## Step 8 — Make one company that is yours, and walk it

Open the door just long enough to make a test company.

1. Railway → Variables → change `SIGNUPS_OPEN` to `1`. Let it redeploy.
2. Go to `https://akyehq.com/signup`.
3. Sign up as **Test Cleaning Co**, with the address `testco`.
4. You should land on `https://testco.akyehq.com`, already signed in, with a
   *Getting started* list.

Now walk the whole thing, ticking as you go:

- [ ] Set your prices
- [ ] Open your booking page and check it says your name and your prices
- [ ] Change your button colour in Settings → Business, and check the booking
      page changes
- [ ] Add a cleaner, add a customer, book a job
- [ ] Assign the job — the *Getting started* banner should go away
- [ ] **Open the cleaner's job link on a real phone.** Tap **Navigate**.
- [ ] Send a job out to the team and claim it from the phone
- [ ] Complete the checklist, clock in and out
- [ ] Check payroll shows what you set, not something else
- [ ] Try to open **Hiring** — it should send you to the upgrade page
- [ ] Upgrade to Pro with Stripe's test card `4242 4242 4242 4242`, any future
      expiry date, any three-digit code
- [ ] **Hiring should now open.** This is the moment billing is proven.
- [ ] The "Booking powered by Akye" line at the bottom of your booking page
      should now be gone

5. Set `SIGNUPS_OPEN` back to `0`.

**✅ Done when:** every box is ticked. If the upgrade did not unlock Hiring,
the webhook is not arriving — look at its delivery log in Stripe before going
any further.

---

## Step 9 — Prove two companies cannot see each other

The automated tests check this on every run. Do it once with your own eyes
anyway. It is the one failure that would end the product.

1. `SIGNUPS_OPEN=1` again.
2. Sign up a **second** company with the address `testtwo`.
3. In it, add a customer called **`SECOND COMPANY ONLY`**.
4. Go back to `testco.akyehq.com` and look at the customer list.

**✅ Done when:** `SECOND COMPANY ONLY` is nowhere to be found.

**If you can see it, stop everything and tell me immediately.**

5. Set `SIGNUPS_OPEN` back to `0`.

---

## Step 10 — Back up the new database

This database will hold other companies' businesses, not just yours. It needs
the same protection your CRM already has.

1. Railway → the **new** Postgres → **Variables** → find `DATABASE_PUBLIC_URL`.
2. Copy it. ⚠️ **Straight into GitHub, not into a message.** It contains a
   password.
3. GitHub → this repository → **Settings** → **Secrets and variables** →
   **Actions**.
4. Add it as a new secret. Tell me what you named it and I will wire the backup
   to use it.

**✅ Done when:** the secret exists in GitHub.

---

## When you are done

Tell me which step you finished and anything that did not match what I said.
Then I will:

- Release the 21 commits to the new deployment
- Wire the backup to the new database
- Build custom domains for booking pages, which needs the live Railway API

---

## If something goes wrong

```bash
python3 release.py --rollback      # put the code back
python3 migrate.py status          # where the database is
python3 backup.py --list           # what backups exist
```

Every deployment reports what it is running at `/version`, without logging in.
Two things behaving differently is almost always two different releases.

**Errors report themselves.** Settings → Errors inside the CRM, and an email
the first time each fault happens. If something is broken, look there first —
it is probably already written down.

---

## Roughly what this costs

| | |
|---|---|
| Railway app + database | ~$20/month to start |
| Stripe | 2.9% + 30¢ per payment |
| Per extra customer | ~$1–3/month |

At $79/month that is about a 95% margin, which is the whole reason for one
database with a schema per company rather than a separate deployment each.
