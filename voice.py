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
    8am-9pm. Not for the caller's convenience: for the person picking up.
  * WHETHER. Not for anyone marked "don't call again", not while the Calling
    switch in the console is off, and not past MONTHLY_CALLS a company a month.
  * RECORDING. On unless the company turned it off, and when it is on the
    person who answers hears the notice before they are connected. The notice
    is the consent: several states need everybody on the call to agree.

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
TOKEN_TTL = 600
RING_SECONDS = 30
NOTICE = 'This call may be recorded for quality and training purposes.'

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
        data = _serializer().loads(ticket, max_age=TICKET_MAX_AGE * 6)
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
    return ('calls only go out 11am-9pm Eastern (8am-9pm in every US time '
            f'zone); it is {eastern.strftime("%-I:%M %p")} Eastern now')


def recording_on():
    from models import BusinessSetting
    return (BusinessSetting.get('call_recording') or '1') != '0'


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
    closed = calling_hours_block(now_utc)
    if closed:
        return closed.capitalize() + '.'
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

    `urls` is {'ended', 'recording', 'notice'}, each already carrying the
    ticket. Recording starts when they answer and keeps the two sides on
    separate channels, so a call can be reviewed one voice at a time."""
    import integrations
    from twilio.twiml.voice_response import VoiceResponse, Dial
    resp = VoiceResponse()
    dial_args = dict(caller_id=integrations.twilio_phone(),
                     timeout=RING_SECONDS, answer_on_bridge=True,
                     action=urls['ended'], method='POST')
    if ticket_data.get('rec'):
        dial_args.update(record='record-from-answer-dual',
                         recording_status_callback=urls['recording'],
                         recording_status_callback_method='POST',
                         recording_status_callback_event='completed')
    dial = Dial(**dial_args)
    if ticket_data.get('rec'):
        dial.number(ticket_data['to'], url=urls['notice'], method='POST')
    else:
        dial.number(ticket_data['to'])
    resp.append(dial)
    return str(resp)


def notice_twiml():
    from twilio.twiml.voice_response import VoiceResponse
    resp = VoiceResponse()
    resp.say(NOTICE, voice='alice')
    return str(resp)


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
