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

    html = c.get(f'/bookings/{done.id}').get_data(as_text=True)
    check(html.count('id="book-again"') == 1, 'offered once')
    check(html.index('id="book-again"') < html.index('>Customer</h3>'), 'at the top of the booking, before the customer details')

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

    print('\n4. Review fixes')
    done.promised_checklist = 'Kitchen\nBathrooms'
    crew_job = Booking(client_id=cl.id, service_type='deep', name=cl.name, status='completed',
                       preferred_date='2026-08-01', crew_size=2, assigned_cleaner='Ana', price=300)
    db.session.add(crew_job); db.session.commit()
    c.post(f'/bookings/{done.id}/book-again', data={'repeat_date': '2026-12-08', 'same_cleaner': '1'})
    kept = Booking.query.filter_by(repeat_of_booking_id=done.id, preferred_date='2026-12-08').one()
    check(kept.promised_checklist == 'Kitchen\nBathrooms', 'accepted checklist carried')
    c.post(f'/bookings/{crew_job.id}/book-again', data={'repeat_date': '2026-12-09', 'same_cleaner': '1'})
    crew_new = Booking.query.filter_by(repeat_of_booking_id=crew_job.id).one()
    check(crew_new.assigned_cleaner is None and crew_new.crew_size == 2, 'crew job repeats unassigned, same size')
    import entitlements
    orig = entitlements.check_limit
    entitlements.check_limit = lambda name: (False, 'at limit')
    n = Booking.query.count()
    c.post(f'/bookings/{done.id}/book-again', data={'repeat_date': '2026-12-10'})
    entitlements.check_limit = orig
    check(Booking.query.count() == n, 'monthly job limit is enforced')
    # completed_at beats booking id for "last clean"
    from datetime import datetime
    done.completed_at = datetime(2026, 10, 1); crew_job.completed_at = datetime(2026, 9, 1)
    db.session.commit()
    check(f'/bookings/{done.id}#book-again' in c.get(f'/bookings/clients/{cl.id}').get_data(as_text=True),
          'last clean picked by completion date, not id')

    print('\n4. Only a login that may create bookings can book again')
    # Unclassified routes defer to the route itself for most roles, and this
    # one checks nothing -- so it must be in the matrix, as creating a booking.
    import rbac
    check(rbac.required_permission('bookings.book_again', 'POST') == 'booking.create',
          'Book again is classified as creating a booking')
    for role, may in (('owner', True), ('admin', True), ('dispatcher', True),
                      ('limited', False), ('cleaner', False), ('sales', False)):
        check(rbac.has_permission(role, 'booking.create') is may,
              f'{role}: {"may" if may else "may not"} book again')

    print('\n5. Posting in the background')
    J = {'X-Requested-With': 'fetch'}
    r = c.post(f'/bookings/{done.id}/book-again', headers=J,
               data={'repeat_date': '2026-12-11', 'repeat_price': '180'})
    d = r.get_json()
    check(r.status_code == 200 and d['ok'] and not r.headers.get('Location'), 'JSON answer, no redirect')
    nb = Booking.query.get(d['id'])
    check(nb.repeat_of_booking_id == done.id and nb.price == 180, 'the booking is created')
    check(d['can_confirm'] and d['confirm_url'].endswith(f"/{d['id']}/proposal/send")
          and d['url'].endswith(f"/bookings/{d['id']}"), 'carries what the page needs for the confirm step')
    n = Booking.query.count()
    r = c.post(f'/bookings/{done.id}/book-again', headers=J, data={'repeat_date': ''})
    check(r.status_code == 400 and r.get_json()['ok'] is False and Booking.query.count() == n,
          'a bad date is a JSON error, nothing created')
    r = c.post(f'/bookings/{done.id}/book-again', headers=J, data={'repeat_date': '2026-12-12', 'repeat_price': 'abc'})
    check(r.status_code == 400 and 'not a number' in r.get_json()['error'], 'a bad price says so')

    print('\n6. The confirm step')
    r = c.post(d['confirm_url'], headers=J, data={
        'to': 'customer', 'plan_frequency': 'one_time', 'plan_date': d['plan_date'],
        'plan_time': d['plan_time'], 'plan_price': '180'})
    j = r.get_json()
    check(r.status_code == 200 and j['ok'] and 'email' in j['sent'], 'asks the customer, answered in JSON')
    check(Booking.query.get(d['id']).confirm_sent_at is not None, 'and records that it was sent')
    nobody = Booking(client_id=cl.id, service_type='standard', name='No Contact', status='pending',
                     preferred_date='2026-12-20', price=100)
    db.session.add(nobody); db.session.commit()
    r = c.post(f'/bookings/{nobody.id}/proposal/send', headers=J, data={'to': 'customer'})
    check(r.status_code == 502 and r.get_json()['ok'] is False, 'nothing to send to is an error, not a silent success')

    print('\n6b. Review fixes: no double-booking, no double-sending, one-off wording')
    n = Booking.query.count()
    r1 = c.post(f'/bookings/{done.id}/book-again', headers=J, data={'repeat_date': '2026-12-14', 'repeat_price': '150'}).get_json()
    r2 = c.post(f'/bookings/{done.id}/book-again', headers=J, data={'repeat_date': '2026-12-14', 'repeat_price': '150'}).get_json()
    check(r1['id'] == r2['id'] and Booking.query.count() == n + 1, 'the same repeat sent twice is booked once')
    r3 = c.post(f'/bookings/{done.id}/book-again', headers=J, data={'repeat_date': '2026-12-14', 'repeat_price': '160'}).get_json()
    check(r3['id'] != r1['id'], 'a different price is a deliberate new booking')
    sent_mail = []
    import blueprints.bookings as bb
    real = notifications.send_email
    notifications.send_email = lambda **k: (sent_mail.append(k) or (True, 'ok'))
    try:
        body = {'to': 'customer', 'plan_frequency': 'one_time', 'plan_date': r1['plan_date'],
                'plan_time': r1['plan_time'], 'plan_price': '150'}
        a1 = c.post(r1['confirm_url'], headers=J, data=body).get_json()
        a2 = c.post(r1['confirm_url'], headers=J, data=body).get_json()
    finally:
        notifications.send_email = real
    check(a1['sent'] and a2.get('already') and len(sent_mail) == 1, 'a confirmation is not sent twice in a row')
    html = sent_mail[0]['html']
    check('regular cleaning' not in html and 'chasing' not in html, 'no regular-cleaning / chasing wording')
    check('Nothing is booked until you say so' in html, 'the one-off note is what the customer reads')
    prev = c.get(f"/bookings/{r1['id']}/proposal/preview").get_data(as_text=True)
    check('chasing' not in prev and 'pencilled in for your next clean' in prev, 'and the preview shows the same')

    print('\n7. Without JavaScript the form still redirects')
    r = c.post(f'/bookings/{done.id}/book-again', data={'repeat_date': '2026-12-13'})
    check(r.status_code == 302, 'plain form post redirects as before')
print('\nAll good')
