"""The half of the trial that leaves the building.

The countdown in the banner is honest and completely useless against the
person it was designed for. It only speaks to somebody who logs in, and the
whole reason the 30-day start-by cap exists is the owner who signs up on a
Tuesday, gets busy, and does not come back. A clock nobody is looking at is
not a deadline. It is a surprise.

So four emails, and no more than four:

    start_7    day 7,  not started   "you have not begun — here is the one
                                      thing that starts it"
    start_21   day 21, not started   the last useful reminder before the door
                                      closes
    ending     3 days left, running  they are using it, so this is the one
                                      that is about money
    ended      the day it lapsed     what changed, what did not, and that
                                      nothing was deleted

Four in a month, each one saying something different, is a sequence. Six is a
drip campaign, and a cleaning company that wanted software does not want a
drip campaign.

What this refuses to do, in every case deliberately:

  * never email a paying customer — `trial_state` returns None for them and
    that is the whole check
  * never email a suspended company
  * never email a company whose owner has opted out, from her own Settings
  * never send the same nudge twice, however often the cron runs. This is why
    `nudges_sent` is written down rather than worked out from dates: a cron
    that fires twice, or a deploy that replays a day, would otherwise send a
    second copy of "9 days left", and the second copy is what gets a sending
    domain marked as spam
  * never email about a trial that lapsed months ago. The first time this
    code runs it meets a table full of history, and without a staleness
    window it would send "your trial has just finished" to everybody who ever
    had one. That is the single worst thing this file could do, so it is
    checked twice — once here and once in the tests
  * never sign the email as the cleaning company. This is Akye writing to its
    customer, not their CRM writing to them, and borrowing their brand or
    their mail account would be both confusing and a leak

Called daily from `/api/trial-nudges` and by hand with
`python3 provisioning.py nudges --dry-run`, which sends nothing and prints
exactly what a real run would do.

## The first week, and the moments worth marking (added October 2026)

Four emails reached the person who never came back, but nothing at all spoke
to them in the week that decides it. Day 0 was the welcome; day 7 was
already a rescue. Paid traffic makes that week the expensive one, so it now
has its own short run, and the two moments somebody decides this is real get
a note of their own:

    day1           day 1, not activated   two things, two minutes
    day2           day 2, everyone        your booking page is already live
    day4           day 4, not activated   where people get stuck
    day5           day 5, not activated   bring your list over
    activated      when the 30 days start what is now switched on
    feature        ~day 10 of the trial   the one useful thing not yet tried
    first_booking  first online booking   somebody booked you (sent at once)
    winback        a week after it lapsed what you would get back, once

Every rule above still holds, plus one more: **one email a day, from any of
these, however it was sent.** `nudge_last_at` is what enforces that, so a
"somebody booked you" at 3pm and the next morning's note are never the same
day's mail. Each not-activated email stops the moment they activate.

`activated` and `first_booking` are sent the moment they happen
(`send_event`), because that is when they mean something; the daily run also
sends `activated` if the moment passed without it, for three days and no more.
"""
from datetime import datetime

import billing
import control_plane
import product


# When each nudge is due, as a window of days since signup rather than an
# exact day. A window, because a cron can miss a day — the machine reboots,
# the schedule is paused, a deploy runs long — and a nudge keyed to `== 7`
# would simply never be sent rather than being sent a day late.
START_7 = (7, 13)
START_21 = (21, 29)

# How close to the end "nearly over" starts.
ENDING_WITHIN_DAYS = 3

# How long after a trial lapses the "it has finished" note is still worth
# sending. Past this it is not news, it is an oddity — and on the first run
# against an existing database, every old trial is past this.
ENDED_WITHIN_DAYS = 3

# The first week. Windows of days since signup, as above; tight on purpose,
# because "two things, two minutes" read on day four is just late.
DAY1 = (1, 2)
DAY2 = (2, 4)
DAY4 = (4, 5)
DAY5 = (5, 6)
# How long after the 30 days start the "now switched on" note still makes
# sense if the moment itself was missed.
ACTIVATED_WITHIN_DAYS = 3
# Days into the running trial for "one thing you have not tried". Ends before
# the "3 days left" note begins, so the two are never in competition.
FEATURE = (8, 10)
# Days after a lapse for the single "here is what you would get back".
WINBACK = (7, 10)
# Fewer hours than a day, so a cron that runs at 9:05 one morning and 8:55
# the next is still "the next day".
ONE_A_DAY_HOURS = 20

ALL = ('start_7', 'start_21', 'ending', 'ended',
       'day1', 'day2', 'day4', 'day5', 'activated', 'feature',
       'first_booking', 'winback')
# Sent when something happens, not on a timetable.
EVENTS = ('activated', 'first_booking')


def _sent(org):
    return {s for s in (org.get('nudges_sent') or '').split(',') if s}


def _blocked(org):
    """Why this company must not be emailed at all, or None."""
    if not org:
        return 'no company'
    if org.get('is_test') or org.get('is_demo'):
        return 'test account'           # marked a test account in the console
    if org.get('nudges_opted_out'):
        return 'opted out'              # she asked not to be, from her own Settings
    if org.get('status') in ('suspended', 'closing', 'closed'):
        return 'not active'
    return None


def emailed_today(org, now=None):
    last = (org or {}).get('nudge_last_at')
    now = now or datetime.utcnow()
    return bool(last) and (now - last).total_seconds() < ONE_A_DAY_HOURS * 3600


def due(org, now=None, next_step=None):
    """Which nudge this company should get today, or None.

    Pure: no database, no mail, no clock of its own. Every rule above is
    decided here so that it can be tested by describing a company rather than
    by building one.

    `next_step` is the one tenant-side fact the "feature" note needs -- the
    first Getting Started step still undone, or None. The caller reads it;
    without it, that note is simply not due.
    """
    if not org:
        return None
    if org.get('is_test'):
        return None                     # marked a test account in the console
    if org.get('nudges_opted_out'):
        return None                     # she asked not to be, from her own Settings
    if org.get('status') in ('suspended', 'closing', 'closed'):
        # A closed company is being wound down, not courted: "your trial is
        # ending" to somebody whose account was closed is worse than silence.
        return None

    state = billing.trial_state(org)
    if state is None:
        return None                     # paying, cancelled, or past due

    now = now or datetime.utcnow()
    if org.get('is_demo'):
        return None
    if emailed_today(org, now):
        return None                     # one a day, whatever sent the last one
    already = _sent(org)
    created = org.get('created_at') or now
    age = (now - created).days

    def open_(window, kind, days=age):
        return window[0] <= days <= window[1] and kind not in already

    if state['phase'] == 'over':
        # Only just over. On the first run this is what stands between a
        # quiet deploy and an apology to everybody who ever trialled it.
        lapsed = (now - state['ends_at']).days
        if 0 <= lapsed <= ENDED_WITHIN_DAYS and 'ended' not in already:
            return 'ended'
        # Once, a week on, and only for somebody who actually started: a
        # trial that lapsed unused has nothing to "get back".
        if org.get('activated_at') and open_(WINBACK, 'winback', lapsed):
            return 'winback'
        return None

    if state['phase'] == 'running':
        if state['days_left'] <= ENDING_WITHIN_DAYS and 'ending' not in already:
            return 'ending'
        began = org.get('activated_at') or now
        days_in = (now - began).days
        if days_in <= ACTIVATED_WITHIN_DAYS and 'activated' not in already:
            return 'activated'
        if open_(DAY2, 'day2'):
            return 'day2'
        if next_step and open_(FEATURE, 'feature', days_in):
            return 'feature'
        return None

    # Not started. The two that matter most, because this is the person the
    # banner cannot reach.
    if START_21[0] <= age <= START_21[1] and 'start_21' not in already:
        return 'start_21'
    if START_7[0] <= age <= START_7[1] and 'start_7' not in already:
        return 'start_7'
    # The first week, earliest first: a run that missed yesterday sends
    # yesterday's note today and today's tomorrow, rather than skipping one.
    for window, kind in ((DAY1, 'day1'), (DAY2, 'day2'),
                         (DAY4, 'day4'), (DAY5, 'day5')):
        if open_(window, kind):
            return kind
    return None


def company_url(org):
    """That company's own address, not the product's.

    The same mistake as every other link the product sends: a nudge that
    points at akyehq.com sends somebody to a login page for a company that
    does not exist there.
    """
    base = product.domain()
    slug = org.get('slug') or ''
    if not base or not slug:
        return product.base_url()
    return f'https://{slug}.{base}'


def compose(org, kind, next_step=None):
    """(subject, html) for one nudge. Separated so the tests can read the
    words without sending anything."""
    import funnel_videos
    name = (org.get('name') or 'there').strip()
    first = (org.get('owner_email') or '').split('@')[0].split('.')[0].title()
    url = company_url(org)
    state = billing.trial_state(org) or {}
    left = state.get('days_left', 0)
    plural = '' if left == 1 else 's'
    brand = product.name()

    def wrap(heading, body, cta='Open your CRM', href=None):
        return f'''
<div style="font-family:-apple-system,Segoe UI,Inter,sans-serif;max-width:520px;
            margin:0 auto;color:#16213a;line-height:1.55">
  <p style="font-size:17px;margin:0 0 18px">Hi {first or name},</p>
  <h2 style="font-size:20px;margin:0 0 14px;color:#16213a">{heading}</h2>
  {body}
  <p style="margin:26px 0">
    <a href="{href or url}" style="background:#f0a44b;color:#16213a;
       text-decoration:none;font-weight:600;padding:12px 22px;border-radius:8px;
       display:inline-block">{cta} &rarr;</a>
  </p>
  <p style="color:#7a8499;font-size:13px;margin-top:28px;border-top:1px solid #e6eaf2;
            padding-top:14px">
    {brand} &middot; {url}<br>
    Questions? Just reply to this email — a person reads it.<br>
    Rather not get these? <a href="{url}/billing" style="color:#7a8499">Turn them off
    under Billing</a>.
  </p>
</div>'''

    if kind == 'start_7':
        return (f'{name}: your {billing.TRIAL_DAYS} days haven\'t started yet',
                wrap(
            f'Your {billing.TRIAL_DAYS} days haven\'t started yet',
            f'''<p>You have everything — scheduling, the team, quotes, hiring,
            the lot — and the clock has not begun. It starts when you add your
            first cleaner and your first customer, so nothing is running down
            while you are still setting up.</p>
            <p><strong>Two things, about two minutes:</strong> add one cleaner
            (yourself counts, if you are still cleaning) and one customer you
            already clean for. That is enough to see the whole thing work, and
            it is what starts your {billing.TRIAL_DAYS} days.</p>
            <p style="color:#7a8499;font-size:14px">You have
            <strong>{left} day{plural}</strong> to make that start.</p>''',
            'Add a cleaner', f'{url}/staff/new'))

    if kind == 'start_21':
        return (f'{name}: {left} day{plural} left to start your trial',
                wrap(
            f'{left} day{plural} left to start your trial',
            f'''<p>Your account still has everything on it, and the
            {billing.TRIAL_DAYS} days still have not begun — they begin when you
            add your first cleaner and your first customer.</p>
            <p>After <strong>{left} day{plural}</strong> the account drops to
            the free plan. Nothing is deleted and you can keep working, but the
            hiring pipeline, the automations and the rest go quiet, and you
            will not have seen them.</p>
            <p>If something is in the way, reply and tell me what it is. If it
            is just that the week got away from you — that is most people, and
            it takes two minutes.</p>''',
            f'Start my {billing.TRIAL_DAYS} days'))

    # What switches off when a trial ends, in the owner's words, from the
    # plan table (entitlements.PLANS). Said concretely because "the paid
    # features" means nothing; "texting your cleaners" is a Tuesday morning.
    LOSES = '''<ul style="padding-left:20px;margin:10px 0 14px">
              <li>Texting your cleaners and customers</li>
              <li>Automatic reminders and follow-ups</li>
              <li>Card payments and invoices</li>
              <li>The hiring pipeline</li>
              <li>More than 2 cleaners, or 20 jobs a month</li>
            </ul>'''

    if kind == 'ending':
        ends = state.get('ends_at')
        when = f"{ends.strftime('%B')} {ends.day}" if ends else 'soon'
        return (f'{name}: {left} day{plural} left of everything',
                wrap(
            f'{left} day{plural} left of everything',
            f'''<p>On <strong>{when}</strong> your account moves to the free
            plan. Your customers, jobs and prices all stay.
            Nothing is deleted. These switch off:</p>
            {LOSES}
            <p>That is the difference between the business texting people for
            you and you doing it from your phone at 10pm again.</p>
            <p>Keeping it takes a minute. If it has not been worth it, reply
            and tell us why. We would genuinely rather know.</p>''',
            'Keep everything on', f'{url}/billing'))

    if kind == 'ended':
        return (f'{name}: your trial has finished — everything is still here',
                wrap(
            'Your trial has finished',
            f'''<p>You are on the free plan from today. Your customers, jobs,
            team and prices are exactly where you left them.
            Nothing has been deleted.</p>
            <p>What is switched off:</p>
            {LOSES}
            <p>It all comes back with one click whenever you want it. If it was
            not right for you, reply and tell us what was missing. That helps
            more than a sale.</p>''',
            'See plans', f'{url}/billing'))

    # ── The first week ────────────────────────────────────────────────────
    # Each one opens on a moment the owner has actually lived, then shows the
    # fix, then asks for one small thing. Real stakes only: no invented
    # deadlines, no made-up testimonials.
    if kind == 'day1':
        return (f'{name}: get the schedule out of your head',
                wrap(
            'Get the schedule out of your head',
            f'''<p>Addresses screenshotted into a group chat. A cleaner texting
            &ldquo;which house again?&rdquo; at 8am. The whole week living in
            your head and your phone.</p>
            <p>That ends with two things: add <strong>one cleaner</strong>
            (you count, if you are still cleaning) and <strong>one
            customer</strong> you already clean for. Then you can watch a job
            go straight to their phone with the address, the time and the
            checklist.</p>
            <p>About two minutes. Your {billing.TRIAL_DAYS} days do not start
            until you do, so you lose nothing by starting now.</p>
            {funnel_videos.email_block('team_and_customer')}''',
            'Add my first cleaner', f'{url}/staff/new'))

    if kind == 'day2':
        return (f'{name}: the jobs you lose while you are cleaning',
                wrap(
            'The jobs you lose while you are cleaning',
            f'''<p>Somebody asks for a price while you are elbow-deep in a
            bathroom. By the time you text back that evening, they have booked
            someone else. Nobody tells you. The job just never happens.</p>
            <p>Your booking page stops that. Customers pick a service, see your
            price and book a time themselves, even while you are working.
            It is already live:</p>
            <p style="font-size:17px"><strong>{url}/book</strong></p>
            <p>Put it in your Facebook bio and your Google profile today, and
            send it next time someone asks &ldquo;how much?&rdquo;</p>
            {funnel_videos.email_block('booking_page')}''',
            'Get my booking link', f'{url}/settings/booking-page'))

    if kind == 'day4':
        return (f'{name}: what usually gets in the way',
                wrap(
            'What usually gets in the way',
            '''<p>Most owners do not stall because it is hard. They stall because
            the week gets away from them, which is the exact problem this is
            meant to fix. A few things we hear a lot:</p>
            <p><strong>&ldquo;I need to set everything up first.&rdquo;</strong><br>
            You do not. One cleaner and one customer is enough to see it work.
            Do the rest when you have a quiet evening.</p>
            <p><strong>&ldquo;My prices are different.&rdquo;</strong><br>
            Change them under Settings, Prices. Your booking page and quotes
            follow, so the price you say is the price they book.</p>
            <p><strong>&ldquo;I do not have cleaners yet.&rdquo;</strong><br>
            Add yourself. That is how most cleaning businesses start.</p>
            <p>Stuck on something else? Reply and tell us what. A real person
            reads every one.</p>''',
            'Pick up where I left off'))

    if kind == 'day5':
        return (f'{name}: your customer list is one lost phone from gone',
                wrap(
            'Your customer list is one lost phone from gone',
            f'''<p>Your customers are the business. If they live in a notebook,
            your phone&rsquo;s contacts or a spreadsheet, that is a lot riding
            on one thing you could drop in a bucket.</p>
            <p>You do not have to type them in one at a time. Bring the whole
            list over in one go, and every customer is saved, searchable and
            ready to book.</p>
            {funnel_videos.email_block('migration')}''',
            'Bring my list over', f'{url}/migration'))

    # ── Moments ───────────────────────────────────────────────────────────
    if kind == 'activated':
        ends = state.get('ends_at')
        until = f"{ends.strftime('%B')} {ends.day}" if ends else 'two weeks from now'
        return (f'{name}: your {billing.TRIAL_DAYS} days just started',
                wrap(
            f'Your {billing.TRIAL_DAYS} days just started',
            f'''<p>You added a cleaner and a customer, so everything is switched
            on until <strong>{until}</strong>.</p>
            <p>Picture next week: jobs land on your cleaners&rsquo; phones,
            customers get their reminders without you, and you are not
            rebuilding the schedule from texts at night.</p>
            <p>To see it for real, <strong>book one real job and assign
            it.</strong> That is the moment it clicks.</p>
            {funnel_videos.email_block('book_job')}''',
            'Book my first job', f'{url}/bookings/new'))

    if kind == 'first_booking':
        return (f'{name}: somebody just booked you online',
                wrap(
            'Somebody booked you through your own page',
            '''<p>A customer just booked you, and you did not have to answer a
            call, play phone tag or send a quote. It is in your calendar now,
            ready for a cleaner.</p>
            <p>That is a job that could easily have gone to someone else.
            Every place your link lives is another chance for this to happen
            again. Add it somewhere new today.</p>''',
            'See the booking', f'{url}/bookings/'))

    if kind == 'feature':
        step = next_step or {}
        title = step.get('title') or 'Getting started'
        why = step.get('why') or ''
        return (f'{name}: before your trial ends, try this',
                wrap(
            'Before your trial ends, try this',
            f'''<p>You have <strong>{left} day{plural}</strong> left with
            everything switched on. Most people only find out what a tool can
            do after it is gone. One thing you have not tried yet:</p>
            <p><strong>{title}</strong><br>{why}</p>
            <p>It takes a few minutes, and then you will know if it is worth
            keeping.</p>''',
            step.get('cta') or 'Open my account',
            f"{url}{step.get('link') or ''}"))

    if kind == 'winback':
        return (f'{name}: still doing it the hard way?',
                wrap(
            'Still doing it the hard way?',
            f'''<p>It has been a week on the free plan. Everything you entered is
            still there.</p>
            <p>If you have caught yourself texting cleaners one by one again,
            chasing a payment, or reminding customers by hand, that is the part
            that switched off:</p>
            {LOSES}
            <p>It comes back the moment you pick a plan. This is the last note
            about it. If something was missing, reply and tell us.</p>''',
            'Turn it back on', f'{url}/billing'))

    raise ValueError(f'unknown nudge: {kind}')


def _send(org, kind, next_step=None, engine=None, sent_by='auto'):
    """Send one, as the product rather than as the cleaning company, and
    write it down for the console's Communications page."""
    to = (org.get('owner_email') or '').strip()
    if not to:
        return False, 'no owner email on the account'
    subject, html = compose(org, kind, next_step)
    ok, detail = _deliver(org, to, subject, html)
    if engine is not None:
        control_plane.record_product_message(engine, org.get('slug'), kind, to,
                                             subject, ok, detail, sent_by)
    return ok, detail


def _deliver(org, to, subject, html):
    import notifications
    support = product.support_email()
    return notifications.send_email(
        to, org.get('name') or '', subject, html,
        # Explicit, all four. Left to default, the identity comes from
        # `branding` and the key from `integrations` — both of which describe
        # whichever cleaning business the process last looked at. The email
        # would arrive signed by somebody else's company, sent from their
        # domain, billed to their email account.
        from_name=product.name(),
        from_email=product.from_email() or None,
        reply_to=support or None,
        api_key=product.resend_api_key() or None)


def run(engine=None, now=None, dry_run=False, sent_by='auto'):
    """Walk every company and send at most one nudge each.

    At most one, on purpose. A company that has been quiet for three weeks
    could be owed both the day-7 and the day-21 note, and receiving them
    together is not two reminders — it is a mail merge that went wrong.
    """
    if engine is None:
        import provisioning
        engine = provisioning._engine()

    counts = {k: 0 for k in ALL}
    counts.update({'considered': 0, 'skipped_no_email': 0, 'failed': 0,
                   'switched_off': 0, 'dry_run': bool(dry_run)})
    plan = []

    try:
        orgs = control_plane.all_orgs(engine)
    except Exception:
        # A single-business install has no control plane at all. That is not
        # an error, it is the other product.
        return counts

    import communications
    switch_map = control_plane.switches(engine)
    now = now or datetime.utcnow()
    for org in orgs:
        counts['considered'] += 1
        step = _next_step_if_needed(org, now)
        kind = due(org, now, next_step=step)
        if not kind:
            continue
        if not communications.is_on(kind, switch_map):
            # Switched off in the console. Not recorded as sent, so turning
            # it back on inside the window still sends it.
            counts['switched_off'] += 1
            continue
        if not (org.get('owner_email') or '').strip():
            counts['skipped_no_email'] += 1
            continue
        plan.append((org['slug'], kind, org['owner_email']))
        if dry_run:
            counts[kind] += 1
            continue
        try:
            ok, detail = _send(org, kind, step, engine, sent_by)
        except Exception as e:
            ok, detail = False, str(e)
        if not ok:
            # Not recorded as sent, so tomorrow's run tries again — within the
            # window, which is what the windows are for.
            counts['failed'] += 1
            print(f'  ⚠️  {org["slug"]} {kind}: {detail}')
            continue
        _record(engine, org, kind, now)
        counts[kind] += 1

    counts['plan'] = plan
    return counts


def _record(engine, org, kind, now=None):
    control_plane.set_billing(
        engine, org['slug'],
        nudges_sent=','.join(sorted(_sent(org) | {kind})),
        nudge_last_at=now or datetime.utcnow())


# The Getting Started steps worth suggesting in the "feature" note, in order.
# Not the two that start the trial -- by then they are done.
FEATURE_STEPS = ('job', 'booking_page', 'pricing')


def _next_step_if_needed(org, now):
    """Read the company's own schema only when the "feature" note could be
    due -- every company, every day, would be a lot of reading for nothing."""
    state = billing.trial_state(org)
    began = org.get('activated_at')
    if not state or state['phase'] != 'running' or not began:
        return None
    if 'feature' in _sent(org):
        return None
    days_in = (now - began).days
    if not (FEATURE[0] <= days_in <= FEATURE[1]):
        return None
    return next_step(org['slug'])


def next_step(slug):
    """The first useful Getting Started step this company has not done, as
    {title, why, cta, link}, or None. Never raises: a company whose schema
    will not read is a company that does not get this one email."""
    try:
        import console_data
        import onboarding
        import tenancy
        from extensions import db
        if not console_data.schema_ready(slug):
            return None
        db.session.remove()
        try:
            with tenancy.use_tenant(slug):
                steps = {s['key']: dict(s) for s in onboarding.journey()}
        finally:
            db.session.remove()
        for key in FEATURE_STEPS:
            s = steps.get(key)
            if s and not s['done']:
                return {k: s.get(k) for k in ('title', 'why', 'cta', 'link')}
    except Exception:
        return None
    return None


def send_event(slug, kind, engine=None):
    """Send `activated` or `first_booking` now, because it just happened.

    Same rules as the daily run, checked against the company as it is this
    second: never twice, never to a paying, opted-out, test or closed
    company. The one-a-day rule is the only one an event does not wait for
    -- "somebody booked you" tomorrow morning is not the same email -- but it
    still counts as today's, so the scheduled note waits until tomorrow.

    Returns (sent, detail). Never raises: it is called from inside a page
    load and a booking, neither of which may fail because of an email.
    """
    if kind not in EVENTS:
        return False, f'not an event: {kind}'
    try:
        if engine is None:
            import provisioning
            engine = provisioning._engine()
        org = control_plane.find(engine, slug)
        why = _blocked(org)
        if why:
            return False, why
        if billing.trial_state(org) is None:
            return False, 'not on a trial'
        if kind in _sent(org):
            return False, 'already sent'
        if kind == 'activated' and not org.get('activated_at'):
            return False, 'not activated'
        import communications
        if not communications.is_on(kind, control_plane.switches(engine)):
            return False, 'switched off in the console'
        ok, detail = _send(org, kind, engine=engine, sent_by='event')
        if ok:
            _record(engine, org, kind)
        return ok, detail
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'

