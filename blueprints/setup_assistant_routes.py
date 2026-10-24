"""The setup chat on the getting-started page: ask, save a card, start over.

`ask` only reads and offers. `confirm` is a separate POST that takes a token
and nothing else, and only runs the four setup actions in setup_assistant.py.
"""
from flask import Blueprint, jsonify, request

import setup_assistant
from auth import login_required, owner_required

setup_assistant_bp = Blueprint('setup_assistant', __name__,
                               url_prefix='/settings/getting-started/assistant')


def _last_step(chat):
    """Which step the chat last asked about."""
    for m in reversed(chat):
        if m.get('role') == 'assistant' and m.get('step'):
            return m['step']
    return None


def transcript(catch_up=True):
    """The conversation so far. Each entry: role, content, cards, step?, hidden?

    Until the owner has said anything, the opening line is rebuilt on every
    visit, so it asks about the step that is actually next.

    After that, the chat catches up with work done elsewhere. An owner who
    leaves to share her booking page and ticks it off there comes back to a
    chat that still asks about the booking page -- the step it asked about
    is finished, but nothing told the chat. So when the next step has moved
    on, Nana says so and asks the next question.

    `catch_up=False` is for the routes that have just finished a step
    themselves (confirm, save, skip) and add the next question on their own.
    Catching up there as well asked the next question twice -- the doubled
    "That's the four essentials done" after the last required step.
    """
    chat = setup_assistant.load_chat()
    if not any(m.get('role') == 'user' for m in chat):
        text, cards, key = setup_assistant.greeting()
        return [{'role': 'assistant', 'content': text, 'cards': cards, 'step': key}]
    if not catch_up:
        return chat
    last = _last_step(chat)
    nxt = setup_assistant._next_step()
    now = nxt['key'] if nxt else 'done'
    if last and last != now:
        text, cards, key = setup_assistant.next_message(
            'That step is done.' if _was_finished(last) else '')
        chat = chat + [{'role': 'assistant', 'content': text, 'cards': cards, 'step': key}]
        setup_assistant.save_chat(chat)
    return chat


def for_display(chat):
    """The conversation as the page shows it: finished steps as one ✓ line.

    The stored chat keeps everything, because Nana needs it as context. But
    replaying it card for card put every step the owner had already done back
    on screen, editable, as if it were still waiting -- and when the current
    step had been asked twice, its card showed twice. On screen:

    - a step that is done is a single ✓ line, once, with no card;
    - the step being asked about keeps its card on its latest ask only;
    - Nana's free-text answers stay, but only the newest ones keep cards.
    """
    import onboarding
    steps = onboarding.progress()['steps']
    done = {s['key']: s['title'] for s in steps if s['done']}
    nxt = setup_assistant._next_step()
    current = nxt['key'] if nxt else 'done'
    last = max((i for i, m in enumerate(chat)
                if m.get('role') == 'assistant' and m.get('step') == current),
               default=-1)
    out, ticked = [], set()
    for i, m in enumerate(chat):
        if m.get('hidden'):
            continue
        step = m.get('step') if m.get('role') == 'assistant' else None
        if step and step in done:
            if step not in ticked:
                ticked.add(step)
                out.append({'role': 'assistant', 'tick': f'✓ {done[step]}'})
            continue
        if step == current and i != last:
            continue
        keep_cards = i >= last
        out.append(dict(m, cards=(m.get('cards') or []) if keep_cards else []))
    return out


def _was_finished(step_key):
    import onboarding
    for s in onboarding.progress()['steps']:
        if s['key'] == step_key:
            return bool(s['done'])
    return False


@setup_assistant_bp.route('/ask', methods=['POST'])
@login_required
@owner_required
def ask():
    data = request.get_json(silent=True) or {}
    text = (data.get('q') or request.form.get('q') or '').strip()
    if not text:
        return jsonify({'say': 'Type an answer or a question.', 'cards': []})
    chat = transcript()
    opening = chat[0]['content'] if chat and chat[0].get('role') == 'assistant' else ''
    out = setup_assistant.ask(text, history=chat, opening=opening)
    chat = chat + [{'role': 'user', 'content': text[:1500]},
                   {'role': 'assistant', 'content': (out.get('say') or '')[:3000],
                    'cards': out.get('cards') or []}]
    setup_assistant.save_chat(chat)
    return jsonify(out)


@setup_assistant_bp.route('/confirm', methods=['POST'])
@login_required
@owner_required
def confirm():
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or request.form.get('token') or '').strip()
    # The chat as it stood BEFORE the press. Read after it, a chat the owner
    # has not typed into yet is rebuilt from scratch -- an opening line about
    # the step that is now next -- and the next question was then added under
    # it: the same card twice.
    chat = transcript(catch_up=False)
    ok, said = setup_assistant.confirm(token)
    follow = ''
    # The card remembers what happened to it, so after a reload it shows the
    # outcome instead of a button that would only say it is already done.
    for m in chat:
        for c in m.get('cards') or []:
            mine = (c.get('kind') == 'confirm' and c.get('token') == token) or (
                c.get('kind') == 'choice'
                and any(o.get('token') == token for o in c.get('options') or []))
            if (mine and token
                    and not (c.get('done') or '').startswith('✅')):
                # A second press on a saved card must not overwrite "saved".
                c['done'] = ('✅ ' if ok else '⚠️ ') + said
    cards = []
    if ok:
        follow, cards, key = setup_assistant.next_message()
        chat = chat + [
            # Context for the model, never shown as something the owner typed.
            {'role': 'user', 'content': f'(I pressed the button. {said})', 'hidden': True},
            {'role': 'assistant', 'content': follow, 'cards': cards, 'step': key},
        ]
    setup_assistant.save_chat(chat)
    import onboarding
    p = onboarding.progress()
    return jsonify({'ok': ok, 'say': said, 'follow': follow,
                    'cards': cards,
                    'progress': {'done': p['done'], 'total': p['total'],
                                 'percent': p['percent']}})


@setup_assistant_bp.route('/save', methods=['POST'])
@login_required
@owner_required
def save():
    """Save an editable card's boxes. Like confirm, but the values come from
    the form and are validated server-side, not replayed from a token."""
    data = request.get_json(silent=True) or {}
    step = (data.get('step') or '').strip()
    fields = data.get('fields') or {}
    import onboarding
    if step not in {s['key'] for s in onboarding.progress()['steps']}:
        return jsonify({'ok': False, 'say': 'That step is not on your list.',
                        'cards': []})
    chat = transcript(catch_up=False)   # before the save; see confirm()
    ok, said = setup_assistant.save_form(step, fields)
    follow, cards = '', []
    if ok:
        follow, cards, key = setup_assistant.next_message()
        chat = chat + [
            {'role': 'user', 'content': f'(I saved my {step} details.)', 'hidden': True},
            {'role': 'assistant', 'content': follow, 'cards': cards, 'step': key},
        ]
        setup_assistant.save_chat(chat)
    p = onboarding.progress()
    return jsonify({'ok': ok, 'say': said, 'follow': follow, 'cards': cards,
                    'progress': {'done': p['done'], 'total': p['total'],
                                 'percent': p['percent']}})


@setup_assistant_bp.route('/skip', methods=['POST'])
@login_required
@owner_required
def skip():
    """Not now. The chat moves on; the getting-started list keeps the step."""
    data = request.get_json(silent=True) or {}
    step = (data.get('step') or '').strip()
    import onboarding
    if step not in {s['key'] for s in onboarding.progress()['steps']}:
        return jsonify({'ok': False, 'say': '', 'cards': []})
    chat = transcript(catch_up=False)   # before the skip; see confirm()
    setup_assistant.skip(step)
    text, cards, key = setup_assistant.next_message('No problem, we can come back to that.')
    chat = chat + [
        {'role': 'user', 'content': f'(I skipped the {step} step for now.)', 'hidden': True},
        {'role': 'assistant', 'content': text, 'cards': cards, 'step': key},
    ]
    setup_assistant.save_chat(chat)
    return jsonify({'ok': True, 'say': text, 'cards': cards})


@setup_assistant_bp.route('/team-file', methods=['POST'])
@login_required
@owner_required
def team_file():
    """Read a spreadsheet of cleaners into the team card. Saves nothing.

    The rows come back to the card as boxes the owner can see and correct;
    the card's own Save is still the only thing that writes, with the same
    checks as rows typed by hand."""
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'say': 'Choose a file first.', 'rows': []})
    rows, err = setup_assistant.read_team_file(f.filename, f.read(2_000_001))
    if err:
        return jsonify({'ok': False, 'say': err, 'rows': []})
    n = len(rows)
    return jsonify({'ok': True, 'rows': rows,
                    'say': f'Found {n} cleaner{"" if n == 1 else "s"}. Check them, '
                           f'then press Save my team.'})


@setup_assistant_bp.route('/reset', methods=['POST'])
@login_required
@owner_required
def reset():
    setup_assistant.clear_chat()
    # Starting over brings skipped steps back too.
    from extensions import db
    from models import BusinessSetting
    BusinessSetting.set(setup_assistant.SKIPPED_KEY, '')
    db.session.commit()
    return jsonify({'ok': True})
