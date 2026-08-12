"""Booking someone the CRM already knows should not mean looking them up and
retyping their address. That is slow, and it is how a cleaner ends up at the
wrong house."""
import os, sys, tempfile
from datetime import date, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/again.db'
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

    print('\n1. An existing client with one job behind them')
    susan = Client(name='Susan Mills', email='susan.a.mills@me.com', phone='5167548696',
                   address='2070 The Oaks Blvd', city='Orlando', zip_code='32836')
    db.session.add(susan); db.session.commit()
    past = Booking(client_id=susan.id, service_type='standard', name='Susan Mills',
                   email=susan.email, phone=susan.phone, address=susan.address,
                   city=susan.city, zip_code=susan.zip_code, bedrooms='4', bathrooms='3',
                   price=260, status='completed', preferred_date='2026-07-25')
    db.session.add(past); db.session.commit()

    print('\n2. Her page offers to book her again')
    page = c.get(f'/bookings/clients/{susan.id}').get_data(as_text=True)
    check('Book Susan again' in page, 'there is a button, on her own page')
    check(f'/bookings/new?client={susan.id}' in page, 'pointing at a booking form that knows her')

    print('\n3. And the form arrives already filled in')
    form = c.get(f'/bookings/new?client={susan.id}').get_data(as_text=True)
    check('New booking for <strong>Susan Mills</strong>' in form, 'it says whose booking this is')
    check('value="Susan Mills"' in form, 'her name')
    check('value="susan.a.mills@me.com"' in form, 'her email')
    check('value="5167548696"' in form, 'her phone')
    check('value="2070 The Oaks Blvd"' in form, 'her address — not retyped')
    check('value="Orlando"' in form, 'her city')
    check('value="32836"' in form, 'her ZIP')

    print('\n4. Including the size of her home, from her last job')
    check('data-prefill="4"' in form, 'four bedrooms')
    check('data-prefill="3"' in form, 'three bathrooms')
    check('data-prefill="standard"' in form, 'and the service she had before')

    print('\n5. Saving it attaches to the same client, not a second one')
    c.post('/bookings/new', data={
        'name': 'Susan Mills', 'email': susan.email, 'phone': susan.phone,
        'address': susan.address, 'city': susan.city, 'zip_code': susan.zip_code,
        'service_type': 'standard', 'bedrooms': '4', 'bathrooms': '3',
        'frequency': 'monthly', 'status': 'pending',
        'preferred_date': (date.today() + timedelta(days=16)).isoformat(),
        'preferred_time': '9:00 AM', 'cleaning_price': '260'}, follow_redirects=True)
    check(Client.query.filter_by(email=susan.email).count() == 1,
          'still one Susan, not a duplicate')
    db.session.expire_all()
    check(len(Client.query.get(susan.id).bookings) == 2, 'with both jobs on her record')

    print('\n6. Booking a brand-new customer is unaffected')
    form = c.get('/bookings/new').get_data(as_text=True)
    check('New booking for' not in form, 'no banner')
    check('value="Susan Mills"' not in form, 'and an empty form, as before')

print('\n🎉 Book a known customer from their own page, with nothing retyped.')
