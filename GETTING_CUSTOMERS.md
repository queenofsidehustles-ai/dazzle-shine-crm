# Getting the first ten

Written 2026-08-29. How to find, call, show and close the first ten cleaning
companies. Step 12 of `LAUNCH_RUNBOOK.md`.

**Do not advertise.** Ten hand-picked companies you have spoken to are worth
more than a thousand signups, because you need to learn what they actually do
all day, and you cannot learn that from a funnel.

---

## Your unfair advantage, and how to use it

Every competitor is software people who interviewed cleaning companies. **You
run one.** That is not a nice-to-have; it is the whole opening.

> *"I run a cleaning company here in Orlando. I built this because I had the
> same problem you do — I had cleaners, jobs, and no idea who I owed what on a
> Friday. Can I show you what I use?"*

Compare that to *"we've developed innovative CRM technology."* One gets a
conversation, the other gets a dial tone.

**Never pretend to be bigger than you are.** "I built this for my own company
and now five others use it" is more persuasive to a small business owner than
any amount of polish, because it means you will actually answer the phone.

---

## Who to call — and who not to

Thirty companies. Screen on all five before you dial:

| | Why it matters |
|---|---|
| **3–10 cleaners** | Fewer and there is no team pain. More and they will drag you into enterprise work you should not do yet. |
| **Evidence of a team** | An "our team" page, hiring ads, multiple vans, a lot of reviews. Somebody managing people. |
| **The owner still does the scheduling** | If they have an office manager, the pain is one step removed and the sale is two steps longer. |
| **50–200 recurring residential customers** | Enough repetition that the calendar matters. |
| **Paid per job or by percentage — not hourly W-2** | The pay engine, the 1099s and the W-9 flow are all built around per-job contractor pay. An hourly time-clock shop will fight the software the whole way. |

That last one is the filter nobody expects and it will save you two wasted
demos in ten. **Ask it early.**

### Where to actually find thirty

1. **Google Maps** — "house cleaning" in your metro, then the neighbouring
   ones. Skip anything with under 15 reviews (too small) or over 400 (too big).
2. **Indeed and Facebook job ads** — a company advertising for cleaners *right
   now* has hiring pain today. This is the single best signal on the page, and
   it is the one thing your software does that nobody else's does.
3. **Facebook groups** — "[Your state] cleaning business owners". Read, do not
   post. You are looking for people complaining about scheduling and no-shows.
4. **Their own websites** — a "Careers" or "Join our team" page means they hire
   often enough to have built one.

Keep it in a spreadsheet: company, owner name, phone, cleaner count guess,
hiring right now (y/n), source, and a notes column that will end up being the
most valuable column.

---

## The call

**You are not selling. You are asking five questions.** If you talk for more
than a third of the call, it went wrong.

### Opening

> *"Hi — is that [name]? My name's Monica, I run a cleaning company over in
> [area]. This isn't a sales call exactly — I built some software for my own
> business and I'm trying to find out if it's useful to anyone else. Have you
> got four minutes?"*

If no: *"No problem — better time?"* Then actually call back.

### The five questions

Ask them in this order. **Shut up after each one.**

1. **"How are you assigning cleaners to tomorrow's jobs?"**
   Listen for: a whiteboard, a group text, "I just know."
2. **"How do they know where they're going?"**
   Listen for: screenshots, texting the address every morning.
3. **"How do you work out what each cleaner gets paid?"**
   Listen for: a spreadsheet, "I add it up Sunday night."
   *This is the question that sells your software.*
4. **"How do you know your standard was actually followed?"**
   Listen for: "I trust them", or "I go back and check."
5. **"What happens when somebody calls out on a Tuesday morning?"**
   Listen for: a pause, then a long story. **That pause is the sale.**

### The close of the call

> *"That sounds a lot like where I was. Look — can I show you for ten minutes
> on a screen share? If it's not for you, tell me and I'll go away."*

**Aim for the demo, not the sale.** Nobody buys from a cold call.

### If they ask the price on the call

Answer plainly, then move on. Never dodge it:

> *"$79 a month. First ten companies get everything in the top plan at that
> price, locked for as long as they stay. But honestly, look at it first — it
> might not be for you."*

---

## The ten-minute demo

**Seed the demo company first.** Never show an empty dashboard.

```bash
python3 seed_demo.py
```

That gives you Sparkle Cleaning Services: six cleaners, twelve customers,
thirty-five jobs, one cancelled, three out to the team unclaimed, and five
weeks of money behind it. It is deliberately a bit messy, because a tidy demo
is a suspicious demo.

### One scenario, start to finish

> *"Mrs Johnson wants a deep clean Thursday at 10."*

| | | |
|---|---|---|
| 1 | Find Mrs Johnson in Clients — already a repeat customer | 20s |
| 2 | Book the deep clean, Thursday 10am | 60s |
| 3 | Calendar — there it is, next to Thursday's other work | 20s |
| 4 | Assign Maria and Jennifer | 30s |
| 5 | **Pick up your phone.** Open the link Maria just got | **2 min** |
| 6 | Walk the checklist. Add a photo. Sign. Complete | 90s |
| 7 | Back on the laptop — the job is done and Maria's pay is calculated | 60s |
| 8 | Payroll: what Maria gets Friday, no spreadsheet | 60s |
| 9 | Job economics: what the owner kept on that $280 | 60s |

**Step 5 is the demo.** Everything else is context. Hold up an actual phone, tap
an actual text, and show a real job page with the address, the entry notes, the
pay and the Navigate button.

Then say:

> *"She didn't download anything. She didn't make an account. Somebody you hire
> Tuesday can work Wednesday."*

**Then stop.** Do not open Settings. Do not show them the SOP library unless
they ask. You have shown the whole economic loop — customer, revenue, job,
labour, execution, pay, profit — and that is the product.

### Show hiring second, but only if they leaned in

If question 3 or 5 got a real reaction, show the hiring pipeline: an
application arriving, a video interview, an offer, an agreement signed. **No
competitor has this.** Thirty seconds is enough to plant it.

---

## What they will say, and what to say back

**"Can you add route optimisation / QuickBooks / an app for the cleaners?"**
> *"Not today. Let me ask you straight — without that, does what you've just
> seen solve enough of the scheduling and pay problem that you'd use it this
> week?"*

If **no prospect** will pay without feature X, X belongs in the product. If
**one** wants it, that is customisation. Those are completely different signals
and it is worth knowing which you have. **Do not promise to build anything.**

**"My cleaners aren't good with technology."**
> *"That's exactly why there's no app. They get a text and tap it. That's the
> whole thing."*

**"I already use [ZenMaid / Jobber / a spreadsheet]."**
> *"How do you work out cleaner pay in it?"* Then listen. If they say
> "spreadsheet", you have found the gap. If they are genuinely happy, thank them
> and move on — a customer you have to argue into buying churns in month two.

**"I need to think about it."**
> *"Of course. Can I ask what you'd be weighing up?"* Then be quiet.

**"It's too expensive."**
> *"What does one no-show cost you?"* Usually more than $79.

---

## When somebody says yes

**Do not send them a signup link and wish them luck.** For the first ten, you
set it up.

> *"Send me your customer list, your cleaners and next week's schedule. I'll
> have it in there by tomorrow."*

Import their clients, cleaners, prices, recurring jobs and pay rates yourself.
They should log in and think: *"my business is already in here."* That is a
completely different first day from *"welcome, start typing."*

You are also learning what the automated importer eventually has to handle.
Every hour of this is research.

### Then

- **Day 1** — owner training, 30 minutes, on their own real data
- **Day 2** — text their cleaners the first real job
- **Week 1** — check in daily. Fix only what stops work
- **Day 30** — sit down and ask three questions:
  1. *"If I turned this off tomorrow, what would you go back to?"*
  2. *"What would you miss most?"*
  3. *"What makes you hesitate about carrying on at $79?"*

Then charge month two. **The second payment matters more than the first.** The
first proves you can sell. The second begins to prove the product works.

---

## The number to watch

Not signups. Not logins.

**Jobs run through the platform per week.**

```
Week 1   12
Week 2   31
Week 3   46
Week 4   57
```

That is adoption. If a company doing 60 jobs a week puts 5 into your software,
something is wrong and no login count will tell you.

Everything is instrumented, so this is a query away, not a guess.

---

## The founding offer

**Founding Operator — first ten companies only**

Everything in Scale: scheduling, calendar, customers, recurring work, crew
assignment, per-job pay, checklists, SOP library, hiring pipeline, messaging,
commercial accounts. Unlimited cleaners, unlimited office logins, hosting
included.

**$79/month — the Pro price, but with everything in Scale included, locked for
as long as you stay a subscriber.** No setup fee, no contract, cancel any time.
**Direct founder onboarding — we load your customers, cleaners, prices and
upcoming jobs for you.**

> The founding perk is the *tier*, not a discount off the list price. Pro is
> $79 to everybody; founding customers get unlimited cleaners, the higher SMS
> allowance and the commercial features at that price. That is worth more to a
> growing company than $20 off, and it does not train the market to wait for a
> sale.

In return, ask for: honest feedback, permission to use anonymised numbers, a
testimonial once they have got value, and bug reports with enough detail to
reproduce.

**Do not promise unlimited custom development.** That is the one promise that
turns ten customers into ten different products.

---

## Stop and think at five

Once five unrelated companies are paying and actually running jobs through it,
stop selling for a week and look at what they have in common: which questions
they all asked, which step of setup they all got stuck on, which feature they
all ignored.

That is what turns hand-selling into something repeatable. Doing it at fifty
customers instead of five means fixing the same thing forty-five times over.
