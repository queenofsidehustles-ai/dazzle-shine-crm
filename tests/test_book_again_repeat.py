"""Repeating a finished job on demand: a plain one-off copy, linked to the
original, that never joins a recurring plan."""
import os, sys, tempfile
from datetime import date
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/repeat.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda **k: (True, 'ok')

from app import create_app
from extensions import db
from models import Booking, Client, BusinessSetting


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


app = create_app()
with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Test Cleaning Co'); db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    cl = Client(name='George Kyere', email='g@example.com', phone='2408865212',
                address='1 Main St', city='Huntsville', zip_code='35801')
    db.session.add(cl); db.session.commit()
    done = Booking(client_id=cl.id, service_type='standard', name=cl.name, email=cl.email,
                   phone=cl.phone, address=cl.address, city=cl.city, zip_code=cl.zip_code,
                   bedrooms='3', bathrooms='2', price=150, balance_due=0, status='completed',
                   preferred_date='2026-09-01', preferred_time='10:00 AM',
                   assigned_cleaner='Ana', paid_at=date.today(), invoice_number='INV-1',
                   cc_email='owner@example.com', frequency='one_time')
    pending = Booking(client_id=cl.id, service_type='standard', name=cl.name, status='pending',
                      preferred_date='2026-11-01')
    db.session.add_all([done, pending]); db.session.commit()

    print('\n1. The offer is on the completed job and the client page only')
    check('Book again' in c.get(f'/bookings/{done.id}').get_data(as_text=True), 'completed job shows the card')
    check('id="book-again"' not in c.get(f'/bookings/{pending.id}').get_data(as_text=True), 'pending job does not')
    check(f'/bookings/{done.id}#book-again' in c.get(f'/bookings/clients/{cl.id}').get_data(as_text=True),
          'client page links to the last completed job')

    print('\n2. Repeating it')
    r = c.post(f'/bookings/{done.id}/book-again',
               data={'repeat_date': '2026-12-05', 'repeat_price': '175', 'same_cleaner': '1'})
    check(r.status_code == 302, 'redirects')
    new = Booking.query.filter(Booking.repeat_of_booking_id == done.id).one()
    check(new.preferred_date == '2026-12-05' and new.price == 175 and new.balance_due == 175, 'date and price applied')
    check(new.status == 'pending' and new.frequency == 'one_time', 'pending one-off')
    check(not new.recurring_group, 'not in any recurring plan')
    check(new.address == '1 Main St' and new.bedrooms == '3' and new.client_id == cl.id, 'home and client carried')
    check(new.preferred_time == '10:00 AM' and new.assigned_cleaner == 'Ana', 'time and cleaner carried')
    check(new.cc_email == 'owner@example.com', 'person in the loop carried')
    check(not new.paid_at and not new.invoice_number, 'payment/invoice state not carried')
    page = c.get(f'/bookings/{new.id}').get_data(as_text=True)
    check(f'#{done.id}' in page and 'on-demand client' in page, 'new job says it is a repeat')
    check(f'#{new.id}' in c.get(f'/bookings/{done.id}').get_data(as_text=True), 'original lists the repeat')

    print('\n3. Guards')
    r = c.post(f'/bookings/{done.id}/book-again', data={'repeat_date': '2026-12-06', 'repeat_price': '150'})
    again = Booking.query.filter(Booking.repeat_of_booking_id == done.id, Booking.preferred_date == '2026-12-06').one()
    check(again.assigned_cleaner is None, 'cleaner dropped when box unchecked')
    n = Booking.query.count()
    c.post(f'/bookings/{done.id}/book-again', data={'repeat_date': ''})
    c.post(f'/bookings/{done.id}/book-again', data={'repeat_date': '2026-12-07', 'repeat_price': 'abc'})
    c.post(f'/bookings/{pending.id}/book-again', data={'repeat_date': '2026-12-07'})
    check(Booking.query.count() == n, 'no date / bad price / not completed creates nothing')
print('\nAll good')
