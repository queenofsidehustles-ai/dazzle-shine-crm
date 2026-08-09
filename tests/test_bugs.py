"""Two bugs: hand-made bookings never created a client, and every invoice was
dated 14 days out."""
import os, sys, tempfile
from datetime import date
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/bg.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, Client
import invoicing
app = create_app()
import blueprints.bookings as bk
bk._send_booking_confirmation = lambda b: None

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. A hand-made booking now creates a client')
    check(Client.query.count() == 0, 'starting with no clients')
    c.post('/bookings/new', data={'name': 'Ashley G', 'address': '280 Ballow Dr',
        'service_type': 'deep', 'bedrooms': '5', 'bathrooms': '4',
        'cleaning_price': '620', 'preferred_date': '2026-08-05',
        'email': 'wckmanager@gmail.com', 'phone': '4079890063'}, follow_redirects=True)
    check(Client.query.count() == 1, 'a client was created')
    cl = Client.query.first()
    check(cl.name == 'Ashley G' and cl.email == 'wckmanager@gmail.com', 'with her details')
    b = Booking.query.first()
    check(b.client_id == cl.id, 'and the booking is linked to her')

    print('\n2. The same customer booking again does NOT duplicate')
    c.post('/bookings/new', data={'name': 'Ashley G', 'address': '280 Ballow Dr',
        'service_type': 'standard', 'bedrooms': '5', 'bathrooms': '4',
        'cleaning_price': '455', 'preferred_date': '2026-09-05',
        'email': 'WCKManager@Gmail.com', 'phone': '4079890063'}, follow_redirects=True)
    check(Client.query.count() == 1, 'still one client (matched on email, any case)')
    check(Booking.query.filter_by(client_id=cl.id).count() == 2, 'both bookings hang off her')

    print('\n3. Matching falls back to phone when the email differs')
    c.post('/bookings/new', data={'name': 'Ashley G', 'address': '280 Ballow Dr',
        'service_type': 'standard', 'bedrooms': '5', 'bathrooms': '4',
        'cleaning_price': '455', 'preferred_date': '2026-10-05',
        'phone': '(407) 989-0063'}, follow_redirects=True)
    check(Client.query.count() == 1, 'same client, matched on the phone number')

    print('\n4. Backfilling old bookings that were never linked')
    for i, (nm, em) in enumerate([('Old One', 'one@x.com'), ('Old Two', 'two@x.com')]):
        db.session.add(Booking(service_type='standard', name=nm, email=em,
                               address='1 St', price=200,
                               preferred_date=f'2026-07-0{i+1}'))
    db.session.add(Booking(service_type='standard', name='No Contact',
                           address='9 St', price=100, preferred_date='2026-07-09'))
    db.session.commit()
    page = c.get('/bookings/clients').get_data(as_text=True)
    # The no-contact booking is correctly excluded — nothing to match it on.
    check('Build client list from 2 existing bookings' in page,
          'the page offers the 2 importable bookings, skipping the one with no details')

    r = c.post('/bookings/clients/rebuild', follow_redirects=True)
    check(Client.query.count() == 3, f'2 new clients created (got {Client.query.count()} total)')
    check('2 new clients from 2 bookings' in r.get_data(as_text=True), 'and it reports what it did')
    nc = Booking.query.filter_by(name='No Contact').first()
    check(nc.client_id is None, 'a booking with no email or phone is left alone, not duplicated')

    print('\n5. Running the import twice changes nothing')
    r = c.post('/bookings/clients/rebuild', follow_redirects=True)
    check(Client.query.count() == 3, 'still 3 clients')
    check('Nothing to import' in r.get_data(as_text=True), 'and it says so')

    print('\n6. Invoices are due the day they are issued')
    b = Booking.query.first()
    invoicing.issue(b)
    check(b.invoice_due_date == date.today().isoformat(),
          f'due today, not in 14 days (got {b.invoice_due_date})')
    check(invoicing.status(b) != 'overdue', 'and it is not immediately overdue')

    print('\n7. Commercial terms are still available for a future caller')
    b2 = Booking(service_type='standard', name='Commercial Co', address='2 St', price=800)
    db.session.add(b2); db.session.commit()
    invoicing.issue(b2, net_days=invoicing.NET_DAYS_COMMERCIAL)
    from datetime import timedelta
    check(b2.invoice_due_date == (date.today() + timedelta(days=14)).isoformat(),
          'net-14 when asked for explicitly')

    print('\n8. An issued invoice keeps its dates unless re-dated on purpose')
    b3 = Booking(service_type='standard', name='Already Issued', address='3 St', price=300,
                 email='x@y.com', invoice_number='INV-1044',
                 invoice_due_date='2026-08-19', pay_token='tok-inv')
    db.session.add(b3); db.session.commit()
    c.post(f'/bookings/{b3.id}/send-invoice', follow_redirects=True)
    db.session.expire_all()
    check(Booking.query.get(b3.id).invoice_due_date == '2026-08-19',
          'a plain resend leaves the date the customer already has')
    c.post(f'/bookings/{b3.id}/send-invoice', data={'reissue_dates': '1'}, follow_redirects=True)
    db.session.expire_all()
    check(Booking.query.get(b3.id).invoice_due_date == date.today().isoformat(),
          'and re-dating is a deliberate, separate action')

print('\n🎉 Clients get created, and invoices are due when they are issued.')
