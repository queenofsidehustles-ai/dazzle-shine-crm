# Setting up your CRM

You'll get two things: a web address and a login. Everything else you do
yourself, from inside the CRM — your prices, your terms, your business details,
and connecting your own Stripe and phone number.

Log in and you'll see a **Setup** checklist showing what's still to do. Work down
it and you're ready. You don't need to ask anyone's permission or wait on anyone
to do a step for you.

**Two things are worth starting today**, because they involve someone else
approving you and that takes days rather than minutes: Stripe and texting. Read
on.

---

## Start these two today

### Stripe — so you can take card payments

**This must be your own Stripe account, in your business's name.** Your
customers' money goes from their card straight into your bank account. It never
passes through anybody else's hands.

1. Go to **stripe.com** and create an account.
2. Complete the business verification. Have ready:
   - Your legal business name and address
   - Your **EIN** (or SSN if you're a sole proprietor)
   - Your **business bank account** details, for payouts
3. Turn on **Stripe Connect** if you want to pay your cleaners from the CRM:
   **Settings → Connect → Get started**.

> Stripe reviews new businesses before letting them take live payments. Sometimes
> that's minutes; sometimes it's several days if they ask for documents. Start it
> now so it isn't what holds you up.

**You keep your own keys.** When Stripe approves you, go to **Developers → API
keys**, copy them, and paste them into your CRM under **Settings → Connections**.
Nobody else ever sees them, and you can change them yourself whenever you like.

### Texting — so your cleaners get their jobs

1. Go to **twilio.com** and create an account.
2. Buy a phone number with SMS enabled, in your area code.
3. Complete **A2P 10DLC registration** — Twilio will prompt you. You'll need your
   EIN and business details.
4. Copy your account SID, auth token and phone number into **Settings →
   Connections**.

> **This is the one that catches people out.** In the US, businesses can't send
> texts from an unregistered number — the carriers block them. Registration
> usually takes **3 to 7 days**. Until it clears your texts may look like they
> sent and simply never arrive.
>
> You can run on email only in the meantime. Your cleaners get job offers by
> email instead. It works; texts just get read faster.

---

## Then, in any order

### Email — so confirmations and invoices reach your customers

1. Go to **resend.com** and create an account (the free tier is plenty to start).
2. Add your domain, e.g. `yourcleaningcompany.com`. Resend gives you some **DNS
   records** — if someone else looks after your website, forward those to them.
3. Copy your API key into **Settings → Connections**.

Haven't got a domain? Not a blocker. Your emails will still carry your business
name, just from a temporary address, and you can switch later.

### Your business details

**Settings → Business.** Name, phone, email, address, website. These appear on
every invoice, quote and email your customers see, so enter them exactly as you
want customers to read them.

Also on that page:

- **Branding** — your tagline, colours, and your Google review link.
- **Commercial brand** — only if you sell commercial work under a *different*
  trading name. Leave it blank if you trade under one name.

### Your prices

**Settings → Pricing.** The CRM quotes jobs from these numbers, so what's here is
what your customers get charged. Set your service prices, your add-ons (oven,
fridge, windows, cabinets, laundry), your recurring discounts, and what you pay
your cleaners per hour.

Take your time on this one. It's the part that decides whether your jobs make
money.

### Your customer terms

**Settings → Business → Customer Terms.** These are editable, and they're
**yours** — your customers agree to them when they book, and you're the one who
has to stand behind them.

They ship as a practical starting draft covering cancellations, cards kept on
file, and what happens when a job turns out bigger than quoted. **They are not
legal advice.** Read them, change anything that doesn't match how you work, and
have an attorney look at them if you're relying on them in a real dispute. If
you already have your own terms, paste those in instead.

---

## Before your first real customer

Do all four. The third one is the one that costs real money if it's wrong.

- [ ] **Send a test text** — Settings → Connections → *Send a test text*. Does it
      arrive from your number?
- [ ] **Send a test email** — same page. Does it arrive with your business name
      on it?
- [ ] **Test your Stripe connection** — same page. **It tells you which business
      the money would go to. Check that name is yours.**
- [ ] **Walk a fake booking all the way through** — create it, send the
      confirmation, take a $1 payment, assign a cleaner, mark it complete. Much
      better to find a problem on a fake job than a real one.

Your Setup checklist tracks most of this for you and will tell you when nothing
essential is missing.

---

## Questions people ask

**Can I try it without charging anyone real money?**
Yes. Use your Stripe **test** keys and test card numbers. The Connections page
tells you plainly when you're in test mode. Swap in your live keys when ready.

**Who can see my Stripe keys?**
Only you. They're encrypted before they're stored, and the CRM never shows a
saved key back in full — just the first and last few characters so you can tell
which one is in there.

**What happens to my data?**
It's yours, in a database only your CRM can reach. No other business is on it.
Ask any time for an export of everything.

**Do I have to keep my old booking system running?**
Keep it until you've done a few real jobs on this one. There's no need to switch
everything on day one.

**Something looks wrong.**
Say so, with a screenshot if you can. Don't quietly work around it — if it's
wrong for you it's probably wrong for everyone, and it's better fixed properly.

**Can I change my prices/terms/branding later?**
All of it, any time, yourself. Nothing here is locked once it's set.
