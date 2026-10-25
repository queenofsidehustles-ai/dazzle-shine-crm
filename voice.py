"""Calling a prospect from the call sheet, in the browser, and recording it.

The caller presses Call; the page asks for a ticket (blueprints/voice.py,
`start`) and connects Twilio's Voice SDK with it. Twilio then asks our
/voice/outbound what to do, and we tell it to dial the prospect's number from
the product's own caller ID, with a notice played to the person who answers.

Four things are decided on the server, none of them by the page:

  * WHO is called. The number comes from the prospect row and is carried in a
    signed ticket. The browser never sends a number, so this cannot be turned
    into a dialer for anywhere else.
  * WHEN. 11am-9pm Eastern, which keeps every continental US time zone inside
    8am-9pm, and 8am-9pm local for Alaska and Hawaii numbers. Not for the
    caller's convenience: for the person picking up.
  * WHETHER. Not for anyone marked "don't call again", not while the Calling
    switch in the console is off, and not past MONTHLY_CALLS a company a month.
  * RECORDING. Off unless the owner turns it on. When it is on, the person
    who answers is asked before they are put through, and the call is only
    recorded if they press 1. Silence, or 2, puts the call through unrecorded.
    A notice that a call "may be recorded" is not consent everywhere: several
    states need everybody on the call to agree, so the recording does not
    start until they have (October 2026; it used to start on answer).
    Recordings are kept RECORDING_KEEP_DAYS and then deleted from Twilio,
    can be played by the owner or the person who made the call, and the
    owner can delete one sooner.

Twilio's reports (how it ended, how long, where the recording is) arrive on the
product's host, not the company's, so each carries the signed ticket, which
names the company and the call.
"""
import os
from datetime import datetime

import lead_outreach

MONTHLY_CALLS = int(os.environ.get('VOICE_MONTHLY_CALLS') or 1000)
TICKET_SALT = 'voice-call-ticket'
TICKET_MAX_AGE = 600           # seconds from pressing Call to Twilio asking
CALLBACK_MAX_AGE = 24 * 3600   # Twilio's later reports: a long call, a delayed or retried recording
TOKEN_TTL = 600
RING_SECONDS = 30
RECORDING_KEEP_DAYS = int(os.environ.get('VOICE_RECORDING_KEEP_DAYS') or 90)
CONSENT_SECONDS = 6
# Asked of the person who answers, before they are connected. Recording waits
# for a 1; anything else, including saying nothing, goes ahead unrecorded.
CONSENT_PROMPT = ('Hello. Before we connect you: we would like to record this call '
                  'for quality and training. Press 1 if that is OK. Press 2, or just '
                  'stay on the line, and the call will not be recorded.')
NOT_RECORDED = 'Thank you. This call will not be recorded. Connecting you now.'
RECORDED = 'Thank you. This call will be recorded. Connecting you now.'

# A call that ended in one of these means somebody was not there, whatever
# Twilio's own word for it is.
UNANSWERED = {'no-answer', 'busy', 'failed', 'canceled'}


def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(os.environ.get('SECRET_KEY') or '', salt=TICKET_SALT)


def make_ticket(slug, call_id, to, record):
    return _serializer().dumps({'s': slug or '', 'c': call_id, 'to': to,
                                'rec': bool(record)})


def read_ticket(ticket):
    """The ticket's contents, or None if it is forged, stale or empty."""
    from itsdangerous import BadData
    if not ticket:
        return None
    try:
        data = _serializer().loads(ticket, max_age=CALLBACK_MAX_AGE)
    except BadData:
        return None
    return data if isinstance(data, dict) and 'c' in data and 'to' in data else None


def read_fresh_ticket(ticket):
    """As read_ticket, but only inside the minutes between pressing Call and
    Twilio asking what to do. The later reports use read_ticket: a long call
    ends long after it began."""
    from itsdangerous import BadData
    try:
        data = _serializer().loads(ticket or '', max_age=TICKET_MAX_AGE)
    except BadData:
        return None
    return data if isinstance(data, dict) and 'c' in data and 'to' in data else None


def month_start(now=None):
    now = now or datetime.utcnow()
    return datetime(now.year, now.month, 1)


def calls_this_month(now=None):
    from models import CallLog
    return CallLog.query.filter(CallLog.created_at >= month_start(now)).count()


def calling_hours_block(now_utc=None):
    """Why a call cannot be placed right now, or None. 11am-9pm Eastern."""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    now = (now_utc or datetime.utcnow()).replace(tzinfo=timezone.utc)
    eastern = now.astimezone(ZoneInfo('America/New_York'))
    if 11 <= eastern.hour < 21:
        return None
    return ('calls only go out 11am-9pm Eastern (8am-9pm in every continental '
            f'US time zone); it is {eastern.strftime("%-I:%M %p")} Eastern now')


# Alaska and Hawaii are the two places the Eastern window does not keep inside
# 8am-9pm: 11am Eastern is 7am in Anchorage and 5-6am in Honolulu. Their area
# codes say where the number is, so those calls also wait for local morning.
_FAR_ZONES = {'907': 'America/Anchorage', '808': 'Pacific/Honolulu'}


def local_hours_block(to_number, now_utc=None):
    """Why a number in Alaska or Hawaii cannot be called now, or None."""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    digits = ''.join(ch for ch in (to_number or '') if ch.isdigit())
    zone = _FAR_ZONES.get(digits[-10:-7]) if len(digits) >= 10 else None
    if not zone:
        return None
    now = (now_utc or datetime.utcnow()).replace(tzinfo=timezone.utc)
    local = now.astimezone(ZoneInfo(zone))
    if 8 <= local.hour < 21:
        return None
    return ('calls to Alaska and Hawaii only go out 8am-9pm their time; '
            f'it is {local.strftime("%-I:%M %p")} there now')


def recording_on():
    """Whether calls ask to be recorded. Off until the owner turns it on."""
    from models import BusinessSetting
    return (BusinessSetting.get('call_recording') or '0') == '1'


def refusal(prospect, now_utc=None):
    """Why this prospect cannot be called now, in words, or None."""
    import integrations
    import platform_switches
    if not platform_switches.is_on('voice'):
        return 'Calling is switched off for the whole product right now.'
    if not integrations.voice_ready():
        return 'Calling is not set up yet. Ask support to turn it on.'
    if not lead_outreach.us_number(prospect.phone):
        return 'There is no usable US phone number for this business.'
    if prospect.status == 'do_not_contact':
        return 'This business is marked "don\'t call again".'
    closed = calling_hours_block(now_utc) or local_hours_block(
        lead_outreach.us_number(prospect.phone), now_utc)
    if closed:
        return closed[0].upper() + closed[1:] + '.'
    if calls_this_month(now_utc) >= MONTHLY_CALLS:
        return (f'You have used all {MONTHLY_CALLS} calls for this month. '
                'The count starts again on the 1st.')
    return None


def access_token(identity):
    """The short-lived key the browser connects Twilio's Voice SDK with. It can
    place calls through our TwiML app and nothing else: no incoming calls, no
    account access."""
    import integrations
    from twilio.jwt.access_token import AccessToken
    from twilio.jwt.access_token.grants import VoiceGrant
    token = AccessToken(integrations.twilio_account_sid(),
                        integrations.twilio_api_key_sid(),
                        integrations.twilio_api_key_secret(),
                        identity=identity, ttl=TOKEN_TTL)
    token.add_grant(VoiceGrant(
        outgoing_application_sid=integrations.twilio_twiml_app_sid(),
        incoming_allow=False))
    jwt = token.to_jwt()
    return jwt.decode() if isinstance(jwt, bytes) else jwt


def outbound_twiml(ticket_data, ticket, urls):
    """What Twilio does once the browser connects: ring the prospect.

    `urls` is {'ended', 'recording', 'notice', 'consent'}, each already
    carrying the ticket. Nothing is recorded here: with recording on, the
    person who answers is asked first (notice_twiml), and only a 1 starts it
    (start_recording)."""
    import integrations
    from twilio.twiml.voice_response import VoiceResponse, Dial
    resp = VoiceResponse()
    dial = Dial(caller_id=integrations.twilio_phone(),
                timeout=RING_SECONDS, answer_on_bridge=True,
                action=urls['ended'], method='POST')
    if ticket_data.get('rec'):
        dial.number(ticket_data['to'], url=urls['notice'], method='POST')
    else:
        dial.number(ticket_data['to'])
    resp.append(dial)
    return str(resp)


def notice_twiml(consent_url):
    """Said to the person who answers, before they are put through: may we
    record? A key press goes to `consent_url`; no answer falls through to
    connecting them unrecorded."""
    from twilio.twiml.voice_response import VoiceResponse, Gather
    resp = VoiceResponse()
    ask = Gather(num_digits=1, timeout=CONSENT_SECONDS, action=consent_url, method='POST')
    ask.say(CONSENT_PROMPT, voice='alice')
    resp.append(ask)
    resp.say(NOT_RECORDED, voice='alice')
    return str(resp)


def consent_twiml(agreed):
    from twilio.twiml.voice_response import VoiceResponse
    resp = VoiceResponse()
    resp.say(RECORDED if agreed else NOT_RECORDED, voice='alice')
    return str(resp)


def _twilio_auth():
    import integrations
    sid, token = integrations.twilio_account_sid(), integrations.twilio_auth_token()
    return (sid, token) if sid and token else None


def start_recording(call_sid, callback_url):
    """Start recording the answered call, both sides on separate channels.
    Only ever after the person who answered pressed 1. Returns (ok, detail);
    never raises -- a recording that will not start is not a call that
    should drop."""
    import requests
    auth = _twilio_auth()
    if not auth or not call_sid:
        return False, 'not configured'
    try:
        r = requests.post(
            f'https://api.twilio.com/2010-04-01/Accounts/{auth[0]}/Calls/{call_sid}/Recordings.json',
            data={'RecordingChannels': 'dual', 'RecordingTrack': 'both',
                  'RecordingStatusCallback': callback_url,
                  'RecordingStatusCallbackMethod': 'POST',
                  'RecordingStatusCallbackEvent': 'completed'},
            auth=auth, timeout=10)
    except Exception as e:
        return False, type(e).__name__
    return (r.status_code in (200, 201)), f'HTTP {r.status_code}'


def delete_recording(call, now=None):
    """Delete a call's recording from Twilio and forget it here. A recording
    Twilio no longer has (404) counts as deleted. Returns True when it is
    gone; False leaves it to be tried again."""
    import requests
    if not call.recording_sid:
        return True
    auth = _twilio_auth()
    if not auth:
        return False
    try:
        r = requests.delete(
            f'https://api.twilio.com/2010-04-01/Accounts/{auth[0]}/Recordings/'
            f'{call.recording_sid}.json', auth=auth, timeout=10)
    except Exception:
        return False
    if r.status_code not in (200, 204, 404):
        return False
    call.recording_sid = None
    call.recording_deleted_at = now or datetime.utcnow()
    return True


def purge_old_recordings(now=None):
    """Delete every recording in the current company older than
    RECORDING_KEEP_DAYS. Returns (deleted, failed)."""
    from datetime import timedelta
    from extensions import db
    from models import CallLog
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=RECORDING_KEEP_DAYS)
    deleted = failed = 0
    for call in CallLog.query.filter(CallLog.recording_sid.isnot(None),
                                     CallLog.created_at < cutoff).all():
        if delete_recording(call, now):
            deleted += 1
        else:
            failed += 1
    db.session.commit()
    return deleted, failed


def purge_everywhere(now=None):
    """purge_old_recordings in every company, or the one business on a
    single-company install. One company failing does not stop the rest."""
    from extensions import db
    deleted = failed = 0
    try:
        import control_plane
        import provisioning
        import tenancy
        orgs = control_plane.all_orgs(provisioning._engine())
    except Exception:
        orgs = None
    if not orgs:
        return purge_old_recordings(now)
    import console_data
    for org in orgs:
        slug = org.get('slug')
        if not slug or not console_data.schema_ready(slug):
            continue
        db.session.remove()
        try:
            with tenancy.use_tenant(slug):
                d, f = purge_old_recordings(now)
            deleted, failed = deleted + d, failed + f
        except Exception:
            db.session.rollback()
            failed += 1
        finally:
            db.session.remove()
    return deleted, failed


def hangup_twiml():
    from twilio.twiml.voice_response import VoiceResponse
    resp = VoiceResponse()
    resp.hangup()
    return str(resp)


def record_ended(call, dial_status, seconds, parent_sid):
    """Fill in how a call ended. Idempotent: Twilio retries."""
    call.call_sid = parent_sid or call.call_sid
    call.status = (dial_status or 'completed')[:20]
    try:
        call.duration = int(seconds or 0)
    except (TypeError, ValueError):
        call.duration = 0
    call.ended_at = datetime.utcnow()


def record_recording(call, recording_sid, seconds):
    call.recording_sid = (recording_sid or '')[:64] or call.recording_sid
    try:
        call.recording_seconds = int(seconds or 0)
    except (TypeError, ValueError):
        call.recording_seconds = 0
