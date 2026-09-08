"""The things Nana can actually do, and the only place they are done.

An action is not a tool. Tools read and answer; an action changes something,
and every one of them arrives here the same way: proposed, read by a person,
approved by a button press, then run.

## Adding one

Write a handler, put it in ACTIONS, and it inherits the whole gate -- the
token, the single use, the expiry, the audit row. There is deliberately no way
to add a capability that skips any of that, because the way capabilities become
dangerous is one exception at a time.

A handler takes the payload that was written down when the offer was made and
returns (ok, sentence). It re-checks everything. The payload was trustworthy
when it was written, but the world moves between the offer and the button: the
job gets finished by somebody else, the customer is deleted, the invoice is
paid. A handler that assumes its arguments are still true is the one that
sends an email about a job that no longer exists.
"""


def complete_booking(payload):
    """Mark a job as finished."""
    from extensions import db
    from models import Booking
    try:
        booking_id = int(payload.get('booking_id') or 0)
    except (TypeError, ValueError):
        return False, 'That job is not here any more.'

    b = db.session.get(Booking, booking_id)
    if not b:
        return False, 'That job is not here any more.'
    if b.status not in ('confirmed', 'pending'):
        # Already finished, cancelled or on hold. Saying so is better than
        # silently doing nothing, and better than doing it anyway.
        return False, f'{b.name} is already {b.status.replace("_", " ")}.'

    b.status = 'completed'
    db.session.commit()
    return True, f'{b.name} marked finished. Open the job to undo it.'


def send_prospect_email(payload):
    """Send the outreach email that was on screen, to the prospect named on it.

    This one leaves the building, which is why the whole gate exists. The words
    approved are the words stored with the offer -- not something the page
    posted back -- so what arrives is what was read.

    Irreversible by nature: an email cannot be recalled. That is why the button
    says so, and why this is one prospect at a time rather than a list.
    """
    from extensions import db
    from models import Prospect
    import prospecting

    try:
        pid = int(payload.get('prospect_id') or 0)
    except (TypeError, ValueError):
        return False, 'That business is not here any more.'
    p = db.session.get(Prospect, pid)
    if not p:
        return False, 'That business is not here any more.'

    return prospecting.send_outreach(
        p, payload.get('subject'), payload.get('body'), to=payload.get('to'))


# name -> (handler, what it is, can it be taken back afterwards)
#
# The third value is the code's judgement, never the model's. It decides how
# the button reads, and a person deserves to know before pressing whether they
# are doing something they can walk back.
ACTIONS = {
    'complete_booking': (complete_booking, 'Mark a job finished', True),
    # False, and it matters: an email cannot be recalled. The page says so
    # above the button because the code says so here.
    'send_prospect_email': (send_prospect_email,
                            'Send an outreach email to one prospect', False),
}


def run(action, payload):
    """Execute an approved action. Returns (ok, sentence)."""
    entry = ACTIONS.get(action)
    if not entry:
        return False, 'That is not something I can do.'
    handler = entry[0]
    try:
        return handler(payload or {})
    except Exception:
        try:
            import errors
            errors.capture(RuntimeError(f'action failed: {action}'),
                           path='/ask/confirm', method='POST')
        except Exception:
            pass
        return False, 'That did not go through. It has been recorded.'
