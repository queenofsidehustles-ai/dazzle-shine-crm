"""A message that couldn't be sent must say so. Returning silently made an
unconfigured service look identical to nothing having happened."""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/s.db'
os.environ['SECRET_KEY'] = 'test'
for k in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE', 'RESEND_API_KEY'):
    os.environ.pop(k, None)          # simulate nothing connected
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
from extensions import db
from models import OutboundLog
import notifications
app = create_app()

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

with app.app_context():
    db.create_all()

    print('\n1. An unsent text is recorded, with the reason')
    ok, detail = notifications.send_sms('+15551234567', 'Your cleaner is on the way!')
    check(ok is False, 'send_sms reports failure')
    rows = OutboundLog.query.filter_by(channel='sms').all()
    check(len(rows) == 1, f'it left a row in the Sent Log (got {len(rows)})')
    check(rows[0].status == 'failed', 'marked failed, not silently missing')
    # The reason is written for the owner, not for a developer: it names the
    # missing pieces in plain words and points at the page that fixes them.
    check('Twilio account SID' in (rows[0].detail or '')
          and 'Settings' in (rows[0].detail or ''),
          f'and names what is missing: "{rows[0].detail}"')
    check('on the way' in (rows[0].body or ''), 'the message that never went is kept')

    print('\n2. An unsent email is recorded too')
    ok, detail = notifications.send_email('client@example.com', 'Susan', 'Your receipt', '<p>hi</p>')
    check(ok is False, 'send_email reports failure')
    rows = OutboundLog.query.filter_by(channel='email').all()
    check(len(rows) == 1, 'it left a row')
    check('Email not connected' in (rows[0].detail or ''), 'naming the missing key')

    print('\n3. Missing contact details are recorded, not swallowed')
    os.environ['TWILIO_ACCOUNT_SID'] = 'sid'; os.environ['TWILIO_AUTH_TOKEN'] = 'tok'
    os.environ['TWILIO_PHONE'] = '+15550000'
    ok, _ = notifications.send_sms('', 'nobody to send to')
    check(ok is False, 'no phone number is a failure')
    r = OutboundLog.query.filter_by(channel='sms').order_by(OutboundLog.id.desc()).first()
    check('No phone number' in (r.detail or ''), f'and says so: "{r.detail}"')

    print('\n4. The Sent Log page warns when nothing can go out')
    for k in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE'):
        os.environ.pop(k, None)
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    page = c.get('/messages/sent').get_data(as_text=True)
    check("Messages can't go out" in page, 'the page leads with the warning')
    check('Texting is not connected' in page, 'says texting is down')
    check('Email is not connected' in page, 'says email is down')
    check('Twilio account SID' in page and 'Email' in page,
          'and names exactly which Railway variables are missing')

    print('\n5. When both are connected it says so instead')
    os.environ.update({'TWILIO_ACCOUNT_SID': 'sid', 'TWILIO_AUTH_TOKEN': 'tok',
                       'TWILIO_PHONE': '+15550000', 'RESEND_API_KEY': 'key'})
    page = c.get('/messages/sent').get_data(as_text=True)
    check('Texting and email are both connected' in page, 'green confirmation shows')
    check("Messages can't go out" not in page, 'and the red warning is gone')
    check('failed' in page.lower(), 'past failures are still surfaced')

print('\n🎉 A message that could not be sent now says so.')
