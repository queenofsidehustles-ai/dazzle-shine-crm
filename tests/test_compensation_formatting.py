"""Cleaner compensation keeps its cents in every cleaner-facing surface."""
import os
import sys
import tempfile
from datetime import date

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/compensation.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Booking, BookingCrew, Staff
import blueprints.workorders as workorders


app = create_app()


with app.app_context():
    db.create_all()
    cleaner = Staff(name='Cents Cleaner', email='cleaner@example.test',
                    phone='+12025550100', is_active=True)
    booking = Booking(name='Cents Job', service_type='standard', status='confirmed',
                      preferred_date='2026-09-20', preferred_time='10:00 AM',
                      address='100 Test Avenue', city='Germantown', zip_code='20874',
                      price=200, crew_size=1)
    db.session.add_all([cleaner, booking])
    db.session.commit()
    db.session.add(BookingCrew(booking_id=booking.id, staff_id=cleaner.id,
                               pay_amount=64.50))
    db.session.commit()

    sent_sms = []
    sent_email = []
    workorders.send_sms = lambda phone, message: (sent_sms.append(message) or True, 'stub')
    workorders.send_email = lambda **kwargs: (sent_email.append(kwargs['html']) or True, 'stub')
    with app.test_request_context('/', base_url='https://test.akyehq.com'):
        workorders.create_and_send_workorder(booking, recipient=cleaner)

    assert len(sent_sms) == 1
    assert 'Your pay: $64.50.' in sent_sms[0]
    assert len(sent_email) == 1
    assert 'Your pay for this job:</strong> $64.50' in sent_email[0]

    with app.test_request_context('/', base_url='https://test.akyehq.com'):
        html = app.jinja_env.get_template('public/my_day.html').render(
            biz='Test Business', s=cleaner,
            days={date(2026, 9, 20): [booking]}, today=date(2026, 9, 20))
    assert 'You earn $64.50' in html
    assert 'You earn $64<' not in html

print('✅ Cleaner pay is $64.50 in work-order SMS, email, and My Day.')
