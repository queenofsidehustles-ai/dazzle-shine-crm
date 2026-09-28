"""What happens after a call.

The call list was a list of outcomes: a status saying "No Answer" and free-text
notes. Nothing said what to do next or when, so a follow-up existed only in
whoever made the call's memory, and the list sorted by the day a business was
imported — which is never the day anything is due.

Every outcome here resolves to two things: the stage the prospect is now in,
and the next action with a date. Both are suggestions the caller can overrule
in the drawer; the point is that hanging up never leaves a prospect with
nothing scheduled.
"""
from datetime import timedelta

from scheduling import local_today

# Commercial prospects rarely pick up before the third or fourth try, so a
# no-answer is a normal step rather than a rejection. After this many attempts
# the odds stop justifying the time and they go to Nurture instead.
MAX_ATTEMPTS = 5

# outcome → (stage, next action, days until it's due, counts as an attempt)
# days = None means nothing is scheduled: the funnel is closed for now.
RULES = {
    'new':            ('new',        'First call',                    0,  False),
    'called':         ('working',    'Follow-up call',                4,  True),
    'no_answer':      ('working',    'Call back — no answer',         2,  True),
    'callback':       ('working',    'Call back — they asked',        3,  True),
    'interested':     ('interested', 'Book the walkthrough',          2,  True),
    'won':            ('won',        'Convert to a commercial account', 0, True),

    # ── The three answers a commercial call actually ends on ───────────────
    #
    # Every one of these used to land on 'called' via the fallback, which set a
    # four-day follow-up and treated a facilities manager under a two-year
    # contract exactly like somebody who missed the phone. Each is now its own
    # outcome with its own cadence, because the whole difference between them
    # is when to come back.
    #
    # "We have a cleaner, but you can be our backup." Worth more than it
    # sounds: standby is who gets rung the week the incumbent misses a clean.
    # Two months is often enough to stay the name they remember without
    # becoming the company that keeps ringing.
    'backup':         ('nurture',    'Check in — still on standby?',  60, True),
    # "Send your information over." Chase quickly — an unopened attachment two
    # days old is still warm, and at three weeks it never happened.
    'send_info':      ('working',    'Did the information land?',      2,  True),
    # "Not now, but take my details." A quarter is the right spacing for a
    # facilities manager; monthly is how a supplier becomes a nuisance.
    'keep_in_touch':  ('nurture',    'Quarterly check-in',            90,  True),

    # "Not interested" is not a no in commercial cleaning — it is almost always
    # "we are under contract", which is a date, not a rejection. Routing it to
    # 'lost' with no date threw away the single most winnable kind of prospect
    # there is: one who has already told you they buy this service. It rests in
    # nurture and comes back in a quarter, and if the call got a renewal month
    # out of them, renewal_date wakes it sooner and with a reason.
    'not_interested': ('nurture',    'Quarterly check-in',            90,  True),
    # A real no, and the only one. Somebody who asks not to be contacted again
    # has to have a way of being obeyed, or the quarterly check-in above turns
    # into harassment.
    'do_not_contact': ('lost',       None,                            None, True),
}

# The same rules, said in the caller's language for the drawer's quick picks.
QUICK_ACTIONS = [
    ('Call back in 2 days',   2),
    ('Call back in 4 days',   4),
    ('Call back in a week',   7),
    ('Call back in a month', 30),
]


def _plus(days):
    return (local_today() + timedelta(days=days)).isoformat()


def apply_outcome(prospect, outcome, next_action=None, next_action_date=None):
    """Move a prospect on after a call. Returns the (stage, action, date) set.

    An explicit next_action / next_action_date from the drawer always wins —
    the person who made the call knows more than the table does.
    """
    stage, action, days, counts = RULES.get(
        outcome, ('working', 'Follow-up call', 4, True))

    if counts:
        prospect.attempts = (prospect.attempts or 0) + 1

    # Out of attempts: stop calling, keep the record. Someone who never picked
    # up is not a no — they're a maybe with a bad phone habit, and the break-up
    # email is the thing that gets replies.
    if stage == 'working' and (prospect.attempts or 0) >= MAX_ATTEMPTS:
        stage, action, days = 'nurture', 'Send the last email, then rest it', 0

    prospect.stage = stage
    prospect.next_action = next_action if next_action is not None else action
    if next_action_date:
        prospect.next_action_date = next_action_date
    elif next_action is not None:
        # A custom action with no date still needs one, or it drops out of the
        # Today list and is never seen again.
        prospect.next_action_date = prospect.next_action_date or _plus(3)
    else:
        prospect.next_action_date = _plus(days) if days is not None else None

    if not prospect.next_action:
        prospect.next_action_date = None

    # Start, switch or stop the email sequence this outcome implies. The clock
    # starts now rather than at import, so day 2 means two days after the call
    # that earned it.
    wanted = SEQUENCE_FOR_OUTCOME.get(outcome)
    if stage in ('lost', 'won'):
        # A no that means no, or a win. Either way stop mailing: the quarterly
        # check-in is the part of this that turns into harassment.
        prospect.sequence = None
    elif wanted and prospect.sequence != wanted:
        from datetime import datetime
        prospect.sequence = wanted
        prospect.drip_step = 0
        prospect.last_drip_at = datetime.utcnow()

    return prospect.stage, prospect.next_action, prospect.next_action_date


# ── Email sequences ──────────────────────────────────────────────────────────
#
# Calls are scheduled by next_action_date and done by a person. These are the
# emails that go out between the calls, and there are deliberately only two.
#
# `stages` is what keeps a sequence honest: it runs only while the prospect is
# still in the stage that started it. Move them to Interested because they rang
# back, and the chasing stops without anybody having to remember to stop it —
# which is the closest thing to reply detection that does not involve reading
# somebody's mailbox.
SEQUENCES = {
    # "Send your information over." The whole value is the first two days --
    # an unopened attachment is still warm on Tuesday and never happened by
    # the end of the month. Three touches, then it rests.
    'send_info': {
        'label': 'After sending information',
        'schedule': [(2, 1), (7, 2), (21, 3)],
        'stages': ('working',),
    },
    # The long one. Quarterly, four times, and then it stops mailing and lives
    # on the call list only. A supplier still sending automated email into a
    # facilities manager's inbox in year two is not nurturing, it is noise, and
    # the unsubscribe costs the address permanently.
    'nurture': {
        'label': 'Quarterly check-in',
        'schedule': [(90, 1), (180, 2), (270, 3), (365, 4)],
        'stages': ('nurture',),
    },
}

# Which outcome starts which sequence. Anything absent starts none: a no-answer
# should not trigger email at somebody who has not spoken to you yet.
SEQUENCE_FOR_OUTCOME = {
    'send_info':      'send_info',
    'not_interested': 'nurture',
    'keep_in_touch':  'nurture',
    'backup':         'nurture',
}


# How long before a contract ends you want to be in the conversation. Short
# enough that the incumbent's renewal is genuinely open, long enough to get a
# walkthrough booked before the paperwork is signed.
RENEWAL_LEAD_DAYS = 30


def wake_renewals(today=None):
    """Put prospects back on the call list before their contract renews.

    The whole reason for taking a renewal date on a cold call. Everything else
    in nurture is a guess about timing; this is the one date where the answer
    is known, and a quarterly check-in that happens to miss it by five weeks is
    the difference between a bid and a "we just re-signed".

    Deliberately does not touch a prospect already being worked -- waking one
    that somebody is mid-conversation with would overwrite a real next action
    with a generic one. Returns how many were woken, for the cron's log.
    """
    from datetime import datetime

    from extensions import db
    from models import Prospect
    today = today or local_today().isoformat()
    horizon = (local_today() + timedelta(days=RENEWAL_LEAD_DAYS)).isoformat()

    woken = 0
    for p in Prospect.query.filter(
            Prospect.renewal_date.isnot(None),
            Prospect.renewal_date <= horizon,
            Prospect.renewal_woken_at.is_(None)).all():
        # Already back in play, or explicitly done with. Mark it so it is not
        # reconsidered every night, but change nothing.
        if (p.stage or 'new') not in ('nurture',):
            p.renewal_woken_at = datetime.utcnow()
            continue
        p.stage = 'working'
        p.next_action = f'Contract renews {p.renewal_date} — get the walkthrough booked'
        p.next_action_date = today
        p.renewal_woken_at = datetime.utcnow()
        p.notes = note_entry(p, f'Woken for renewal on {p.renewal_date}.')
        woken += 1
    if woken:
        db.session.commit()
    return woken


def stage_from_status(status):
    """Where an existing prospect belongs, for records that predate stages."""
    return RULES.get(status or 'new', ('new',))[0]


def backfill(prospect):
    """Give a pre-stages prospect a stage and, if it's live, something to do.

    Runs once per record. A prospect that was already called gets its next
    action dated today rather than in the past — the point is to put it in
    front of her, not to open with a list that is already late.
    """
    changed = False
    if not prospect.stage:
        prospect.stage = stage_from_status(prospect.status)
        changed = True
    if prospect.attempts is None:
        prospect.attempts = 1 if prospect.status not in (None, '', 'new') else 0
        changed = True
    if prospect.is_open and not prospect.next_action:
        prospect.next_action = ('First call' if prospect.stage == 'new'
                                else 'Follow-up call')
        prospect.next_action_date = local_today().isoformat()
        changed = True
    return changed


def due_counts(prospects):
    today = local_today().isoformat()
    out = {'overdue': 0, 'today': 0, 'later': 0, 'unscheduled': 0}
    for p in prospects:
        if not p.is_open:
            continue
        state = p.due_state(today)
        out['unscheduled' if state is None else state] += 1
    return out


def due_sort_key(p):
    """Overdue first, oldest first; unscheduled live ones last."""
    return (p.next_action_date or '9999-99-99', p.business_name or '')


def note_entry(prospect, header):
    """One dated line above the existing notes."""
    from scheduling import local_now
    stamp = local_now().strftime('[%b %d] ')
    return (stamp + header + '\n\n' + (prospect.notes or '')).strip()


def send_outreach(prospect, subject, body, to=None):
    """Send one outreach email to one prospect and record it as a touch.

    Lifted out of the route so the assistant can use the same code rather than
    a second copy of it. Two implementations of "send an email to a prospect"
    is how one of them quietly stops logging the touch, or stops setting the
    follow-up, and nobody notices until a month of outreach has no trail.

    Returns (ok, sentence). Commits either way: a failed send still needs the
    address saved, or the next attempt asks for it again.
    """
    from datetime import datetime
    from html import escape

    from extensions import db
    import brands
    from notifications import send_email

    to = (to or prospect.email or '').strip()
    subject = (subject or '').strip()
    body = (body or '').strip()
    if not to:
        return False, ('No email address for this business yet — ask for one '
                       'on the call.')
    if not subject or not body:
        return False, 'The email needs a subject and a body.'

    prospect.email = to
    # The commercial identity, not the residential one. Outreach and a
    # customer's booking confirmation should not share a sender reputation:
    # the mail that can be marked as spam is not the mail that has to arrive.
    from_name, from_email, reply_to = brands.send_identity(brands.COMMERCIAL)
    html = ('<div style="font-family:Inter,Arial,sans-serif;font-size:15px;'
            'line-height:1.65;color:#1f1333;white-space:pre-wrap">'
            + escape(body) + '</div>')
    ok, detail = send_email(to, prospect.contact_name or prospect.business_name,
                            subject, html, from_name=from_name,
                            from_email=from_email, reply_to=reply_to)

    if ok:
        prospect.last_emailed_at = datetime.utcnow()
        prospect.notes = note_entry(prospect, f'Emailed — {subject}')
        if prospect.stage in (None, 'new'):
            prospect.stage = 'working'
        # An email is a touch like any other: it earns a follow-up date, or it
        # is just another thing sent into a void.
        prospect.next_action = 'Follow up on the email'
        prospect.next_action_date = _plus(4)
        db.session.commit()
        return True, f'Sent to {to}. Follow up {prospect.next_action_date}.'

    db.session.commit()
    return False, f'Could not send: {detail}'
