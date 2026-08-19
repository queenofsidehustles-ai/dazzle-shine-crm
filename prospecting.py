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
from datetime import date, timedelta

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
    'not_interested': ('lost',       None,                            None, True),
    'won':            ('won',        'Convert to a commercial account', 0, True),
}

# The same rules, said in the caller's language for the drawer's quick picks.
QUICK_ACTIONS = [
    ('Call back in 2 days',   2),
    ('Call back in 4 days',   4),
    ('Call back in a week',   7),
    ('Call back in a month', 30),
]


def _plus(days):
    return (date.today() + timedelta(days=days)).isoformat()


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

    return prospect.stage, prospect.next_action, prospect.next_action_date


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
        prospect.next_action_date = date.today().isoformat()
        changed = True
    return changed


def due_counts(prospects):
    today = date.today().isoformat()
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
