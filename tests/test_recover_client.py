"""Getting one deleted customer back, without rolling everything else back.

Deleting a client deletes their bookings, and with those goes every job
checklist — the before-and-after photos, the arrival and finish times, the
signature — and every rating. That is precisely the evidence a card network
asks for when a charge is disputed.

The tempting recovery is to restore last night's backup. It is the wrong one:
it takes the whole database back to that night and discards every booking,
payment and message since. What is protected here is that this does not do
that — it writes one customer's rows and touches nothing else, and it survives
the ids having been reused in the meantime.
"""
import os, sys, gzip, json, subprocess, tempfile, shutil
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/live.db'
os.environ['SECRET_KEY'] = 'test'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Client, Booking, JobChecklist
import recover_client as rc
app = create_app()

PASS = 'a-long-test-passphrase'


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def make_backup(rows):
    """A dump in the real format, encrypted the way the workflow encrypts."""
    raw = os.path.join(TMP, 'b.json.gz')
    with gzip.open(raw, 'wt') as fh:
        fh.write(json.dumps({'format': 1, 'tables': ['client', 'booking']}) + '\n')
        for t, r in rows:
            fh.write(json.dumps({'__table__': t, 'row': r}) + '\n')
    enc = raw + '.enc'
    p = subprocess.run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-salt',
                        '-pass', 'stdin', '-in', raw, '-out', enc],
                       input=(PASS + '\n').encode(), capture_output=True)
    assert p.returncode == 0, p.stderr
    return enc


ROWS = [
    ('client', {'id': 7, 'name': 'Susan Mills', 'email': 'susan@example.com',
                'phone': '4075551234', 'address': '9 Oak St', 'city': 'Orlando',
                'zip_code': '32801'}),
    ('client', {'id': 8, 'name': 'Someone Else', 'email': 'other@example.com'}),
    ('booking', {'id': 41, 'client_id': 7, 'name': 'Susan Mills',
                 'email': 'susan@example.com', 'service_type': 'deep',
                 'price': 290.0, 'preferred_date': '2026-07-14', 'status': 'completed',
                 'address': '9 Oak St', 'paid_at': '2026-07-14T15:00:00',
                 'stripe_payment_intent': 'pi_susan_july',
                 'terms_accepted_at': '2026-07-10T12:00:00',
                 'terms_accepted_ip': '10.0.0.9'}),
    ('booking', {'id': 42, 'client_id': 8, 'name': 'Someone Else',
                 'service_type': 'standard', 'price': 150.0, 'address': '1 Elm'}),
    ('job_checklist', {'id': 90, 'booking_id': 41, 'template_name': 'Deep',
                       'items': '[]', 'token': 'tok-susan',
                       'before_photos': '["https://img/before1.jpg"]',
                       'after_photos': '["https://img/after1.jpg"]',
                       'client_signature': 'data:image/png;base64,AAA'}),
    ('job_checklist', {'id': 91, 'booking_id': 42, 'template_name': 'Std',
                       'items': '[]', 'token': 'tok-other'}),
]

print('\n1. The backup decrypts only with the right passphrase')
enc = make_backup(ROWS)
try:
    rc.decrypt(enc, 'wrong-passphrase')
    raise AssertionError('a wrong passphrase must not decrypt')
except SystemExit as e:
    check('Could not decrypt' in str(e), 'a wrong passphrase is refused, with a reason')
plain = rc.decrypt(enc, PASS)
check(os.path.exists(plain), 'the right one opens it')

print('\n2. It finds the customer and everything hanging off them')
found, _ = rc.collect(plain, 'Susan Mills')
check(found is not None, 'Susan is in the backup')
check(found['client']['email'] == 'susan@example.com', 'with her contact details')
check(len(found['booking']) == 1 and found['booking'][0]['id'] == 41,
      'her July booking, and only hers')
check(len(found['job_checklist']) == 1, 'and its checklist')
check('before1.jpg' in found['job_checklist'][0]['before_photos'],
      'carrying the photos that prove the work was done')

print('\n3. Somebody else\'s records are left alone')
ids = {b['id'] for b in found['booking']}
check(42 not in ids, "the other customer's booking is not swept up")

print('\n4. Searching by email works too')
byemail, _ = rc.collect(plain, 'susan@example.com')
check(byemail and byemail['client']['id'] == 7, 'found by address as well as name')

print('\n5. A name that is not there says so rather than guessing')
check(rc.collect(plain, 'Nobody At All')[0] is None, 'no match returns nothing')

with app.app_context():
    db.create_all()
    # The live database has moved on: ids 7 and 41 were reused by other people
    # after the delete, which is exactly what makes a naive restore corrupt data.
    db.session.add(Client(id=7, name='A New Customer', email='new@example.com'))
    db.session.add(Booking(id=41, service_type='standard', name='A Newer Job',
                           address='2 Pine', price=100))
    db.session.commit()
    before_clients = Client.query.count()
    before_bookings = Booking.query.count()

    print('\n6. Restoring works around ids that have since been taken')
    rc.restore(found, os.environ['DATABASE_URL'])
    db.session.expire_all()
    check(Client.query.get(7).name == 'A New Customer',
          'the customer who took id 7 is untouched')
    check(Booking.query.get(41).name == 'A Newer Job',
          'and the booking that took id 41')
    susan = Client.query.filter_by(email='susan@example.com').first()
    check(susan is not None and susan.id != 7, f'Susan is back under a free id ({susan.id})')

    print('\n7. Her booking and its evidence came with her')
    jobs = Booking.query.filter_by(client_id=susan.id).all()
    check(len(jobs) == 1, 'her one booking is back')
    j = jobs[0]
    check(j.preferred_date == '2026-07-14' and float(j.price) == 290.0, 'with the July date and price')
    check(j.stripe_payment_intent == 'pi_susan_july', 'and the Stripe payment it belongs to')
    check(j.terms_accepted_at is not None, 'and the record that she accepted the terms')
    cl = JobChecklist.query.filter_by(booking_id=j.id).first()
    check(cl is not None, 'the job checklist is back')
    check('before1.jpg' in (cl.before_photos or ''), 'with the before photo')
    check('after1.jpg' in (cl.after_photos or ''), 'and the after photo')
    check(cl.client_signature, 'and her signature')

    print('\n8. Nothing else in the business was disturbed')
    check(Client.query.count() == before_clients + 1, 'exactly one client added')
    check(Booking.query.count() == before_bookings + 1, 'exactly one booking added')
    check(Client.query.filter_by(email='new@example.com').first() is not None,
          'work done since the backup is still there — this is not a rollback')

shutil.rmtree(os.path.dirname(plain), ignore_errors=True)
print('\n🎉 One customer comes back; the rest of the business stays where it is.')
