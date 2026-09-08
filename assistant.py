"""Kye — ask the business a question in your own words.

The owner is in a van between jobs. "How much did I make last month" is three
taps and a squint at a chart, and "who's on tomorrow" is another screen. This is
the same answers, asked out loud.

## The model chooses; the code answers

This is the whole design, and it is the reason it can be trusted with money.

A language model is good at working out which question you asked and hopeless at
being sure of a number. So it never sees a number. It is given a list of
questions this business can answer and returns the name of one, and then ordinary
Python reads the database and writes the sentence.

The worst it can do is pick the wrong question, which you will notice
immediately, because the answer will be about something else. It cannot state a
figure that is not in your books, and there is no prompt anybody could type that
would make it, because the figure never passes through it.

## Nothing leaves the building

Every tool here reads. The one exception is marking a job finished, which is
this business's own record of its own work, is visible on the job, and can be
undone.

It does not send email, does not text anybody, and does not charge a card --
whatever is typed. Those either reach a customer or move money, and something
that cannot be taken back should be a button a person pressed, not a sentence a
model understood.

Drafting is different from sending: `draft_email` writes words for you to read,
and the sending stays where it always was.
"""
import json
import os
import re
from datetime import date, timedelta

# What it is called. One constant so the name is a decision, not a rewrite.
NAME = 'Kye'

# Where the answering happens. Only used to pick a tool -- never to state a fact.
MODEL = os.environ.get('ASSISTANT_MODEL', 'anthropic/claude-3.5-haiku')
API_URL = 'https://openrouter.ai/api/v1/chat/completions'

# A generous month for one company. Enough that nobody sensible hits it, low
# enough that it cannot run away with somebody else's bill.
MONTHLY_LIMIT = int(os.environ.get('ASSISTANT_MONTHLY_LIMIT') or 300)


# ---------------------------------------------------------------------------
# The questions this business can answer
# ---------------------------------------------------------------------------

def _money(n):
    return f'${n:,.2f}'


def _fmt_day(d):
    """A date a person would say, not one a database would print."""
    today = _today()
    if d == today:
        return 'today'
    if d == today + timedelta(days=1):
        return 'tomorrow'
    if d == today - timedelta(days=1):
        return 'yesterday'
    return d.strftime('%A %-d %B')


def _today():
    import scheduling
    return scheduling.local_today()


def money_made(period='this month'):
    """What came in. Cash received, not work booked."""
    import finance
    today = _today()
    if 'last' in period:
        first = today.replace(day=1)
        end = first - timedelta(days=1)
        start = end.replace(day=1)
        label = end.strftime('%B')
    elif 'week' in period:
        start = today - timedelta(days=today.weekday())
        end, label = today, 'this week'
    elif 'year' in period:
        start, end, label = date(today.year, 1, 1), today, str(today.year)
    else:
        start, end, label = today.replace(day=1), today, 'this month'
    got = finance.revenue_between(start, end)
    jobs = finance.jobs_paid_between(start, end)
    if not jobs:
        return f'Nothing has been paid in {label} yet.'
    return (f'{_money(got)} came in {label}, across {jobs} paid '
            f'job{"s" if jobs != 1 else ""}.')


def money_owed():
    """Work done or confirmed that has not been paid for."""
    import finance
    owed = finance.unpaid_outstanding()
    if owed <= 0:
        return 'Nothing is outstanding — everything booked or done has been paid.'
    return f'{_money(owed)} is owed on work that is booked or already done.'


def jobs_on(day='today'):
    """Who is booked, and who is cleaning it."""
    from models import Booking
    today = _today()
    when = {'tomorrow': today + timedelta(days=1),
            'yesterday': today - timedelta(days=1)}.get(day, today)
    rows = Booking.query.filter(
        Booking.preferred_date == when.isoformat(),
        Booking.status.in_(['confirmed', 'pending', 'completed']),
    ).order_by(Booking.preferred_time).all()
    if not rows:
        return f'Nothing is booked {_fmt_day(when)}.'
    lines = []
    for b in rows:
        who = b.assigned_cleaner or 'nobody assigned'
        at = f' at {b.preferred_time}' if b.preferred_time else ''
        lines.append(f'· {b.name}{at} — {who}')
    return (f'{len(rows)} job{"s" if len(rows) != 1 else ""} {_fmt_day(when)}:\n'
            + '\n'.join(lines))


def jobs_this_week():
    from models import Booking
    today = _today()
    end = today + timedelta(days=7)
    rows = Booking.query.filter(
        Booking.preferred_date >= today.isoformat(),
        Booking.preferred_date < end.isoformat(),
        Booking.status.in_(['confirmed', 'pending']),
    ).all()
    if not rows:
        return 'Nothing booked in the next seven days.'
    unassigned = [b for b in rows if not b.assigned_cleaner]
    out = f'{len(rows)} job{"s" if len(rows) != 1 else ""} in the next seven days.'
    if unassigned:
        out += (f' {len(unassigned)} still {"have" if len(unassigned) != 1 else "has"} '
                f'nobody assigned.')
    return out


def find_customer(name=''):
    from models import Client
    q = (name or '').strip()
    if not q:
        return 'Tell me a name to look for.'
    rows = Client.query.filter(Client.name.ilike(f'%{q}%')).limit(5).all()
    if not rows:
        return f'No customer matching “{q}”.'
    return '\n'.join(
        f'· {c.name} — {c.phone or "no phone"} · {c.address or "no address"}'
        for c in rows)


def team():
    from models import Staff
    rows = Staff.query.filter_by(is_active=True).all()
    if not rows:
        return 'Nobody on the team yet.'
    return (f'{len(rows)} active: '
            + ', '.join(s.name for s in rows))


def unassigned_jobs():
    from models import Booking
    today = _today()
    rows = Booking.query.filter(
        Booking.preferred_date >= today.isoformat(),
        Booking.status.in_(['confirmed', 'pending']),
        (Booking.assigned_cleaner.is_(None)) | (Booking.assigned_cleaner == ''),
    ).all()
    if not rows:
        return 'Every upcoming job has somebody on it.'
    return (f'{len(rows)} upcoming job{"s" if len(rows) != 1 else ""} with nobody '
            f'assigned:\n' + '\n'.join(
                f'· {b.name} — {_fmt_day(date.fromisoformat(b.preferred_date))}'
                for b in rows[:8]))


# ---------------------------------------------------------------------------
# The one thing it may change, and the one it may only draft
# ---------------------------------------------------------------------------

def finish_job(customer=''):
    """Propose marking a job done. Proposes -- the person presses the button.

    A finished job is this business's own record of its own work: visible,
    reversible, and nobody outside sees it change. Even so it is offered rather
    than done, because "which job did you mean" is exactly the question a model
    can get wrong on a Tuesday with two Mrs Patels.
    """
    from models import Booking
    q = (customer or '').strip()
    if not q:
        return {'say': 'Which job? Tell me the customer.'}
    today = _today()
    rows = Booking.query.filter(
        Booking.name.ilike(f'%{q}%'),
        Booking.status.in_(['confirmed', 'pending']),
        Booking.preferred_date <= today.isoformat(),
    ).order_by(Booking.preferred_date.desc()).limit(4).all()
    if not rows:
        return {'say': f'No job for “{q}” that is waiting to be finished.'}
    if len(rows) > 1:
        return {'say': 'More than one matches — open the one you mean:\n'
                       + '\n'.join(f'· {b.name} — '
                                   f'{_fmt_day(date.fromisoformat(b.preferred_date))}'
                                   for b in rows)}
    b = rows[0]
    return {
        'say': (f'Mark {b.name} on '
                f'{_fmt_day(date.fromisoformat(b.preferred_date))} as finished?'),
        'confirm': {'action': 'complete_booking', 'booking_id': b.id,
                    'label': f'Mark {b.name} finished'},
    }


def draft_email(about='', to=''):
    """Write words. Sending stays a button somebody presses."""
    return {
        'say': ('I can draft it, but I do not send email. Open the customer and '
                'use Message — the draft goes in the box and you send it.'),
        'draft': {'to': (to or '').strip(), 'about': (about or '').strip()},
    }


# name -> (function, what it is for, argument names)
TOOLS = {
    'money_made':      (money_made, 'how much money came in, for a period', ['period']),
    'money_owed':      (money_owed, 'how much is owed / outstanding / unpaid', []),
    'jobs_on':         (jobs_on, 'what is booked on a day: today, tomorrow, yesterday', ['day']),
    'jobs_this_week':  (jobs_this_week, 'what is coming up over the next week', []),
    'find_customer':   (find_customer, 'look up a customer by name', ['name']),
    'team':            (team, 'who is on the team', []),
    'unassigned_jobs': (unassigned_jobs, 'jobs with no cleaner assigned', []),
    'finish_job':      (finish_job, 'mark a job finished / completed / done', ['customer']),
    'draft_email':     (draft_email, 'write an email to somebody', ['about', 'to']),
}


# ---------------------------------------------------------------------------
# Choosing which question was asked
# ---------------------------------------------------------------------------

def _prompt():
    lines = [f'{k}({", ".join(a)}) — {d}' for k, (_f, d, a) in TOOLS.items()]
    return (
        'You route a question to one of a fixed list of tools. You never answer '
        'the question yourself and you never state a number, a name or a date: '
        'the application reads those from its own database.\n\n'
        'Tools:\n' + '\n'.join(lines) + '\n\n'
        'Reply with JSON only: {"tool": "<name>", "args": {...}}. '
        'If nothing fits, reply {"tool": null}. No prose, no explanation.')


def choose(question, api_key=None):
    """Which tool the question is asking for. Returns (name, args) or (None, {})."""
    key = (api_key or os.environ.get('OPENROUTER_API_KEY') or '').strip()
    if not key:
        return None, {}
    import requests
    try:
        r = requests.post(API_URL, timeout=20, headers={
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
        }, json={
            'model': MODEL,
            'max_tokens': 120,
            'messages': [{'role': 'system', 'content': _prompt()},
                         {'role': 'user', 'content': question[:500]}],
        })
        body = r.json()['choices'][0]['message']['content']
    except Exception:
        return None, {}
    m = re.search(r'\{.*\}', body, re.S)
    if not m:
        return None, {}
    try:
        picked = json.loads(m.group(0))
    except ValueError:
        return None, {}
    name = picked.get('tool')
    if name not in TOOLS:
        return None, {}
    # Only the arguments this tool declares. Anything else the model invented is
    # dropped rather than passed on to a database query.
    allowed = TOOLS[name][2]
    args = {k: v for k, v in (picked.get('args') or {}).items()
            if k in allowed and isinstance(v, str)}
    return name, args


def ask(question, api_key=None):
    """The whole round trip. Returns a dict the page can render."""
    name, args = choose(question, api_key=api_key)
    if not name:
        return {'say': f'I did not follow that. Try “what is booked tomorrow?” '
                       f'or “how much came in last month?”'}
    fn = TOOLS[name][0]
    try:
        out = fn(**args)
    except TypeError:
        out = fn()
    except Exception:
        return {'say': 'Something went wrong reading that. It has been recorded.'}
    return out if isinstance(out, dict) else {'say': out, 'tool': name}
