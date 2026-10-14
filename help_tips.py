"""Short help for the features people don't open, in one place.

Most of what this product does is a menu item somebody has never clicked:
Find leads, Job economics, Rentals, Cleaners near you. A label says what a
page is called, not why a cleaning-company owner would want it, so the page
never gets opened and the feature might as well not exist.

Each tip answers "what is this, and what does it get me" in a sentence or two,
in the owner's words, not ours. Where there is more -- a setup video, or a
question whose answer depends on this business -- the tip links to it rather
than trying to say it. "Ask Nana" is for that second kind (see the .ask-hint
note in akye.css): a tip states what is true for everybody.

Keys are Flask endpoints for menu items and pages, so the sidebar and the page
title find their tip without a lookup table; anything else (a term on a page)
uses a dotted name of its own and is placed with {{ tip('key') }}.

Wording lives here, not in templates, so a tip can be rewritten without
touching a page. tests/test_help_tips.py holds every tip to the same rules.
"""
from markupsafe import Markup, escape

# How long a tip may be. Past this it is a help page, and nobody reads those.
MAX_TEXT = 240

# key: (title, text, video, ask)
#   video -- a funnel_videos key; shown only once that video is recorded
#   ask   -- a question to open Ask Nana with, for what depends on the business
TIPS = {
    # ── Jobs & Money ────────────────────────────────────────────────────
    'admin.dashboard': (
        'Dashboard',
        "Today at a glance: who is working where, what is unpaid, and the one "
        "thing that needs you next.", None, None),
    'bookings.index': (
        'Bookings',
        "Every job, booked by you or by customers on your booking page. Open one "
        "to assign a cleaner, take a deposit or send the confirmation.",
        'book_job', None),
    'invoices.index': (
        'Invoices',
        "Itemised invoices with a pay-online link, for customers who pay after the "
        "job or by the month.",
        None, 'When should I invoice instead of charging the card on file?'),
    'bookings.calendar': (
        'Calendar',
        "The week's jobs by day and cleaner, so double-bookings and empty days "
        "are easy to spot.", None, None),
    'bookings.clients': (
        'Clients',
        "Everyone you have cleaned for, with their jobs and notes in one place — "
        "so the next booking starts from what you already know.",
        'team_and_customer', None),
    'messages.inbox': (
        'Messages',
        "Two-way texts with customers, cleaners and leads in one inbox — replies "
        "land here, not on your personal phone.",
        None, None),
    'messages.sent_log': (
        'Sent log',
        "Every text and email the system sent for you — confirmations, reminders, "
        "pay updates — so you can prove what went out and when.", None, None),
    'messages.templates': (
        'Text templates',
        "Wording you send again and again, saved once and picked in a tap from "
        "any conversation.", None, None),
    'money.pnl': (
        'Profit & Loss',
        "What came in, what went out and what you kept, by month — counted when "
        "money actually landed, the way your accountant will.", None,
        'Is my business profitable this month, and why?'),
    'admin.reports': (
        'Trends',
        "Six months of revenue, jobs and new customers side by side, so you see "
        "whether you are growing before your bank balance tells you.", None, None),
    'money.expenses': (
        'Expenses',
        "Supplies, mileage, software — logged as they happen so your Profit & Loss "
        "and tax time are right without a shoebox of receipts.", None, None),
    'money.job_economics': (
        'Job economics',
        "Which jobs actually make money, what discounts cost you, and what each "
        "cleaner really earns per hour once drive time is counted.", None,
        'Which of my jobs are losing money?'),
    'contractors.payroll': (
        'Payroll',
        "What each cleaner is owed for the period, worked out from their jobs and "
        "pay rate, with pay statements they can see.", None, None),
    'contractors.timesheet': (
        'Timesheet',
        "Hours each cleaner worked this week, from clocking in and out on the job.",
        None, None),
    'money.tax_forms': (
        '1099 & W-9',
        "Who you paid what this year, and whose W-9 you still need — the list your "
        "1099s are filed from in January.", None, 'Do I need to send 1099s?'),
    'commissions.index': (
        'Sales commissions',
        "What each salesperson earned this month from the customers they brought "
        "in, and a record of what you have paid them.", None, None),

    # ── Get customers ───────────────────────────────────────────────────
    'leads.index': (
        'Website leads',
        "People who asked for a quote on your website. Price it, send it, and the "
        "follow-ups go out until they book or say no.", None, None),
    'lsa.index': (
        'Missed contacts',
        "Calls, texts and forms you didn't get to in time. Add them here and they "
        "are followed up for you, so a missed call isn't a lost job.", None, None),
    'places_finder.dashboard': (
        'Find leads',
        "Find offices, gyms and restaurants near you that need regular cleaning, "
        "and work through calling them one at a time. Contracts pay every month.",
        None, 'How do I win my first commercial cleaning contract?'),
    'commercial.index': (
        'Commercial accounts',
        "Businesses you clean on contract, with their schedule and monthly value. "
        "A lead you win on Find leads becomes one in a click.", None, None),
    'quotes.index': (
        'Quotes',
        "Commercial proposals priced area by area, reviewed as a document and sent "
        "for the customer to accept online.", None, None),
    'discounts.index': (
        'Discounts',
        "Codes for a first clean, a referral or a slow week. Job economics shows "
        "what each one has actually cost you.", None, None),
    'content.index': (
        'Social posts',
        "Posts for Facebook, Instagram, TikTok and your Google Business profile, "
        "written for you in a few seconds.", None, None),

    # ── My team ─────────────────────────────────────────────────────────
    'rentals.index': (
        'Rentals',
        "Paste an Airbnb or Vrbo calendar link and every checkout becomes a "
        "turnover clean on the right day, without the host texting you.",
        None, None),
    'contractors.team': (
        'Team',
        "Your cleaners: their pay rates, documents and the jobs you send them.",
        'team_and_customer', None),
    'team.availability': (
        'Availability',
        "Who can work next week, and who hasn't answered yet — before you build "
        "the schedule, not after.", None, None),
    'team.broadcast': (
        'Message the team',
        "One text to every cleaner at once: a schedule change, a reminder, a "
        "thank-you.", None, None),
    'contractors.applications': (
        'Hiring',
        "Everyone who applied to clean for you, in one list with their answers. "
        "Move the good ones on to an interview.", None, None),
    'interviews.admin_interviews': (
        'Interviews',
        "Recorded video interviews you watch when it suits you, instead of "
        "scheduling a call with everyone who applies.", None, None),
    'directory.talent_pool': (
        'Cleaners near you',
        "Cleaners in your area who said they are looking for work. Reach out "
        "before anyone else does.", None, None),
    'directory.invite_past_applicants': (
        'Invite past applicants',
        "People who applied and you didn't hire are still the biggest pool of "
        "cleaners you have. Ask them back in one go.", None, None),
    'directory.hiring_ads': (
        'Job adverts',
        "Ready-written job ads to paste on Indeed, Facebook or Craigslist, linked "
        "to your application page.", None, None),
    'contractors.hiring_settings': (
        'Hiring settings',
        "Your interview link and background-check provider, used by the hiring "
        "pages next to it.", None, None),

    # ── Toolkit ─────────────────────────────────────────────────────────
    'settings.pricing': (
        'Pricing',
        "Your prices for each size of home and each extra. Your booking page and "
        "quotes use these, so a customer sees your price, not a guess.",
        None, 'How should I price a standard clean in my area?'),
    'email_templates.index': (
        'Templates',
        "The emails your business sends — confirmations, reminders, quotes — in "
        "your own words.", None, None),
    'scripts.index': (
        'Call scripts',
        "What to say when you ring a business, by kind of business, shown on the "
        "call sheet while you call.", None, None),
    'workorders.templates': (
        'Cleaning checklist',
        "The room-by-room list your cleaners tick off on the job, with photos, so "
        "every clean is done the same way.", None, None),
    'settings.followup_texts': (
        'Follow-up texts',
        "The wording of the texts that chase missed contacts until they book.",
        None, None),

    # ── Knowledge base ──────────────────────────────────────────────────
    'assistant.page': (
        'Ask Nana',
        "Ask anything about running your business or using this app. She can look "
        "up your jobs, pay and money, so the answer is about your business.",
        None, None),
    'sops.index': (
        'SOPs',
        "How your business does things, written down once, so a new cleaner "
        "learns your way and not the last company's.", None, None),
    'faq.index': (
        'FAQs',
        "Answers to the questions customers and cleaners ask again and again, "
        "ready to paste into a reply.", None, None),

    # ── Settings ────────────────────────────────────────────────────────
    'settings.getting_started': (
        'Getting started',
        "The few steps between signing up and your first booked job, each with a "
        "short video.", 'overview', None),
    'migration.index': (
        'Migration Toolbox',
        "Bring your cleaners and customers over from a spreadsheet or your old "
        "software, instead of typing them in.", 'migration', None),
    'account.my_account': (
        'Security',
        "Your own login: change your password and turn on two-step sign-in.",
        None, None),
    'settings.business': (
        'Settings',
        "Your business name, logo, hours and policies — what customers see on "
        "every quote, invoice and text.", None, None),
    'settings.connections': (
        'Connections',
        "Connect your own Stripe, texting and email so payments and messages go "
        "out under your name.", None, None),
    'settings.sending_domain': (
        'Sending domain',
        "Send emails from your own web address, so they land in the inbox instead "
        "of spam. Needed before cold outreach.", None, None),
    'settings.automations_page': (
        'Automations',
        "Reminders, follow-ups and nudges that run on their own, and whether "
        "each one is running.", None, None),
    'team_logins.index': (
        'Team logins',
        "Logins for the people who help run the office — a dispatcher, an "
        "admin, a salesperson — each seeing only what their job needs.",
        None, 'Which role should I give my office helper?'),
    'settings.commercial': (
        'Commercial brand',
        "A second name and look for your commercial work, so offices get "
        "proposals from a janitorial company, not a house cleaner.", None, None),
    'settings.export': (
        'Export data',
        "Everything you have put in, downloaded as spreadsheets — yours to keep.",
        None, None),

    # ── Terms on pages ──────────────────────────────────────────────────
    'lead.stages': (
        'Lead stages',
        "New: not called yet. Working: being called. Interested: wants a "
        "walkthrough or a price. Proposal: quote sent. Nurture: not now, try "
        "again later.", None, None),
    'lead.ready_to_quote': (
        'Ready to quote',
        "The salesperson's part is done: the lead is qualified and the "
        "walkthrough found what the quote needs. The owner prices it and sends it.",
        None, None),
    'lead.assignment': (
        'Who works a lead',
        "A salesperson sees their own leads and the unassigned ones. Working an "
        "unassigned lead makes it theirs, for the follow-ups and the commission.",
        None, None),
    'rep.daily_target': (
        'Daily call target',
        "Calls a day expected of each salesperson. Their call sheet stops there "
        "with a \"target made\" — they can keep going if they like.", None, None),
}


def get(key):
    """The tip as a dict, or None. Videos and Nana are resolved here, so a
    template never links to a video that hasn't been recorded or to an
    assistant this login can't open."""
    row = TIPS.get(key)
    if not row:
        return None
    title, text, video, ask = row
    out = {'key': key, 'title': title, 'text': text, 'video': '', 'ask': ''}
    if video:
        try:
            import funnel_videos
            out['video'] = funnel_videos.url(video)
        except Exception:
            pass
    if ask and _may_ask():
        try:
            from flask import url_for
            out['ask'] = url_for('assistant.page', q=ask)
        except Exception:
            pass
    return out


def _may_ask():
    """Ask Nana is the owner's, on a plan that has her."""
    try:
        from flask import session
        import entitlements
        return session.get('role') == 'owner' and entitlements.can('assistant')
    except Exception:
        return False


def locked_note(feature):
    """"Part of the Scale plan" -- named right, which "Included in Pro" on
    every locked item was not."""
    try:
        import entitlements
        plan = entitlements.plan_for_feature(feature)
        return f"Part of the {entitlements.PLANS[plan]['label']} plan." if plan else ''
    except Exception:
        return ''


def for_menu(nav):
    """{endpoint: {title, text, locked}} for every menu item and tab on
    screen, for the sidebar's hover tips. Text only: a hover tip is read in
    passing, and its links live in the page's own ⓘ."""
    import navigation
    out = {}
    for section in nav or []:
        for item in section.get('items', []):
            for ep, locked in [(item['endpoint'], item.get('locked'))] + \
                    [(t['endpoint'], t.get('locked')) for t in item.get('tabs', [])]:
                row = TIPS.get(ep)
                if not row or ep in out:
                    continue
                note = locked_note(navigation.feature_for(ep)) if locked else ''
                out[ep] = {'title': row[0], 'text': row[1], 'locked': note}
    return out


_counter = {'n': 0}


def render(key, label=None):
    """The ⓘ button and its popover, for {{ tip('key') }}. Empty for an
    unknown key -- a missing tip never breaks a page (the test catches it)."""
    t = get(key)
    if not t:
        return Markup('')
    try:
        from flask import g
        n = g.get('_tip_n', 0) + 1
        g._tip_n = n
    except Exception:
        _counter['n'] += 1
        n = _counter['n']
    pid = f'tip-{escape(key).replace(".", "-")}-{n}'
    links = []
    if t['video']:
        links.append(f'<a href="{escape(t["video"])}" target="_blank" rel="noopener">▶ Watch how (1 min)</a>')
    if t['ask']:
        links.append(f'<a href="{escape(t["ask"])}">💬 Ask Nana</a>')
    return Markup(
        f'<span class="tip">'
        f'<button type="button" class="tip-btn" aria-expanded="false" aria-controls="{pid}" '
        f'aria-label="{escape(label or "What is " + t["title"] + "?")}">i</button>'
        f'<span class="tip-pop" id="{pid}" role="dialog" aria-label="{escape(t["title"])}" hidden>'
        f'<strong>{escape(t["title"])}</strong> {escape(t["text"])}'
        + (f'<span class="tip-links">{"".join(links)}</span>' if links else '')
        + '</span></span>')
