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
"""
import os
from datetime import datetime, timedelta

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

ALL = ('start_7', 'start_21', 'ending', 'ended')


def _sent(org):
    return {s for s in (org.get('nudges_sent') or '').split(',') if s}


def due(org, now=None):
    """Which nudge this company should get today, or None.

    Pure: no database, no mail, no clock of its own. Every rule above is
    decided here so that it can be tested by describing a company rather than
    by building one.
    """
    if not org:
        return None
    if org.get('status') == 'suspended':
        return None

    state = billing.trial_state(org)
    if state is None:
        return None                     # paying, cancelled, or past due

    now = now or datetime.utcnow()
    already = _sent(org)
    created = org.get('created_at') or now
    age = (now - created).days

    if state['phase'] == 'over':
        # Only just over. On the first run this is what stands between a
        # quiet deploy and an apology to everybody who ever trialled it.
        lapsed = (now - state['ends_at']).days
        if 0 <= lapsed <= ENDED_WITHIN_DAYS and 'ended' not in already:
            return 'ended'
        return None

    if state['phase'] == 'running':
        if state['days_left'] <= ENDING_WITHIN_DAYS and 'ending' not in already:
            return 'ending'
        return None

    # Not started. The two that matter most, because this is the person the
    # banner cannot reach.
    if START_21[0] <= age <= START_21[1] and 'start_21' not in already:
        return 'start_21'
    if START_7[0] <= age <= START_7[1] and 'start_7' not in already:
        return 'start_7'
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


def compose(org, kind):
    """(subject, html) for one nudge. Separated so the tests can read the
    words without sending anything."""
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
    Questions? Just reply to this email — a person reads it.
  </p>
</div>'''

    if kind == 'start_7':
        return (f'{name}: your {billing.TRIAL_DAYS} days haven\'t started yet',
                wrap(
            f'Your {billing.TRIAL_DAYS} days haven\'t started yet',
            f'''<p>You have everything — scheduling, the team, quotes, hiring,
            the lot — and the clock has not begun. It starts the first time you
            put somebody's name on a job, so nothing is running down while you
            are still setting up.</p>
            <p><strong>One thing to try:</strong> add a job, assign a cleaner
            to it, and send them the link. That is the whole product in about
            two minutes, and it is the bit people say they wish they had seen
            first.</p>
            <p style="color:#7a8499;font-size:14px">You have
            <strong>{left} day{plural}</strong> to make that start.</p>''',
            'Add your first job'))

    if kind == 'start_21':
        return (f'{name}: {left} day{plural} left to start your trial',
                wrap(
            f'{left} day{plural} left to start your trial',
            f'''<p>Your account still has everything on it, and the
            {billing.TRIAL_DAYS} days still have not begun — they begin when you
            assign a job to somebody.</p>
            <p>After <strong>{left} day{plural}</strong> the account drops to
            the free plan. Nothing is deleted and you can keep working, but the
            hiring pipeline, the automations and the rest go quiet, and you
            will not have seen them.</p>
            <p>If something is in the way, reply and tell me what it is. If it
            is just that the week got away from you — that is most people, and
            it takes two minutes.</p>''',
            'Start my 14 days'))

    if kind == 'ending':
        return (f'{name}: {left} day{plural} left of everything',
                wrap(
            f'{left} day{plural} left of everything',
            f'''<p>Your trial ends on
            <strong>{state.get("ends_at").strftime("%d %B") if state.get("ends_at") else "soon"}</strong>.</p>
            <p>After that you keep your account and everything in it — your
            customers, your jobs, your team, your prices. Nothing is deleted.
            What stops is the paid side: the hiring pipeline, the automations
            and the extra seats.</p>
            <p>If it has been useful, picking a plan takes a minute. If it has
            not, I would genuinely rather know why — reply and tell me.</p>''',
            'See plans', f'{url}/billing'))

    if kind == 'ended':
        return (f'{name}: your trial has finished — everything is still here',
                wrap(
            'Your trial has finished',
            '''<p>You are on the free plan from today. Your customers, jobs,
            team, prices and history are all exactly where you left them —
            nothing has been deleted and nothing will be.</p>
            <p>What is switched off is the paid side: the hiring pipeline, the
            automations, and extra team seats. They are still there in the
            menu, and turning them back on is one click whenever you want
            them.</p>
            <p>If you tried it and it was not right, reply and tell me what
            was missing. That is more useful to me than a sale.</p>''',
            'See plans', f'{url}/billing'))

    raise ValueError(f'unknown nudge: {kind}')


def _send(org, kind):
    """Send one, as the product rather than as the cleaning company."""
    import notifications
    to = (org.get('owner_email') or '').strip()
    if not to:
        return False, 'no owner email on the account'
    subject, html = compose(org, kind)
    support = product.support_email()
    return notifications.send_email(
        to, org.get('name') or '', subject, html,
        # Explicit, all three. Left to default these would come from
        # `branding`, which describes whichever cleaning business the process
        # last looked at — so the email would arrive signed by somebody
        # else's company, sent from their domain.
        from_name=product.name(),
        from_email=os.environ.get('PRODUCT_FROM_EMAIL') or support or None,
        reply_to=support or None)


def run(engine=None, now=None, dry_run=False):
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
                   'dry_run': bool(dry_run)})
    plan = []

    try:
        orgs = control_plane.all_orgs(engine)
    except Exception:
        # A single-business install has no control plane at all. That is not
        # an error, it is the other product.
        return counts

    now = now or datetime.utcnow()
    for org in orgs:
        counts['considered'] += 1
        kind = due(org, now)
        if not kind:
            continue
        if not (org.get('owner_email') or '').strip():
            counts['skipped_no_email'] += 1
            continue
        plan.append((org['slug'], kind, org['owner_email']))
        if dry_run:
            counts[kind] += 1
            continue
        try:
            ok, detail = _send(org, kind)
        except Exception as e:
            ok, detail = False, str(e)
        if not ok:
            # Not recorded as sent, so tomorrow's run tries again — within the
            # window, which is what the windows are for.
            counts['failed'] += 1
            print(f'  ⚠️  {org["slug"]} {kind}: {detail}')
            continue
        control_plane.set_billing(
            engine, org['slug'],
            nudges_sent=','.join(sorted(_sent(org) | {kind})))
        counts[kind] += 1

    counts['plan'] = plan
    return counts
