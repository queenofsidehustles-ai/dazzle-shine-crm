"""The "what got in the way" survey, for owners who signed up and went quiet.

Two groups, because they stalled in different places and a single question
list would be wrong for both:

    A  never set up    signed up, still no customer and job, a week or more on
    B  went quiet      got it working, then the owner stopped coming back

Segment C (the free plan, barely used) is deliberately not here yet. It is the
group most likely to answer "price", and we would rather read what A and B say
first than ask a third group the same thing.

How it reaches them is one more email kind in trial_nudges.py, `survey`, with
every rule that file has (one a day, never twice, never to a paying, test,
opted-out or closed company, sent as the product). This module owns the rest:

  * who counts as A or B, and the windows in which they are asked
  * the questions, and the signed link that carries "which company, which
    group" so nobody has to sign in to answer
  * saving an answer, and adding it up for the console

An emailed link opens a page with the tapped answer already ticked and does
not record anything. Mail scanners follow every link in a message, and a
survey that counts those clicks reports a bottleneck nobody has. A person
presses the button on the page.

One answer per company. Answering again replaces the row, so a counted answer
is always a counted company.
"""
import os
from datetime import datetime, timedelta

# What each group is asked, in the order shown. Keys are stored; labels are
# what the owner reads. Their words, not ours.
BLOCKERS = [
    ('time', "I didn't have time to set it up"),
    ('start', "I wasn't sure where to start"),
    ('work', 'Adding my customers or cleaners was too much work'),
    ('missing', "It's missing something I need"),
    ('other_tool', "I'm already using something else"),
    ('confusing', 'Something broke or confused me'),
    ('price', "It's too expensive, or I'm not ready to pay"),
    ('paused', "I'm not running the business right now"),
    ('other', 'Something else'),
]
BLOCKER_LABELS = dict(BLOCKERS)

# Where they got stuck: the real setup steps, plus "never got that far".
STUCK = [
    ('client', 'Adding a customer'),
    ('team', 'Adding a cleaner'),
    ('job', 'Putting a job on the calendar'),
    ('booking_page', 'Setting up my booking page'),
    ('payments', 'Getting paid'),
    ('invoices', 'Invoices or quotes'),
    ('none', "I didn't get that far"),
]
STUCK_LABELS = dict(STUCK)

# Which follow-up each answer opens. "Missing" and "other tool" need a name to
# be useful; "broke or confused" needs a place.
FOLLOW_UP = {
    'missing': 'What is it missing?',
    'other_tool': 'What are you using?',
    'confusing': 'Where did it break or confuse you?',
    'other': 'What was it?',
}

# The answers offered as one-tap links inside the email, per group. "Something
# else" is left to the button, which opens the whole form. A company that never
# set up is not asked whether the product is missing something, and one that
# did is not asked whether it knew where to start.
EMAIL_OPTIONS = {
    'A': ['time', 'start', 'work', 'missing', 'other_tool', 'confusing',
          'price', 'paused'],
    'B': ['time', 'work', 'missing', 'other_tool', 'confusing', 'price',
          'paused'],
}

MAX_BLOCKERS = 2
MAX_TEXT = 1000

# How long an emailed link keeps working. Long: somebody who is busy answers a
# week later, and a dead link to a one-minute survey is a lost answer.
LINK_MAX_AGE = timedelta(days=60)
_SALT = 'akye-survey'

# Segment A has to have had time to get set up before "what got in the way" is
# a fair question. Five days, matching the end of the first-week run.
A_MIN_AGE_DAYS = 5
# Segment B is away for two weeks at least. `quiet` (7 to 13) speaks first.
B_MIN_AWAY_DAYS = 14


def segment(org, now=None):
    """'A', 'B' or None for a company, from its record alone.

    Pure. This says who may be asked at all; the window in which they are
    actually asked lives in trial_nudges.due() with every other window.
    "Away" is owner_active_at, never last sign-in (a session renews itself, so
    somebody in every day can show no sign-in for months), and a company with
    no owner_active_at yet is not B rather than being guessed at.
    """
    if not org:
        return None
    now = now or datetime.utcnow()
    if not org.get('activated_at'):
        created = org.get('created_at')
        if created and (now - created).days >= A_MIN_AGE_DAYS:
            return 'A'
        return None
    seen = org.get('owner_active_at')
    if seen and (now - seen).days >= B_MIN_AWAY_DAYS:
        return 'B'
    return None


# ── The signed link ─────────────────────────────────────────────────────────

def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(os.environ.get('SECRET_KEY') or '', salt=_SALT)


def token(slug, seg):
    return _serializer().dumps({'s': slug, 'g': seg})


def read_token(raw):
    """(slug, segment) from a link, or (None, None) when it is bad or old."""
    try:
        data = _serializer().loads(raw, max_age=int(LINK_MAX_AGE.total_seconds()))
        seg = data.get('g')
        if seg not in ('A', 'B'):
            return None, None
        return data.get('s'), seg
    except Exception:
        return None, None


def link(base_url, slug, seg, answer=None):
    """The survey page on that company's own address. With `answer`, the page
    opens with it ticked."""
    url = f'{base_url.rstrip("/")}/survey/{token(slug, seg)}'
    if answer in BLOCKER_LABELS:
        url += f'?a={answer}'
    return url


# ── Saving ──────────────────────────────────────────────────────────────────

def _clean_text(value):
    return (value or '').strip()[:MAX_TEXT]


def clean(form):
    """The answer fields from a submitted form, trimmed to what is allowed.

    Unknown keys are dropped, not rejected: a stale page with an option we
    have since renamed should still save the rest.
    """
    picked = []
    for key in form.getlist('blockers') if hasattr(form, 'getlist') else form.get('blockers', []):
        if key in BLOCKER_LABELS and key not in picked:
            picked.append(key)
    stuck = (form.get('stuck_at') or '').strip()
    return {
        'blockers': ','.join(picked[:MAX_BLOCKERS]),
        'stuck_at': stuck if stuck in STUCK_LABELS else None,
        'other_text': _clean_text(form.get('other_text')),
        'wish': _clean_text(form.get('wish')),
        'wants_call': (form.get('wants_call') or '') == 'yes',
    }


def is_empty(answer):
    """Nothing chosen and nothing written: not worth a row."""
    return not (answer['blockers'] or answer['stuck_at']
                or answer['other_text'] or answer['wish'])


def save(engine, org, seg, answer, now=None):
    """Record one company's answer, replacing any earlier one. Returns True.

    Also writes 'survey' into the company's sent emails, so an owner who
    answers (from this link, or any other) can never be sent the survey email
    afterwards.
    """
    import control_plane
    from sqlalchemy import insert, select, update
    now = now or datetime.utcnow()
    created = org.get('created_at')
    seen = org.get('owner_active_at')
    row = dict(answer)
    row.update(
        segment=seg,
        org_age_days=(now - created).days if created else None,
        days_away=(now - seen).days if seen else None,
        activated=bool(org.get('activated_at')),
        updated_at=now)
    t = control_plane.survey_responses
    with engine.begin() as conn:
        had = conn.execute(select(t.c.id).where(t.c.org_slug == org['slug'])).first()
        if had:
            conn.execute(update(t).where(t.c.org_slug == org['slug']).values(**row))
        else:
            conn.execute(insert(t).values(org_slug=org['slug'], created_at=now, **row))
    sent = {s for s in (org.get('nudges_sent') or '').split(',') if s}
    if 'survey' not in sent:
        control_plane.set_billing(engine, org['slug'],
                                  nudges_sent=','.join(sorted(sent | {'survey'})))
    return True


def existing(engine, slug):
    """This company's earlier answer as a dict, or None."""
    import control_plane
    from sqlalchemy import select
    t = control_plane.survey_responses
    with engine.connect() as conn:
        row = conn.execute(select(t).where(t.c.org_slug == slug)).mappings().first()
    return dict(row) if row else None


# ── Reading, for the console ────────────────────────────────────────────────

def responses(engine, limit=500):
    """Every answer, newest first."""
    import control_plane
    from sqlalchemy import select
    t = control_plane.survey_responses
    try:
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(
                select(t).order_by(t.c.updated_at.desc()).limit(limit)).mappings()]
    except Exception:
        return []


def tally(rows):
    """What got in the way, counted per segment.

    {'A': {'n': 4, 'blockers': [(key, label, count, share)...], 'stuck': [...]}, 'B': ...}

    A company that ticked two blockers counts once in each, so shares are of
    companies, not of ticks, and can add up to more than 100%. Sorted most
    common first, which is the whole point of the page.
    """
    out = {}
    for seg in ('A', 'B'):
        mine = [r for r in rows if r.get('segment') == seg]
        n = len(mine)
        blockers, stuck = {}, {}
        for r in mine:
            for key in (r.get('blockers') or '').split(','):
                if key:
                    blockers[key] = blockers.get(key, 0) + 1
            if r.get('stuck_at'):
                stuck[r['stuck_at']] = stuck.get(r['stuck_at'], 0) + 1

        def ranked(counts, labels):
            rows_ = [(k, labels.get(k, k), c, round(100 * c / n) if n else 0)
                     for k, c in counts.items()]
            return sorted(rows_, key=lambda x: (-x[2], x[1]))
        out[seg] = {'n': n,
                    'blockers': ranked(blockers, BLOCKER_LABELS),
                    'stuck': ranked(stuck, STUCK_LABELS),
                    'calls': sum(1 for r in mine if r.get('wants_call'))}
    return out
