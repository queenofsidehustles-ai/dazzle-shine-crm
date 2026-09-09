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
        '3. Call several tools if the question needs them. Look at what comes '
        'back before deciding what else to ask for.\n'
        '4. When you have enough, answer. Do not narrate what you are about '
        'to do.\n\n'

        'WHAT YOU CANNOT DO\n'
        'You cannot text anybody and cannot charge a card, ever. You can offer '
        'to send one outreach email to one commercial prospect, and that only '
        'becomes real when they read it and press send. Never say you have '
        'sent, texted, booked or charged anything.\n\n'

        'STYLE\n'
        'Short paragraphs, plain words, no headings, no numbered lists, no '
        'exclamation marks, no motivational filler. Name the actual customers, '
        'jobs and companies you found rather than talking in general terms. '
        'If you are giving advice, say what to do first and why it matters '
        'more than the rest. Six sentences is usually plenty; go longer only '
        'when they asked for a plan.'
    )


def run(question, history=None, api_key=None):
    """One question, as many steps as it takes. Returns the dict the page renders."""
    key = (api_key or os.environ.get('OPENROUTER_API_KEY') or '').strip()
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


def _sentences(text):
    import re
    return [p for p in re.split(r'(?<=[.!?])\s+|\n+', text or '') if p.strip()]


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
    assistant._record(f'agent figure not in the tools: {bad[:160]}')
    if retry:
        fixed = retry(bad)
        if fixed and _figures_ok(fixed, sources):
            return _wrap(fixed, proposal)
        if fixed:
            assistant._record('agent could not restate it without the figure')

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
    return line.startswith(('Business name:', 'Based in:', 'Website:',
                            'Phone:', 'Services it books most:',
                            'It does commercial work'))


def _wrap(said, proposal):
    out = {'say': said}
    if proposal:
        out.update(proposal)
    return out
