# Getting your CRM set up — what we need from you

Welcome. This walks through the accounts you'll need to open and the details to
send over. Most of it is form-filling. Set aside about an hour, plus some waiting
time for two approvals that aren't instant.

**Start with steps 1 and 2 today**, even if you do nothing else this week. Both
involve someone else approving you, and that approval takes days rather than
minutes. Everything else can be done in an afternoon once they clear.

You don't need to be technical for any of this. If a step asks for something you
don't have, say so rather than guessing — a wrong number here is much easier to
fix now than after your customers are using it.

---

## Step 1 — Stripe, for taking payments *(start today)*

This is how your customers pay you by card, and how you pay your cleaners.

**It has to be your own Stripe account, in your business's name.** Your customers'
money goes straight from their card into your bank account. It never passes
through anyone else.

1. Go to **stripe.com** and create an account.
2. Complete the business verification. You'll need:
   - Your legal business name and address
   - Your **EIN** (or SSN if you're a sole proprietor)
   - Your **business bank account** details, for payouts
3. Turn on **Stripe Connect** — this is what lets you pay cleaners directly from
   the CRM. In your Stripe dashboard: **Settings → Connect → Get started**.

> **Why it can take a few days:** Stripe reviews new businesses before letting
> them accept live payments. You can be approved in minutes or it can take
> several days if they ask for documents. Start it now so it isn't what's holding
> you up later.

**How to give us access — don't email us your keys.** In Stripe, go to
**Settings → Team → New member** and invite us as a **Developer**. That lets us
wire up your CRM without you ever sending a password or key over email, and you
can remove the access with one click whenever you like.

---

## Step 2 — Texting, so your cleaners get their jobs *(start today)*

The CRM texts your cleaners when they get a job, and texts your customers their
appointment reminders and payment links. That needs a business texting number.

1. Go to **twilio.com** and create an account.
2. Buy a phone number with SMS enabled, in your area code.
3. Complete **A2P 10DLC registration**. Twilio will prompt you. You'll need your
   EIN and your business details.

> **This is the one that catches people out.** In the US, businesses aren't
> allowed to send texts from an unregistered number — the carriers block them.
> Registration usually takes **3 to 7 days** and sometimes longer. Your texts
> will silently fail to arrive until it clears, so please start it early.
>
> If you'd rather not deal with this, we can turn texting off and run on email
> only to begin with. Your cleaners would get job offers by email instead. It
> works, but texts get read faster.

---

## Step 3 — Email, so messages come from your business

Your customers get booking confirmations, invoices and receipts by email. These
should arrive from your business, not a generic address.

1. Go to **resend.com** and create an account (there's a free tier that's plenty
   to start).
2. Add your domain — e.g. `yourcleaningcompany.com`.
3. Resend gives you a few **DNS records** to add. If someone else manages your
   website or domain, forward those records to them and ask them to add them.
   That's all they need to do.

**Haven't got a domain?** Not a blocker. We'll start you on a temporary address
and switch it over whenever you're ready. Your emails will still say your
business name on them.

---

## Step 4 — Your web address

You've got three options:

| Option | What your CRM address looks like | Cost |
|---|---|---|
| We give you one | `yourcompany.up.railway.app` | Free |
| A subdomain of your site | `app.yourcleaningcompany.com` | Free if you own the domain |
| A new domain | `yourcompanycrm.com` | ~$12/year |

Most people start with the free one and move later. Moving is easy and doesn't
break anything.

---

## Step 5 — Send us your business details

Just reply with these. They go on your invoices, your quotes and every email your
customers receive, so send them **exactly as you want customers to see them**.

- [ ] Business name, spelled how you want it to appear
- [ ] Business phone number
- [ ] The email address you want customers to reply to
- [ ] Business address, city, state, ZIP
- [ ] Your website, if you have one
- [ ] Your logo and brand colours, if you have them *(optional — we'll use
      something clean and neutral until you do)*
- [ ] Your Google review link, if you have a Google Business listing *(optional)*

**Do you sell commercial cleaning under a different name?** Some companies trade
as one name for homes and another for offices. If you do, send both names. If you
trade under one name, ignore this — everything goes out under the one name.

---

## Step 6 — Send us your prices

This is the part worth taking your time over. The CRM quotes jobs automatically
from these numbers, so what you send is what your customers will be charged.

- [ ] **What you charge**, by service and home size. Whatever form you have it in
      is fine — a spreadsheet, a screenshot, a photo of a notebook page. We'll
      turn it into the pricing table.
  - Standard clean
  - Deep clean
  - Move-in / move-out
  - Recurring (weekly, every two weeks, monthly) and any discount you give
- [ ] **Your add-on prices** — inside the oven, inside the fridge, interior
      windows, inside cabinets, laundry, anything else you offer
- [ ] **What you pay your cleaners.** An hourly rate is what the CRM works from.
      If you currently pay a percentage of the job price, tell us what percentage
      and we'll help you work out the equivalent hourly rate.
- [ ] **Your minimum job price**, if you have one
- [ ] **Your service area** — the ZIP codes or towns you'll travel to

---

## Step 7 — Read the customer terms before you go live

Your CRM comes with a starter set of customer terms covering things like
cancellations, cards kept on file, and what happens when a job turns out to be
bigger than quoted.

**Please read them and tell us what to change.** They're a sensible starting
point, not legal advice, and they're *your* terms — your customers agree to them
when they book with you, and you're the one who has to stand behind them. If
you've got your own terms already, send those instead and we'll use them.

---

## What happens next

1. You work through the steps above.
2. We set up your CRM and put your prices and details in.
3. We test it end to end — a real booking, a $1 test payment into your Stripe, a
   job offer to a test phone — and check every bit of it lands with **you**.
4. We walk you through it together.
5. You add your cleaners and take your first real booking.

---

## Quick questions people ask

**Can I try it before it's connected to real money?**
Yes. Stripe has a test mode, and we can run you on that with fake card numbers
until you're happy. Nothing real gets charged.

**What happens to my data?**
It's yours, in a database only your CRM can reach. Nobody else's business is on
it, and you can have an export of everything whenever you ask.

**What if I want to stop?**
You take your data and go. No lock-in.

**Do I need to keep my current booking system running?**
Keep it until you've done a few real jobs on this one. There's no rush to switch
everything over on day one.

**Something looks wrong — what do I do?**
Tell us, with a screenshot if you can. Don't work around it quietly; if it's
wrong for you it's probably wrong for everyone, and we'd rather fix it properly.
