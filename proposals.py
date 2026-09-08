"""Offer, approve, execute — in that order, with nothing skippable.

Nana can work out what wants doing. She does not get to do it. Between the
two sits a person reading a sentence and pressing a button, and this file is
that gap made concrete.

## Why a token rather than the thing itself

The obvious design is for the answer to carry what to do -- a job id, an email
address -- and for the page to post it back. It is also wrong, because then what
runs is what the *page* sent, not what the *person read*. Those are the same
thing right up until they are not: a bug, a stale tab, a second window, anybody
who edits a form field.

So the proposal is written down first, and the page is handed a token. Approval
posts the token and nothing else. What executes is read back out of the row that
was on screen, which makes "you approved exactly this" true by construction
instead of by hoping.

## The three rules

1. The model never executes. It picks an action name from a fixed list; the
   code decides what that name means and what arguments it gets.
2. Nothing runs twice. A token is spent on use, so a double-tap, a refresh or a
   replayed request does the work once.
3. Nothing runs later. Offers go stale, because an assistant that will still
   send an email you glanced at yesterday is not one anybody should trust.
"""
import json
import secrets
from datetime import datetime, timedelta

# How long an offer stands. Long enough to read it, take a call and come back;
# short enough that nothing acts on a business as it was this morning.
TTL_MINUTES = 30


def offer(action, payload=None, summary='', label='Confirm', reversible=True,
          asked_by=None):
    """Write down what is being offered and return the token that stands for it.

    Everything a person needs to judge it is stored here rather than rebuilt
    later: the sentence they read, whether it can be undone, and the exact
    arguments. The record is of the decision, not of a reconstruction of it.
    """
    from extensions import db
    from models import AssistantProposal
    row = AssistantProposal(
        token=secrets.token_urlsafe(24),
        action=action,
        payload=json.dumps(payload or {}),
        summary=summary or '',
        label=label or 'Confirm',
        reversible=bool(reversible),
        asked_by=asked_by,
    )
    db.session.add(row)
    db.session.commit()
    return row.token


def take(token):
    """Spend a token. Returns (action, payload, row) or (None, {}, None).

    Spending happens here, before the work runs, so a double-tap cannot do the
    thing twice. The cost of that order is that work which then fails has still
    used the offer up -- which is the right way round: making somebody ask
    again is a smaller harm than sending an email twice.
    """
    from extensions import db
    from models import AssistantProposal
    token = (token or '').strip()
    if not token:
        return None, {}, None
    row = AssistantProposal.query.filter_by(token=token).first()
    if row is None or row.used_at is not None:
        return None, {}, None
    if row.created_at < datetime.utcnow() - timedelta(minutes=TTL_MINUTES):
        return None, {}, None

    row.used_at = datetime.utcnow()
    db.session.commit()
    try:
        payload = json.loads(row.payload or '{}')
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return row.action, payload, row


def record(row, outcome):
    """What actually happened, kept next to what was approved."""
    from extensions import db
    if row is None:
        return
    row.outcome = (outcome or '')[:2000]
    db.session.commit()


def why_not(token):
    """Why a token would not work, for a message that says something useful.

    "That did not work" is the sentence that makes people distrust software.
    Expired, already done and never existed are three different situations and
    the person in front of it can act on the difference.
    """
    from models import AssistantProposal
    row = AssistantProposal.query.filter_by(token=(token or '').strip()).first()
    if row is None:
        return 'gone'
    if row.used_at is not None:
        return 'already-done'
    if row.created_at < datetime.utcnow() - timedelta(minutes=TTL_MINUTES):
        return 'stale'
    return None
