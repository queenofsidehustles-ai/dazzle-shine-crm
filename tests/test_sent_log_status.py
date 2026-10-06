"""What the Sent Log says happened, against what actually happened.

Asking Twilio to report delivery was supposed to make this screen honest:
"sent" had only ever meant the provider accepted the message, which is not the
same as it arriving and reads exactly as though it were.

It made it dishonest in the other direction instead. The receipts write
delivered, undelivered, queued and sending; the page tested for the single
word "sent" and called everything else a failure -- so twenty-two texts that
reached somebody's phone were drawn as red failures, with "Twilio: delivered."
printed underneath them.

A delivery receipt that makes a delivered message look failed is worse than no
receipt at all: the first costs trust in the whole screen, the second only
leaves a question open.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/sentlog.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


with app.app_context():
    db.create_all()
    from models import OutboundLog
    rows = {
        'delivered':   'Twilio: delivered.',
        'sent':        'Accepted by Twilio.',
        'queued':      'Twilio: queued.',
        'undelivered': 'Twilio: undelivered (30007: carrier filtered).',
        'failed':      'Twilio error: unsubscribed recipient.',
    }
    for status, detail in rows.items():
        db.session.add(OutboundLog(channel='sms', to_address='4075551212',
                                   body=f'body for {status}', status=status,
                                   detail=detail, provider_id='SM' + status))
    db.session.commit()

    c = app.test_client()
    with c.session_transaction() as sess:
        sess['logged_in'] = True
        sess['role'] = 'owner'
    page = c.get('/messages/sent').get_data(as_text=True)

    print('1. Every status Twilio reports is accounted for')
    body = page[page.index('body for delivered'):] if 'body for delivered' in page else ''
    check('✅ Delivered' in page, 'a text that reached the phone says Delivered')
    check('📨 Sent' in page, 'one the provider has taken but not confirmed says Sent')
    check('⚠️ Failed' in page, 'and one that did not arrive says Failed')

    print('\n2. Nothing good is called a failure')
    # Count the badges: three statuses are fine, two are not.
    check(page.count('⚠️ Failed') == 2,
          'exactly the two that failed — not queued, not sent, not delivered')
    check(page.count('status-confirmed') == 3,
          'and the three that are fine are all marked as fine')

    print('\n3. The difference between accepted and arrived is kept')
    check('accepted, not yet confirmed' in page,
          '"sent" still says what it has always really meant')
    check(page.count('accepted, not yet confirmed') == 2,
          'on the two that are accepted, and not on the one that arrived')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
