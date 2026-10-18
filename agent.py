"""Nana, as something that thinks in more than one step.

## What was wrong

The first Nana did exactly one pass: decide which of twelve lookups the
question wanted, run them, write a sentence. She could never look at what came
back and decide to check something else, so every answer was as good as her
first guess and no better. That is why she read like a search box with a
personality bolted on, and it is why "help me plan my month" came back as a
list of figures.

## What this is instead

A loop. She is given the question and a set of tools, calls one, sees the
result, and decides what to do next -- another tool, or an answer. Same shape
as any capable assistant, and the reason one feels like it is paying attention.

## The two rules that did not change

Figures still come from the code. She can ask for a number; she cannot make
one. Everything she writes is checked against what the tools actually returned
before anybody sees it, and an answer with a figure nobody computed is thrown
away unread.

Nothing leaves without a person pressing a button. Actions still come back as
proposals with a token, exactly as before.

## The rule that did change, because it was wrong

She used to be told: say nothing that is not in the facts. That was meant to
stop her inventing revenue. It also stopped her knowing anything -- what
cleaning companies charge for a move-out, how to price a recurring contract,
what to put on a flyer. Those are not the same risk. Getting the going rate
slightly wrong is a conversation; getting last month's takings wrong is a lie
about somebody's business.

So: what is true *of this business* comes from a tool, always. How the world
works, she may simply know, and say so plainly as general knowledge.
"""
import re
import json
import os

import assistant

# How many times round the loop before she has to answer with what she has.
# Enough to look something up, notice it raises a question, and check that too.
# Past this the cost stops buying insight.
MAX_STEPS = int(os.environ.get('ASSISTANT_MAX_STEPS') or 6)

# How much of the conversation she carries. Enough that "those companies" and
# "what about last month?" mean something; short enough that a long session
# does not turn into a long bill.
MEMORY_TURNS = 6


def tool_schema():
    """The tools, in the shape the model expects to be offered them."""
    out = []
    for name, (_fn, what, args) in assistant.TOOLS.items():
        props = {a: {'type': 'string'} for a in args}
        out.append({
            'type': 'function',
            'function': {
                'name': name,
                'description': what,
                'parameters': {'type': 'object', 'properties': props,
                               'required': []},
            },
        })
    return out


def system_prompt(profile):
    return (
        f'You are {assistant.NAME}, the assistant to the owner of a small '
        'cleaning business. You are practical, warm and brief. You are talking '
        'to somebody who is busy running a company, not reading a report.\n\n'

        'THE BUSINESS YOU WORK FOR:\n'
        + ('\n'.join(profile) or '(nothing on file yet)') + '\n\n'

        'HOW TO ANSWER\n'
        '1. Anything true of THIS business — money, jobs, customers, leads, '
        'staff, dates — comes from a tool. Call one. Never guess at it, never '
        'work it out yourself, never estimate it. If a tool cannot tell you, '
        'say you do not have it rather than inventing it.\n'
        '2. Anything about how the world works — what cleaning companies '
        'charge, how to win commercial contracts, what to post, how to handle '
        'a complaint, how to price a recurring clean — you may simply know. '
        'Say it plainly. Say "typically" or "in most areas" where it varies, '
        'and never dress general knowledge up as a fact about their books.\n'
        '3. Call several tools if the question needs them -- independent '
        'lookups together in one turn, at most four at a time. Look at what '
        'comes back before deciding what else to ask for.\n'
        '4. Write nothing before or between tool calls. When you have enough, '
        'write only the final answer.\n\n'

        'WHAT YOU CANNOT DO\n'
        'You cannot text anybody and cannot charge a card, ever. You can offer '
        'to send one outreach email to one commercial prospect, and that only '
        'becomes real when they read it and press send. Never say you have '
        'sent, texted, booked or charged anything.\n\n'

        'STYLE\n'
        'Plain text only: no markdown, no bold, no bullet symbols. '
        'Short paragraphs, plain words, no headings, no numbered lists, no '
        'exclamation marks, no motivational filler. Name the actual customers, '
        'jobs and companies you found rather than talking in general terms. '
        'If you are giving advice, say what to do first and why it matters '
        'more than the rest. Six sentences is usually plenty; go longer only '
        'when they asked for a plan.'
    )


def run(question, history=None, api_key=None):
    """One question, as many steps as it takes. Returns the dict the page renders."""
    import demo_guard
    if demo_guard.active():
        # The main path every question to Nana takes: no platform key for the demo.
        return {'say': assistant.TROUBLE['demo']}
    import llm
    if llm.ready():
        return run_claude(question, history=history)

    key = assistant._api_key(api_key)
    if not key:
        return {'say': assistant.TROUBLE['not-configured']}

    import requests
    profile = assistant.business_profile()
    messages = [{'role': 'system', 'content': system_prompt(profile)}]
    messages.extend(history or [])
    messages.append({'role': 'user', 'content': question[:1000]})

    tools = tool_schema()
    # What the tools actually returned. The business profile is checked
    # against too -- her own phone number is a real fact -- but it is kept
    # apart, because it is context she reads and never something to show.
    seen = []
    proposal = None

    def ask_again(bad_line):
        """One more go, told exactly what was wrong with the last one."""
        try:
            r2 = requests.post(assistant.API_URL, timeout=45, headers={
                'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json'},
                json={'model': assistant.THINK_MODEL, 'max_tokens': 2000,
                      'reasoning': {'effort': 'low'},
                      'messages': messages + [{
                          'role': 'user',
                          'content': (
                              'This sentence states a figure about my business '
                              'that no tool gave you: "' + bad_line + '". Say '
                              'the same thing again without it. Either leave '
                              'the number out, or make plain that it is a '
                              'target rather than something from my books. '
                              'Everything else in your answer was fine — keep '
                              'it.')}]})
            p2 = r2.json()
            return (p2['choices'][0]['message'].get('content') or '').strip()
        except Exception:
            return ''

    for step in range(MAX_STEPS):
        body = {
            'model': assistant.THINK_MODEL,
            'max_tokens': 2000,
            'messages': messages,
            'tools': tools,
            'reasoning': {'effort': 'low'},
        }
        try:
            r = requests.post(assistant.API_URL, timeout=45, headers={
                'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json'}, json=body)
            payload = r.json()
        except Exception as e:
            assistant._record(f'agent could not reach the service: {type(e).__name__}')
            return {'say': assistant.TROUBLE['unreachable']}

        if isinstance(payload.get('error'), dict):
            assistant._record('agent: ' + str(payload['error'].get('message'))[:200])
            return {'say': assistant.TROUBLE['service-error']}
        try:
            choice = payload['choices'][0]
            msg = choice['message']
        except (KeyError, IndexError, TypeError):
            assistant._record(f'agent got an odd reply: {str(payload)[:200]}')
            return {'say': assistant.TROUBLE['service-error']}

        calls = msg.get('tool_calls') or []
        if not calls:
            said = (msg.get('content') or '').strip()
            if not said:
                assistant._record(
                    f'agent said nothing at step {step} '
                    f'(finish_reason={choice.get("finish_reason")})')
                return {'say': assistant.TROUBLE['service-error']}
            return _finish(said, seen + profile, question, proposal,
                           retry=ask_again)

        # She asked for something. Run it, hand back the result, go round again.
        messages.append(msg)
        for call in calls[:4]:
            name, args = _decode(call)
            out, prop = _call_tool(name, args)
            if prop:
                proposal = prop
            if out:
                seen.append(out)
            messages.append({
                'role': 'tool',
                'tool_call_id': call.get('id') or name,
                'content': out or 'nothing found',
            })

    # Out of steps. Say what was found rather than nothing at all.
    return _finish(_plain(seen) or 'I could not get to the bottom of that one.',
                   seen + profile, question, proposal)


# ---------------------------------------------------------------------------
# The same loop, on the Claude API
# ---------------------------------------------------------------------------
#
# Same tools, same rules, same figure check -- only the conversation format
# differs. Claude takes tools as {name, description, input_schema}, answers
# with tool_use blocks, and expects each one answered with a tool_result in
# the next user turn. Its whole reply (thinking included) goes back as-is.

# Gunicorn kills a request at 60 seconds; stop looping well before that.
DEADLINE_SECONDS = 50

# Thinking and the answer share this budget; it is a ceiling, not a charge.
MAX_TOKENS = 6000


# What each argument accepts. A bare "period: string" left the model guessing
# at wording the lookup code would not recognise, and a guess that misses
# quietly answers for the wrong dates.
ARG_HINTS = {
    'period': {'type': 'string', 'description':
               'One of: "this month", "last month", "this week", "this year".'},
    'day': {'type': 'string', 'enum': ['today', 'tomorrow', 'yesterday']},
    'name': {'type': 'string', 'description': 'A person or customer name, as the owner said it.'},
    'customer': {'type': 'string', 'description': 'The customer whose job it is.'},
    'about': {'type': 'string', 'description': 'What the email should say, in the owner\'s words.'},
    'to': {'type': 'string', 'description': 'Who it is for: a customer, lead or company name.'},
}


def claude_tools():
    out = []
    for name, (_fn, what, args) in assistant.TOOLS.items():
        out.append({'name': name, 'description': what,
                    'input_schema': {'type': 'object',
                                     'properties': {a: dict(ARG_HINTS.get(a, {'type': 'string'}))
                                                    for a in args}}})
    if out:
        # The tool list is the same on every call, so it is cached with the
        # system prompt rather than paid for in full each step.
        out[-1]['cache_control'] = {'type': 'ephemeral'}
    return out


def _alternate(history):
    """Stored history -> user/assistant turns that alternate and start with user."""
    msgs = []
    for m in history or []:
        role, text = m.get('role'), (m.get('content') or '').strip()
        if role not in ('user', 'assistant') or not text:
            continue
        if msgs and msgs[-1]['role'] == role:
            msgs[-1]['content'] += '\n\n' + text
        else:
            msgs.append({'role': role, 'content': text})
    while msgs and msgs[0]['role'] != 'user':
        msgs.pop(0)
    if msgs and msgs[-1]['role'] == 'user':
        # The new question follows; two user turns in a row are not allowed.
        msgs.pop()
    return msgs


def run_claude(question, history=None):
    import time
    import llm

    question = (question or '').strip()
    if not question:
        return {'say': f'Ask {assistant.NAME} something.'}
    # Today's date, so "this week" and "overdue" mean something. It sits in
    # the profile so a date she repeats from it passes the figure check.
    profile = assistant.business_profile() + [
        f'Today is {assistant._today():%A %-d %B %Y}.']
    system = llm.cached_system(system_prompt(profile))
    messages = _alternate(history)
    messages.append({'role': 'user', 'content': question[:1000]})
    tools = claude_tools()
    seen = []
    final = ''         # what she wrote on the turn that ended the loop
    proposal = None
    deadline = time.monotonic() + DEADLINE_SECONDS

    def ask_again(bad_line):
        try:
            fix = messages + [{'role': 'assistant', 'content': final or '...'},
                              {'role': 'user', 'content': (
                'This sentence states a figure about my business that no tool '
                'gave you: "' + bad_line + '". Say the same thing again without '
                'it. Either leave the number out, or make plain that it is a '
                'target rather than something from my books. Everything else '
                'in your answer was fine — keep it.')}]
            left = deadline - time.monotonic()
            if left < 5:
                return ''
            # Tools must be declared whenever tool_use blocks are in the
            # history, even when she is not allowed to call one.
            reply = llm.post({'model': llm.SMART_MODEL, 'max_tokens': MAX_TOKENS,
                              'system': system, 'tools': tools,
                              'tool_choice': {'type': 'none'}, 'messages': fix},
                             timeout=min(25, left))
            return llm.text_of(reply)
        except Exception:
            return ''

    def answer_now():
        """Out of steps, or a turn with no words: ask for the answer, no tools."""
        left = deadline - time.monotonic()
        if left < 5:
            return ''
        try:
            reply = llm.post({'model': llm.SMART_MODEL, 'max_tokens': MAX_TOKENS,
                              'system': system, 'tools': tools,
                              'tool_choice': {'type': 'none'},
                              'messages': messages + ([{'role': 'user', 'content':
                                  'Answer my question now with what you found.'}]
                                  if messages[-1]['role'] == 'assistant' else [])},
                             timeout=min(25, left))
            return llm.text_of(reply)
        except Exception:
            return ''

    for step in range(MAX_STEPS):
        left = deadline - time.monotonic()
        if left < 5:
            break
        try:
            reply = llm.post({'model': llm.SMART_MODEL, 'max_tokens': MAX_TOKENS,
                              'system': system, 'tools': tools,
                              'messages': messages}, timeout=min(30, left))
        except llm.ClaudeError as e:
            assistant._record(f'agent (Claude): {e}')
            if seen:
                break
            return {'say': assistant.TROUBLE['unreachable' if isinstance(
                e, llm.ClaudeUnreachable) else 'service-error']}

        content = reply.get('content') or []
        uses = [b for b in content if b.get('type') == 'tool_use']

        if not uses or reply.get('stop_reason') == 'max_tokens':
            # Only this turn's words are the answer. Text from earlier turns
            # was her thinking out loud between lookups.
            final = llm.text_of(reply) if not uses else ''
            if not final:
                final = answer_now()
            if not final:
                assistant._record(f'agent said nothing at step {step} '
                                  f'(stop_reason={reply.get("stop_reason")})')
                if not seen:
                    return {'say': assistant.TROUBLE['service-error']}
                break
            return _finish(final, seen + profile, question, proposal,
                           retry=ask_again)

        messages.append({'role': 'assistant', 'content': content})
        results = []
        for i, b in enumerate(uses):
            if i >= 4:
                # Every call needs an answer or the next request is refused.
                results.append({'type': 'tool_result', 'tool_use_id': b.get('id'),
                                'content': 'Not run: too many at once.',
                                'is_error': True})
                continue
            args = b.get('input') if isinstance(b.get('input'), dict) else {}
            out, prop = _call_tool(b.get('name'), args)
            if prop:
                proposal = prop
            if out:
                seen.append(out)
            results.append({'type': 'tool_result', 'tool_use_id': b.get('id'),
                            'content': out or 'nothing found'})
        messages.append({'role': 'user', 'content': results})

    if not final:
        final = answer_now()
    if final:
        return _finish(final, seen + profile, question, proposal, retry=ask_again)
    return _finish(_plain(seen) or 'I could not get to the bottom of that one.',
                   seen + profile, question, proposal)


def _decode(call):
    fn = (call or {}).get('function') or {}
    name = fn.get('name')
    try:
        args = json.loads(fn.get('arguments') or '{}')
    except ValueError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    return name, args


def _call_tool(name, args):
    """(text for the model, proposal dict or None)."""
    if name not in assistant.TOOLS:
        return 'that is not a tool', None
    allowed = assistant.TOOLS[name][2]
    args = {k: v for k, v in args.items()
            if k in allowed and isinstance(v, str)}
    fn = assistant.TOOLS[name][0]
    try:
        out = fn(**args)
    except TypeError:
        out = fn()
    except Exception:
        return 'that could not be read', None

    if isinstance(out, dict):
        # A draft or a button to press. It travels back to the page as itself,
        # never rewritten by the model on the way out.
        prop = {k: out[k] for k in ('confirm', 'draft') if k in out} or None
        return out.get('say') or '', prop
    return out or '', None


# Words that mark a figure as being about the world rather than about this
# business. "Most companies charge around $150" is general knowledge and is
# allowed to carry a number; "you took $150 last month" is a claim about their
# books and has to have come from a tool.
HEDGES = ('typical', 'usually', 'usual', 'most ', 'many ', 'around', 'roughly',
          'about ', 'average', 'commonly', 'often', 'tend to', 'generally',
          'industry', 'in most', 'a rough', 'ballpark', 'somewhere between',
          'range', 'rule of thumb', 'per hour', 'benchmark')

# A plan is made of numbers that are not facts. "Aim for three contracts" and
# "call five of them this week" are things to do, not claims about the books,
# and blocking them is what turned every game plan back into a wall of
# figures. A target can be wrong without anybody being misled.
GOALS = ('aim ', 'target', 'goal', 'try to', 'try for', 'go after', 'push for',
         'would need', 'you could', 'you should', 'consider', 'if you', 'plan to',
         'next step', 'this week', 'focus on', 'start with', 'book ', 'call ',
         'reach out', 'follow up', 'add ', 'set a', 'shoot for', 'work toward',
         'that would', 'each ', 'per week', 'per day', 'a week', 'a day')


# A list marker is not a figure. "3) Send interview links to the promising
# ones" failed the check because the 3 was nowhere in the tools -- so every
# answer written as a numbered list was thrown away, and logged as an error the
# owner could do nothing about. Only a marker followed by a space counts, so
# "5.5% of jobs" and "3 jobs are unassigned" are still checked as figures.
_LIST_MARKER = re.compile(r'^\s*(?:(?:step\s+)?\(?\d{1,2}[.):](?=\s|$)|[-*•](?=\s))\s*', re.I)


def _sentences(text):
    out = []
    for p in re.split(r'(?<=[.!?])\s+|\n+', text or ''):
        p = _LIST_MARKER.sub('', p, count=1)
        if p.strip():
            out.append(p)
    return out


def _figures_ok(said, sources):
    """Every unhedged figure came from a tool.

    Checking the whole answer at once was too blunt: one sentence of ordinary
    market knowledge -- "most companies charge around $150 for a move-out" --
    would throw away a page of correct advice. So it is checked a sentence at a
    time, and a sentence that visibly presents itself as general knowledge is
    allowed to carry a number.

    The strict half is unchanged and is the half that matters. A sentence
    stating a figure as a fact about this business, with no hedge, must have
    that figure in what the tools returned.
    """
    for line in _sentences(said):
        if assistant._grounded(line, sources):
            continue
        low = line.lower()
        if any(h in low for h in HEDGES):
            continue
        if any(g in low for g in GOALS):
            continue
        return False
    return True


def _unbacked(said, sources):
    """The first sentence that states a figure nobody computed."""
    for line in _sentences(said):
        if assistant._grounded(line, sources):
            continue
        low = line.lower()
        if any(h in low for h in HEDGES) or any(g in low for g in GOALS):
            continue
        return line.strip()
    return ''


def _finish(said, seen, question, proposal, retry=None):
    """Check the figures, then hand it over.

    When one does not check out the answer is not thrown away any more. She is
    told which sentence was the problem and asked once for the same answer
    without it -- because the old behaviour was to fall back to printing the
    raw context, and the raw context includes the business profile she is
    given to read. An owner asking for a game plan got her own phone number
    read back at her, which is worse than any wrong figure would have been.
    """
    sources = seen + [question]
    if _figures_ok(said, sources):
        return _wrap(said, proposal)

    bad = _unbacked(said, sources)
    if retry:
        fixed = retry(bad)
        if fixed and _figures_ok(fixed, sources):
            # Caught and corrected: the check doing its job, not a fault. It
            # used to be recorded as an error anyway, which filled the owner's
            # Errors page -- and the console -- with things nobody could fix.
            return _wrap(fixed, proposal)
    # Recorded only when the owner actually got the fallback below instead of
    # an answer, which is the case worth somebody looking at.
    assistant._record(f'agent figure not in the tools, and not corrected: {bad[:160]}')

    # Still not right. Say what is certain, and never the profile -- that is
    # context for her, not an answer for anybody.
    facts = _plain(seen)
    if facts:
        return _wrap('Here is what I can tell you for certain:\n' + facts,
                     proposal)
    return _wrap('I could not put that together just now. Ask me again, or '
                 'ask me for one piece of it at a time.', proposal)


def _plain(seen):
    """The tool results, once each, with nothing internal in them."""
    out, done = [], set()
    for line in seen:
        line = (line or '').strip()
        # Repeats happen when she calls the same tool twice in a loop, and a
        # thing said twice reads as a fault whatever else is right.
        if not line or line in done or _is_profile(line):
            continue
        done.add(line)
        out.append(line)
    return '\n'.join(out)


def _is_profile(line):
    return line.startswith(('Today is ', 'Business name:', 'Based in:', 'Website:',
                            'Phone:', 'Services it books most:',
                            'It does commercial work'))


def _wrap(said, proposal):
    # The page shows text as text, so markdown would arrive as asterisks.
    said = re.sub(r'\*\*(.+?)\*\*', r'\1', said or '')
    out = {'say': said}
    if proposal:
        out.update(proposal)
    return out
