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


def transcript():
    """The conversation so far. Each entry: role, content, cards, step?, hidden?

    Until the owner has said anything, the opening line is rebuilt on every
    visit, so it asks about the step that is actually next.

    After that, the chat catches up with work done elsewhere. An owner who
    leaves to share her booking page and ticks it off there comes back to a
    chat that still asks about the booking page -- the step it asked about
    is finished, but nothing told the chat. So when the next step has moved
    on, Nana says so and asks the next question.
    """
    chat = setup_assistant.load_chat()
    if not any(m.get('role') == 'user' for m in chat):
        text, cards, key = setup_assistant.greeting()
        return [{'role': 'assistant', 'content': text, 'cards': cards, 'step': key}]
    last = _last_step(chat)
    nxt = setup_assistant._next_step()
    now = nxt['key'] if nxt else 'done'
    if last and last != now:
        text, cards, key = setup_assistant.next_message(
            'That step is done.' if _was_finished(last) else '')
        chat = chat + [{'role': 'assistant', 'content': text, 'cards': cards, 'step': key}]
        setup_assistant.save_chat(chat)
    return chat


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
    ok, said = setup_assistant.confirm(token)
    follow = ''
    chat = transcript()
    # The card remembers what happened to it, so after a reload it shows the
    # outcome instead of a button that would only say it is already done.
    for m in chat:
        for c in m.get('cards') or []:
            if (c.get('kind') == 'confirm' and token and c.get('token') == token
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
    setup_assistant.skip(step)
    text, cards, key = setup_assistant.next_message('No problem, we can come back to that.')
    chat = transcript() + [
        {'role': 'user', 'content': f'(I skipped the {step} step for now.)', 'hidden': True},
        {'role': 'assistant', 'content': text, 'cards': cards, 'step': key},
    ]
    setup_assistant.save_chat(chat)
    return jsonify({'ok': True, 'say': text, 'cards': cards})


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
