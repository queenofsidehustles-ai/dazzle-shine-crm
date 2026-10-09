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
    # A message left is not the same as a phone that rang out. They know who
    # you are now, so giving them a day to ring back before trying again is
    # the difference between persistent and pestering.
    'voicemail':      ('working',    'Call back — left a message',    3,  True),
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

    # Cold outreach leaves the company's own domain or it does not leave at
    # all. A stranger receiving mail from a company they have never heard of,
    # sent from an address belonging to a company they have ALSO never heard
    # of, is the shape of every phishing email ever written -- and if it is
    # marked as spam often enough, the domain it was sent from stops reaching
    # anybody. On a shared sender that is every other cleaning company's work
    # orders and invoices paying for one company's prospecting.
    #
    # The check is here rather than in the screens because the drawer, the
    # call sheet and the assistant all send through this function, and a rule
    # enforced in two of three places is not a rule.
    #
    # A single-business install has no platform to protect and no registration
    # flow to use: whoever runs the server set FROM_EMAIL and owns the DNS, so
    # the question has already been answered by somebody who could answer it.
    try:
        import product
        hosted = bool(product.domain())
    except Exception:
        hosted = False
    if hosted:
        import email_domains
        if not email_domains.may_send_as(from_email):
            return False, ('Introductions have to come from your own domain, or '
                           'they land in spam. It is a one-time setup in '
                           'Settings → Sending Domain.')
    html = ('<div style="font-family:Inter,Arial,sans-serif;font-size:15px;'
            'line-height:1.65;color:#1f1333;white-space:pre-wrap">'
            + escape(body) + '</div>')
    # Give this message its own return address, so a reply comes back to the
    # record it belongs to instead of disappearing into her inbox while the
    # chase carries on nagging somebody who has already answered.
    try:
        import email_replies
        own = email_replies.address_for(email_replies.current_slug(), prospect.id)
        if own:
            reply_to = own
    except Exception:
        pass        # no return address is survivable; a failed send is not

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


def quote_moved(prospect_id, stage, status, next_action, days, note):
    """Keep a call-list lead in step with what happened to its quote.

    Without this the two drifted apart: a proposal sat in somebody's inbox
    while the call list still said "Book the walkthrough", and a business that
    had signed stayed due a follow-up call. Shared by both kinds of quote -- a
    commercial contract and a residential per-home price -- so they cannot move
    a lead differently. Never fatal: a quote that cannot update its lead is
    still a quote that was sent or accepted. Callers commit.
    """
    if not prospect_id:
        return None
    try:
        from models import Prospect
        p = Prospect.query.get(prospect_id)
        if p is None:
            return None
        # A business that has signed stays signed. Resending an accepted quote,
        # or re-quoting a customer, must not put them back on the call list as
        # a proposal to chase.
        if p.stage == 'won' and stage != 'won':
            return None
        p.stage = stage
        if status:
            p.status = status
        p.next_action = next_action
        p.next_action_date = _plus(days) if days is not None else None
        p.notes = note_entry(p, note)
        return p
    except Exception:
        return None


# ── The walkthrough ────────────────────────────────────────────────────────
#
# What gets ticked on site. Each service knows the line it becomes on the
# contract quote, and -- where the price carries it -- the commercial
# calculator add-on it turns on. Floors and carpets are the clean itself and
# price through the hours; a kitchen, a hood or the restrooms are what make a
# visit take longer than its square footage says.
WALKTHROUGH_SERVICES = [
    # key, label on the checklist, line on the quote, pricing add-on
    ('floors',       'Floors — sweep & mop',          'Floor Care (Sweep & Mop)',  None),
    ('carpet',       'Carpets — vacuum',              'Carpet Cleaning',           None),
    ('restrooms',    'Restrooms',                     'Restroom Sanitation',       'restrooms'),
    ('kitchen',      'Kitchen / break room',          'Kitchen / Break Room',      'breakroom'),
    ('hood',         'Hood & vents — degrease',       'Hood & Vent Degreasing',    'breakroom'),
    ('equipment',    'Equipment wipe-down',           'Equipment Cleaning',        None),
    ('dusting',      'Dusting & surfaces',            'Dusting & Surfaces',        None),
    ('windows',      'Windows & glass',               'Window Cleaning',           None),
    ('trash',        'Trash & liners',                'Trash Removal',             'trash'),
    ('disinfection', 'High-touch disinfection',       'High-Touch Disinfection',   'disinfection'),
    ('strip_wax',    'Floor strip & wax',             'Floor Stripping & Waxing',  None),
]
WALKTHROUGH_SERVICE_KEYS = [k for k, *_ in WALKTHROUGH_SERVICES]

# How often, in the walkthrough's words -> the contract quote's -> the
# commercial calculator's (visits a month).
WALKTHROUGH_FREQUENCIES = [
    ('nightly',   'Every weeknight', 'daily',     'nightly'),
    ('weekly',    'Weekly',          'weekly',    'weekly'),
    ('biweekly',  'Every two weeks', 'biweekly',  'biweekly'),
    ('monthly',   'Monthly',         'monthly',   'monthly'),
    ('one_time',  'One time',        'as_needed', 'custom'),
]


def _num(value, kind=float):
    try:
        v = kind(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def walkthrough(prospect):
    """The walkthrough as a dict, or {} if there has not been one."""
    import json
    try:
        data = json.loads(prospect.walkthrough or '{}')
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def walkthrough_from_form(form):
    """Read the checklist as submitted. Only known keys, numbers as numbers."""
    freq = form.get('frequency')
    return {
        'sqft': _num(form.get('sqft'), int),
        'restrooms': _num(form.get('restrooms'), int),
        'hours': _num(form.get('hours')),
        'frequency': freq if freq in [f[0] for f in WALKTHROUGH_FREQUENCIES] else '',
        'services': [k for k in form.getlist('services') if k in WALKTHROUGH_SERVICE_KEYS],
        'days': (form.get('days') or '').strip()[:120],
        'access': (form.get('access') or '').strip()[:300],
        'contact_on_site': (form.get('contact_on_site') or '').strip()[:120],
        'current_cleaner': (form.get('current_cleaner') or '').strip()[:200],
        'notes': (form.get('notes') or '').strip()[:2000],
    }


def walkthrough_summary(w):
    """One line a person can read: '3,200 sq ft · weekly · floors, restrooms'."""
    labels = dict((k, lbl) for k, lbl, *_ in WALKTHROUGH_SERVICES)
    freq = dict((k, lbl) for k, lbl, *_ in WALKTHROUGH_FREQUENCIES)
    parts = []
    if w.get('sqft'):
        parts.append(f"{w['sqft']:,} sq ft")
    if w.get('restrooms'):
        parts.append(f"{w['restrooms']} restroom{'' if w['restrooms'] == 1 else 's'}")
    if w.get('frequency'):
        parts.append(freq.get(w['frequency'], w['frequency']).lower())
    if w.get('hours'):
        parts.append(f"about {w['hours']:g} h a visit")
    if w.get('services'):
        parts.append(', '.join(labels[k].split(' — ')[0].lower() for k in w['services'] if k in labels))
    return ' · '.join(parts)


def walkthrough_price(prospect, w=None):
    """What the walkthrough says this is worth, through the commercial
    calculator: its own judged hours if given, else the floor area at this
    kind of business's rate. None when there is nothing to price from."""
    import commercial_pricing as cp
    w = w if w is not None else walkthrough(prospect)
    if not (w.get('sqft') or w.get('hours')):
        return None
    calc_freq = {k: c for k, _l, _q, c in WALKTHROUGH_FREQUENCIES}.get(w.get('frequency'), 'weekly')
    extras = sorted({addon for k, _l, _q, addon in WALKTHROUGH_SERVICES
                     if addon and k in (w.get('services') or [])})
    category = prospect.category if prospect.category in cp.PROD_RATES else 'other'
    out = cp.quote(w.get('sqft') or 0, category=category, frequency=calc_freq,
                   extras=extras, hours=w.get('hours'))
    out['by_hours'] = bool(w.get('hours'))
    return out


def walkthrough_quote_prefill(prospect):
    """What the contract quote form should start with, from the walkthrough."""
    w = walkthrough(prospect)
    if not w:
        return {}
    lines = {k: q for k, _l, q, _a in WALKTHROUGH_SERVICES}
    quote_freq = {k: q for k, _l, q, _c in WALKTHROUGH_FREQUENCIES}
    scope = []
    if w.get('services'):
        scope.append('Included: ' + ', '.join(lines[k] for k in w['services'] if k in lines) + '.')
    if w.get('restrooms'):
        scope.append(f"{w['restrooms']} restroom{'' if w['restrooms'] == 1 else 's'}.")
    if w.get('days'):
        scope.append(f"Preferred days/times: {w['days']}.")
    if w.get('access'):
        scope.append(f"Access: {w['access']}.")
    out = {
        'sqft': str(w['sqft']) if w.get('sqft') else '',
        'frequency': quote_freq.get(w.get('frequency'), ''),
        'services': [lines[k] for k in (w.get('services') or []) if k in lines],
        'scope_notes': ' '.join(scope),
    }
    price = walkthrough_price(prospect, w)
    if price:
        out['price_per_visit'] = price['per_visit']
        if w.get('frequency') != 'one_time':
            out['monthly_price'] = price['monthly']
    return out
