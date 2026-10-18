"""The setup chat on the getting-started page: ask, save a card, start over.

`ask` only reads and offers. `confirm` is a separate POST that takes a token
and nothing else, and only runs the four setup actions in setup_assistant.py.
"""
from flask import Blueprint, jsonify, request

import setup_assistant
from auth import login_required, owner_required

setup_assistant_bp = Blueprint('setup_assistant', __name__,
                               url_prefix='/settings/getting-started/assistant')


def transcript():
    """The conversation so far. Each entry: role, content, cards, hidden?

    Until the owner has said anything, the opening line is rebuilt on every
    visit, so it asks about the step that is actually next rather than the one
    that was next when the page was first opened.
    """
    chat = setup_assistant.load_chat()
    if not any(m.get('role') == 'user' for m in chat):
        text, link = setup_assistant.greeting()
        chat = [{'role': 'assistant', 'content': text,
                 'cards': [link] if link else []}]
    return chat


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
    follow, link = ('', None)
    chat = transcript()
    # The card remembers what happened to it, so after a reload it shows the
    # outcome instead of a button that would only say it is already done.
    for m in chat:
        for c in m.get('cards') or []:
            if (c.get('kind') == 'confirm' and token and c.get('token') == token
                    and not (c.get('done') or '').startswith('✅')):
                # A second press on a saved card must not overwrite "saved".
                c['done'] = ('✅ ' if ok else '⚠️ ') + said
    if ok:
        follow, link = setup_assistant.nudge()
        chat = chat + [
            # Context for the model, never shown as something the owner typed.
            {'role': 'user', 'content': f'(I pressed the button. {said})', 'hidden': True},
            {'role': 'assistant', 'content': follow, 'cards': [link] if link else []},
        ]
    setup_assistant.save_chat(chat)
    import onboarding
    p = onboarding.progress()
    return jsonify({'ok': ok, 'say': said, 'follow': follow,
                    'cards': [link] if link else [],
                    'progress': {'done': p['done'], 'total': p['total'],
                                 'percent': p['percent']}})


@setup_assistant_bp.route('/reset', methods=['POST'])
@login_required
@owner_required
def reset():
    setup_assistant.clear_chat()
    return jsonify({'ok': True})
