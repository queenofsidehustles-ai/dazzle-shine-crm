"""The page you ask, and the button that acts.

Two routes and a deliberate gap between them. `ask` reads and answers; it never
changes anything. When the answer includes something to do, it comes back as a
proposal with a label, and `confirm` is a separate POST that only accepts
actions from a fixed list.

That gap is the safety. A model cannot reach `confirm` -- it produces the
suggestion, a person produces the click.
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash

import assistant
from auth import login_required, owner_required
from entitlements import requires_plan
from extensions import db

assistant_bp = Blueprint('assistant', __name__)

# Everything a confirmation is allowed to do. Not "whatever the model named" --
# a fixed list, checked here, so a new tool cannot quietly become a new power.
ACTIONS = ('complete_booking',)


@assistant_bp.route('/ask')
@login_required
@owner_required
@requires_plan('assistant')
def page():
    return render_template('admin/assistant.html',
                           name=assistant.NAME,
                           configured=bool(assistant.os.environ.get('OPENROUTER_API_KEY')),
                           left=assistant.remaining(),
                           limit=assistant.MONTHLY_LIMIT)


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
    """Do the thing a person just pressed. Never reached by the model."""
    action = (request.form.get('action') or '').strip()
    if action not in ACTIONS:
        flash('That is not something to confirm.', 'error')
        return redirect(url_for('assistant.page'))

    if action == 'complete_booking':
        from models import Booking
        try:
            booking_id = int(request.form.get('booking_id') or 0)
        except ValueError:
            booking_id = 0
        b = Booking.query.get(booking_id)
        if not b:
            flash('That job is not here any more.', 'error')
        elif b.status not in ('confirmed', 'pending'):
            # Already finished, cancelled or on hold. Saying so is better than
            # silently doing nothing, and better than doing it anyway.
            flash(f'{b.name} is already {b.status.replace("_", " ")}.', 'error')
        else:
            b.status = 'completed'
            db.session.commit()
            flash(f'{b.name} marked finished. Open the job to undo it.', 'success')

    return redirect(url_for('assistant.page'))
