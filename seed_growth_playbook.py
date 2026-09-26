"""Load the Akye freemium growth program into the console's Playbooks page.

Run once, the same way console_admin.py is run -- with the production
DATABASE_URL in the environment, since this writes to the control plane:

    railway run python3 seed_growth_playbook.py

Safe to run again: it skips any title that is already there rather than
making a duplicate. The one exception is a playbook still exactly as an
earlier run of this script wrote it (see UNTOUCHED), which is brought up to
date; anything edited or ticked in the console is left alone.
"""
import sys

import control_plane
import provisioning

DOCS = [
    ("Growth Program — Overview & Strategy", r"""As of 2026-09-24.

Fastest realistic path to 5,000 freemium signups for akyehq.com is an 8-week, multi-channel blitz built on a warm base you already have (Dazzle & Shine's own network and the Queen of Side Hustles audience) plus community seeding, creator partnerships, a stacked launch (Product Hunt + a founding-cohort offer), paid social, and a referral loop — not a single channel. Assumptions below are stated explicitly; flag anything that's wrong and the plan adjusts.

## Who the freemium user is

Akye is a white-labeled ops platform for home-services businesses (cleaning, landscaping, home maintenance) — bookings, payments, messaging, contractor payouts. The freemium user is a small home-services business owner (1–15 person crew) currently running on spreadsheets, texts, and 2–3 disconnected apps (Jobber/Housecall Pro's cheaper alternative, or nothing at all). This is the same buyer Dazzle & Shine Maids already sells to, and the same audience the Queen of Side Hustles brand already reaches — that overlap is the unfair advantage here, not a cold-start.

Where they already gather (in order of concentration):

| Channel | Why it's high-yield |
| --- | --- |
| Facebook groups ("Cleaning Business Owners," "Six Figure Cleaning Academy," "House Cleaning 6 & 7 Figures," local landscaping/handyman groups) | Tens of thousands of exactly this owner, self-identified, actively asking "what software do you use?" |
| Thumbtack / Angi / Google LSA pro communities | Same owners already paying per-lead — price-sensitive to a free tool that helps them close more of what they pay for |
| r/CleaningBusinessOwners, r/Landscaping, r/smallbusiness | Smaller but high-intent, searchable, evergreen traffic |
| TikTok/Instagram #cleaningbusiness and #sidehustle creators | Where this owner gets business advice; a few creators reach 100k+ of them directly |
| Nextdoor Business, local chambers of commerce | Lower volume, high trust, good for the first 100 |
| Dazzle & Shine's own client/contractor/VA network and past leads | Warm, zero-cost, fastest to activate in week 1 |

Assumption flagged: if Akye is meant to target a different vertical or geography than home services, the channel list above changes — everything else in this plan holds either way.

## 8-week plan and weekly targets

An 8-week blitz, not a slow drip — speed comes from running every channel in parallel from week 1 rather than sequencing them.

| Week | New signups target | Cumulative | Primary driver |
| --- | --- | --- | --- |
| 1 | 150 | 150 | Warm outreach: Dazzle & Shine's own client/contractor/VA list + Queen of Side Hustles audience |
| 2 | 350 | 500 | Community seeding live in 15+ Facebook/Reddit groups; founding-cohort offer announced |
| 3 | 900 | 1,400 | Product Hunt launch day + founding-cohort deadline (scarcity spike) |
| 4 | 900 | 2,300 | Creator partnerships go live (3–5 paid shoutouts/affiliate posts) |
| 5 | 800 | 3,100 | Paid social (Meta + TikTok) turns on, targeting validated by weeks 1–4 |
| 6 | 700 | 3,800 | Referral loop compounding (each new user's referral link live from signup) |
| 7 | 650 | 4,450 | Second wave of creator partnerships + retargeting |
| 8 | 550 | 5,000 | Final push: AppSumo-style lifetime-deal listing or a second scarcity deadline |

Why this order: the warm list and community seeding (weeks 1–2) exist to generate the reviews, testimonials, and case studies that make the Product Hunt launch and creator pitches (weeks 3–4) convert instead of falling flat. Paid ads only turn on in week 5, once organic channels have proven which message and which ICP segment actually converts — that avoids burning ad spend on an untested pitch, which is usually the single biggest time-waster in a "fastest possible" push.

(See the "90-Day Day-by-Day Plan" playbook for the same targets stretched into a literal day-by-day action list — used once the program was extended past 8 weeks.)

## Launch tactics, ranked by speed-to-signup

1. Warm network activation (day 1, zero cost). Personal texts/emails/DMs from Dazzle & Shine and Queen of Side Hustles to every past client, contractor, VA, and follower who runs or knows someone running a home-services business. Ask for a forward, not just a signup — each warm contact reaches 5–20 more.
2. Founding-cohort offer. "First 500 free forever on the Pro tier" (or similar) creates urgency without discounting the paid plan long-term. This is the single biggest lever for turning "I'll check it out later" into "I'm signing up today."
3. Community seeding. Daily, non-spammy participation (answering real questions, then mentioning Akye when it's the actual answer) in the 15–20 Facebook/Reddit groups identified above. One person posting from a personal account outperforms a business page post — groups penalize obvious promotion.
4. Product Hunt launch. Free, reaches an adjacent SaaS/tools audience, and gives a shareable "we launched" moment for every other channel to point at. Needs 2–3 weeks of hunter/upvoter outreach beforehand to not flop on launch day.
5. Creator/affiliate partnerships. 5–10 micro-creators (5k–150k followers) in the #cleaningbusiness / #sidehustle space, paid flat fee or rev-share per signup. Fastest paid channel to activate because these creators already have the exact audience — no targeting guesswork.
6. Paid social (Meta + TikTok). Turn on only after organic messaging is validated (week 5). Lookalike audience built from Dazzle & Shine's real client list is the fastest-converting seed audience available.
7. In-product referral loop. Every signup gets a referral link and an incentive (e.g., a free month of the next tier up, or an extra feature unlock) for each referral who activates. Compounds through weeks 6–8 rather than driving week-1 volume.
8. AppSumo-style lifetime-deal listing. Reaches a large deal-seeking SaaS-buyer audience fast, but takes 1–2 weeks of platform approval lead time — apply in week 1 so it's ready to fire in week 8 if the earlier channels are short of target.

## Outreach templates (short set — see the "Weekly Email/SMS Templates" playbook for the full week-by-week set)

Warm text/DM: "Hey [name] — quick one. I've been building a free tool that runs bookings, payments, and texting for cleaning/home-service businesses — no more spreadsheets. Giving away free-forever Pro access to the first 500 who sign up: [link]. Know anyone running a cleaning, lawn care, or handyman business who'd want it? Would mean a lot if you shared it."

Community group post (non-spammy, answer-first): "[Answering the actual question in the thread first.] ...For what it's worth, this is exactly the gap I built Akye to close — free tier is live if anyone wants to try it: [link]. Happy to answer questions here, not trying to hard-sell."

Creator/affiliate DM: "Hi [creator] — love your content for cleaning/home-service business owners. I run Akye, a free CRM/booking tool built specifically for this audience (not a generic SaaS retrofit). Would you be open to a paid post or an affiliate link ($X per signup or flat fee)? Happy to set you up with a free account first so it's not a cold pitch."

Cold email to public business contacts (CAN-SPAM compliant — see Guardrails below): Subject: "Free CRM built for [cleaning/landscaping] businesses like [Business Name]" — "Hi [Owner name], I found [Business Name] on Google/Yelp. I built Akye, a free ops platform for home-services businesses — bookings, payments, and customer texting in one place. No cost to try, no card required: [link]. If it's not useful, no worries — reply STOP and you won't hear from me again."

In-product referral ask (triggered on activation): "You're set up! Know another cleaning/lawn/handyman business owner who's still juggling spreadsheets? Share your link and you'll both get [incentive] when they sign up: [referral link]."

## Activation — making 5,000 a real number, not a vanity one

"Reach 5,000 freemium users" is easy to hit with a giveaway and hollow if most never open the product twice. Two things keep the number real:

- Define activation before launch, not after. Suggested bar: a signup counts as activated once they've created their business profile, added one real customer or job, and sent one message/invoice through the platform — not just "created an account." Track activation rate alongside raw signups every week (target: 40%+ activated by day 7).
- Use the product's own lifecycle automations on itself. lifecycle.py and automations.py already run lead-nurture drips, onboarding reminders, and win-back sequences for Akye's own customers — point that same machinery at freemium signups: an onboarding-reminder drip for anyone who signs up but doesn't finish setup within 48 hours, and a win-back nudge for accounts that go quiet. This is faster to stand up than a separate marketing-automation tool and doubles as a live demo of the product for the sales conversation ("the tool you're using to grow is the tool we're selling you").

### Measuring activation

Track it as a funnel, not a single percentage — the single number hides which step is actually losing people:

| Step | What it means | Target (by day 7) | If it's low, the problem is |
| --- | --- | --- | --- |
| Signed up | Created an account | 100% (baseline) | — |
| Profile completed | Business name, service area, logo/branding set | ≥80% | Signup form asked for too much, or the value of finishing isn't obvious |
| First customer/job added | At least one real customer or booking entered | ≥60% | The empty-state screen doesn't show what to do next |
| First message/invoice sent | Actually used the tool to communicate or bill someone | ≥40% (this is "activated") | The tool works but hasn't touched a real workflow yet — usually a trust or habit problem, not a features problem |
| Still active at day 30 | Logged in and used it again after the first week | ≥25% | Activation happened once but didn't become a habit — look at retention hooks (reminders, recurring jobs), not acquisition |

Report this funnel weekly, by signup cohort (the week they joined), not just as one rolling number — a cohort table shows whether activation is improving over time or just being diluted by a bigger top of funnel.

### Improving it, in order of impact

1. Cut steps before first value, don't add guidance around them. If profile completion or adding a first customer takes more than 2–3 minutes, that's the fix — shorten the form, pre-fill what you can (business name/address from Google Places, already integrated via places_finder.py), and let a customer be added with just a name and phone number, not a full record.
2. Put a real human on the first 100–500 signups. A personal welcome text within an hour of signup ("Hey [Name], saw you just joined Akye — want me to walk you through adding your first job?") converts far better than any automated email at this volume, and it's the fastest way to learn what's actually confusing people.
3. Reuse the product's own onboarding-reminder automation (lifecycle.py's onboarding_reminder_count logic, already built for contractor onboarding) for freemium signups who stall — a nudge at 24 hours and again at 72 hours if setup isn't finished, capped so it doesn't turn into nagging.
4. Make the founding-cohort status something to finish setup for, not just sign up for. E.g., "your free-forever spot is reserved, but locks in once you complete setup" turns activation into part of claiming the offer, not a separate ask.
5. Fix the single biggest drop-off step first, every week. The funnel table above will usually show one step losing far more people than the others — spend the week's product/onboarding attention there, not spread evenly across the whole funnel.

## Budget and tools

| Item | Cost | Notes |
| --- | --- | --- |
| Warm outreach + community seeding | $0 | Time only — the highest-ROI weeks in the plan |
| Product Hunt launch | $0 | Time to prep hunters/upvoters in weeks 1–2 |
| Founding-cohort / lifetime-deal offer | $0 direct cost | Cost is in future paid-tier revenue given away — worth it for the conversion lift |
| Creator/affiliate partnerships | $1,500–$3,000 | 5–10 micro-creators at flat fee or rev-share |
| Paid social (Meta + TikTok) | $3,000–$5,000 | Weeks 5–8 only, once messaging is validated |
| AppSumo-style listing | $0 upfront | Revenue share on any paid conversions; apply week 1 for week-8 readiness |
| Email/SMS sending (Resend, Twilio) | <$100/mo | Already integrated in the CRM (integrations.py) — reuse, don't rebuild |
| Total cash budget | ~$4,500–$8,000 | Front-load nothing — organic/warm channels prove the message before paid spend turns on |

Team needed: one owner driving outreach and community engagement daily (this can't be outsourced in week 1–2 — it needs a real, recognizable person), one person handling creator outreach/paid ads setup, and the existing dev/product side kept free to fix onboarding friction fast as activation data comes in.

Per-week breakdown (point estimate within the $4,500–$8,000 range above — totals $6,575; adjust up toward $8,000 by scaling the paid-social weeks if budget allows, or down toward $4,500 by trimming creator wave 2):

| Week | Spend this week | Cumulative | What it's for |
| --- | --- | --- | --- |
| 1 | $25 | $25 | Email/SMS tool only — warm outreach is free |
| 2 | $25 | $50 | Email/SMS tool only — community seeding is free |
| 3 | $25 | $75 | Email/SMS tool only — Product Hunt launch is free |
| 4 | $700 | $775 | Tool ($25) + creator wave 1 kickoff ($675) |
| 5 | $700 | $1,475 | Tool ($25) + creator wave 1 continued ($675) |
| 6 | $525 | $2,000 | Tool ($25) + paid social test budget ($500) |
| 7 | $725 | $2,725 | Tool ($25) + paid social, scaling what worked ($700) |
| 8 | $925 | $3,650 | Tool ($25) + paid social at validated budget ($900) |
| 9 | $975 | $4,625 | Tool ($25) + paid social continues ($950) |
| 10 | $975 | $5,600 | Tool ($25) + paid social continues ($950) |
| 11 | $475 | $6,075 | Tool ($25) + creator wave 2 ($450) |
| 12 | $475 | $6,550 | Tool ($25) + creator wave 2 ($450) |
| 13 | $25 | $6,575 | Tool only — AppSumo-style listing is revenue-share, no upfront cost |

Weeks 1–3 and 13 are near-zero cash cost by design — they lean on warm network, community, Product Hunt, and a revenue-share listing, not spend. Don't move paid-social spend earlier than week 6: it's deliberately gated on organic weeks proving which message converts, so it isn't spent finding that out the expensive way.

## Tracking and weekly cadence

Track per channel, per week, in one place:

| Metric | Why it matters |
| --- | --- |
| Signups by source (UTM per channel/template) | Tells you which of the 8 tactics is actually working — reallocate weekly, don't wait for week 8 |
| Activation rate (7-day) | The real health metric — see Activation section |
| Cost per activated user (paid channels only) | Compares creator spend vs. paid social spend on equal footing |
| Referral rate (% of activated users who send ≥1 referral) | Leading indicator for whether weeks 6–8 compound or flatten |
| Weekly cumulative vs. the 150/500/1,400/2,300/... target line | Catch a miss in week 2, not week 7 |

Cadence: a 30-minute weekly review against the target table in the 8-week plan above. Behind target two weeks running → pull forward a later-week tactic (paid ads, lifetime-deal listing) rather than waiting for its scheduled week.

## Guardrails

Speed at this volume is easy to get wrong in ways that get the account or the domain banned — which is slower than doing it right the first time:

- Cold email: only to publicly listed business contact info (a business's own "Contact Us" email, not scraped personal emails or a purchased list), include a real physical address and a working one-click unsubscribe (CAN-SPAM), and honor opt-outs immediately — the CRM's existing _unsub_url pattern in lifecycle.py is the right model to reuse.
- Facebook/Reddit groups: read each group's rules before posting; groups ban self-promotion fast, and a banned account can't be un-banned in week 6 when it matters most. Post from a real person, answer real questions, mention the product when it's genuinely the answer — not as a first post.
- Creator partnerships: written agreement, FTC-compliant #ad disclosure on every sponsored post.
- Paid ads: don't launch Meta/TikTok campaigns on a brand-new ad account at full budget — warm it up gradually or it gets flagged.
- Referral incentives: cap or fraud-check referral rewards so the loop can't be gamed with fake signups — especially once a cash or lifetime-deal incentive is attached.

## Risk and mitigation — if a channel underperforms

| Channel | Early warning sign | Mitigation / fallback |
| --- | --- | --- |
| Warm network (week 1) | Fewer than ~50 signups by end of day 2 despite outreach sent | Widen the ask beyond direct contacts — ask each warm contact to forward to 2–3 people by name, not just "share it"; personal asks convert far better than a broadcast |
| Community seeding (week 2+) | Posts get no engagement, or groups remove/flag them | Switch groups — not every group is a fit; lead with answering questions for a few days before any mention; if repeatedly flagged, stop and shift budget to creators/paid earlier |
| Product Hunt launch (week 3) | Launch day ends outside the top ~10 products, low upvote/comment count | Traffic and signups from PH are a bonus, not the plan's backbone — don't delay the founding-cohort deadline waiting for a better PH result; redirect the launch-day energy (comments, shares) straight into community posts and warm-list follow-up instead |
| Founding-cohort offer (week 3) | Signups don't spike in the 48–24 hour deadline window | The offer terms are the likely issue, not the channel — tighten the deadline further (24h instead of 48h) or sharpen the value stated ("free forever" vs "first 3 months free") and re-test on the next scarcity moment (week 13) rather than repeating the same offer |
| Creator partnerships (weeks 4–5, 11–12) | A creator's post drives under ~20 signups per 10k followers reached | Don't renew that creator for wave 2; before paying the next one, ask for their engagement rate and past sponsored-post performance, not just follower count — a smaller, more engaged creator usually outperforms a bigger, passive one |
| Paid social (weeks 6–10) | Cost per activated user exceeds ~2x what organic/creator channels cost | Pause spend, don't keep scaling a losing channel — go back to the best-performing organic message/creative and rebuild the ad around that instead of a fresh guess; re-test with a smaller budget before scaling again |
| Referral loop (weeks 6–12) | Referral rate stays under ~10% of activated users | The incentive is probably too weak or too delayed — make the reward instant and visible in-product (not a delayed email), and surface the referral ask at the moment of a user's first "win" (first booking, first payment) rather than only right after signup |
| AppSumo-style listing (week 13) | Listing approval is delayed or rejected | Apply in week 1 specifically so there's lead time to fix and resubmit; if it still isn't live by week 12, fall back to a direct "lifetime deal" page and promote it through the warm list, communities, and creators instead — the mechanic matters more than the specific platform |

If overall progress is materially behind by the week-8 checkpoint (cumulative signups well under ~3,250 from the 90-Day Day-by-Day Plan playbook): the honest options are (1) extend the program past day 90 rather than force the remaining weeks, (2) increase paid-social and creator budget beyond the $6,575 estimate now that cost-per-activated-user is known, or (3) accept a lower 90-day number and keep compounding channels (referral, community, SEO from Product Hunt backlinks) running past the deadline. Choosing between these is a call for whoever owns the budget — flag it as soon as the week-8 checkpoint shows a real gap, not at day 90.

## SEO and content marketing (organic growth)

Honest framing: SEO is not a fast-path lever — content published in week 1 typically doesn't rank meaningfully until month 3–6, so it contributes little to the literal 90-day, 5,000-signup number above. It's included because it should start on day 1 anyway: it compounds after day 90, and the same content doubles as ammunition for the faster channels (a stat-backed article to cite in community posts, a free template to offer creators' audiences, credibility to point to in cold email).

### Content pillars and target keywords

| Pillar | Example pieces | Target keywords |
| --- | --- | --- |
| Alternative/comparison pages | "Akye vs. Jobber," "Akye vs. Housecall Pro," "Best free CRM for cleaning businesses" | "[competitor] alternative," "free cleaning business software," "CRM for cleaning business" |
| Free templates & tools (lead magnets) | Downloadable pricing calculator, invoice template, cleaning contract template, new-hire onboarding checklist | "cleaning business invoice template," "how to price a cleaning job," "cleaning contract template" |
| Operator how-to guides | "How to get your first 10 cleaning clients," "Speed-to-lead for home service businesses," "How to price deep cleaning vs. standard" | "how to start a cleaning business," "how to get cleaning clients," "cleaning business marketing" |
| Local/vertical landing pages (only if targeting specific metros or verticals) | "[City] cleaning business software," landscaping- or handyman-specific variants | "[city] cleaning business," "landscaping business software" |

The template pillar is the fastest-converting of the four and cheapest to produce — the repo already has real operational documents (CONTRACTOR_PAY_POLICY.md, CUSTOMER_ONBOARDING.md, VA_TRAINING_PLAN.md, the pricing logic in pricing.py) that can be stripped of anything Dazzle & Shine-specific and turned into free, gated templates for other operators — real material already proven in a working business, not written from scratch.

### Publishing cadence within the 90 days

- Weeks 1–2: publish the 3–4 highest-intent template/lead-magnet pieces first (pricing calculator, invoice template) — these can drive signups within weeks via direct sharing and community posts, not just search.
- Weeks 3–13: 1–2 articles/week from the how-to and comparison pillars, each one repurposed into a community post, a creator talking point, or a cold-email attachment — never published and left to sit.
- Every piece links to a freemium signup with a specific, relevant CTA (the pricing calculator links to "do this automatically in Akye," not a generic "sign up").

### Basics not to skip

- On-page: one clear target keyword per page, descriptive title/meta description, fast page load (the marketing site is already static HTML, which helps).
- Backlinks: the Product Hunt launch, any directory listings (Capterra, G2, GetApp — free to list on), and creator posts that link back all count toward domain authority — claim these listings in week 1–2 even though the content plan runs longer.
- Track organic separately from the 90-day paid/organic-outreach signup count above, and expect it to be a small fraction of the 5,000 in this window — its payoff shows up as declining cost-per-signup in months 4–6, after this program ends.

## Competitor comparison

Pricing as of September 2026 — published rates shift often, so re-verify before using these numbers in outward-facing comparison content (the "Akye vs. [competitor]" pillar above).

| Competitor | Published starting price | Realistic monthly cost for a 3–5 person crew | Free tier | Built for |
| --- | --- | --- | --- | --- |
| Jobber (getjobber.com/pricing) | $49/mo (Core, 1 user) | ~$199–239/mo (Connect plan, 5 users, +$29/extra seat) | No — 14-day trial only | General field service, all trades |
| Housecall Pro (housecallpro.com/pricing) | $79/mo (Basic) | ~$189–224/mo (Essentials, 5 users — the plan reviewers say you actually need for QuickBooks sync, GPS, and estimates); add-ons commonly add another $40–149/mo | No — 14-day trial only | General field service, all trades |
| ZenMaid (zenmaid.com) | $19/mo (Starter, 1 user) | ~$49–99/mo base + $24/extra user + SMS bundles from $14 | No — 14-day trial (mid-tier plan) | Cleaning businesses specifically |
| Akye | Free (founding-cohort Pro tier) | Free at this tier; paid tiers above it for larger teams | Yes | Home services (cleaning, landscaping, handyman) — white-labeled |

### Where this is the wedge

- None of the three has a real free tier. Every competitor above gates real functionality behind a 14-day trial, then charges $150–250+/month for a small crew before add-ons. "Free, forever, no card required" is a genuinely different claim in this category, not just cheaper marketing copy — lead with it everywhere, especially in the founding-cohort messaging already in this plan's templates.
- Housecall Pro's add-on fees are a known pain point in its own reviews — Akye's pricing should be positioned as transparent (one number, nothing unlocked separately) rather than just "cheaper."
- ZenMaid is the only true like-for-like competitor (cleaning-specific, not a generalist tool retrofitted). Akye's advantage there is the free tier plus that it's built for the broader home-services category (cleaning, landscaping, handyman) rather than cleaning alone — worth confirming which framing (cleaning-first or category-wide) the go-to-market should actually lead with.
- Native industry pricing logic (pricing.py's deep/move-out/post-construction multipliers, contractor payouts via Stripe Connect) reflects real operating knowledge of the cleaning business, not features bolted onto a generic field-service tool — a credible point of difference against Jobber and Housecall Pro specifically.

## Akye pricing tiers

No pricing tiers exist in the codebase today (no billing/plan-gating logic in models.py or elsewhere) — this is a proposal built to support the growth program above, priced to stay meaningfully under the competitors in the comparison section while still being sustainable. It needs sign-off from whoever owns product/pricing before it's published anywhere.

| Tier | Price | Users | Key features | Best for |
| --- | --- | --- | --- | --- |
| Free | $0, forever | 1 | Bookings & CRM (up to 50 active customers), manual pay-by-link, email-only customer messaging, Akye branding on customer-facing pages | Solo operators just leaving spreadsheets |
| Pro | $29/mo | Up to 3 | Unlimited customers, auto-invoices + on-site QR payment, two-way SMS + email, automations & follow-up drips, no branding | Small crews (1–3 people) ready to stop manually chasing payments and leads |
| Team | $79/mo | Up to 10 | Everything in Pro, plus the open-job board, contractor payouts via Stripe Connect, hiring/video-interview screening, priority support | Growing crews with contractors or W-2 hires |
| White-label / Enterprise | Custom — contact sales | Unlimited | Full white-label licensing under the licensee's own brand and domain, dedicated onboarding, everything in Team | Other cleaning, landscaping, or home-maintenance companies licensing Akye as their own platform (the model the README already describes) |

How this reconciles with the founding-cohort offer used throughout this plan: "free forever for the first 500 signups" means Pro tier access at $0, not a fifth tier — it's a time-limited, quantity-limited promotion on top of the real pricing above. Once the cohort closes (or the 500 spots fill), new signups land on the standard Free tier by default and can upgrade to Pro at $29/mo. This is why the founding-cohort deadline in week 3 matters for real unit economics, not just marketing urgency — it caps how many users get Pro-tier features at zero long-term revenue.
"""),

    ("90-Day Day-by-Day Plan", r"""Assumptions made explicit: Day 1 below is illustrative (a Monday) — start the count on whatever day you actually kick off, and nudge the schedule if a key deadline (Product Hunt launch, founding-cohort close, final deadline) would otherwise land on a major holiday or a weekend when your audience is quiet. Daily signup numbers are the weekly targets from the Growth Program playbook split evenly across each week's days for tracking purposes, not a claim that growth is literally linear day to day — what matters is hitting each week's cumulative checkpoint, not each day's exact number.

How to use this table: treat every Sunday row as a real checkpoint, not busywork — if a week's actual cumulative is more than ~15% behind the target in that row, pull forward a later-phase tactic (see the Growth Program playbook's "launch tactics" section) rather than waiting for its scheduled week.

| Day | Weekday | Phase | Action | New signups (est.) | Cumulative |
| --- | --- | --- | --- | --- | --- |
| 1 | Mon | W1 — Prep & warm activation | Lock founding-cohort offer terms + UTM tracking links; send warm texts/DMs to top 20 contacts. | 15 | 15 |
| 2 | Tue | W1 — Prep & warm activation | Warm outreach batch 2 (next 30-50 contacts); enable referral link in product. | 15 | 30 |
| 3 | Wed | W1 — Prep & warm activation | Announce founding-cohort offer to Queen of Side Hustles audience (email + social). | 14 | 44 |
| 4 | Thu | W1 — Prep & warm activation | Join and read rules for 15-20 target Facebook/Reddit groups; begin genuine engagement, no pitching yet. | 14 | 58 |
| 5 | Fri | W1 — Prep & warm activation | Apply for AppSumo-style lifetime-deal listing (lead time); start Product Hunt hunter/upvoter outreach. | 14 | 72 |
| 6 | Sat | W1 — Prep & warm activation | Founder's personal social posts about the free tool (light touch, weekend reach). | 14 | 86 |
| 7 | Sun | W1 — Prep & warm activation | Week review: tally signups + activation rate; adjust messaging for week 2. | 14 | 100 |
| 8 | Mon | W2 — Community seeding ramp | Answer real questions in 2-3 target groups; mention Akye only where it's the genuine answer. | 29 | 129 |
| 9 | Tue | W2 — Community seeding ramp | Warm outreach to secondary contact list (contractors, VAs, past leads). | 29 | 158 |
| 10 | Wed | W2 — Community seeding ramp | Reach out to first 3 candidate creators for partnership terms. | 29 | 187 |
| 11 | Thu | W2 — Community seeding ramp | Continue community engagement; collect first testimonials/reviews from activated signups. | 29 | 216 |
| 12 | Fri | W2 — Community seeding ramp | Finalize Product Hunt launch assets (tagline, screenshots, demo video, first-comment copy). | 28 | 244 |
| 13 | Sat | W2 — Community seeding ramp | Line up Product Hunt launch-day supporters (personal network) for day-of upvotes/comments. | 28 | 272 |
| 14 | Sun | W2 — Community seeding ramp | Week review: signups, activation rate, which group posts converted best. | 28 | 300 |
| 15 | Mon | W3 — Launch week (Product Hunt + founding cohort) | Final Product Hunt prep; confirm launch-day support list is ready. | 86 | 386 |
| 16 | Tue | W3 — Launch week (Product Hunt + founding cohort) | PRODUCT HUNT LAUNCH DAY — post at 12:01am PT, rally supporters, respond to every comment. | 86 | 472 |
| 17 | Wed | W3 — Launch week (Product Hunt + founding cohort) | Ride launch momentum: share PH result across all channels + community groups. | 86 | 558 |
| 18 | Thu | W3 — Launch week (Product Hunt + founding cohort) | Push founding-cohort urgency messaging (spots filling) across warm list + groups. | 86 | 644 |
| 19 | Fri | W3 — Launch week (Product Hunt + founding cohort) | Founding-cohort deadline reminder (48 hours left) to warm list + community groups. | 86 | 730 |
| 20 | Sat | W3 — Launch week (Product Hunt + founding cohort) | Founding-cohort deadline reminder (24 hours left); light paid boost on best-performing organic post. | 85 | 815 |
| 21 | Sun | W3 — Launch week (Product Hunt + founding cohort) | FOUNDING-COHORT OFFER CLOSES. Week + launch review: signups, activation, cost per signup so far. | 85 | 900 |
| 22 | Mon | W4 — Creator partnerships wave 1 | Creator post/story goes live (rotate 1-2 creators per week); track referral code performance. | 72 | 972 |
| 23 | Tue | W4 — Creator partnerships wave 1 | Community engagement continues; reply to every comment/DM from creator posts. | 72 | 1044 |
| 24 | Wed | W4 — Creator partnerships wave 1 | Second creator post/story goes live; cross-post creator content to Akye's own channels. | 72 | 1116 |
| 25 | Thu | W4 — Creator partnerships wave 1 | Follow up with non-activated signups from weeks 1-3 (onboarding-reminder drip via lifecycle.py). | 71 | 1187 |
| 26 | Fri | W4 — Creator partnerships wave 1 | Negotiate/lock next batch of creators for weeks 6-8; review which creator format converts best. | 71 | 1258 |
| 27 | Sat | W4 — Creator partnerships wave 1 | Light community + social presence; no new paid spend yet. | 71 | 1329 |
| 28 | Sun | W4 — Creator partnerships wave 1 | Week review: creator cost-per-signup, activation rate, decide on paid-ads go/no-go for week 6. | 71 | 1400 |
| 29 | Mon | W5 — Creator partnerships wave 1 (cont.) | Creator post/story goes live (rotate 1-2 creators per week); track referral code performance. | 72 | 1472 |
| 30 | Tue | W5 — Creator partnerships wave 1 (cont.) | Community engagement continues; reply to every comment/DM from creator posts. | 72 | 1544 |
| 31 | Wed | W5 — Creator partnerships wave 1 (cont.) | Second creator post/story goes live; cross-post creator content to Akye's own channels. | 72 | 1616 |
| 32 | Thu | W5 — Creator partnerships wave 1 (cont.) | Follow up with non-activated signups from weeks 1-3 (onboarding-reminder drip via lifecycle.py). | 71 | 1687 |
| 33 | Fri | W5 — Creator partnerships wave 1 (cont.) | Negotiate/lock next batch of creators for weeks 6-8; review which creator format converts best. | 71 | 1758 |
| 34 | Sat | W5 — Creator partnerships wave 1 (cont.) | Light community + social presence; no new paid spend yet. | 71 | 1829 |
| 35 | Sun | W5 — Creator partnerships wave 1 (cont.) | Week review: creator cost-per-signup, activation rate, decide on paid-ads go/no-go for week 6. | 71 | 1900 |
| 36 | Mon | W6 — Paid social validation | Paid social: review previous week's ad performance; adjust budget to winning creative/audience. | 65 | 1965 |
| 37 | Tue | W6 — Paid social validation | Launch/rotate new ad creative (use best-performing organic + creator content as ad creative). | 65 | 2030 |
| 38 | Wed | W6 — Paid social validation | Retarget site visitors who didn't sign up; retarget signups who didn't activate. | 64 | 2094 |
| 39 | Thu | W6 — Paid social validation | Community + warm-list engagement continues in parallel (don't drop organic while paid ramps). | 64 | 2158 |
| 40 | Fri | W6 — Paid social validation | Check ad account health (frequency, CPM drift); warm up spend increases gradually. | 64 | 2222 |
| 41 | Sat | W6 — Paid social validation | Light-touch weekend community presence. | 64 | 2286 |
| 42 | Sun | W6 — Paid social validation | Week review: cost per activated user by channel; reallocate budget for next week. | 64 | 2350 |
| 43 | Mon | W7 — Paid social scale | Paid social: review previous week's ad performance; adjust budget to winning creative/audience. | 65 | 2415 |
| 44 | Tue | W7 — Paid social scale | Launch/rotate new ad creative (use best-performing organic + creator content as ad creative). | 65 | 2480 |
| 45 | Wed | W7 — Paid social scale | Retarget site visitors who didn't sign up; retarget signups who didn't activate. | 64 | 2544 |
| 46 | Thu | W7 — Paid social scale | Community + warm-list engagement continues in parallel (don't drop organic while paid ramps). | 64 | 2608 |
| 47 | Fri | W7 — Paid social scale | Check ad account health (frequency, CPM drift); warm up spend increases gradually. | 64 | 2672 |
| 48 | Sat | W7 — Paid social scale | Light-touch weekend community presence. | 64 | 2736 |
| 49 | Sun | W7 — Paid social scale | Week review: cost per activated user by channel; reallocate budget for next week. | 64 | 2800 |
| 50 | Mon | W8 — Paid social scale (cont.) | Paid social: review previous week's ad performance; adjust budget to winning creative/audience. | 65 | 2865 |
| 51 | Tue | W8 — Paid social scale (cont.) | Launch/rotate new ad creative (use best-performing organic + creator content as ad creative). | 65 | 2930 |
| 52 | Wed | W8 — Paid social scale (cont.) | Retarget site visitors who didn't sign up; retarget signups who didn't activate. | 64 | 2994 |
| 53 | Thu | W8 — Paid social scale (cont.) | Community + warm-list engagement continues in parallel (don't drop organic while paid ramps). | 64 | 3058 |
| 54 | Fri | W8 — Paid social scale (cont.) | Check ad account health (frequency, CPM drift); warm up spend increases gradually. | 64 | 3122 |
| 55 | Sat | W8 — Paid social scale (cont.) | Light-touch weekend community presence. | 64 | 3186 |
| 56 | Sun | W8 — Paid social scale (cont.) | Week review: cost per activated user by channel; reallocate budget for next week. | 64 | 3250 |
| 57 | Mon | W9 — Referral loop compounding | Push in-product referral prompt to all activated users who haven't referred yet. | 58 | 3308 |
| 58 | Tue | W9 — Referral loop compounding | Highlight top referrers publicly (leaderboard/shoutout) to encourage more sharing. | 57 | 3365 |
| 59 | Wed | W9 — Referral loop compounding | Community engagement continues; harvest new testimonials from referred signups. | 57 | 3422 |
| 60 | Thu | W9 — Referral loop compounding | Review referral fraud/abuse checks; confirm incentive payouts are accurate. | 57 | 3479 |
| 61 | Fri | W9 — Referral loop compounding | Paid ads continue at validated budget; test one new audience segment. | 57 | 3536 |
| 62 | Sat | W9 — Referral loop compounding | Light-touch weekend presence. | 57 | 3593 |
| 63 | Sun | W9 — Referral loop compounding | Week review: referral rate, viral coefficient, progress vs. cumulative target. | 57 | 3650 |
| 64 | Mon | W10 — Referral loop compounding (cont.) | Push in-product referral prompt to all activated users who haven't referred yet. | 58 | 3708 |
| 65 | Tue | W10 — Referral loop compounding (cont.) | Highlight top referrers publicly (leaderboard/shoutout) to encourage more sharing. | 57 | 3765 |
| 66 | Wed | W10 — Referral loop compounding (cont.) | Community engagement continues; harvest new testimonials from referred signups. | 57 | 3822 |
| 67 | Thu | W10 — Referral loop compounding (cont.) | Review referral fraud/abuse checks; confirm incentive payouts are accurate. | 57 | 3879 |
| 68 | Fri | W10 — Referral loop compounding (cont.) | Paid ads continue at validated budget; test one new audience segment. | 57 | 3936 |
| 69 | Sat | W10 — Referral loop compounding (cont.) | Light-touch weekend presence. | 57 | 3993 |
| 70 | Sun | W10 — Referral loop compounding (cont.) | Week review: referral rate, viral coefficient, progress vs. cumulative target. | 57 | 4050 |
| 71 | Mon | W11 — Creator wave 2 | Creator wave 2 post goes live (new creators or repeat top performers from wave 1). | 50 | 4100 |
| 72 | Tue | W11 — Creator wave 2 | Cross-promote creator wave 2 content across paid + owned channels. | 50 | 4150 |
| 73 | Wed | W11 — Creator wave 2 | Community engagement + referral push continue in parallel. | 50 | 4200 |
| 74 | Thu | W11 — Creator wave 2 | Prep AppSumo-style listing assets (copy, screenshots, FAQ) for week 13 launch. | 50 | 4250 |
| 75 | Fri | W11 — Creator wave 2 | Paid ads: shift budget toward best cost-per-activated-user channel found so far. | 50 | 4300 |
| 76 | Sat | W11 — Creator wave 2 | Light-touch weekend presence. | 50 | 4350 |
| 77 | Sun | W11 — Creator wave 2 | Week review: gap to 5,000 target; decide if a second scarcity deadline is needed. | 50 | 4400 |
| 78 | Mon | W12 — Creator wave 2 (cont.) | Creator wave 2 post goes live (new creators or repeat top performers from wave 1). | 50 | 4450 |
| 79 | Tue | W12 — Creator wave 2 (cont.) | Cross-promote creator wave 2 content across paid + owned channels. | 50 | 4500 |
| 80 | Wed | W12 — Creator wave 2 (cont.) | Community engagement + referral push continue in parallel. | 50 | 4550 |
| 81 | Thu | W12 — Creator wave 2 (cont.) | Prep AppSumo-style listing assets (copy, screenshots, FAQ) for week 13 launch. | 50 | 4600 |
| 82 | Fri | W12 — Creator wave 2 (cont.) | Paid ads: shift budget toward best cost-per-activated-user channel found so far. | 50 | 4650 |
| 83 | Sat | W12 — Creator wave 2 (cont.) | Light-touch weekend presence. | 50 | 4700 |
| 84 | Sun | W12 — Creator wave 2 (cont.) | Week review: gap to 5,000 target; decide if a second scarcity deadline is needed. | 50 | 4750 |
| 85 | Mon | W13 — Final push (lifetime-deal listing + deadline) | AppSumo-style lifetime-deal listing goes live. | 42 | 4792 |
| 86 | Tue | W13 — Final push (lifetime-deal listing + deadline) | Announce second/final scarcity deadline (if behind target) to full list + groups. | 42 | 4834 |
| 87 | Wed | W13 — Final push (lifetime-deal listing + deadline) | All-channel final push: warm list, communities, creators, paid ads, referral all active at once. | 42 | 4876 |
| 88 | Thu | W13 — Final push (lifetime-deal listing + deadline) | Deadline reminder (48 hours) across every channel. | 42 | 4918 |
| 89 | Fri | W13 — Final push (lifetime-deal listing + deadline) | Deadline reminder (24 hours); founder does personal outreach to close the gap. | 41 | 4959 |
| 90 | Sat | W13 — Final push (lifetime-deal listing + deadline) | FINAL DAY — deadline closes at end of day. | 41 | 5000 |

Ready-to-send copy for each week's outreach lives in the "Weekly Email/SMS Templates" playbook. A condensed, printable version of this whole plan lives in the "Printable Launch Checklist" playbook.
"""),

    ("Week 1 — Prep & Warm Activation", r"""As of 2026-09-26. Week 1 of the 90-Day Day-by-Day Plan, as steps you can work through. The plan's target is **100 signups by Day 7**. This playbook also tracks **activations** (a company assigning its first job), because a signup that never gets that far never starts its trial and never pays.

## What the review tightened

The seven days, their order and the signup targets are the 90-Day plan's. These changes make the same week more likely to work:

| # | Change | Why |
| --- | --- | --- |
| 1 | Test the signup path on a phone before the first message | Every week-1 channel is opened on a phone. A first message to a warm contact cannot be sent twice. |
| 2 | Track activations beside signups | Activation is what the Day 7 review acts on. The console counts a company as activated when it assigns its first job. The Launch Checklist's "profile + first customer + first message/invoice" is not what the console measures. |
| 3 | Two asks for the warm list: owners try it, connectors introduce | Someone who doesn't run a cleaning business says no to "try my software" but often says yes to "who's one owner I should talk to?" |
| 4 | One follow-up, 48 hours after every first message | Many replies come from a single polite follow-up. More than one reads as pressure. |
| 5 | Request group membership on Day 1, post from Day 4 | Admin approval can take days. Requested on Day 4, the groups open in week 2. |
| 6 | Set up every signup within 24 hours | The trial starts at the first assigned job. A short setup call is the fastest way there. |
| 7 | Lead with cleaning businesses | Akye is built for cleaning companies (cleaner pay, cleaning checklists, a cleaning price book). The Week 1 templates also name lawn care and handyman businesses. Save those for later, or drop them. |
| 8 | Settle the card question before Day 3 | Checkout asks for a card even when the total is $0. The Day 3 announcement goes to the biggest audience, so its wording must match what checkout does. |
| 9 | Decide whether a lifetime deal fits before applying | A lifetime deal sold during the founding-cohort offer competes with it, and Pro's texts and Nana cost money every month. |

## Daily scoreboard

Fill in each evening (5 minutes). Tick the steps below as you go; the console saves the ticks for everyone. Signups and activations come from Console → Funnel.

| Day | Messages sent | Replies | Signups | Activated | Plan target (running) |
| --- | --- | --- | --- | --- | --- |
| 1 Mon | | | | | 15 |
| 2 Tue | | | | | 30 |
| 3 Wed | | | | | 44 |
| 4 Thu | | | | | 58 |
| 5 Fri | | | | | 72 |
| 6 Sat | | | | | 86 |
| 7 Sun | | | | | 100 |

## Before Day 1: test the funnel (20 minutes)

1. [ ] On a phone, in a private window, open `akyehq.com/?utm_source=test&utm_campaign=check`.
2. [ ] Sign up a throwaway company. Note anything confusing on a small screen.
3. [ ] In the console, open its company page. It should say "Came from: test · check". Mark it **Test**.
4. [ ] On that company's Billing page, check that the referral link shows and copies.

**If any step fails,** fix it before Day 1's messages go out.

## Tracking links

Tags work on any akyehq.com page. Every signup is recorded under Console → Funnel → "Where signups came from". Use these exact links so each channel adds up in one row.

| Channel | Link |
| --- | --- |
| Texts / DMs | `akyehq.com/?utm_source=sms&utm_medium=text&utm_campaign=founding` |
| Newsletter | `akyehq.com/how-to-start-a-cleaning-business?utm_source=newsletter&utm_medium=email&utm_campaign=founding` |
| Facebook | `akyehq.com/?utm_source=facebook&utm_medium=social&utm_campaign=founding` |
| Instagram | `akyehq.com/?utm_source=instagram&utm_medium=social&utm_campaign=founding` |
| Founder's posts | `akyehq.com/?utm_source=personal&utm_medium=social&utm_campaign=founding` |
| Referrals | each owner's own `akyehq.com/r/[their address]`, shown on their Billing page |

## Messages

Start from the Weekly Email/SMS Templates playbook (Week 1), with these three asks. Keep texts under about 320 characters.

- **Owner (asks them to try it):** "Hi [Name], I built Akye, software for cleaning companies: scheduling, crew pay and a free booking page. [Your founding-cohort offer.] Would you try it? I'll set it up with you on a 15-minute call. [link]"
- **Connector (asks for one introduction):** "Hi [Name], I built Akye, software for cleaning companies. Do you know one cleaning-business owner I should talk to? A name is plenty. [link]"
- **Follow-up (once, 48 hours later):** "Bumping this in case it got buried. Happy to set it up with you, or to hear it's not a fit."

## Day 1 — Mon: 1. Lock founding-cohort offer terms 2. UTM tracking links; 3. Send warm texts/DMs to top 20 contacts.

1. [ ] Lock founding-cohort offer terms. Then create the code in Console → Discounts and check it at checkout with a test account; mark that account Test. Before choosing: a code works on every paid plan, so a 100%-off code would make Scale free as well as Pro; and checkout asks for a card even at $0.
2. [ ] If it isn't done yet, the funnel test above.
3. [ ] Request to join the 15–20 owner groups now (5 minutes). Only request; no posting until Day 4.
4. [ ] Split the top 20 into owners (ask them to try it) and connectors (ask for an introduction).
5. [ ] Send each a personal message on the Texts / DMs link. Never a group text.
6. [ ] Reply within the hour, and offer everyone who says yes a 15-minute setup call.

**Done when:** the offer terms are locked, the code works at checkout, the group requests are in, all 20 messages are sent, and the scoreboard is filled in.

## Day 2 — Tue: warm outreach batch 2; referral link

1. [ ] Reply to Day 1 first, and hold the setup calls booked for today.
2. [ ] Batch 2: the next 30–50 contacts, with the same split and the same messages.
3. [ ] Show every new owner their Billing page → "Refer another cleaning business". Reward: one free month of Scale when someone they referred activates. Check Console → Funnel → Referrals, then create a one-month code in Console → Discounts.
4. [ ] Hold a setup call with every signup within 24 hours. Aim to assign their first job on the call.

**Done when:** batch 2 is sent, every signup has a call booked, and the scoreboard is filled in.

## Day 3 — Wed: announce to the Queen of Side Hustles audience

1. [ ] Settle the card question first: the copy says "card needed to claim, never charged", or checkout skips the card at $0.
2. [ ] Angle for this audience: "Start or run your cleaning business on free software." Solo is free for everyone; the founding-cohort offer is for owners who want more.
3. [ ] Send the email on the Newsletter link, and one post per platform on its own link.
4. [ ] Follow up once with Day 1 contacts who haven't replied.
5. [ ] Clear the replies by the evening.

**Note:** many readers are starting out, so expect more signups than activations from this channel. Judge it on Day 7 by its own row in "Where signups came from".

## Day 4 — Thu: owner groups, no pitching

1. [ ] In the groups that approved you since Day 1, read the rules (is self-promotion allowed, is there a promo day, do links need approval) and note them.
2. [ ] Post 3–5 genuinely useful answers (pricing a job, paying crew, hiring), with no links.
3. [ ] Write down the questions that keep coming up. They become week 2's posts.
4. [ ] Follow up once with Day 2 contacts who haven't replied.

## Day 5 — Fri: lifetime deal and Product Hunt

1. [ ] Decide whether a lifetime deal belongs in the program. It competes with the founding-cohort offer, and Pro's texts (1,000 a month) and Nana cost money every month. If yes, offer it only on a tier without texts and Nana, or cap them.
2. [ ] If yes, submit the AppSumo-style application. Approval takes weeks.
3. [ ] Product Hunt: find a hunter, and draft the tagline, gallery and first comment for the week-3 launch.

## Day 6 — Sat: founder's personal post

1. [ ] One post on why you built Akye (the Dazzle & Shine story), on the Founder's posts link. End it with a question so people reply.
2. [ ] Reply to every comment the same day.

## Day 7 — Sun: week review (1 hour)

1. [ ] Mark any test signups as Test.
2. [ ] Console → Funnel, 30-day window: signed up, activated, paying. Fill in the scoreboard's last row.
3. [ ] "Where signups came from": rank the channels by activations, not signups.
4. [ ] "Referrals": who sent whom, and which rewards are owed.
5. [ ] Jobs run this week by each new company.
6. [ ] Three decisions for week 2, one line each: the channel to double, the message to rewrite, the setup step to fix.

**Rule from the 90-Day plan:** if the week ends more than about 15% behind 100 (under about 85), pull a later tactic forward instead of waiting.
"""),
    ("Weekly Email/SMS Templates", r"""Ready-to-send SMS/DM and email copy, one set per week of the 90-day plan. Fill in [brackets]; keep SMS under ~320 characters so it doesn't split into multiple texts.

## Week 1 — Warm activation

SMS/DM (personal contacts):
"Hey [Name]! Quick one — I built a free tool called Akye that runs bookings, payments & texting for cleaning/home-service businesses. No more spreadsheets. Giving free-forever Pro access to the first 500 signups: [link]. Know anyone running a cleaning, lawn care, or handyman business who'd want it?"

Email (warm list):
Subject: A favor + something free for cleaning/home-service business owners
"Hi [Name], I've been building Akye — a free ops platform for home-services businesses (bookings, payments, customer texting, all in one place). We're opening it up to the first 500 businesses free, forever, on the Pro tier. If you run one, or know someone who does, here's the link: [link]. Would mean a lot if you passed it along. Thanks, [Your name]"

## Week 2 — Community seeding

SMS/DM (secondary contacts — contractors, VAs, past leads):
"Hi [Name] — following up because you know a lot of folks in the cleaning/home-service world. I'm giving away free-forever access to Akye (bookings + payments + texting tool) to the first 500 signups: [link]. Could you share it in any groups you're part of?"

Email (community group admins/moderators, asking permission to post):
Subject: Free tool for your group's members — okay to share?
"Hi [Name], I run Akye, a free CRM/booking tool built specifically for cleaning and home-service businesses. Would it be okay to share it with your group ([Group name])? Happy to answer questions in the thread rather than just drop a link. Thanks either way, [Your name]"

## Week 3 — Product Hunt launch + founding-cohort deadline

SMS/DM (launch-day ask to supporters):
"We're live on Product Hunt right now! If you have 30 seconds, an upvote + comment would mean the world: [PH link]. Thank you!!"

Email (launch-day announcement to full list):
Subject: We just launched on Product Hunt
"Hi [Name], Today's the day — Akye is live on Product Hunt: [PH link]. If you've been meaning to try it, now's a great time — the founding-cohort free-forever offer closes this week. [Signup link] Thanks for being part of this, [Your name]"

SMS (48-hour deadline reminder):
"Reminder: free-forever founding-cohort spots on Akye close in 48 hours. [X] of 500 left. Grab yours: [link]"

SMS (24-hour deadline reminder):
"Last call — free-forever Akye access closes tomorrow. Don't want you to miss it: [link]"

## Weeks 4–5 — Creator partnerships (wave 1)

Email (creator outreach/confirmation):
Subject: Partnering on a post for [Creator handle]
"Hi [Creator name], Confirming details for [date]: we'll set you up with a free Akye account to try first, then a [post/story] with your unique link ([link]) so we can track signups from your audience. [Flat fee / rev-share] as discussed. Anything you need from us before then? [Your name]"

SMS/DM (follow-up to signups who haven't activated):
"Hi [Name] — noticed you signed up for Akye but haven't finished setup. Takes 2 minutes: add your business profile + first customer here: [onboarding link]. Reply if you get stuck, happy to help!"

## Weeks 6–8 — Paid social validation & scale

Email (retargeting — visited but didn't sign up):
Subject: Still juggling spreadsheets for [Business Name]?
"Hi [Name], Saw you checked out Akye recently. Free-forever access is still open for now — takes 5 minutes to set up bookings, payments, and customer texting in one place: [link]. No card required. [Your name]"

SMS (retargeting — signed up but inactive):
"Hi [Name], your Akye account is ready but not set up yet. Add your first job in 2 min: [link]. Questions? Just reply here."

## Weeks 9–10 — Referral loop compounding

Email (referral push to activated users):
Subject: Know another cleaning/lawn/handyman business owner?
"Hi [Name], Glad Akye's working for you! If you know another home-services business owner still stuck on spreadsheets, share your link and you'll both get [incentive] when they sign up: [referral link]. Thanks for spreading the word, [Your name]"

SMS (leaderboard shoutout to top referrers):
"[Name], you're one of our top referrers this week! Thank you — [incentive] is on its way. Keep sharing your link: [referral link]"

## Weeks 11–12 — Creator wave 2

Email (re-engaging wave-1 creators + new candidates):
Subject: Round 2 — want to work together again?
"Hi [Creator name], Loved working together for the launch. We're running a second wave of partnerships in [month] — same structure as before ([fee/rev-share]), or open to other ideas if you've got them. Interested? [Your name]"

SMS/DM (dormant-signup re-engagement):
"Hi [Name] — it's been a while since you looked at Akye. We've added [new feature] since then. Still free to try: [link]. Let me know if anything was confusing last time."

## Week 13 — Final push (lifetime-deal listing + deadline)

Email (lifetime-deal listing announcement):
Subject: Akye lifetime deal is live
"Hi [Name], We just launched a lifetime-deal listing for Akye: [listing link]. If you've been on the fence, this is the best it'll ever be priced. [Your name]"

SMS (48-hour final deadline):
"Final 48 hours for the Akye lifetime deal: [link]. Don't want you to miss it."

SMS (24-hour final deadline):
"Last day for the Akye lifetime deal — closes tomorrow: [link]"

Email (final day, personal note):
Subject: Today's the last day
"Hi [Name], This closes tonight. If Akye's been on your list to try, here's the link: [link]. Thanks for considering it — reply if you have any last questions, happy to jump on a quick call. [Your name]"
"""),

    ("Printable Launch Checklist", r"""One page per phase — print and check off as you go. Details/copy for each item live in the other playbooks (90-Day Day-by-Day Plan, Weekly Email/SMS Templates).

## Before Day 1 — setup

[ ] Founding-cohort offer defined and confirmed (free-forever Pro tier, capped at 500 signups)
[ ] UTM/tracking links created for every channel (warm, community, Product Hunt, creators, paid, referral)
[ ] In-product referral link/incentive turned on
[ ] Activation event defined and trackable (profile + first customer + first message/invoice)
[ ] Onboarding-reminder drip enabled for stalled signups (reuse lifecycle.py onboarding automation)
[ ] Apply for AppSumo-style lifetime-deal listing (lead time — do this now for week 13)
[ ] Warm contact list assembled (past clients, contractors, VAs, Queen of Side Hustles audience)
[ ] Weekly tracking sheet/dashboard set up (signups by source, activation rate, cost per activated user)

## Week 1 — Warm activation

[ ] Send warm SMS/DM to top 20 contacts (template: Weekly Email/SMS Templates, Week 1)
[ ] Send warm outreach batch 2 (next 30–50 contacts)
[ ] Announce founding-cohort offer to Queen of Side Hustles audience
[ ] Join 15–20 target Facebook/Reddit groups; read rules
[ ] Founder's personal social posts about the free tool
[ ] Week 1 review: signups vs. 100 target, activation rate

## Week 2 — Community seeding

[ ] Answer real questions in 2–3 groups/day; mention Akye only when genuinely relevant
[ ] Warm outreach to secondary contacts (contractors, VAs, past leads)
[ ] Reach out to first 3 candidate creators
[ ] Collect first testimonials from activated signups
[ ] Finalize Product Hunt launch assets (tagline, screenshots, demo video, first comment)
[ ] Line up Product Hunt launch-day supporters
[ ] Week 2 review: signups vs. 300 cumulative target

## Week 3 — Launch week

[ ] Confirm Product Hunt launch-day support list is ready
[ ] LAUNCH on Product Hunt (12:01am PT) — respond to every comment
[ ] Share PH result across all channels + community groups
[ ] Push founding-cohort urgency messaging (spots filling)
[ ] Send 48-hour founding-cohort deadline reminder
[ ] Send 24-hour founding-cohort deadline reminder
[ ] Founding-cohort offer closes — week 3 + launch review: signups vs. 900 cumulative target

## Weeks 4–5 — Creator partnerships, wave 1

[ ] Confirm terms with 2–3 creators (fee/rev-share, post dates)
[ ] Set creators up with free accounts to try before posting
[ ] Creator posts go live; track referral-code performance
[ ] Reply to every comment/DM the creator posts generate
[ ] Send onboarding-reminder follow-up to non-activated signups from weeks 1–3
[ ] Lock next batch of creators for weeks 6–8 prep
[ ] Week 4–5 review: cost per signup by creator, decide paid-ads go/no-go

## Weeks 6–8 — Paid social validation & scale

[ ] Turn on Meta + TikTok campaigns with warmed-up ad accounts (small initial budget)
[ ] Use best-performing organic/creator content as ad creative
[ ] Set up retargeting: site visitors who didn't sign up, signups who didn't activate
[ ] Check ad account health weekly (frequency, CPM drift)
[ ] Keep community + warm-list engagement running in parallel — don't drop organic
[ ] Weekly review: cost per activated user by channel, reallocate budget

## Weeks 9–10 — Referral loop compounding

[ ] Push in-product referral prompt to all activated, non-referring users
[ ] Publicly highlight top referrers (leaderboard/shoutout)
[ ] Confirm referral incentive payouts are accurate; check for abuse
[ ] Harvest new testimonials from referred signups
[ ] Weekly review: referral rate, viral coefficient vs. target

## Weeks 11–12 — Creator wave 2

[ ] Re-engage wave-1 creators + recruit new candidates
[ ] Wave 2 posts go live; cross-promote across paid + owned channels
[ ] Prep AppSumo-style listing assets (copy, screenshots, FAQ)
[ ] Shift paid budget toward best-performing channel found so far
[ ] Weekly review: gap to 5,000 target; decide if a second scarcity deadline is needed

## Week 13 — Final push

[ ] AppSumo-style lifetime-deal listing goes live
[ ] Announce second/final scarcity deadline across every channel
[ ] All-channel push: warm list, communities, creators, paid ads, referral simultaneously
[ ] Send 48-hour final deadline reminder
[ ] Send 24-hour final deadline reminder + founder personal outreach to close any gap
[ ] Final day — deadline closes; tally final signup count vs. 5,000 target

## Every week, regardless of phase

[ ] Run the weekly 30-minute review against that week's cumulative target
[ ] If more than ~15% behind target two weeks running, pull forward a later-phase tactic
[ ] Check activation funnel for the week's cohort (see the Growth Program playbook's Activation section) — fix the biggest drop-off step
"""),
]


# Earlier versions of a playbook this script wrote, by the sha256 of their
# content. A playbook still exactly as one of these was never edited in the
# console, so running the script again brings it up to date. One that differs
# at all has been edited (or ticked) by someone, and is left alone.
UNTOUCHED = {
    "Week 1 — Prep & Warm Activation": {
        # First version, without checkboxes (PR #36).
        '2b69c3d272aee6a0a1de25979d7ae39bde13eb25624050dda287fca5e22f01f9',
    },
}


def _fingerprint(content):
    import hashlib
    return hashlib.sha256((content or '').strip().encode()).hexdigest()


def main():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)

    existing = {d['title']: d for d in control_plane.all_console_docs(engine)}
    added = 0
    for i, (title, content) in enumerate(DOCS):
        if title in existing:
            doc = existing[title]
            if _fingerprint(doc['content']) in UNTOUCHED.get(title, ()):
                control_plane.update_console_doc(engine, doc['id'], title, content.strip())
                print(f'  ✅ updated to the latest version: {title}')
                added += 1
            else:
                print(f'  ⏭  already there: {title}')
            continue
        control_plane.add_console_doc(
            engine, title, content.strip(), created_by='seed script',
            sort_order=i)
        print(f'  ✅ added: {title}')
        added += 1

    print(f'\n{added} playbook(s) added or updated. View them at /console/playbooks.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
