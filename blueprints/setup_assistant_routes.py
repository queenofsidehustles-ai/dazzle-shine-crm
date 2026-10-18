"""The setup chat on the getting-started page: ask, save a card, start over.

`ask` only reads and offers. `confirm` is a separate POST that takes a token
and nothing else, and only runs the four setup actions in setup_assistant.py.
"""
from flask import Blueprint, jsonify, request, session

import setup_assistant
from auth import login_required, owner_required

setup_assistant_bp = Blueprint('setup_assistant', __name__,
                               url_prefix='/settings/getting-started/assistant')

# Display history kept in the cookie session: short, and it belongs to the
# person having the conversation. Each entry is {'role', 'content', 'cards'?}.
MAX_KEPT = 24


def transcript():
    """The conversation so far, starting with the opening line."""
    chat = session.get(setup_assistant.SESSION_KEY)
    if not chat:
        text, link = setup_assistant.greeting()
        chat = [{'role': 'assistant', 'content': text,
                 'cards': [link] if link else []}]
        session[setup_assistant.SESSION_KEY] = chat
    return chat


def _keep(chat):
    # Confirm cards are not carried over a reload: their buttons belong to the
    # moment they were offered, and an old one would only say it expired.
    for m in chat:
        m['cards'] = [c for c in (m.get('cards') or []) if c.get('kind') == 'link']
    session[setup_assistant.SESSION_KEY] = chat[-MAX_KEPT:]


@setup_assistant_bp.route('/ask', methods=['POST'])
@login_required
@owner_required
def ask():
    data = request.get_json(silent=True) or {}
    text = (data.get('q') or request.form.get('q') or '').strip()
    if not text:
        return jsonify({'say': 'Type an answer or a question.', 'cards': []})
    chat = transcript()
    opening = chat[0]['content'] if chat else ''
    out = setup_assistant.ask(text, history=chat, opening=opening)
    chat = chat + [{'role': 'user', 'content': text[:1500]},
                   {'role': 'assistant', 'content': out.get('say', '')[:3000],
                    'cards': out.get('cards') or []}]
    _keep(chat)
    return jsonify(out)


@setup_assistant_bp.route('/confirm', methods=['POST'])
@login_required
@owner_required
def confirm():
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or request.form.get('token') or '').strip()
    ok, said = setup_assistant.confirm(token)
    follow, link = ('', None)
    if ok:
        follow, link = setup_assistant.nudge()
        chat = transcript() + [
            {'role': 'user', 'content': f'(I pressed the button. {said})'},
            {'role': 'assistant', 'content': f'{said} {follow}'.strip(),
             'cards': [link] if link else []},
        ]
        _keep(chat)
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
    session.pop(setup_assistant.SESSION_KEY, None)
    return jsonify({'ok': True})
