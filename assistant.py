"""Nana — ask the business a question in your own words.

The owner is in a van between jobs. "How much did I make last month" is three
taps and a squint at a chart, and "who's on tomorrow" is another screen. This is
the same answers, asked out loud.

## The code counts; the model writes; the count is checked

This is the whole design, and it is the reason it can be trusted with money.

A language model is good at working out what you meant and at saying it back
like a person, and hopeless at being sure of a number. So it is never asked for
one. Ordinary Python reads the database and produces the figures; the model is
handed those as facts and writes the answer around them.

It was stricter than this once -- the code wrote the sentences too, so a figure
it had never seen was impossible to say. It was also useless. Asked for a game
plan for the week it answered "1 job in the next seven days", because the
nearest of twelve canned lines was everything it had.

So the guarantee moved from "it never sees a number" to "it never gets to keep
one it made up". Every figure in what it writes must already appear in the facts
it was given or in the question that was asked. If one does not, the written
answer is thrown away unread and the plain computed lines are shown instead.
A wrong figure cannot reach the screen. The worst case is a duller answer than
intended, which is exactly where this started.

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

# What it is called. Akan for an elder -- the person you take a question to,
# which is the job. One constant, so the name stays a decision rather than a
# rewrite.
NAME = 'Nana'

# Where the answering happens. Only used to pick a tool -- never to state a fact.
# Checked against OpenRouter's own model list, not typed from memory. The first
# value here was 'anthropic/claude-3.5-haiku', which does not exist -- every call
# came back an error, the error was swallowed, and every question got the same
# "I did not follow that". A wrong name looked exactly like a stupid assistant.
MODEL = os.environ.get('ASSISTANT_MODEL', 'anthropic/claude-haiku-4.5')
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
    day = _fmt_day(date.fromisoformat(b.preferred_date))
    summary = f'Mark {b.name} on {day} as finished?'
    # Written down before it is offered, so what runs is what was on screen.
    # The page never carries the job id; it carries a token that stands for
    # this whole sentence. See proposals.py.
    import proposals
    token = proposals.offer(
        'complete_booking', {'booking_id': b.id}, summary=summary,
        label=f'Mark {b.name} finished', reversible=True)
    return {
        'say': summary,
        'confirm': {'token': token, 'label': f'Mark {b.name} finished',
                    'reversible': True},
    }


def draft_email(about='', to='', api_key=None):
    """Write the words. Sending stays a button somebody presses.

    The only place a model writes prose here rather than picking a question, so
    it is the only place it could state something untrue. Two things hold it:
    it is handed the facts rather than asked to recall them, and it is told to
    use no others -- no prices, no dates, nothing it was not given. And the
    facts it was given come back with the draft, so the person approving can see
    what it was working from rather than trusting the paragraph.

    It still does not send. A draft somebody read and sent is a different thing
    from an email that left on its own.
    """
    about = (about or '').strip()
    to = (to or '').strip()
    if not about and not to:
        return {'say': 'Who is it to, and what about?'}

    person = _who(to)
    # Who the business is, always. An introduction is written out of what you
    # do, not out of what you already know about them, and until now she was
    # handed only the second kind and told to invent nothing.
    facts = list(business_profile())
    if person:
        facts.append(f'Their name: {person["name"]}')
        facts.append(f'They are a {person["kind"]}')
        if person.get('company'):
            facts.append(f'Company: {person["company"]}')
        if person.get('service'):
            facts.append(f'They asked about: {person["service"]}')
        if person.get('quoted') is not None:
            facts.append(f'They were quoted: {_money(person["quoted"])}')
        if person.get('city'):
            facts.append(f'City: {person["city"]}')
    try:
        import branding
        facts.append(f'Your business: {branding.business_name()}')
    except Exception:
        pass

    key = (api_key or os.environ.get('OPENROUTER_API_KEY') or '').strip()
    if not key:
        return {'say': 'I cannot write it — no writing key is set up on this account.'}

    import requests
    system = (
        'You write a short, plain business email for a cleaning company owner to '
        'send. Warm, direct, no marketing language, no exclamation marks, five '
        'sentences at most.\n\n'
        # The line that mattered, and the one that was wrong. "Invent nothing"
        # with no facts to hand produced a refusal to write at all -- which is
        # right for "tell Rita her price" and absurd for an introduction.
        # The rule is about specifics, not about sentences.
        'Never state a price, a date, an appointment time, a discount or a '
        'promise about their property unless it appears in the facts below. '
        'Where one of those is needed and is not here, write [ ] and let the '
        'owner fill it in.\n\n'
        'You may otherwise write normally: introduce the business, say what it '
        'does, ask for a conversation. Writing an ordinary business email is '
        'the job — an introduction is not made of database facts, and coming '
        'back to say you have none is never the right answer.\n\n'
        'Facts:\n' + ('\n'.join(facts) if facts else
                       '(nothing on file about them — write an introduction)') +
        '\n\nReply with the email body only. No subject line, no signature.')
    try:
        r = requests.post(API_URL, timeout=25, headers={
            'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
        }, json={'model': MODEL, 'max_tokens': 320,
                 'messages': [{'role': 'system', 'content': system},
                              {'role': 'user', 'content': about[:400]}]})
        body = r.json()['choices'][0]['message']['content'].strip()
    except Exception:
        return {'say': 'Could not write it just then. Try again.'}

    who = person['name'] if person else (to or 'them')
    return {
        'say': f'A draft for {who}. Read it before it goes anywhere — '
               f'I do not send email.',
        'draft': {'to': (person or {}).get('email') or to,
                  'body': body, 'facts': facts},
    }


def whats_next():
    """What is worth doing today. Counted, not composed -- see daily_plan.py."""
    import daily_plan
    return daily_plan.as_text()


def leads_waiting():
    """Website enquiries nobody has answered yet.

    The one thing on this list that goes off if you leave it: somebody asked for
    a price and is currently deciding whether you are the sort of company that
    replies.
    """
    from models import Lead
    rows = Lead.query.filter(Lead.status == 'new').order_by(
        Lead.id.desc()).limit(10).all()
    if not rows:
        waiting = Lead.query.filter(Lead.status == 'contacted').count()
        if waiting:
            return (f'No new enquiries. {waiting} you have already replied to and '
                    f'not heard back from.')
        return 'No new enquiries waiting.'
    lines = []
    for l in rows:
        price = f' — quoted {_money(float(l.quoted_price))}' if l.quoted_price else ''
        where = f' · {l.city}' if l.city else ''
        lines.append(f'· {l.name}{where}{price}')
    n = Lead.query.filter(Lead.status == 'new').count()
    head = f'{n} enquir{"y" if n == 1 else "ies"} waiting for a reply'
    return head + ':\n' + '\n'.join(lines)


def commercial_pipeline():
    """Where the commercial work stands: prospects, quotes out, accounts won."""
    from models import Prospect, CommercialQuote, CommercialAccount
    won = CommercialAccount.query.filter(
        CommercialAccount.status == 'active').count()
    quotes = CommercialQuote.query.filter(
        CommercialQuote.status.in_(['sent', 'pending'])).count()

    by_stage = {}
    for p in Prospect.query.all():
        key = (p.stage or p.status or 'not called yet').replace('_', ' ')
        by_stage[key] = by_stage.get(key, 0) + 1

    if not (won or quotes or by_stage):
        return ('Nothing commercial yet. Commercial → Find leads pulls property '
                'managers and offices near you.')

    out = []
    if won:
        out.append(f'{won} account{"s" if won != 1 else ""} won and active')
    if quotes:
        out.append(f'{quotes} quote{"s" if quotes != 1 else ""} out and unanswered')
    for stage, n in sorted(by_stage.items(), key=lambda kv: -kv[1]):
        out.append(f'{n} {stage}')

    due = Prospect.query.filter(
        Prospect.next_action_date.isnot(None),
        Prospect.next_action_date <= _today().isoformat()).count()
    text = 'Commercial: ' + ', '.join(out) + '.'
    if due:
        text += (f'\n{due} {"is" if due == 1 else "are"} due a call back today '
                 f'or earlier.')
    return text


def business_profile():
    """What this business is, in the words somebody would use to describe it.

    Nana knew every number in the books and nothing about the company. That is
    why "draft an intro email to Harbor Realty Group" produced a refusal: the
    only facts she was ever handed were facts about the *recipient*, and an
    introduction is not made of those. It is made of what you do, where, and
    for whom -- which was sitting in settings the whole time, unread.

    Everything here is real and read from this business's own records. Nothing
    is inferred, so a blank stays blank rather than becoming a guess.
    """
    out = []
    try:
        import branding
        name = branding.biz_name()
        if name:
            out.append(f'Business name: {name}')
        where = branding.city_line()
        if where:
            out.append(f'Based in: {where}')
        site = branding.website()
        if site:
            out.append(f'Website: {site}')
        tel = branding.phone()
        if tel:
            out.append(f'Phone: {tel}')
    except Exception:
        pass

    # What it actually sells, taken from the work on the books rather than from
    # a description somebody wrote once and never updated.
    try:
        from models import Booking
        from sqlalchemy import func
        rows = (db_session().query(Booking.service_type, func.count(Booking.id))
                .group_by(Booking.service_type).all())
        kinds = [r[0] for r in sorted(rows, key=lambda r: -r[1]) if r[0]][:5]
        if kinds:
            out.append('Services it books most: ' + ', '.join(kinds))
    except Exception:
        pass

    try:
        from models import CommercialAccount, Prospect
        if CommercialAccount.query.count() or Prospect.query.count():
            out.append('It does commercial work as well as homes')
    except Exception:
        pass
    return out


def db_session():
    from extensions import db
    return db.session


def _who(name):
    """Find one person by name across the places somebody might mean.

    Leads, customers and commercial contacts are different tables and the person
    asking does not think of them that way.
    """
    from models import Lead, Client, CommercialAccount
    q = (name or '').strip()
    if not q:
        return None
    like = f'%{q}%'
    c = Client.query.filter(Client.name.ilike(like)).first()
    if c:
        return {'name': c.name, 'email': c.email, 'kind': 'customer'}
    l = Lead.query.filter(Lead.name.ilike(like)).order_by(Lead.id.desc()).first()
    if l:
        return {'name': l.name, 'email': l.email, 'kind': 'enquiry',
                'quoted': float(l.quoted_price) if l.quoted_price else None,
                'service': l.service_type, 'city': l.city}
    # By the company OR the person. Somebody asking about "Sam" means the
    # contact; somebody asking about "Lakeview" means the account. Searching
    # only the business name found neither half the time.
    a = CommercialAccount.query.filter(
        (CommercialAccount.business_name.ilike(like))
        | (CommercialAccount.contact_name.ilike(like))).first()
    if a:
        return {'name': a.contact_name or a.business_name, 'email': a.email,
                'kind': 'commercial', 'company': a.business_name}

    # Prospects last, and they were missing entirely. This is the commercial
    # list somebody is actually working -- the companies pulled off the map
    # that have not been called yet -- so "draft an email to Harbor Realty
    # Group" looked in three tables, missed the only one it could have been in,
    # and came back with nothing to write from.
    from models import Prospect
    pr = Prospect.query.filter(Prospect.business_name.ilike(like)).first()
    if pr:
        return {'name': pr.business_name, 'email': None, 'kind': 'prospect',
                'company': pr.business_name, 'city': pr.city,
                'stage': (pr.status or 'not called yet').replace('_', ' ')}
    return None


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
    'draft_email':     (draft_email, 'write or draft an email to somebody', ['about', 'to']),
    'whats_next':      (whats_next, 'what to do today / what needs doing / plan my day', []),
    'leads_waiting':   (leads_waiting, 'new website enquiries waiting for a reply', []),
    'commercial_pipeline': (commercial_pipeline,
                            'how the commercial leads, quotes and accounts stand', []),
}


# ---------------------------------------------------------------------------
# Choosing which question was asked
# ---------------------------------------------------------------------------

# Marking a job finished and writing an email are not lookups: one offers a
# button and the other returns a draft. They stay on their own path, alone.
ACTION_TOOLS = ('finish_job', 'draft_email')

# How many lookups one question may pull. "What is my plan this week" honestly
# needs four; past that the answer stops being an answer and becomes a report.
MAX_TOOLS = 4


def _prompt():
    lines = [f'{k}({", ".join(a)}) — {d}' for k, (_f, d, a) in TOOLS.items()]
    return (
        'You pick which of a fixed list of lookups will answer a small cleaning '
        'business owner\'s question. You do not answer it yourself: the '
        'application reads every number, name and date from its own database.\n\n'
        'Lookups:\n' + '\n'.join(lines) + '\n\n'
        'Pick every lookup the question needs, most important first. A narrow '
        'question ("what is owed?") takes one. A broad or planning question '
        '("what is my game plan this week?", "how is the business doing?") takes '
        f'several, up to {MAX_TOOLS} — choose the ones whose facts together '
        'would let somebody answer it properly.\n\n'
        'finish_job and draft_email are actions, not lookups. If the question '
        'asks for one of those, return it alone.\n\n'
        'Reply with JSON only: {"tools": [{"tool": "<name>", "args": {...}}]}. '
        'If nothing fits, reply {"tools": []}. No prose, no explanation.')


def _month_key():
    from datetime import date as _d
    return f'assistant_used_{_d.today():%Y-%m}'


def used_this_month():
    from models import BusinessSetting
    try:
        return int(BusinessSetting.get(_month_key()) or 0)
    except (TypeError, ValueError):
        return 0


def remaining():
    return max(0, MONTHLY_LIMIT - used_this_month())


def _count_one():
    """One more question asked. Written before the call, not after.

    Counting after would mean a call that timed out cost money and counted for
    nothing, which is the direction that lets a bill run away quietly.
    """
    from models import BusinessSetting
    from extensions import db
    BusinessSetting.set(_month_key(), str(used_this_month() + 1))
    db.session.commit()


def _record(detail):
    """Put the real reason somewhere a person can read it.

    The owner should never see this text -- they get a plain sentence. But when
    Nana stops working, the reason has to exist somewhere other than nowhere.
    """
    try:
        import errors
        errors.capture(RuntimeError(f'{NAME}: {detail}'), path='/ask', method='POST')
    except Exception:
        pass


# What the owner is told, by what actually went wrong. Never the same sentence
# twice: each one points at a different thing to go and fix.
TROUBLE = {
    'not-configured': (f'{NAME} is not switched on yet. Add an OpenRouter key in '
                       f'Settings and she will start answering.'),
    'unreachable': (f'I could not reach {NAME} just then — that is the connection, '
                    f'not your question. Try again in a moment.'),
    'service-error': (f'{NAME} is having trouble on her end. It has been recorded '
                      f'and it is not something you have done. Everything else in '
                      f'here works as normal.'),
}


def choose(question, api_key=None):
    """Which lookups the question is asking for.

    Returns (picks, problem), where picks is a list of (name, args) in the
    order they should be read. `problem` is None when the round trip worked,
    whatever the answer was -- so "I did not follow that" is said only when the
    service answered and none of the lookups fit.

    Everything used to collapse into one return and one message. A missing key,
    a model name that does not exist, a network blip and a genuinely odd
    question all produced "I did not follow that", which is how a typo in a
    model name spent an evening looking like a stupid assistant.
    """
    key = (api_key or os.environ.get('OPENROUTER_API_KEY') or '').strip()
    if not key:
        return [], 'not-configured'

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
    except Exception as e:
        _record(f'could not reach the answering service: {type(e).__name__}')
        return [], 'unreachable'

    try:
        payload = r.json()
    except ValueError:
        _record(f'answering service returned {r.status_code}, not JSON')
        return [], 'service-error'

    # OpenRouter reports a bad model or a spent balance as an error object with
    # a 200, so the status code alone is not enough to tell whether it worked.
    if isinstance(payload.get('error'), dict):
        _record('answering service: ' + str(payload['error'].get('message'))[:200])
        return [], 'service-error'
    try:
        body = payload['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        _record(f'unexpected reply from the answering service: {str(payload)[:200]}')
        return [], 'service-error'

    m = re.search(r'\{.*\}', body, re.S)
    if not m:
        return [], None
    try:
        picked = json.loads(m.group(0))
    except ValueError:
        return [], None

    # Accept the old single-tool shape too, so a model that ignores the new
    # instruction still gets an answer rather than a shrug.
    raw = picked.get('tools')
    if raw is None:
        raw = [picked] if picked.get('tool') else []
    if not isinstance(raw, list):
        return [], None

    out = []
    for item in raw[:MAX_TOOLS]:
        if not isinstance(item, dict):
            continue
        name = item.get('tool')
        if name not in TOOLS or any(name == p[0] for p in out):
            continue
        # Only the arguments this tool declares. Anything else the model
        # invented is dropped rather than passed on to a database query.
        allowed = TOOLS[name][2]
        args = {k: v for k, v in (item.get('args') or {}).items()
                if k in allowed and isinstance(v, str)}
        out.append((name, args))
        if name in ACTION_TOOLS:      # an action travels alone
            return [(name, args)], None
    return out, None


# ---------------------------------------------------------------------------
# Writing the answer, without letting it write the figures
#
# The first version of this file had the code write the sentences as well as
# read the numbers. That made a figure it had never seen impossible to say --
# and made Nana useless for any question that was not one of twelve lookups.
# Asked for a game plan for the week she answered "1 job in the next seven
# days", because the nearest of twelve canned lines is all she had.
#
# So the two jobs are split. The code still reads every number out of the
# database; the model never calculates, never counts, never estimates. It is
# handed those facts as text and writes the answer around them.
#
# The guarantee that used to come from the model never seeing a number now
# comes from checking: every figure in what it wrote has to already appear in
# the facts it was given, or in the question the owner asked. Anything else and
# the written answer is thrown away and the plain computed lines are shown
# instead. A wrong number cannot reach the screen; the worst case is a duller
# answer than intended, which is where we started.

_DIGITS = re.compile(r'\d[\d,]*(?:\.\d+)?')

# "two jobs" has to be checked as hard as "2 jobs", or the check is decoration.
_WORD_NUMBERS = {
    'no': '0', 'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
    'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
    'ten': '10', 'eleven': '11', 'twelve': '12',
}


def _canon(tok):
    """$1,450.00 and 1450 are the same figure and must compare equal."""
    t = tok.replace(',', '').lstrip('$')
    if '.' in t:
        t = t.rstrip('0').rstrip('.')
    t = t.lstrip('0') or '0'
    return t


def _numbers(text):
    found = {_canon(m) for m in _DIGITS.findall(text or '')}
    for word, digit in _WORD_NUMBERS.items():
        if re.search(rf'\b{word}\b', (text or ''), re.I):
            found.add(digit)
    return found


# A true figure hung on the wrong month is still a lie: "$450.00 came in in
# July" passes a check that only looks at digits. Months and weekdays are a
# closed set, so they can be held to the same rule as the numbers.
_PERIODS = ('january february march april may june july august september '
            'october november december monday tuesday wednesday thursday '
            'friday saturday sunday').split()


def _periods(text):
    low = (text or '').lower()
    return {w for w in _PERIODS if re.search(rf'\b{w}', low)}


def _grounded(answer, sources):
    """True when every figure and date in `answer` came from somewhere real.

    Names are not checked. A closed set can be checked exactly and an open one
    cannot, and a rule that guesses at proper nouns would throw away good
    answers for saying "Chase". A wrong name is also visible to the person
    reading -- they know their own customers -- in the way a wrong number is
    not, which is the whole reason numbers get the hard rule.
    """
    nums, pers = set(), set()
    for src in sources:
        nums |= _numbers(src)
        pers |= _periods(src)
    return _numbers(answer) <= nums and _periods(answer) <= pers


def _compose(question, facts, api_key=None):
    """Turn the facts into the answer a person would give. None if it can't."""
    key = (api_key or os.environ.get('OPENROUTER_API_KEY') or '').strip()
    if not key:
        return None
    system = (
        f'You are {NAME}, the assistant to the owner of a small cleaning '
        'business. You are talking to them while they are between jobs, so you '
        'are brief and you sound like a person, not a report.\n\n'
        'Answer their question using ONLY the facts below. Every figure, name '
        'and date you write must already appear in them. Do not add up, work '
        'out, estimate or count anything — if a number is not in the facts, it '
        'does not go in your answer, and do not number your points either. '
        'Where the facts do not cover something, say so plainly in a few '
        'words.\n\n'
        'If they asked what to do or how to plan, say which thing to do first '
        'and why it matters — but only about what is in the facts. Never '
        'suggest sending, texting, emailing or charging anything: you cannot '
        'do those and neither should you promise them.\n\n'
        'Three sentences at most. No greeting, no sign-off, no bullet numbers, '
        'no exclamation marks.\n\n'
        'Facts:\n' + '\n'.join(f'· {f}' for f in facts))
    import requests
    try:
        r = requests.post(API_URL, timeout=25, headers={
            'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
        }, json={'model': MODEL, 'max_tokens': 260,
                 'messages': [{'role': 'system', 'content': system},
                              {'role': 'user', 'content': question[:500]}]})
        payload = r.json()
        if isinstance(payload.get('error'), dict):
            _record('writing: ' + str(payload['error'].get('message'))[:200])
            return None
        return (payload['choices'][0]['message']['content'] or '').strip() or None
    except Exception as e:
        _record(f'could not write the answer: {type(e).__name__}')
        return None


def _run(name, args):
    """One lookup. Its own text, or None if it could not be read."""
    fn = TOOLS[name][0]
    try:
        out = fn(**args)
    except TypeError:
        out = fn()
    except Exception:
        return None
    if isinstance(out, dict):
        return out.get('say')
    return out


def ask(question, api_key=None):
    """The whole round trip. Returns a dict the page can render."""
    if remaining() <= 0:
        return {'say': (f'{NAME} has answered {MONTHLY_LIMIT} questions this month, '
                        f'which is the limit. It starts again next month — '
                        f'everything else in here works as normal.')}
    _count_one()
    picks, problem = choose(question, api_key=api_key)
    if problem:
        # Nana never got asked. Saying "I did not follow that" here would blame
        # the owner's wording for something on our side.
        return {'say': TROUBLE[problem]}
    if not picks:
        return {'say': f'I did not follow that one. I can tell you what is booked, '
                       f'what came in, who is owed, who is asking — try '
                       f'“what is booked tomorrow?” or “how much came in last month?”'}

    # An action is offered as itself: a button to press or a draft to read.
    # Nothing gets rewritten on the way out.
    name, args = picks[0]
    if name in ACTION_TOOLS:
        fn = TOOLS[name][0]
        try:
            out = fn(**args)
        except TypeError:
            out = fn()
        except Exception:
            return {'say': 'Something went wrong reading that. It has been recorded.'}
        return out if isinstance(out, dict) else {'say': out, 'tool': name}

    facts, used = [], []
    for name, args in picks:
        text = _run(name, args)
        if text:
            facts.append(text)
            used.append(name)
    if not facts:
        return {'say': 'Something went wrong reading that. It has been recorded.'}

    plain = '\n'.join(facts)
    written = _compose(question, facts, api_key=api_key)
    if written and _grounded(written, facts + [question]):
        return {'say': written, 'tools': used, 'facts': facts}
    if written:
        # It wrote a figure that is not in the books. Nobody sees that figure.
        _record(f'answer dropped, a figure was not in the facts: {written[:160]}')
    return {'say': plain, 'tools': used, 'facts': facts}
