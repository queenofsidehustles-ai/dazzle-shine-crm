"""A number the carrier refuses is written down, not retried in silence.

Somebody can opt out of texts by replying STOP to any number -- including one
that was never ours. Twilio then refuses every message to them with error
21610, and the only trace was a failed row in the Sent Log reading "Twilio
error: ... unsubscribed recipient", which looks like a glitch.

Three of Dazzle & Shine's numbers were refused five times each over several
weeks. Nobody knew those people were unreachable, because nothing said so.

What is worth protecting here:

  * a carrier refusal lands on the do-not-text list, so there is a record
  * it is marked 'carrier', not 'stop' -- they did not ask US to stop, and
    that difference matters when the owner asks why
  * the Sent Log says it in words an owner can act on
  * an ordinary Twilio failure is NOT treated as an opt-out, which would
    silently stop texting a customer over a network blip
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/optout.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
import notifications, integrations

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


class FakeTwilioError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def send_raising(exc, to='+14075551234'):
    """Run send_sms with Twilio's client raising exc."""
    import sys as _s, types
    real = _s.modules.get('twilio.rest')
    mod = types.ModuleType('twilio.rest')

    class Client:
        def __init__(self, *a, **k):
            self.messages = self

        def create(self, **k):
            raise exc
    mod.Client = Client
    _s.modules['twilio.rest'] = mod
    try:
        return notifications.send_sms(to, 'Your cleaner is on the way.')
    finally:
        if real is not None:
            _s.modules['twilio.rest'] = real
        else:
            _s.modules.pop('twilio.rest', None)


with app.app_context():
    db.create_all()
    from models import BusinessSetting, SmsOptOut, OutboundLog
    BusinessSetting.set('plan', 'scale')
    BusinessSetting.set('plan_status', 'active')
    for k, v in (('int_twilio_account_sid', 'AC123'),
                 ('int_twilio_auth_token', 'tok'),
                 ('int_twilio_phone', '+16894074848')):
        BusinessSetting.set(k, v)
    db.session.commit()

    print('1. A carrier refusal becomes a record')
    ok, detail = send_raising(FakeTwilioError(
        'HTTP 400 error: Unable to create record: Attempt to send to unsubscribed recipient'))
    check(ok is False, 'the text still fails, as it must')
    row = SmsOptOut.query.filter_by(phone='4075551234').first()
    check(row is not None, 'and the number is on the do-not-text list')
    check(row is not None and row.reason == 'carrier',
          "marked 'carrier' — they never asked us to stop")
    check('opted out of texts with the carrier' in detail,
          'the Sent Log says it in words, not as a provider error')
    check('START' in detail, 'and says how they can undo it')

    print('\n2. By error code as well as by wording')
    ok, detail = send_raising(FakeTwilioError('something else entirely', code=21610),
                              to='+14075559999')
    check(SmsOptOut.query.filter_by(phone='4075559999').first() is not None,
          'code 21610 is enough on its own, whatever the message says')

    print('\n3. An ordinary failure is not an opt-out')
    ok, detail = send_raising(FakeTwilioError('HTTP 500: service unavailable'),
                              to='+14075550000')
    check(ok is False, 'it still fails')
    check(SmsOptOut.query.filter_by(phone='4075550000').first() is None,
          'but a network blip must never silently stop texting a customer')
    check('Twilio error' in detail, 'and the real reason is still recorded')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
