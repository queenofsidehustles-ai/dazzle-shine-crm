"""Starter cold-call scripts for commercial outreach.

These are seeded into the Script table so they show up in the Scripts library
AND alongside the prospect being called on the Find Leads page. Once seeded they
are ordinary rows — edit them in the UI, not here. Re-running the seeder only
adds scripts whose (category, title) is missing, so edits are never overwritten.

Formatting follows the convention templates/admin/scripts.html already renders:
a line starting with 💡 collapses into a "Why this works" box, blank lines
become spacers, everything else prints as-is.
"""

from models import Script
from extensions import db

# (category, title, sort_order, content)
STARTER_SCRIPTS = [

    # ── Gatekeeper ────────────────────────────────────────────────────────────
    ('outbound', 'Getting past the front desk', 10, """\
"Hi, this is {owner} with {biz}. Who handles your janitorial vendor — is that you or someone else?"

If they say it's someone else:

"Got it — what's their name, and are they in today?"

If they won't put you through:

"No problem — what's the best way to reach them?"

💡 Don't ask "how are you today" and don't ask for "the owner." Ask by function. Receptionists screen for salespeople, and someone who already knows what they're calling about doesn't sound like one. If you get blocked, take the name and email, send a note, and call back Thursday.\
"""),

    # ── Property managers ─────────────────────────────────────────────────────
    ('call_property_manager', 'Opening — property & facility managers', 10, """\
"Hi [Name], {owner} with {biz}. I'll be quick — I'm not calling to sell you anything today. We clean commercial buildings around {city}, and I'm reaching out to a handful of properties in the area to see if it'd be worth walking your building and putting a number in front of you. Most people already have somebody. Do you?"

Then, the moment they say yes:

"When does that contract come up for renewal?"

WRITE THE DATE DOWN. Then:

"That's actually fine. I'm not asking you to break anything. What I'd like to do is walk the building, put a written scope together, and hold the proposal until [month] so you've got a real number to compare against when it's time. Costs you nothing and takes about twenty minutes."

💡 Assume they already have a vendor — they do. Saying it out loud disarms the reflex to brush you off. And the renewal date is worth more than a maybe: it turns a no-today into a scheduled opportunity. Property managers are the highest-leverage call you can make because one relationship can put you in front of a dozen buildings.\
"""),

    # ── Medical ───────────────────────────────────────────────────────────────
    ('call_medical', 'Opening — medical & dental practices', 10, """\
"Hi [Name], {owner} with {biz}. I'll be brief — we do commercial cleaning around {city} and we work with medical and dental practices specifically, because clinical space has a documentation side that most cleaning companies aren't set up for. Who handles your cleaning vendor?"

Once you have the right person:

"Are you cleaning clinical areas — exam and treatment rooms — or just the front of house and admin space?"

Then:

"What I'd like to do is walk the practice, put a written scope together separating clinical from administrative, and get you a flat monthly number. Takes about twenty minutes. Would a morning or an afternoon work better?"

⚠️ DO NOT SAY you already maintain a written exposure control plan until that document actually exists. Book the walkthrough — it's a week or two out — and have the plan finished before you show up.

If they ask about it before it's done, the honest answer is:
"That's exactly what I want to go over at the walkthrough — I'll bring the exposure control plan and training documentation with me."

💡 The compliance file is your best card against every other cleaning company, which is precisely why you can't bluff it. A practice manager who asks to see the plan and hears you backpedal is a permanently dead account — and they talk to each other.\
"""),

    ('call_medical', 'Medical — qualifying questions', 20, """\
Ask these on the first call, before you quote anything:

"Are we cleaning exam and treatment rooms, or administrative areas only?"
"How many exam rooms, and how many restrooms?"
"Roughly what square footage?"
"What days are you open, and what time does the last patient leave?"
"Who handles your regulated medical waste now?"
"Do you have a vendor currently, and when does that agreement end?"

💡 The clinical-versus-administrative answer decides everything. Admin-only is an ordinary office account. Exam rooms mean OSHA's bloodborne pathogen standard applies and you need the documentation in place. The regulated waste question matters because you need to say plainly that you don't touch sharps or red-bag waste — that boundary is a selling point, not a limitation.\
"""),

    # ── General contractors ───────────────────────────────────────────────────
    ('call_construction', 'Opening — general contractors (post-construction)', 10, """\
"Hi [Name], {owner} with {biz}. We do post-construction final cleans around {city}. Who's handling your cleaning subs — is that you or the super?"

Once you've got them:

"Do you have anything coming up to turnover? I ask because we quote it in three phases — rough clean, final clean, and punch-list touch-up — so you get the closeout number up front instead of a change order at the end."

Then:

"What's the square footage and when's your handover date?"

💡 This is your fastest money. GCs decide in days, not months, there's no long vendor-vetting cycle, and the work is project-priced rather than squeezed monthly. Leading with the three-phase quote hits a real pain: cleaning subs routinely bid the first two phases and then come back for more when the punch list lands. Saying you price all three up front marks you as someone who has done this before.\
"""),

    ('call_construction', 'GC — what to have ready', 20, """\
They will ask for these, usually on the first call. Have them ready to send within ten minutes:

• Certificate of insurance, with the general contractor named as additional insured
• W-9
• Your phase pricing — rough / final / punch-list

Say this when they ask:

"I can have the COI over to you in ten minutes with your company named as additional insured. What's the best email?"

⚠️ Ask about payment terms before you commit. GCs commonly pay 30–60 days and sometimes tie it to their own draw schedule.

"What are your payment terms on subs?"

💡 Sending the COI while they're still on the phone is the single fastest trust-builder in this business. Most cleaning companies take three days and two reminders. Asking about payment terms up front isn't rude — it's what a real contractor does, and it stops post-construction work from quietly strangling your cash flow.\
"""),

    # ── Offices & retail ──────────────────────────────────────────────────────
    ('call_office', 'Opening — offices, retail & general commercial', 10, """\
"Hi [Name], {owner} with {biz}. I'll keep it short — we clean offices around {city} and I'm calling a few businesses in the area to see if it's worth walking your space and getting you a number. You've probably already got somebody. Do you?"

If yes:

"When's that up for renewal?"

If no, or they're doing it themselves:

"How are you handling it now?"

Then either way:

"Let me walk it, put the scope in writing, and quote you flat by month. Twenty minutes. I'm out that way Tuesday and Thursday — which is better for you?"

💡 "How are you handling it now?" is the best question for a small office, because the honest answer is often "the staff does it" or "my sister-in-law." That's not a competitor you have to displace — that's a resentment you get to solve.\
"""),

    # ── Qualifying ────────────────────────────────────────────────────────────
    ('outbound', 'Qualifying questions — ask while you have them', 20, """\
"Roughly how many square feet?"
"How many restrooms?"
"What's the schedule now — nightly, few times a week?"
"Is it just your suite, or common areas too?"
"What made you think about looking?"

💡 That last one is the money question. The answer is almost never price — it's that the crew stopped showing up, quality slid after month three, or nobody answers the phone when something goes wrong. Whatever they tell you is what your entire proposal should be built around. Write it down in their words and use their words back at the walkthrough.\
"""),

    # ── Closing ───────────────────────────────────────────────────────────────
    ('closing', 'The close — booking the walkthrough', 10, """\
"Let's get twenty minutes on the calendar. I'm out that way Tuesday and Thursday — does one of those work better, morning or afternoon?"

Once they pick:

"Perfect. And who should I ask for when I get there? What's the best cell to reach you if anything shifts?"

💡 Two options, never open-ended. "When works for you?" invites "just email me something," and that's where deals go to die. Getting a name and a mobile number at the booking cuts your no-show rate roughly in half, because now it's an appointment with a person instead of an entry on a calendar.\
"""),

    # ── Voicemail ─────────────────────────────────────────────────────────────
    ('voicemail', 'Voicemail — leave one every time', 10, """\
"Hi [Name], {owner} with {biz} in {city}, {phone}. I'm reaching out about your janitorial service — not asking you to switch anything, just to walk the building and get you a number to compare against at renewal. {phone}. Thanks."

Keep it under 20 seconds.

💡 Say the number twice, once at the start and once at the end — people reach for a pen halfway through. Leave a message every single time: most commercial prospects answer on the third or fourth attempt, and the earlier voicemails are why they eventually pick up. Call back in three days, not tomorrow.\
"""),

    # ── Objections ────────────────────────────────────────────────────────────
    ('objection', '"We\'re happy with our current company"', 10, """\
"Good — that's how it should be. All I'd ask is thirty seconds: when's your renewal? I'll put a proposal in front of you then, and if you're still happy you throw it away."

💡 Never argue with this one. Agreeing with them costs you nothing and keeps the call alive, and "if you're still happy you throw it away" removes the last bit of risk. You're not trying to win today — you're trying to be the call they remember at renewal.\
"""),

    ('objection', '"Send me some information"', 20, """\
"Happy to. So I send something useful instead of generic — is it just your suite or common areas too, and roughly what square footage?"

Then actually send it, and call back in four days.

💡 This is usually a polite brush-off, so the trick is to answer a question with a question. If they engage with the square footage, they're real. If they won't give you anything, they're not — send the email anyway, but don't spend more of the day on it.\
"""),

    ('objection', '"What are your rates?"', 30, """\
"I won't quote you blind — anybody who does is guessing and you'll get surprised on the invoice. Commercial pricing depends on square footage, restroom count, and frequency. Twenty minutes in the building and I'll give you a flat monthly number."

💡 Refusing to quote over the phone raises your standing rather than lowering it. Every cleaning company that throws out a number gets the job and then either loses money or nickel-and-dimes the client — and the client has been burned by that before. Naming the three real variables proves you actually price the work instead of guessing at it.\
"""),

    ('objection', '"We\'re under contract"', 40, """\
"Understood. What month does it end?"

That's the whole response. Write the date down, thank them, and move on.

💡 Don't try to talk them out of a contract. Get the date, log it, and be the first call when it's up. A pipeline of renewal dates is the most valuable thing you'll build in your first ninety days of calling — it's the reason month four looks nothing like month one.\
"""),

    ('objection', '"Are you insured?"', 50, """\
"Yes — one million general liability, and I can name your property as additional insured. Want me to text you the certificate right now?"

Then actually do it, while you're still on the phone.

💡 Sending the COI during the call is the strongest move available to you on a first contact. It converts an abstract claim into a document in their hand inside sixty seconds, and it's the thing most small cleaning companies cannot do because they have to go find it.\
"""),

    ('objection', '"How long have you been in business?"', 60, """\
Answer with the real history of the company behind the brand — not the age of the brand name.

"We've been operating in Central Florida since [year]. {biz} is our commercial division."

💡 This is an honest answer and it's also the strongest one available. The commercial brand is a trade name on an established company, so the insurance, the track record, and the references all belong to it. Never invent years — commercial buyers check, and one caught exaggeration ends the relationship.\
"""),

    # ── Follow-up ─────────────────────────────────────────────────────────────
    ('followup', 'Follow-up email — after "send me information"', 10, """\
Subject: {biz} — walkthrough for [Company]

Hi [Name],

Good speaking with you. As promised — we handle commercial cleaning for offices, medical suites, retail and post-construction across {city}.

A few things that usually matter:

• $1,000,000 general liability, your property named as additional insured on request
• Background-checked crews, same faces every visit
• Written scope per site, so nothing gets quietly dropped
• Photo log after every service, and a monthly walkthrough with you

I'd like twenty minutes to walk your building and put a flat monthly number in front of you. No obligation, and if you're under contract I'll hold the proposal until your renewal.

Would [day] morning or afternoon work better?

{owner}
{biz}
{phone}

💡 Send this the same day, while the call is still fresh. Four bullets, not fourteen — this is a follow-up, not a brochure. Close with two specific time options exactly like you did on the phone. Then call back in four days; the email alone almost never books anything.\
"""),

    ('followup', 'The callback — third and fourth attempts', 20, """\
"Hi [Name], {owner} with {biz} — I left you a message last week about walking your building. Is now a bad time?"

💡 "Is now a bad time?" outperforms "do you have a minute?" because it's easy to say no to and most people reflexively say "no, it's fine." Most commercial prospects don't pick up until the third or fourth attempt, so the callbacks aren't nagging — they're the actual job. Space them three or four days apart and stop after five.\
"""),

    # ── Email outreach ────────────────────────────────────────────────────────
    # Written to be pasted into an ordinary inbox, not sent as a campaign: no
    # images, no attachment on the first touch, one ask. Anything in [brackets]
    # is filled in per prospect; {biz}, {owner} and {phone} fill themselves.
    ('email_outreach', 'Cold email #1 — property manager', 10, """\
Subject: cleaning your [building name] property

Hi [Name],

I run {biz} here in [city]. We handle janitorial and turnover cleaning for properties like [building name].

I'm not asking you to switch anything today. I'd just like to walk the property and put a flat monthly number in front of you, so you have a real comparison on file for whenever your current contract comes up.

Takes about twenty minutes. Would [day] or [day] suit you better?

{owner}
{biz}
{phone}

💡 Send it Tuesday–Thursday morning. Subject line in lower case, naming their building — it reads like a colleague, not a campaign. No attachment and no brochure on a first email: the only thing you're selling is a twenty-minute walkthrough. Two named days beat "let me know when works."\
"""),

    ('email_outreach', 'Cold email #2 — the follow-up nobody sends', 20, """\
Subject: re: cleaning your [building name] property

Hi [Name],

Following up on the note below. Still happy to walk [building name] and leave you a number — no obligation, and if you're under contract I'll hold the proposal until your renewal date.

If you're not the right person for this, could you point me to whoever is?

{owner}
{phone}

💡 Reply on the original thread so the subject keeps the "re:". Send it four days later. This one asks for a referral as well as a meeting, which gives a busy person an easy way to be helpful — that's how you get the facilities manager's name without a gatekeeper.\
"""),

    ('email_outreach', 'Cold email — realtors & listing agents', 30, """\
Subject: move-out cleans for your listings

Hi [Name],

I'm {owner} with {biz}. We do move-out and make-ready cleans around [city] — the deep clean that gets a property photo-ready before it lists, or handed back after a tenant leaves.

Turnaround is [X] days, we work to the standard your sellers expect, and we invoice you or the seller directly, whichever is easier at closing.

If a listing comes up that needs one, would you like me to send my pricing so you have it on hand?

{owner}
{biz}
{phone}

💡 Agents don't buy cleaning, they buy a listing that shows well on a deadline. Lead with turnaround time and who gets the invoice — those are the two things that decide whether they call you. Ask to send pricing rather than asking for a meeting; it's a smaller yes, and it gets you into their contacts.\
"""),

    ('email_outreach', 'After the walkthrough — sending the proposal', 40, """\
Subject: your cleaning proposal — [building name]

Hi [Name],

Good to meet you [today/yesterday]. Here's the proposal for [building name]:

• [Scope — e.g. common areas, restrooms, lobby, [X] floors]
• [Frequency — e.g. 3 nights a week, after 6pm]
• [$X] per month, flat, all supplies included
• Start date: as soon as [date]

Everything in it comes straight from what we walked through. Anything you want changed, tell me and I'll re-issue it.

Can I put you down for a [date] start?

{owner}
{biz}
{phone}

💡 Same day as the walkthrough, while they still remember you. Four bullets, not four pages. Close by asking for a specific start date — a proposal that ends with "let me know your thoughts" gets thought about forever.\
"""),

    ('email_outreach', 'The last email — closing the loop', 50, """\
Subject: closing your file

Hi [Name],

I've not managed to catch you, so I'll assume the timing isn't right and stop emailing.

If it changes — a contract ending, a vendor letting you down, a property changing hands — keep my number. We can usually start within a week.

{owner}
{biz}
{phone}

💡 Send this after four or five unanswered touches. It gets more replies than any other email on this page, because it removes the pressure and hands them a deadline of their own. Mean it: if there's no answer to this one, stop — and pick the file back up in six months.\
"""),
]


def tokens():
    """Values substituted into scripts at display time — business, owner,
    phone and city.

    Kept out of the stored content so a business that renames itself, changes
    its number, or resells this CRM never has to re-edit sixteen scripts. The
    commercial division name is preferred where one is set, since these are
    commercial outreach scripts.
    """
    import branding
    from models import BusinessSetting
    biz = (BusinessSetting.get('commercial_name') or '').strip() or branding.biz_name()
    return {
        'biz': biz,
        'owner': (BusinessSetting.get('owner_name') or '').strip() or 'me',
        'phone': branding.phone() or '[your number]',
        # The town the VA says out loud. A script naming somebody else's city is
        # worse than one naming no city at all.
        'city': (BusinessSetting.get('city') or '').strip() or 'your area',
    }


def render(content, vals=None):
    """Fill {biz} / {owner} / {phone} without exploding on other braces."""
    vals = vals or tokens()
    for k, v in vals.items():
        content = content.replace('{' + k + '}', v)
    return content


def seed(force=False):
    """Insert any starter script that isn't already present.

    Matched on (category, title) so a re-run never clobbers edits made in the UI.
    Returns the number of scripts added.
    """
    added = 0
    for category, title, sort_order, content in STARTER_SCRIPTS:
        exists = Script.query.filter_by(category=category, title=title).first()
        if exists:
            if force:
                exists.content = content
                exists.sort_order = sort_order
            continue
        db.session.add(Script(
            category=category,
            title=title,
            content=content,
            sort_order=sort_order,
        ))
        added += 1
    db.session.commit()
    return added
