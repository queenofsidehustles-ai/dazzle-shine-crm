"""A cleaner whose pay is not set is never sent a job at $0.

Decided 2026-10-24: cleaners added in setup or by import are saved with
"Pay not set" rather than somebody else's 50%. A job with estimated hours pays
from its labor budget and does not care. A job without them falls back to the
cleaner's own rate -- and with none, that figure is $0. This holds that such a
job is stopped, and the owner told why, before anything reaches a phone.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/paynotset.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
texts = []
notifications.send_email = lambda **k: (True, 'ok')
notifications.send_sms = lambda to, body: (texts.append((to, body)), (True, 'ok'))[1]

import sqlalchemy as sa
from app import create_app
from extensions import db
from models import Booking, BookingCrew, Staff
import blueprints.claims as claims
claims.send_sms = notifications.send_sms

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def a_booking(**kw):
    b = Booking(service_type='standard', name='Eric Rosebro', email='eric@example.com',
                phone='+17165550100', status='confirmed', price=300.0,
                preferred_date='2026-11-02', address='1 Oak St', city='Orlando',
                bedrooms=2, bathrooms=2, **kw)
    db.session.add(b)
    db.session.commit()
    return b


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'
    unset = Staff(name='Una Set', is_active=True, phone='+14075550111',
                  email='una@example.com', pay_type='percent', pay_rate=sa.null())
    paid = Staff(name='Pia Paid', is_active=True, phone='+14075550112',
                 email='pia@example.com', pay_type='percent', pay_rate=45)
    db.session.add_all([unset, paid])
    db.session.commit()
    check(unset.pay_rate is None, 'Una really has no pay set')

    print('\n1. No hours on the job: assigning Una with no pay typed is stopped')
    b = a_booking()
    check(b.pay_unset_for(unset), 'the job knows she would be offered $0')
    check(not b.pay_unset_for(paid), 'and that Pia would not')
    r = c.post(f'/bookings/{b.id}/assign', data={'assign_to': str(unset.id),
                                                 'send_checklist': '1'},
               follow_redirects=True)
    page = r.get_data(as_text=True)
    check('pay isn’t set' in page, 'the owner is told why')
    check(BookingCrew.query.filter_by(booking_id=b.id).count() == 0, 'nobody was put on it')
    check(not texts, 'and nothing was texted')

    print('\n2. Typing the pay lets it through')
    r = c.post(f'/bookings/{b.id}/assign', data={'assign_to': str(unset.id), 'add_pay': '120'})
    row = BookingCrew.query.filter_by(booking_id=b.id, staff_id=unset.id).first()
    check(row is not None and float(row.pay_amount) == 120, 'she is on it at the $120 typed')

    print('\n3. The dropdown says so before the owner picks her')
    b2 = a_booking()
    page = c.get(f'/bookings/{b2.id}').get_data(as_text=True)
    check('Una Set — pay not set' in page, 'her name carries "pay not set"')
    check('Pia Paid — pay not set' not in page, 'Pia’s does not')

    print('\n4. Offering to the whole team leaves Una out, and says so')
    texts.clear()
    r = c.post(f'/bookings/{b2.id}/broadcast', follow_redirects=True)
    page = r.get_data(as_text=True)
    to = [t for t, _ in texts]
    check('+14075550112' in to, 'Pia got the offer')
    check('+14075550111' not in to, 'Una did not')
    check(not any('$0.00' in body for _, body in texts), 'no text anywhere says $0.00')
    check('Not offered to Una Set' in page, 'the owner is told who was left out')

    print('\n5. A job with estimated hours pays from its budget, so it is not stopped')
    b3 = a_booking(estimated_hours=3)
    check((b3.default_crew_pay(unset) or 0) > 0,
          f'the budget pays her ${b3.default_crew_pay(unset) or 0:.2f}')
    check(not b3.pay_unset_for(unset), 'so she is not blocked')

print()
if failures:
    print(f'❌ {len(failures)} pay-not-set check(s) failed')
    sys.exit(1)
print('✅ nobody is sent a job at $0 for want of a pay rate')
