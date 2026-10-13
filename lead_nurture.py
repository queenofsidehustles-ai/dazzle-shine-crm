"""Four useful emails for somebody who came close and did not sign up.

Who gets them: people who came to us. Somebody who typed their email into
the signup form and left (`abandoned_signup`), or asked for early access.
Never an uploaded prospect list -- those people did not ask for anything, and
cold outreach is the console's job (lead_outreach.py), pressed by a person.

What they get, over about two weeks, each one worth reading on its own:

    1  day 1    what it actually costs to start
    2  day 4    how to price a job
    3  day 8    the decision that gets new owners fined
    4  day 13   a soft "open an account free", and then nothing

Every email carries the free signup link, an unsubscribe link and the postal
address (lead_outreach.email_html, the same footer the console uses). Then
they go quiet; the Meta custom audience is where they are reached after that.

What it refuses to do:

  * email anybody who already owns a company -- checked before every send,
    so finishing signup halfway through the sequence ends it
  * email anybody who unsubscribed, or whom the console is already talking to
    (`contacted_at` set: a person replied, and a robot should not)
  * start the sequence for somebody who asked weeks ago. On the first run
    the table is full of history; without FRESH_DAYS every old lead would get
    "email 1" on the same morning
  * send two of these within MIN_GAP, or more than MAX_PER_RUN in one run
    (each send is a call inside the web request; see lead_outreach.MAX_BULK)

Called daily from `/api/lead-nurture` (scheduler.PRODUCT_JOBS).
"""
from datetime import datetime, timedelta

import product

# Days after the lead was created that each email becomes due.
SCHEDULE = (1, 4, 8, 13)
FRESH_DAYS = 21
MIN_GAP = timedelta(days=2)
MAX_PER_RUN = 40
NEVER_SOURCES = ('console upload',)


def _guide():
    import lead_outreach
    return f'{lead_outreach.site()}/how-to-start-a-cleaning-business'


def signup_link():
    import lead_outreach
    return (f'{lead_outreach.site()}/signup?utm_source=email'
            f'&utm_medium=nurture&utm_campaign=lead_nurture')


def due_step(lead, owners=(), now=None):
    """Which email (1-4) this lead should get today, or None. Pure."""
    import notifications
    now = now or datetime.utcnow()
    email = (lead.get('email') or '').strip().lower()
    if not email or not notifications.looks_like_email(email):
        return None
    if lead.get('unsubscribed_at') or lead.get('contacted_at'):
        return None
    if (lead.get('source') or '') in NEVER_SOURCES:
        return None
    if email in owners:
        return None
    step = lead.get('nurture_step') or 0
    if step >= len(SCHEDULE):
        return None
    created = lead.get('created_at') or now
    age = (now - created).days
    if step == 0 and age > FRESH_DAYS:
        return None
    if age < SCHEDULE[step]:
        return None
    for last in (lead.get('nurture_last_at'), lead.get('last_emailed_at')):
        if last and now - last < MIN_GAP:
            return None
    return step + 1


def compose(lead, step):
    """(subject, plain-text body). Paragraphs split on blank lines."""
    first = (lead.get('name') or '').split()[0] if lead.get('name') else 'there'
    guide = _guide()
    link = signup_link()
    name = product.name()
    started = ''
    if step == 1 and lead.get('source') == 'abandoned_signup':
        biz = lead.get('company') or 'your business'
        started = (f'You started setting up {biz} with {name}. If you want to '
                   f'finish, it picks up right where you left off: {link}\n\n')

    # Each one is useful on its own (the guide), then names the everyday
    # problem behind it and how Akye takes it off their plate. One link to
    # sign up, no invented urgency, no made-up customers.
    if step == 1:
        return ('What it actually costs to start a cleaning business', (
            f'Hi {first},\n\n{started}'
            'Less than most people think. Most owners start with a few hundred '
            'to a couple of thousand dollars: supplies, a good vacuum, '
            'registration and a year of insurance. A van, a website and staff '
            'can wait until the business pays for them.\n\n'
            'The cost nobody budgets for is the work that slips through. The '
            'quote you meant to send that evening. The customer who asked for a '
            'price and booked someone else before you replied. Nobody tells you '
            'it happened.\n\n'
            f'{name} gives you a booking page that answers for you: customers see '
            'your price and book a time while you are still cleaning.\n\n'
            f'The full cost breakdown: {guide}#what-it-costs\n\n'
            f'Free to start, no card needed: {link}'))
    if step == 2:
        return ('How to price a cleaning job (and stop undercharging)', (
            f'Hi {first},\n\n'
            'Price the job, not the hour. Customers want the price before you '
            'arrive, and hourly pricing punishes you for getting faster.\n\n'
            'Start from what you need to earn. Add what it costs to send '
            'somebody: their pay, supplies, travel, insurance. Then add margin. '
            'And charge more for a first clean. A home nobody has deep cleaned '
            'in a year can take twice as long, and quoting the regular price for '
            'it is how a three-hour price turns into a ten-hour day.\n\n'
            f'In {name} you set your prices once. Every quote and every booking '
            'uses them, so the price you say out loud is the price they '
            'book.\n\n'
            f'More on pricing: {guide}#pricing\n\n'
            f'Free to start: {link}'))
    if step == 3:
        return ('The decision that gets new cleaning owners fined', (
            f'Hi {first},\n\n'
            'Calling your cleaners 1099 contractors looks cheaper. Get it wrong '
            'and the bill shows up years later: back taxes, penalties and '
            'interest, usually when someone files for unemployment or gets '
            'hurt.\n\n'
            'What decides it is not the paperwork. It is how the work happens. '
            'If you set their hours, supply the products and tell them how to '
            'clean, they may count as employees whatever the contract says. '
            'Rules differ by state, so talk to an accountant where you are '
            'before you hire the first person.\n\n'
            'Whichever way you go, keep a clear record of who cleaned where '
            f'and when. {name} keeps that for every job, so pay day is not a '
            'memory test.\n\n'
            f'The full section: {guide}#contractors-or-employees\n\n'
            f'Free to start: {link}'))
    if step == 4:
        return (f'Last one from us', (
            f'Hi {first},\n\n'
            f'If any of this sounds familiar, it is what {name} is for:\n\n'
            '- The schedule lives in your head and your phone.\n'
            '- Addresses go to cleaners as screenshots in a group chat.\n'
            '- Quotes and follow-ups wait until you have a free evening.\n'
            '- A job got cleaned and never got billed.\n\n'
            'Opening an account is free and takes about a minute. No card '
            f'needed.\n\n{link}\n\n'
            'Either way, the guide is yours to keep: '
            f'{guide}\n\n'
            'Questions? Just reply. A real person reads it.'))
    raise ValueError(f'unknown nurture step: {step}')


def _send(engine, lead, step):
    import control_plane
    import lead_outreach
    import notifications
    to = lead['email'].strip().lower()
    subject, body = compose(lead, step)
    ok, detail = notifications.send_email(
        to, lead.get('name') or '', subject, lead_outreach.email_html(body, to),
        from_name=product.name(),
        from_email=product.outreach_from_email() or None,
        reply_to=product.outreach_reply_to() or None,
        api_key=product.resend_api_key() or None)
    control_plane.record_lead_message(engine, lead['id'], 'email', to, subject,
                                      body, ok, detail, f'nurture {step}')
    return ok, detail


def run(engine=None, now=None, dry_run=False):
    import control_plane
    if engine is None:
        import provisioning
        engine = provisioning._engine()
    now = now or datetime.utcnow()
    counts = {'considered': 0, 'sent': 0, 'failed': 0, 'dry_run': bool(dry_run),
              **{f'step_{i}': 0 for i in range(1, len(SCHEDULE) + 1)}}
    plan = []
    try:
        control_plane.ensure_table(engine)
        leads = control_plane.all_leads(engine)
    except Exception:
        return counts
    owners = control_plane.owner_emails(engine)
    for lead in reversed(leads):                    # oldest first
        counts['considered'] += 1
        step = due_step(lead, owners, now)
        if not step:
            continue
        if len(plan) >= MAX_PER_RUN:
            break                                   # the rest are due tomorrow
        plan.append((lead['id'], step, lead['email']))
        counts[f'step_{step}'] += 1
        if dry_run:
            continue
        try:
            ok, detail = _send(engine, lead, step)
        except Exception as e:
            ok, detail = False, str(e)
        if not ok:
            counts['failed'] += 1
            print(f'  ⚠️  lead {lead["id"]} nurture {step}: {detail}')
            continue
        control_plane.set_lead_nurture(engine, lead['id'], step, now)
        counts['sent'] += 1
    counts['plan'] = plan
    return counts
