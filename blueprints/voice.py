"""Calling from the call sheet: the page's two endpoints, and Twilio's four.

The page asks `start` for a token and a ticket. Twilio then calls
/voice/outbound (what to do), /voice/notice (said to whoever picks up),
/voice/ended and /voice/recording (what happened). Those four arrive on the
product's host, signature-checked in security.py, and each is tied to one
company and one call by the ticket -- see voice.py.
"""
import contextlib

import requests
from flask import (Blueprint, Response, abort, jsonify, request, session,
                   url_for)

import voice
from auth import login_required, owner_required
from entitlements import requires_plan
from extensions import db
from models import CallLog, Prospect

voice_bp = Blueprint('voice', __name__)


def _xml(body):
    return Response(body, mimetype='text/xml')


@voice_bp.route('/find-leads/call/<int:prospect_id>/start', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def start(prospect_id):
    """Press Call. Writes the call down first, then hands the page what it
    needs to ring. Every refusal is a sentence the caller can act on."""
    import lead_outreach
    p = Prospect.query.get_or_404(prospect_id)
    why = voice.refusal(p)
    if why:
        return jsonify(error=why), 409
    call = CallLog(prospect_id=p.id, user_id=session.get('user_id'),
                   agent=session.get('user_name'),
                   to_number=lead_outreach.us_number(p.phone))
    db.session.add(call)
    db.session.commit()
    slug = _slug()
    ticket = voice.make_ticket(slug, call.id, call.to_number,
                               voice.recording_on())
    identity = f'agent-{session.get("user_id") or 0}'
    try:
        token = voice.access_token(identity)
    except Exception as e:
        call.status = 'failed'
        db.session.commit()
        return jsonify(error=f'Could not start the phone: {e}'), 502
    return jsonify(token=token, ticket=ticket, call_id=call.id,
                   recording=voice.recording_on(),
                   used=voice.calls_this_month(), limit=voice.MONTHLY_CALLS)


def _slug():
    """This request's company, '' on a single-business install."""
    from flask import g
    return getattr(g, 'tenant_slug', '') or ''


@voice_bp.route('/find-leads/call/<int:call_id>/recording')
@login_required
@requires_plan('lead_finder')
def recording(call_id):
    """Play a recording. Twilio keeps it behind our account's login, so it is
    fetched here and passed on, and only to somebody signed in to the company
    that made the call."""
    import integrations
    call = CallLog.query.get_or_404(call_id)
    if not call.recording_sid:
        abort(404)
    sid = integrations.twilio_account_sid()
    token = integrations.twilio_auth_token()
    if not (sid and token):
        abort(404)
    r = requests.get(
        f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Recordings/'
        f'{call.recording_sid}.mp3', auth=(sid, token), timeout=20)
    if r.status_code != 200:
        abort(404)
    return Response(r.content, mimetype='audio/mpeg',
                    headers={'Cache-Control': 'private, no-store'})


# ── Twilio ──────────────────────────────────────────────────────────────────

def _urls(ticket):
    return {key: url_for(f'voice.{endpoint}', t=ticket, _external=True)
            for key, endpoint in (('ended', 'ended'), ('notice', 'notice'),
                                  ('recording', 'recording_ready'))}


@contextlib.contextmanager
def _in_company(data):
    """Run against the company the ticket names."""
    import tenancy
    slug = data.get('s') or ''
    with (tenancy.use_tenant(slug) if slug else contextlib.nullcontext()):
        yield


@voice_bp.route('/voice/outbound', methods=['POST'])
def outbound():
    """The browser has connected; say who to ring. Anything wrong ends the
    call with a hang-up rather than an error Twilio would read aloud."""
    import platform_switches
    ticket = request.form.get('ticket') or ''
    data = voice.read_fresh_ticket(ticket)
    if not data or not platform_switches.is_on('voice'):
        return _xml(voice.hangup_twiml())
    with _in_company(data):
        call = CallLog.query.get(data['c'])
        if not call:
            return _xml(voice.hangup_twiml())
        # Single use: a ticket rings once. The claim is one conditional UPDATE,
        # so two requests with the same ticket cannot both win it, and a
        # replay cannot ring again or slip past the monthly count (it is one
        # CallLog row) or a "don't call again" set since.
        if _stale_since_start(call):
            return _xml(voice.hangup_twiml())
        claimed = (CallLog.query
                   .filter(CallLog.id == call.id, CallLog.call_sid.is_(None))
                   .update({'call_sid': (request.form.get('CallSid') or '')[:64]
                            or 'pending'}))
        db.session.commit()
        if claimed != 1:
            return _xml(voice.hangup_twiml())
    return _xml(voice.outbound_twiml(data, ticket, _urls(ticket)))


def _stale_since_start(call):
    """True if the prospect can no longer be called: marked "don't call
    again", or the hours closed, in the minutes since Call was pressed."""
    p = Prospect.query.get(call.prospect_id) if call.prospect_id else None
    if p is None or p.status == 'do_not_contact':
        return True
    return bool(voice.calling_hours_block() or voice.local_hours_block(call.to_number))


@voice_bp.route('/find-leads/call/recording-setting', methods=['POST'])
@owner_required
def recording_setting():
    """The owner's switch for recording calls. Off means no recording and no
    notice; on is the default."""
    from flask import flash, redirect
    from models import BusinessSetting
    on = request.form.get('recording') == '1'
    BusinessSetting.set('call_recording', '1' if on else '0')
    flash('Calls will be recorded, and the person who answers is told.' if on
          else 'Calls will not be recorded.', 'success')
    return redirect(url_for('places_finder.call_sheet'))


@voice_bp.route('/voice/notice', methods=['POST'])
def notice():
    """Said to the person who picks up, before they are put through."""
    if not voice.read_ticket(request.args.get('t')):
        abort(403)
    return _xml(voice.notice_twiml())


@voice_bp.route('/voice/ended', methods=['POST'])
def ended():
    data = voice.read_ticket(request.args.get('t'))
    if not data:
        abort(403)
    with _in_company(data):
        call = CallLog.query.get(data['c'])
        if call:
            voice.record_ended(call, request.form.get('DialCallStatus'),
                               request.form.get('DialCallDuration'),
                               request.form.get('CallSid'))
            db.session.commit()
    return _xml(voice.hangup_twiml())


@voice_bp.route('/voice/recording', methods=['POST'])
def recording_ready():
    data = voice.read_ticket(request.args.get('t'))
    if not data:
        abort(403)
    with _in_company(data):
        call = CallLog.query.get(data['c'])
        if call:
            voice.record_recording(call, request.form.get('RecordingSid'),
                                   request.form.get('RecordingDuration'))
            db.session.commit()
    return ('', 204)
