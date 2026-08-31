"""A customer's name, email and phone can be corrected in place.

None of them could be. The only way to change an email address was to open
Email Customer and send the customer a message, because that form happens to
write the address it sent to back onto the booking — a correction you could not
make without also mailing somebody.

That is how `duffytyler96@gmail`, with no `.com`, stayed on booking #59 and
stopped it being paid. The payment path no longer breaks on a bad address, but
the address still has to be fixable or no receipt ever reaches them.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/edit.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, Client
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    cl = Client(name='Duffy Tyler', email='duffytyler96@gmail', phone='7036736816',
                address='3320 Lila drive', city='Orlando', zip_code='32806')
    db.session.add(cl); db.session.commit()
    b = Booking(service_type='moveout', name='Duffy Tyler', email='duffytyler96@gmail',
                phone='7036736816', address='3320 Lila drive', price=290.0,
                client_id=cl.id, recurring_group='grp-1', preferred_date='2026-09-10',
                status='confirmed')
    old = Booking(service_type='moveout', name='Duffy Tyler', email='duffytyler96@gmail',
                  phone='7036736816', address='3320 Lila drive', price=290.0,
                  client_id=cl.id, recurring_group='grp-1', preferred_date='2026-01-05',
                  status='completed')
    db.session.add_all([b, old]); db.session.commit()
    bid, oid = b.id, old.id

    print('\n1. The booking page warns that the address cannot be delivered to')
    page = c.get(f'/bookings/{bid}').get_data(as_text=True)
    check('This address looks incomplete' in page, 'the broken address is called out on the page')
    check('Correct their name, email or phone' in page, 'and there is a form to fix it')

    print('\n2. An incomplete address is refused rather than saved')
    c.post(f'/bookings/{bid}/contact', data={
        'name': 'Duffy Tyler', 'email': 'duffytyler96@gmail', 'phone': '7036736816'},
        follow_redirects=True)
    db.session.expire_all()
    check(Booking.query.get(bid).email == 'duffytyler96@gmail', 'still the old value, not a worse one')

    print('\n3. The correction saves, and carries across the plan and the client')
    c.post(f'/bookings/{bid}/contact', data={
        'name': 'Duffy Tyler', 'email': 'DuffyTyler96@Gmail.com', 'phone': '(703) 673-6816',
        'apply_series': '1', 'apply_client': '1'}, follow_redirects=True)
    db.session.expire_all()
    check(Booking.query.get(bid).email == 'duffytyler96@gmail.com', 'saved, lowercased')
    check(Booking.query.get(bid).phone == '(703) 673-6816', 'the phone came with it')
    check(Booking.query.get(oid).email == 'duffytyler96@gmail.com',
          'the completed visit was fixed too — it is the same person')
    check(Client.query.get(cl.id).email == 'duffytyler96@gmail.com', 'and her client record')

    print('\n4. The change is written down')
    check('Contact details corrected' in (Booking.query.get(bid).internal_notes or ''),
          'the booking notes record what changed')

    print('\n5. The warning is gone and the payment page is reachable again')
    page = c.get(f'/bookings/{bid}').get_data(as_text=True)
    check('This address looks incomplete' not in page, 'no warning on a good address')

    print('\n6. A booking with no email is allowed — some customers only give a phone')
    c.post(f'/bookings/{bid}/contact', data={
        'name': 'Duffy Tyler', 'email': '', 'phone': '7036736816'}, follow_redirects=True)
    db.session.expire_all()
    check(Booking.query.get(bid).email == '', 'blank is accepted')

    print('\n7. The client page edits too, and reaches the bookings')
    c.post(f'/bookings/clients/{cl.id}/contact', data={
        'name': 'Duffy Tyler', 'email': 'duffy@tyler.com', 'phone': '7036736816',
        'address': '9 New Road', 'city': 'Orlando', 'zip_code': '32801',
        'apply_bookings': '1'}, follow_redirects=True)
    db.session.expire_all()
    check(Client.query.get(cl.id).email == 'duffy@tyler.com', 'the client record changed')
    check(Client.query.get(cl.id).address == '9 New Road', 'including her address')
    check(Booking.query.get(bid).email == 'duffy@tyler.com', 'and both bookings followed')
    check(Booking.query.get(oid).email == 'duffy@tyler.com', 'including the completed one')
    check(Booking.query.get(oid).address == '3320 Lila drive',
          'but a booking keeps the address the work was actually done at')

    print('\n8. The client page refuses an incomplete address as well')
    c.post(f'/bookings/clients/{cl.id}/contact', data={
        'name': 'Duffy Tyler', 'email': 'duffy@tyler', 'phone': '7036736816'},
        follow_redirects=True)
    db.session.expire_all()
    check(Client.query.get(cl.id).email == 'duffy@tyler.com', 'the good address survived')

    print('\n9. A name is still required on both')
    c.post(f'/bookings/{bid}/contact', data={'name': '', 'email': 'a@b.com'},
           follow_redirects=True)
    db.session.expire_all()
    check(Booking.query.get(bid).name == 'Duffy Tyler', 'the booking kept its name')

print('\n🎉 Customer details are editable, and a broken address is visible and fixable.')
