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

2. **Check the account belongs to Yaa Mansa LLC.** The name at the top left
   may be a trading name rather than the company — Kids Party Profit System is
   a DBA of Yaa Mansa LLC, and that is fine. What matters is the legal entity
   underneath, because that is the company named on the terms of service.

   To be sure: **Settings** (the gear, top right) → **Business** → check the
   registered business name.

   ⚠️ **Before going live, check the statement descriptor** — Settings →
   Business → Public details. That short line is what appears on a customer's
   card statement. If it says the name of a different DBA, a cleaning company
   owner will see a charge they do not recognise and dispute it. Stripe can
   set a different descriptor per subscription, so this does not need a
   separate account. It does not matter in test mode; it matters the day real
   cards are charged.

3. **Get into test mode.** Stripe renamed this and where it lives depends on
   how old your account is:

   - **Newer accounts:** there is no "Test mode" switch. It is called a
     **Sandbox**. Click the business name at the top left; below the list of
     accounts there is a **Sandboxes** section. Open one, or create one.
   - **If that section is not there:** click **Developers** at the bottom left.
     The sandbox controls often live in that panel.
   - **Older accounts:** a **Test mode** toggle sits in the top right.
   - **Last resort:** type `dashboard.stripe.com/test/products` into the
     address bar. On older accounts the `/test/` puts you straight into test
     mode.

   Either way you are in the right place when the screen carries an obvious
   orange or yellow marking saying test or sandbox. Nothing you do there
   involves real money.

4. Left sidebar → **Product catalogue** (older accounts say **Products**).
5. Click **+ Add product**.
6. Name: `Pro`
7. Price: `79.00`, currency **USD**.
8. Under it, choose **Recurring**, and set the billing period to **Monthly**.
9. Click **Add product** to save.
10. Do steps 5–9 again, but name it `Scale` and price it `249.00`.
    This must match `entitlements.py`, which is what the software
    actually charges. It said `149.00` here for a while; following it
    would have set up every Scale customer $100/month short, and the
    first sign would have been money that never arrived.

Now collect three things. Keep them in a note on your computer — not in a
message to me.

11. Open the **Pro** product. Under **Pricing** there is a row with the price.
    On the right of that row is an ID starting with **`price_`**. Copy it.
    ⚠️ It is **not** the one starting `prod_`. That is the product ID and it
    will not work.
12. Do the same for **Scale**.
13. Left sidebar → **Developers** → **API keys**. Find **Secret key**. Click
    **Reveal test key**. Copy it. It starts `sk_test_`.

**✅ Done when:** you are in the Yaa Mansa LLC account, in test mode, and you
have two IDs starting `price_` and one key starting `sk_test_`.

⚠️ If your key starts `sk_live_` you are not in test mode. Go back to point 3.

---

## Step 2 — The app's secret key

The app needs one long random string to lock its cookies with.

**This is already done.** There is a file on your Desktop called
`AKYE-SECRET-KEY-delete-after-use.txt`. Open it, and it tells you what to do
with what is inside.

You need it in Step 4. **Delete the file once it is in Railway.**

⚠️ Generate it once and never change it. Changing it later signs everybody out
and makes every saved Stripe key unreadable.

⚠️ Never paste it into a chat, an email or a screenshot — not to me, not to
anybody.

<details>
<summary>If you ever need to make another one yourself</summary>

Open **Terminal** and paste this **one line only**:

    python3 -c "import secrets; print(secrets.token_urlsafe(48))"

⚠️ Copy the line starting `python3`. Do **not** copy any line made of three
backticks — that is formatting from this document, and pasting it leaves the
terminal stuck at a prompt that says `bquote>`. If that happens, press
**Control + C** and try again.

</details>

**✅ Done when:** you know where that file is.

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
9. Find **Source**. Set the branch to **`feature/tenancy`**.

   ⚠️ Not `main`, and not `stable`. This surprises people, so here is why:

   - `stable` is what **your cleaning company** runs. Never point anything new
     at it.
   - `main` is currently identical to `stable` — the old single-business CRM.
     All the multi-company work, the booking page and the new design are on
     `feature/tenancy`.
   - If you pointed this at `main`, it would build and start fine, `/version`
     in Step 5 would pass, DNS in Step 6 would work, and you would not find
     out anything was wrong until `/signup` gave you a 404 in Step 8.

   Once the product is proven online we will tidy the branch names. Until
   then, watching the branch the work is actually on is the honest setting.
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
| `CRM_BASE` | `https://www.akyehq.com` | The product's own address — **with the `www`**, because that is the host the site is actually served on. |
| `CANONICAL_HOST` | leave blank for now | See the note under Step 6. |
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
Type    Name                 Value
CNAME   www                  <the www target Railway gave>
TXT     _railway-verify.www  <the www verify string>
CNAME   *                    <the WILDCARD target — a different one>
CNAME   _acme-challenge      <…authorize.railwaydns.net>
TXT     _railway-verify      <the wildcard verify string>
```

The underscores are real. Names are short — GoDaddy appends the domain itself,
so `www`, not `www.akyehq.com`.

The TXT values are **truncated on screen**. Copy them from Railway rather than
typing what you can see, or verification silently never completes.

⚠️ `www` usually already exists at GoDaddy, pointing at `@`. **Edit** that row
rather than adding a second — two CNAMEs on one name is not allowed.

7. Save, and wait. Usually a few minutes. Sometimes a few hours.

**✅ Done when:** `https://akyehq.com` loads the Akye website with a padlock in
the address bar, **and** `https://testco.akyehq.com` also loads something. It
does not matter what the second one shows yet — what matters is that it
resolves and has a padlock.

If the padlock is missing or you get a certificate warning, wait longer before
telling me it is broken. Certificates can take a while after DNS moves.

### Check the apex on a real page, not just the homepage

Load **`https://akyehq.com/pricing`**, not `https://akyehq.com`.

A homepage that loads proves almost nothing. A registrar's forwarding service
will happily redirect `akyehq.com` → `www.akyehq.com` and answer **404 for every
other path** — the redirect is configured on the root only. That is what
happened here: the site looked fine, and `akyehq.com/pricing`, `/terms`,
`/privacy` and `/subprocessors` were all dead, which is precisely the set of
URLs the sitemap hands to Google.

- **If `/pricing` loads** — the apex reaches Railway. Good.
- **If `/pricing` 404s** — the apex is still on a forwarding service. Remove the
  forwarding record and add `akyehq.com` as a Custom Domain on the Railway
  service, alongside `*.akyehq.com`.

**Only once `/pricing` loads on the apex**, set `CANONICAL_HOST` to `akyehq.com`.
That makes `www` redirect to the apex, keeping the path, so the site has one
address instead of two copies of itself. Setting it before the apex works would
redirect the working site to a broken one — which is why it is blank by default
and every page just advertises whatever host served it.

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

## Step 11 — Email for the whole deployment

`akyehq.com` currently has **no email key at all**. Open
`www.akyehq.com/version` and it says so. That means no trial reminders, no
crash alerts, and no company on the platform can email its own customers
unless it connects its own account first — which is not a thing to ask a beta
tester to do.

Two parts, and only the first is urgent. The second can wait weeks.

### Part 1 — Sending. About 30 minutes, and it unblocks everything

This needs **no mailbox**. Proving you own the domain is a different thing
from having an inbox at it, and that is why this part can be done now.

**1. Add the domain to Resend**

Resend → **Domains** → **Add Domain** → type `akyehq.com` → pick the region
closest to you.

**2. Copy the DNS records it shows you**

Three of them, roughly: an `MX`, and two `TXT`. The values are unique to your
account — do not copy them from anywhere else.

⚠️ Notice that Resend's `MX` record is for **`send.akyehq.com`**, not for
`akyehq.com` itself. That is deliberate and it is what keeps this from
colliding with Part 2. Your future `support@akyehq.com` mailbox needs the MX
record at the *root*, and Resend is not taking it.

**3. Add them at GoDaddy**

Same screen where you added the Railway records: GoDaddy → **My Products** →
`akyehq.com` → **DNS** → **Add New Record**, one per row.

⚠️ **Do not delete or edit anything already there.** The `A`, `CNAME` and
wildcard records are what make the website and every company's subdomain work.
You are only adding.

⚠️ If GoDaddy warns you that a record **conflicts with an existing one** —
stop and tell me what it says. Two `SPF` records (`v=spf1 ...`) on the same
name break email for the whole domain, and the fix is to merge them into one,
not to keep both.

**4. Verify**

Back in Resend, press **Verify DNS Records**. It can be instant or it can take
an hour. Press it again later; nothing is lost by waiting.

**5. Make a key**

Resend → **API Keys** → **Create API Key** → name it `Akye product` →
**Sending access** only.

⚠️ It is shown **once**. Copy it straight into Railway in the next step, and
never into a message, an email, or a screenshot. If you lose it, delete it and
make another — that costs nothing.

**6. Set three variables in Railway**

Railway → the **Akye** project → the app service → **Variables**:

| Variable | Set it to |
|---|---|
| `RESEND_API_KEY` | the key you just made |
| `PRODUCT_FROM_EMAIL` | `support@akyehq.com` |
| `PRODUCT_SUPPORT_EMAIL` | **your Gmail address**, for now |

Using your Gmail for the third one is what makes this whole part possible
today. It is where alerts get *delivered*; it has nothing to do with what the
emails are sent *from*, and it costs nothing to change later.

**7. Redeploy, then check**

Open `www.akyehq.com/version`. It should now say:

```
"product_mail": "ok"
```

**8. Prove an email actually arrives**

```
python3 provisioning.py testmail your.name@gmail.com
```

Then go and look in that inbox. "Accepted" means Resend took it, not that it
landed — it can still bounce or go to spam, and that is the half no command
can tell you.

**✅ Part 1 is done when:** the test email is in your inbox and `/version`
says `ok`.

### Part 2 — Receiving. Whenever you like

A real `support@akyehq.com` that forwards to Gmail. Nothing depends on this;
Part 1 already delivers your alerts to Gmail directly. This is about what a
customer sees when they hit reply.

1. Set up email forwarding for `akyehq.com` with whichever provider you are
   using, forwarding `support@` to your Gmail.
2. It will give you `MX` records for the **root** domain. Add them at GoDaddy.
   They will not clash with the Resend ones from Part 1, which live on
   `send.akyehq.com`.
3. Send yourself a message at `support@akyehq.com` and check it arrives.
4. Only then, change `PRODUCT_SUPPORT_EMAIL` in Railway to
   `support@akyehq.com` and redeploy.

Step 4 last, and only after step 3. Pointing alerts at a mailbox that does not
receive yet is how you end up with a crash nobody hears about.

### Part 3 — A separate domain for outreach. Before the first real batch

Emails to New Leads (Console → Funnel → New Leads) are cold: those people
never asked for them, and that is the mail that draws spam complaints.
Mailbox providers judge a sender by its domain, so outreach gets a domain of
its own. A bad week there then cannot push receipts and trial reminders from
`akyehq.com` into junk.

1. **Register the domain.** Pick one that is recognisably Akye, such as
   `getakye.com` or `tryakye.com`, and use it only for outreach.
2. **Make the domain name go somewhere real.** At the registrar, forward the
   domain's website to `https://www.akyehq.com`. People check where a sender
   comes from, and a domain that shows nothing looks like spam.
3. **Add it to Resend.** Go to Resend → **Domains** → **Add Domain**, enter the
   new domain, and add the records it lists at *that* domain's registrar.
   Use the same Resend account and the same key; there is no new key to make.
   Then press **Verify DNS Records**.
4. **Add a DMARC record** to the new domain: a `TXT` record named `_dmarc`
   with the value `v=DMARC1; p=none;`. Gmail and Yahoo expect one from anyone
   sending in bulk.
5. **Set the variables in Railway** (on the app service, under **Variables**):

   | Variable | Set it to |
   |---|---|
   | `PRODUCT_OUTREACH_FROM_EMAIL` | e.g. `hello@getakye.com` |
   | `PRODUCT_OUTREACH_REPLY_TO` | optional. Leave it unset and replies go to `PRODUCT_SUPPORT_EMAIL` |

   Nothing else moves. Receipts, trial reminders and alerts keep sending from
   `PRODUCT_FROM_EMAIL`.
6. **Check it.** Open Console → Funnel → New Leads and pick **Email**. The box
   should say *Sent from hello@getakye.com*. Add yourself as a lead and send
   yourself one before sending to anyone else.
7. **Warm it up.** Start with a few dozen emails a day for the first two
   weeks, then raise the number. A new domain that sends 200 on day one gets
   filtered, however clean the list is.

---

## Step 12 — Turn on the trial emails

The countdown in the banner is only ever seen by somebody who logs in. The
person the trial is really aimed at — signed up on a Tuesday, got busy, has
not been back — never sees it. These four emails are what reaches them:

| When | What it says |
|---|---|
| Day 7, not started | you have not begun, and here is the one thing that starts it |
| Day 21, not started | the last useful reminder before the door closes |
| 3 days left, running | the one about money |
| The day it lapses | what changed, what did not, and that nothing was deleted |

Four in a month. Not a drip campaign — a cleaning company that wanted software
does not want a drip campaign.

1. Go to **cron-job.org** (the same place as your other jobs).
2. **Create cronjob**.
3. URL: `https://www.akyehq.com/api/trial-nudges`
4. Method: **POST**
5. Header: `X-Api-Key` set to the same `REMINDER_API_KEY` your other jobs use.
6. Schedule: **once a day**, around 9am your time. Not hourly — every nudge is
   recorded so it can never be sent twice, but hourly would fire "3 days left"
   at 2am the moment the threshold ticked over.

**Before you switch it on**, see exactly who would get what — this sends
nothing:

```
python3 provisioning.py nudges --dry-run
```

Run it against the live database and read the list. It should be short and it
should make sense. Drop `--dry-run` to actually send.

**✅ Done when:** the dry run prints a list you agree with, and the cron is
saved.

---

## Step 13 — Payments belong to each company

On hosted Akye a company takes payments **only** through the Stripe keys saved
on its own **Settings → Connections** page. There is no fallback of any kind:
the `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` and `STRIPE_WEBHOOK_SECRET`
variables in Railway are never used for a company. A company that has not
saved keys shows Stripe as not connected, rather than quietly taking its
customers' money, and paying its cleaners, through somebody else's account.

Akye and Dazzle & Shine share one Stripe account. That stays true, but in the
open: Dazzle & Shine has that account's keys saved on its own Connections page,
where anybody looking can see which account it uses.

**Before this release goes out:**

1. Sign in to Dazzle & Shine, go to **Settings → Connections**, and look at
   Stripe. If it says *Currently coming from your hosting settings*, it is
   using the Railway key today and would lose payments on release.
2. Paste the shared account's keys into that page yourself (the secret key,
   the publishable key, and the webhook signing secret if it shows one) and
   save. Never paste them into a chat or an email.
3. Do the same check for any other live company. Each must have its **own**
   keys saved, or show *not connected* on purpose.
4. After the release, open Dazzle & Shine's booking page and check the payment
   form loads.
5. Once every company shows *Saved*, delete `STRIPE_SECRET_KEY`,
   `STRIPE_PUBLISHABLE_KEY` and `STRIPE_WEBHOOK_SECRET` from Railway. Nothing
   on hosted Akye reads them any more.

Your own Akye subscription billing is untouched: it uses
`STRIPE_PLATFORM_SECRET_KEY` and `STRIPE_PLATFORM_WEBHOOK_SECRET`, not these.

**✅ Done when:** Dazzle & Shine shows Stripe as *Saved*, and its booking page
takes a payment.

---

## Step 14 — Move the hourly charging clock off GitHub

**Why.** The hourly job that charges outstanding balances is scheduled as a
GitHub Actions workflow. GitHub drops scheduled runs under load and promises no
delivery: on 7 October 2026 it was set to run hourly and ran about four times.
A balance still gets charged the same day, because the next run picks it up, so
nothing is lost today — but a clock that silently runs a sixth as often as it
says is not a clock to put real money on.

### Read this before you click anything

**This is a new service, not a setting on the Akye service.** Railway cron runs
the service's *own start command* on the schedule, and the service has to exit
when it is finished. The Akye service runs gunicorn, which never exits. Putting
a cron schedule on it would mean "run the website on a timetable": the first run
would never finish, every later run would be skipped, and you would be gambling
the site on it. The clock gets its own service, sharing the repo and the
database.

**Do these in order.** Steps 1–2 make overlap safe and must come first. Steps
3–8 add a second clock, which is harmless once step 1 is live. Step 10 removes
the old clock. Never remove the old clock first, or there is a window with no
clock at all.

1. **Merge and deploy the double-charge guard** (`fix/charge-balances-no-double-run`,
   PR #61). Two clocks running at once would otherwise charge the same card
   twice — see `_one_charge_run_at_a_time` in `blueprints/api.py`.
2. **Check it is actually live** before going on: `https://www.akyehq.com/version`
   should report a `build` matching the merge. A guard that is merged but not
   deployed is not a guard.
3. **Railway → the Akye project → `+ New` → `GitHub Repo` → `dazzle-shine-crm`.**
   This creates a second service in the same project.
4. **That new service → Settings → Source → Branch: `akye-stable`.** The same
   branch the Akye service serves, so the clock and the app are never different
   code.
5. **Settings → Deploy → Custom Start Command:**

   ```
   python scheduler.py --cadence hourly
   ```

   There is no separate command box for a cron job — the start command *is* what
   the schedule runs. `--cadence hourly` resolves to exactly one job,
   `charge-balances`; the eight daily jobs are untouched.
6. **Settings → Deploy → Cron Schedule:** `5 * * * *`

   Railway's minimum gap is 5 minutes, so hourly is well within it. Schedules
   are UTC, which does not matter here: each business's charge timing comes from
   its own time zone (`scheduling.local_now`), not the server's.
7. **Settings → Networking: add no domain.** It serves nothing. If Railway has
   generated one, remove it.
8. **Variables.** Add three:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | A reference to the same Postgres service the Akye service uses — pick it from Railway's variable picker rather than pasting the string. |
   | `BASE_DOMAIN` | `akyehq.com` |
   | `REMINDER_API_KEY` | The same value the Akye service has. A different one makes every call come back 403, which looks exactly like nothing running. |

   Nothing else. The scheduler reads only these, and falls back from
   `AKYE_DATABASE_URL` to `DATABASE_URL` on its own.
9. **Watch one run.** Deploy, then open the service's logs. A good run prints
   `N companies × 1 job` and a line per company. A company that has not chosen
   automatic collection prints `turned off by this business` — correct, not a
   fault. The script exits non-zero if any company failed, so a red cron
   execution in Railway means a real failure rather than a dropped run.
10. **Let both clocks run for a day, then remove the old one.** They cannot
    collide: whichever arrives second is told another run is in progress and
    does nothing, so seeing that occasionally in the logs is the guard working.
    When you are satisfied, delete `- cron: '5 * * * *'` and the comment above
    it from `.github/workflows/automations.yml`, keeping `- cron: '0 22 * * *'`
    — the daily jobs are reminders and digests, where a missed run costs nothing
    the next day does not fix.

    That workflow only runs from the default branch, so the change has to land
    there. See **The third branch choice** in `RELEASING.md`.

**✅ Done when:** Railway shows an hourly cron execution succeeding on its own
service, the Akye service is still serving the website normally, and
`.github/workflows/automations.yml` on the default branch has one `cron:` line
left.

**Cost:** a cron service bills only while it runs. The hourly job takes about
ten seconds for twelve companies, so this is a few minutes of compute a day.

---

## Other settings this release adds

All optional. The defaults are what you want on the live product.

| Variable | Default | What it does |
|---|---|---|
| `WEB_CONCURRENCY` | `3` | Web workers (see `gunicorn.conf.py`). Raise once memory shows room. |
| `GUNICORN_TIMEOUT` | `60` | Seconds before a request is cut off. |
| `CONSOLE_REQUIRE_2FA` | on in production | `0` lets console logins skip two-factor. Leave it on. |
| `SIGNUP_LIMITS` | on in production | `0` turns off the per-address and daily signup limits. |
| `SIGNUP_DAILY_CAP` | `50` | Most new companies opened in 24 hours. |

---

## Settings reference

These are the settings the code reads that the steps above do not cover. Most
are optional, and Railway sets a few itself.

**Connections Akye provides to every company.** On hosted Akye every company
uses these master accounts. A company cannot see the values on its Connections
page or replace them, and any copy it saved earlier is ignored. Stripe is the
exception: each company connects its own, and it never falls back (Step 13).
On a single-business install these are simply the business's own keys.

| Variable | What it does |
|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE` | Texting for companies that have not connected their own Twilio. |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | Job photos, and the account applicants' interview videos upload to. With no cloud name, applicants see "not set up yet" instead of a broken recorder. |
| `CLOUDINARY_UPLOAD_PRESET` | The unsigned upload preset interview videos use. Default `interviews`; create it once on Akye's master Cloudinary account. |
| `GOOGLE_PLACES_API_KEY` | The lead finder. |

**Akye itself, the product.** These are never used for a cleaning company's own
messages.

| Variable | What it does |
|---|---|
| `PRODUCT_NAME`, `PRODUCT_TAGLINE` | Name and tagline on the marketing site. Default `Akye`. |
| `PRODUCT_LEGAL_ENTITY`, `PRODUCT_LEGAL_ADDRESS` | Company name and postal address on Terms, Privacy and every outreach email (CAN-SPAM). Set both. |
| `PRODUCT_RESEND_API_KEY` | Email sent as Akye: console outreach, trial emails, directory invites. |
| `PRODUCT_TWILIO_ACCOUNT_SID`, `PRODUCT_TWILIO_AUTH_TOKEN`, `PRODUCT_TWILIO_PHONE` | Akye's own number for console texts to leads, and the STOP/START webhook. These are separate from `TWILIO_*`, so Akye never pitches from a company's number. |
| `PRODUCT_HOST` | Where the scheduler calls the product's own jobs. Default `www.<BASE_DOMAIN>`. |
| `LEGAL_UPDATED`, `SECURITY_UPDATED` | The "last updated" date on the legal and security pages. Change it when you change the text. |
| `ALLOWED_FORM_ORIGINS` | Other sites, comma separated, allowed to post forms to the app, such as the getakye.com directory's claim form. The default is `getakye.com,www.getakye.com,getakye.netlify.app`; setting this replaces it. |
| `ALLOWED_ORIGINS` | Extra sites, comma separated, allowed to call the booking API from a browser. Each company's own website is allowed automatically. |

**Nana, the assistant, and her voice.**

| Variable | Default | What it does |
|---|---|---|
| `ASSISTANT_MODEL` | `anthropic/claude-haiku-4.5` | Model for lookups, through OpenRouter. |
| `ASSISTANT_THINK_MODEL` | `openai/gpt-5-mini` | Model for advice questions. |
| `ASSISTANT_MONTHLY_LIMIT` | `300` | Questions per company per month. |
| `ASSISTANT_MAX_STEPS` | `6` | Most lookups per question. |
| `OPENAI_API_KEY` | none | Optional. Speech goes straight to OpenAI when set, otherwise through OpenRouter. |
| `SPEECH_MODEL`, `SPEECH_VOICE`, `SPEECH_MANNER` | `gpt-4o-mini-tts`, `sage` | The speaking voice. |
| `SPEECH_MODELS_ROUTER` | a list | Voice models tried in order through OpenRouter. |
| `SPEECH_CAP_CHARS` | `60000` | Characters of speech per company per month. |

**Single-business installs only.** On hosted Akye each company sets these in its
own Settings, so leave them blank there.

| Variable | What it does |
|---|---|
| `BUSINESS_NAME`, `BUSINESS_PHONE`, `WEBSITE`, `OWNER_EMAIL`, `REPLY_TO_EMAIL` | The business's details, if not saved in Settings. |
| `BUSINESS_TZ` | Its time zone. Default Eastern. |
| `WORKER_MODEL` | `contractor` (1099) or `employee` (W-2), if not chosen in Settings. |

**Operations, backups and scripts.**

| Variable | What it does |
|---|---|
| `AKYE_DATABASE_URL` | GitHub Actions secret for the scheduler. Railway's public Postgres URL, used to read the company list. |
| `BACKUP_DIR`, `BACKUP_KEEP_DAYS`, `BACKUP_VERIFY_URL` | Where backups go, how long they are kept (default 30 days), and the scratch Postgres a restore is checked against. |
| `DEMO_CITY` | The city the demo company is set in. |
| `SOURCE_DATABASE_URL`, `TENANT_SLUG` | Arguments to `adopt_tenant.py` and `seed_huntsville_pricing.py` when run by hand. |
| `FLASK_ENV` | `development` turns off the production protections locally. Never set it on Railway. |
| `FLASK_SECRET_KEY` | Older name for `SECRET_KEY`. Only read when `SECRET_KEY` is missing. |

**Set by Railway or the release script. Do not set these yourself:**
`RAILWAY_ENVIRONMENT`, `RAILWAY_PROJECT_ID`, `RAILWAY_GIT_BRANCH`,
`RAILWAY_GIT_COMMIT_SHA`, `SOURCE_COMMIT`, `RELEASE_SHA`, `RELEASE_TAG`,
`RELEASE_HANDED_OVER`.

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
