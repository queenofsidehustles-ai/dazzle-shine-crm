"""Calling from the call sheet, and the welcome text at signup.

What is worth protecting:

  * the number dialled is the one on the prospect's record -- never one the
    browser sent -- and a forged or stale ticket dials nothing
  * nobody is called outside 8am-9pm their time, after "don't call again", with
    the switch off, or past the monthly limit
  * recording is off until the owner turns it on; with it on, the person who
    answers is asked first and only a 1 starts a recording -- silence or 2
    goes through unrecorded
  * a recording is played only to the owner or the caller, can be deleted by
    the owner, and is deleted from Twilio after RECORDING_KEEP_DAYS
  * Twilio's reports are signature-checked and land on the right call
  * a welcome text goes only to a plainly valid US number, goes at any hour,
    and a failure never raises into the signup
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/voice.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
os.environ.update(TWILIO_ACCOUNT_SID='AC' + 'a' * 32, TWILIO_AUTH_TOKEN='tok123',
                  TWILIO_PHONE='+14075550100', TWILIO_API_KEY_SID='SK' + 'b' * 32,
                  TWILIO_API_KEY_SECRET='sekret', TWILIO_TWIML_APP_SID='AP' + 'c' * 32,
                  PRODUCT_TWILIO_ACCOUNT_SID='AC' + 'd' * 32,
                  PRODUCT_TWILIO_AUTH_TOKEN='ptok', PRODUCT_TWILIO_PHONE='+14075550199')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from twilio.request_validator import RequestValidator
from app import create_app
from extensions import db
from models import Prospect, CallLog, BusinessSetting
import voice, lead_outreach

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


def signed_post(client, path, data):
    url = 'http://localhost' + path
    sig = RequestValidator('tok123').compute_signature(url, data)
    return client.post(path, data=data, headers={'X-Twilio-Signature': sig})


with app.app_context():
    db.create_all()
    BusinessSetting.set('plan', 'scale')
    BusinessSetting.set('plan_status', 'active')
    p = Prospect(business_name='Acme Property', phone='(256) 555-0142')
    nophone = Prospect(business_name='No Phone', phone='12')
    dnc = Prospect(business_name='Never', phone='256-555-0143', status='do_not_contact')
    db.session.add_all([p, nophone, dnc])
    db.session.commit()
    noon = datetime(2026, 10, 20, 17, 0)      # 1pm Eastern
    night = datetime(2026, 10, 21, 2, 0)      # 10pm Eastern

    print('1. Phone numbers and hours')
    check(lead_outreach.us_number('(256) 555-0142') == '+12565550142', 'a US number is normalised')
    check(lead_outreach.us_number('1-256-555-0142') == '+12565550142', 'a leading 1 is dropped')
    check(lead_outreach.us_number('555-0142') is None, 'seven digits is not a number')
    check(lead_outreach.us_number('+44 20 7946 0958') is None, 'a foreign number is refused')
    check(lead_outreach.us_number('056-555-0142') is None, 'an area code cannot start with 0')
    check(voice.calling_hours_block(noon) is None, 'one in the afternoon is fine')
    check(voice.calling_hours_block(night) is not None, 'ten at night is not')

    print('\n2. Who may be called, and when')
    check(voice.refusal(p, noon) is None, 'an ordinary prospect at a good hour')
    check('11am-9pm' in (voice.refusal(p, night) or ''), 'refused outside calling hours')
    check('no usable' in (voice.refusal(nophone, noon) or '').lower(), 'refused with no number')
    check("don't call" in (voice.refusal(dnc, noon) or ''), 'refused after "don\'t call again"')
    old = voice.MONTHLY_CALLS
    voice.MONTHLY_CALLS = 2
    for _ in range(2):
        db.session.add(CallLog(prospect_id=p.id, created_at=datetime(2026, 10, 20, 15)))
    db.session.commit()
    check('all 2 calls' in (voice.refusal(p, datetime(2026, 10, 20, 17)) or ''), 'refused at the monthly limit')
    check(voice.refusal(p, datetime(2026, 11, 2, 17)) is None, 'and fine again next month')
    voice.MONTHLY_CALLS = old
    CallLog.query.delete()
    db.session.commit()

    print('\n3. The ticket and the TwiML')
    t = voice.make_ticket('acme', 7, '+12565550142', True)
    d = voice.read_ticket(t)
    check(d and d['c'] == 7 and d['to'] == '+12565550142' and d['s'] == 'acme', 'a ticket reads back')
    check(voice.read_ticket(t[:-3] + 'xxx') is None, 'a tampered ticket is refused')
    check(voice.read_ticket('') is None and voice.read_ticket(None) is None, 'so is none at all')
    urls = {'ended': 'https://x/voice/ended?t=T', 'recording': 'https://x/voice/recording?t=T',
            'notice': 'https://x/voice/notice?t=T', 'consent': 'https://x/voice/consent?t=T'}
    xml = voice.outbound_twiml(d, t, urls)
    check('+12565550142' in xml and 'callerId="+14075550100"' in xml, 'rings the prospect from our number')
    check('/voice/notice' in xml and 'record=' not in xml,
          'with recording on they are asked first, and nothing records on answer')
    d2 = dict(d, rec=False)
    xml2 = voice.outbound_twiml(d2, t, urls)
    check('record' not in xml2.replace('recording', '') and '/voice/notice' not in xml2,
          'with recording off there is no question and no recording')
    ask = voice.notice_twiml('https://x/voice/consent?t=T')
    check('<Gather' in ask and 'numDigits="1"' in ask and '/voice/consent' in ask and 'Press 1' in ask,
          'the question waits for one key and sends it to /voice/consent')
    check(ask.index('</Gather>') < ask.index('will not be recorded. Connecting'),
          'saying nothing falls through to "will not be recorded"')

    print('\n4. The page: start')
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(logged_in=True, role='owner', user_name='Dana')
    voice.calling_hours_block = lambda now=None: None      # the clock is not under test
    r = c.post(f'/find-leads/call/{p.id}/start', headers={'Origin': 'http://localhost'})
    j = r.get_json() or {}
    check(r.status_code == 200 and j.get('token') and j.get('ticket'), 'start returns a token and a ticket')
    call = CallLog.query.get(j.get('call_id'))
    check(call is not None and call.to_number == '+12565550142', 'the call is written down with the record\'s number')
    r = c.post(f'/find-leads/call/{dnc.id}/start', headers={'Origin': 'http://localhost'})
    check(r.status_code == 409 and "don't call" in (r.get_json() or {}).get('error', ''),
          'a refused prospect gets a sentence, not a call')
    check(CallLog.query.count() == 1, 'and nothing is written down for it')
    anon = app.test_client().post(f'/find-leads/call/{p.id}/start', headers={'Origin': 'http://localhost'})
    check(anon.status_code in (302, 401, 403), 'signed out, you cannot start a call')

    print('\n5. Twilio calling back')
    ticket = j['ticket']
    r = signed_post(app.test_client(), '/voice/outbound', {'ticket': ticket, 'CallSid': 'CA111'})
    check(r.status_code == 200 and b'+12565550142' in r.data, 'outbound rings the number in the ticket')
    check(CallLog.query.get(call.id).call_sid == 'CA111', 'and remembers the call sid')
    r = signed_post(app.test_client(), '/voice/outbound', {'ticket': ticket, 'CallSid': 'CA222'})
    check(r.status_code == 200 and b'<Hangup' in r.data and b'<Dial' not in r.data,
          'the same ticket cannot ring a second time')
    check(CallLog.query.get(call.id).call_sid == 'CA111' and CallLog.query.count() == 1,
          'and it neither changes the call nor adds one')
    r2 = c.post(f'/find-leads/call/{p.id}/start', headers={'Origin': 'http://localhost'})
    t2 = (r2.get_json() or {}).get('ticket')
    p.status = 'do_not_contact'
    db.session.commit()
    r = signed_post(app.test_client(), '/voice/outbound', {'ticket': t2, 'CallSid': 'CA333'})
    check(b'<Hangup' in r.data and b'<Dial' not in r.data,
          'a prospect marked "don\'t call again" after Call was pressed is not rung')
    p.status = 'new'
    CallLog.query.filter(CallLog.id != call.id).delete()
    db.session.commit()
    r = signed_post(app.test_client(), '/voice/outbound', {'ticket': 'junk', 'To': '+19995550000'})
    check(r.status_code == 200 and b'<Hangup' in r.data and b'9995550000' not in r.data,
          'a forged ticket hangs up and dials nothing, whatever number is posted')
    r = app.test_client().post('/voice/outbound', data={'ticket': ticket})
    check(r.status_code == 403, 'an unsigned post is refused')
    r = signed_post(app.test_client(), f'/voice/ended?t={ticket}',
                    {'DialCallStatus': 'completed', 'DialCallDuration': '73', 'CallSid': 'CA111'})
    row = CallLog.query.get(call.id)
    check(r.status_code == 200 and row.status == 'completed' and row.duration == 73, 'the end of the call is recorded')
    r = signed_post(app.test_client(), f'/voice/recording?t={ticket}',
                    {'RecordingSid': 'RE999', 'RecordingDuration': '72'})
    row = CallLog.query.get(call.id)
    check(r.status_code == 204 and row.recording_sid == 'RE999', 'and so is the recording')
    r = signed_post(app.test_client(), '/voice/ended?t=junk', {'DialCallStatus': 'completed'})
    check(r.status_code == 403, 'a report with a forged ticket is refused')
    page = c.get('/find-leads/call')
    check(page.status_code == 200, 'the call sheet renders with the softphone')

    print('\n5b. The review fixes')
    old_ready = os.environ.pop('TWILIO_AUTH_TOKEN')
    import integrations
    check(not integrations.voice_ready(), 'calling is not ready without the auth token')
    check(any('auth' in x.lower() for x in integrations.missing_for('voice')), 'and the token is listed as missing')
    os.environ['TWILIO_AUTH_TOKEN'] = old_ready
    check(voice.read_ticket(voice.make_ticket('a', 1, '+12565550142', True)) is not None, 'a callback ticket is good for the report')
    stale = voice._serializer().dumps({'s': '', 'c': 1, 'to': '+1'})
    check(voice.read_ticket(stale) is not None, 'and a recording callback an hour+ later is still accepted')
    check(voice.read_fresh_ticket(voice.make_ticket('a', 1, '+1', True)) is not None, 'while a fresh ticket still works to start a call')
    check(voice.local_hours_block('+19075550100', datetime(2026, 10, 20, 15, 0)) is not None, '7am in Anchorage is too early')
    check(voice.local_hours_block('+18085550100', datetime(2026, 10, 20, 17, 0)) is not None, '7am in Honolulu is too early')
    check(voice.local_hours_block('+19075550100', datetime(2026, 10, 20, 21, 0)) is None, '1pm in Anchorage is fine')
    check(voice.local_hours_block('+12565550142', datetime(2026, 10, 20, 15, 0)) is None, 'other area codes are on the Eastern window')
    ak = Prospect(business_name='Ak', phone='907-555-0100')
    db.session.add(ak); db.session.commit()
    check('alaska' in (voice.refusal(ak, datetime(2026, 10, 20, 15, 0)) or '').lower(), 'an Alaska prospect is refused at 7am their time')
    cl = CallLog(prospect_id=ak.id, to_number='+19075550100')
    db.session.add(cl); db.session.commit()
    r = c.post(f'/find-leads/{ak.id}/delete', headers={'Origin': 'http://localhost'})
    check(r.status_code in (200, 302) and Prospect.query.get(ak.id) is None, 'a prospect with a call can be removed')
    check(CallLog.query.get(cl.id) is not None and CallLog.query.get(cl.id).prospect_id is None, 'its call stays, pointing nowhere')
    BusinessSetting.query.filter_by(key='call_recording').delete(); db.session.commit()
    check(not voice.recording_on(), 'recording is off until the owner turns it on')
    staff = app.test_client()
    with staff.session_transaction() as s:
        s.update(logged_in=True, role='cleaner', user_name='Sam')
    staff.post('/find-leads/call/recording-setting', data={'recording': '1'}, headers={'Origin': 'http://localhost'})
    check(not voice.recording_on(), 'nobody but the owner can turn it on')
    c.post('/find-leads/call/recording-setting', data={'recording': '1'}, headers={'Origin': 'http://localhost'})
    check(voice.recording_on(), 'the owner can')
    r = c.post('/find-leads/call/recording-setting', data={'recording': '0'}, headers={'Origin': 'http://localhost'})
    check(r.status_code == 302 and not voice.recording_on(), 'and can turn it off again')

    print('\n5c. Consent: only a 1 records')
    started = []
    real_start = voice.start_recording
    voice.start_recording = lambda sid, cb: (started.append((sid, cb)), (True, 'HTTP 201'))[1]
    try:
        yes = CallLog(prospect_id=p.id, user_id=11, to_number='+12565550142'); db.session.add(yes)
        no = CallLog(prospect_id=p.id, user_id=11, to_number='+12565550142'); db.session.add(no)
        db.session.commit()
        ty = voice.make_ticket('', yes.id, yes.to_number, True)
        tn = voice.make_ticket('', no.id, no.to_number, True)
        r = signed_post(app.test_client(), f'/voice/notice?t={ty}', {'CallSid': 'CAchild'})
        check(r.status_code == 200 and b'<Gather' in r.data and b'/voice/consent' in r.data,
              'the person who answers is asked')
        r = signed_post(app.test_client(), f'/voice/consent?t={ty}', {'Digits': '1', 'CallSid': 'CAchild'})
        check(r.status_code == 200 and b'will be recorded' in r.data, 'pressing 1: told it is recorded')
        check(started and started[0][0] == 'CAchild' and '/voice/recording' in started[0][1],
              'and only now does the recording start, on the answered call')
        check(CallLog.query.get(yes.id).recording_consent == 'yes', 'their yes is written down')
        n = len(started)
        r = signed_post(app.test_client(), f'/voice/consent?t={tn}', {'Digits': '2', 'CallSid': 'CAchild2'})
        check(b'will not be recorded' in r.data and len(started) == n, 'pressing 2: no recording')
        check(CallLog.query.get(no.id).recording_consent == 'no', 'and their no is written down')
        r = signed_post(app.test_client(), '/voice/consent?t=junk', {'Digits': '1'})
        check(r.status_code == 403 and len(started) == n, 'a forged consent is refused and records nothing')
        r = app.test_client().post(f'/voice/consent?t={ty}', data={'Digits': '1'})
        check(r.status_code == 403, 'an unsigned consent is refused')
        off = voice.make_ticket('', no.id, no.to_number, False)
        signed_post(app.test_client(), f'/voice/consent?t={off}', {'Digits': '1', 'CallSid': 'CAx'})
        check(len(started) == n, 'a ticket made with recording off never starts one, whatever is pressed')
    finally:
        voice.start_recording = real_start

    print('\n5d. Who hears a recording, and how long it is kept')
    from datetime import timedelta
    yes.recording_sid = 'RE1'; yes.created_at = datetime.utcnow() - timedelta(days=voice.RECORDING_KEEP_DAYS + 1)
    no.recording_sid = 'RE2'; no.created_at = datetime.utcnow() - timedelta(days=3)
    db.session.commit()
    import requests as _rq
    deletes = []

    class _R:
        def __init__(self, code, content=b''): self.status_code, self.content = code, content
    real_get, real_delete = _rq.get, _rq.delete
    _rq.get = lambda *a, **k: _R(200, b'ID3')
    _rq.delete = lambda url, **k: (deletes.append(url), _R(204))[1]
    try:
        import auth
        from models import User

        def signed_in_as(uid, name):
            u = User(id=uid, name=name, username=f'{name.lower()}@x.test', role='sales', active=True)
            u.set_password('pw-long-enough-1') if hasattr(u, 'set_password') else None
            u.password_hash = u.password_hash or 'x'
            db.session.add(u); db.session.commit()
            cl = app.test_client()
            with cl.session_transaction() as s:
                s.update(logged_in=True, role='sales', user_name=name, user_id=uid,
                         auth_fingerprint=auth._auth_fingerprint(u.password_hash))
            return cl
        caller = signed_in_as(11, 'Vee')
        other = signed_in_as(12, 'Kai')
        check(c.get(f'/find-leads/call/{no.id}/recording').status_code == 200, 'the owner can play it')
        check(caller.get(f'/find-leads/call/{no.id}/recording').status_code == 200, 'so can the caller')
        check(other.get(f'/find-leads/call/{no.id}/recording').status_code == 403, 'another salesperson cannot')
        deleted, failed = voice.purge_old_recordings()
        check(deleted == 1 and failed == 0 and any('RE1' in u for u in deletes),
              f'a recording past {voice.RECORDING_KEEP_DAYS} days is deleted from Twilio')
        y = CallLog.query.get(yes.id)
        check(y.recording_sid is None and y.recording_deleted_at, 'and forgotten here, with when')
        check(CallLog.query.get(no.id).recording_sid == 'RE2', 'a recent one is kept')
        caller.post(f'/find-leads/call/{no.id}/recording/delete', headers={'Origin': 'http://localhost'})
        check(CallLog.query.get(no.id).recording_sid == 'RE2', 'the caller cannot delete it')
        c.post(f'/find-leads/call/{no.id}/recording/delete', headers={'Origin': 'http://localhost'})
        check(CallLog.query.get(no.id).recording_sid is None, 'the owner can, at once')
        h = {'X-Api-Key': os.environ.get('REMINDER_API_KEY', '')}
        r = app.test_client().post('/api/recording-retention')
        check(r.status_code == 403, 'the retention job needs the cron key')
    finally:
        _rq.get, _rq.delete = real_get, real_delete

    print('\n6. The welcome text')
    import control_plane, twilio.rest
    sent, logged = [], []

    class FakeClient:
        def __init__(self, sid, tok): pass
        class messages:
            @staticmethod
            def create(body, from_, to):
                sent.append((body, from_, to))
                return type('M', (), {'sid': 'SM1'})()
    twilio.rest.Client = FakeClient
    control_plane.number_text_block = lambda e, ph: None
    control_plane.record_product_message = lambda *a, **k: logged.append(a)
    ok, why = lead_outreach.send_welcome_text(None, 'acme', '(256) 555-0142', 'Dana', 'acme.akyehq.com')
    check(ok and sent and sent[0][2] == '+12565550142', 'a valid number gets the text')
    check('acme.akyehq.com' in sent[0][0] and 'STOP' in sent[0][0], 'it carries the address and how to stop')
    check(sent[0][1] == '+14075550199', "from the product's own number, not a company's")
    check(logged and logged[0][2] == 'welcome_sms', 'and it is written to the log')
    n = len(sent)
    ok, why = lead_outreach.send_welcome_text(None, 'acme', 'not a phone', 'Dana', 'h')
    check(not ok and len(sent) == n, 'a junk number sends nothing')
    control_plane.number_text_block = lambda e, ph: 'replied STOP'
    ok, why = lead_outreach.send_welcome_text(None, 'acme', '256-555-0142', 'Dana', 'h')
    check(not ok and len(sent) == n, 'a number that said STOP is not texted')
    control_plane.number_text_block = lambda e, ph: None
    twilio.rest.Client = lambda *a: (_ for _ in ()).throw(RuntimeError('boom'))
    ok, why = lead_outreach.send_welcome_text(None, 'acme', '256-555-0142', 'Dana', 'h')
    check(not ok and 'boom' in why, 'a Twilio failure is reported, not raised')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
