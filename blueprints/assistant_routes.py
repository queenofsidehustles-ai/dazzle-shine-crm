"""The page you ask, and the button that acts.

Two routes and a deliberate gap between them. `ask` reads and answers; it never
changes anything. When the answer includes something to do, it comes back as a
proposal with a label, and `confirm` is a separate POST that only accepts
actions from a fixed list.

That gap is the safety. A model cannot reach `confirm` -- it produces the
suggestion, a person produces the click.
"""
from flask import (Blueprint, render_template, request, jsonify, redirect,
                   url_for, flash, Response)

import assistant
import speech
from auth import login_required, owner_required
from entitlements import requires_plan
from extensions import db

assistant_bp = Blueprint('assistant', __name__)

# The allowlist lives in actions.py, next to the code that runs each one.
# Two lists in two files drift, and the way this one drifts is that something
# becomes runnable before anybody decided it should be.
from actions import ACTIONS  # noqa: F401  (imported for callers and tests)


@assistant_bp.route('/ask')
@login_required
@owner_required
@requires_plan('assistant')
def page():
    return render_template('admin/assistant.html',
                           name=assistant.NAME,
                           configured=bool(assistant.os.environ.get('OPENROUTER_API_KEY')),
                           left=assistant.remaining(),
                           limit=assistant.MONTHLY_LIMIT,
                           real_voice=speech.configured())


@assistant_bp.route('/ask', methods=['POST'])
@login_required
@owner_required
@requires_plan('assistant')
def ask():
    question = (request.form.get('q') or request.json.get('q', '') if request.is_json
                else request.form.get('q') or '')
    question = (question or '').strip()
    if not question:
        return jsonify({'say': f'Ask {assistant.NAME} something.'})
    out = assistant.ask(question)
    out['left'] = assistant.remaining()
    return jsonify(out)


@assistant_bp.route('/ask/confirm', methods=['POST'])
@login_required
@owner_required
@requires_plan('assistant')
def confirm():
    """Do the thing a person just pressed. Never reached by the model.

    The page posts a token and nothing else. What runs is read back out of the
    proposal that was written down when it was offered, so it is the same thing
    that was on screen -- not whatever the form happened to contain.
    """
    import actions
    import proposals

    token = (request.form.get('token') or '').strip()
    action, payload, row = proposals.take(token)
    if not action:
        # Three different situations, and the person in front of it can act on
        # the difference. "That did not work" is the sentence that makes people
        # stop trusting software.
        flash({
            'already-done': 'That one is already done.',
            'stale': 'That offer is too old to act on now — ask me again and '
                     'I will check it against how things stand.',
        }.get(proposals.why_not(token),
              'That is not something to confirm any more.'), 'error')
        return redirect(url_for('assistant.page'))

    ok, said = actions.run(action, payload)
    proposals.record(row, ('done: ' if ok else 'refused: ') + said)
    flash(said, 'success' if ok else 'error')
    return redirect(url_for('assistant.page'))


@assistant_bp.route('/ask/voice', methods=['POST'])
@login_required
@owner_required
@requires_plan('assistant')
def voice():
    """Audio for a sentence Nana just said, or 204 meaning 'read it yourself'.

    204 is the ordinary answer, not a failure: no key, allowance spent, service
    down. The page hears it and uses the browser voice, and the owner is told
    nothing, because there is nothing they could do about any of it.

    Only text is accepted, and it is spoken as given. Nothing here reads the
    database, so the worst a bad request can do is spend some of this month's
    characters saying something silly back to the person who typed it.
    """
    text = (request.get_json(silent=True) or {}).get('text') or ''
    audio = speech.say(text)
    if not audio:
        return ('', 204)
    return Response(audio, mimetype='audio/mpeg',
                    headers={'Cache-Control': 'no-store'})
