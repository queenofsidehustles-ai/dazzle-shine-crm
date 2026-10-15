# Setup videos — scripts

Six short Looms. Record them in the **demo company** (akyehq.com/demo), not a
real account, so no real customer's name or address is ever on screen.

Talk like one cleaning business owner showing another. Short sentences. You
don't need to say who built it, and you don't need to say "it's easy." Just
show it working.

After recording, paste each Loom share link into Railway as the variable
named under the title. Each video then appears by itself in the app and in
the emails. No code change and no redeploy needed beyond Railway's restart.

---

## 1. What it looks like once it's set up (60 sec)
`AKYE_VIDEO_OVERVIEW` · shows above the signup form

The point of this one is how a job reaches the team: it goes out to everyone,
the first to claim it gets it, and only then do they see the address.

**Show:** today's jobs → open the job that's open to claim (in the demo,
Leticia Ashford's 2:30) → Send to team → the text a cleaner gets → the claim
page with no address → tap Claim → full address, time, checklist and
directions → a paid invoice.

**Say:**
> This is a cleaning business running on Akye.
> Here's a job that needs a cleaner. One tap, and it goes out to the whole team.
> Every cleaner gets a text with the bedrooms, bathrooms, what it pays and the area. No address yet.
> First one to claim it gets it, kind of like Uber for your cleaning jobs.
> Once she claims it, the full address, time and checklist show up, with directions.
> Everyone else sees it's been taken. No group chat, no calling around.
> And when the job's done, you get paid.
> Setting yours up takes a few minutes. The form is right below.

**Recording the cleaner's side in the demo.** The demo company never sends a
real text (demo_guard.py), so:

1. After Send to team, open the **Sent Log**. Every text the team would have
   received is there, word for word. It is labeled "not sent" because it is
   the demo, so zoom in on the message itself.
2. Copy the claim link from that text into a second browser window narrowed
   to phone width (about 390 wide; Chrome: right-click → Inspect → the phone
   icon). Show the page without the address, tap **Claim**, show the address
   appear.
3. Ask for the demo to be rebuilt afterwards, because claiming changes it for
   the next visitor (DEMO.md).

Never record this in a real company: Send to team texts every real cleaner.

---

## 2. Sign up and find your address (60 sec)
`AKYE_VIDEO_SIGNUP` · in the welcome email

**Show:** signup form → typing the business name and watching the web
address fill in → landing on Getting Started → the welcome email with the
address and code.

**Say:**
> Type your business name, and your web address fills itself in. That's the
> link your cleaners will see on every job, so pick one you like. It can't
> change later.
> Add your name, your email and a password, tick the box, and you're in.
> Check your email. You'll get your address in writing, plus a six-digit code.
> Type the code on your dashboard, or tap the button in the email. That
> just tells us we have the right address.
> Bookmark your link. That's how you get back in.

---

## 3. Add a cleaner and a customer (90 sec)
`AKYE_VIDEO_TEAM_AND_CUSTOMER` · day-1 email, Getting Started steps

**Show:** Getting Started → Add a cleaner (name, phone) → save → Add a
customer (name, address, phone) → save → the trial banner switching to a
countdown.

**Say:**
> Two things get you going: one cleaner and one customer.
> If you're still cleaning yourself, add yourself. That counts.
> Name and phone number is enough for now. The phone number is where job
> details get texted.
> Now a customer. Pick one you already clean for. Real is better than made up,
> because you'll see exactly how it works for your business.
> Name, address, phone. Save.
> See the banner? That's what starts your 14 days with everything switched on.

---

## 4. Your booking page, and where to put the link (75 sec)
`AKYE_VIDEO_BOOKING_PAGE` · day-2 email, Settings → Booking page

**Show:** Settings → Booking page → copy the link → open it in a new tab →
pick a service, see the price → back to Facebook, paste into the page's bio.

**Say:**
> You already have a booking page. It came with your account.
> Customers pick what they want, see your price, and book a time. No back and
> forth over text.
> Copy the link here.
> Now put it where people already find you: your Facebook page, your Instagram
> bio, your Google profile.
> And the next time somebody asks "how much do you charge?", send them the link.
> When somebody books, it shows up in your calendar and we'll let you know.

---

## 5. Book a job and send it to a cleaner (90 sec)
`AKYE_VIDEO_BOOK_JOB` · the "your 14 days just started" email, Getting Started

**Show:** Bookings → New → pick the customer → service, date, time → assign
the cleaner → save → the cleaner's text on a phone.

**Say:**
> This is the moment it starts being useful.
> New booking. Pick your customer, the service, the day and the time.
> The price fills in from your prices.
> Now assign it to a cleaner and save.
> Your cleaner gets a text with the address, the time and the checklist.
> No more screenshots of addresses in a group chat.

---

## 6. Bring your customer list over (75 sec)
`AKYE_VIDEO_MIGRATION` · day-5 email, the Migration page

**Show:** a simple spreadsheet (name, phone, email, address) → Migration
page → upload → the customers list filled in.

**Say:**
> If your customers live in a notebook, a spreadsheet, or another app, you don't
> have to type them in one at a time.
> Put them in a spreadsheet like this: name, phone, email, address.
> Go to Migration, and upload it.
> And there they are, ready to book.
> You can do the same with your team.

---

## Recording tips

- Keep each under 90 seconds. If a take runs long, cut a sentence rather than
  talking faster.
- Camera bubble on is good. It feels like a person, not a product tour.
- Record on a laptop at normal zoom so text is readable on a phone.
- Don't worry about one perfect take. Loom lets you trim the start and end.
