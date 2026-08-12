"""Some customers go quiet. They asked about regular cleaning, sounded keen, then
stopped answering texts and calls.

A specific date at a specific price with two buttons is easier to answer than
"are you still interested?" — and either answer is better than more silence.
"""
import os, sys, tempfile
from datetime import date, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/confirm.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['CRM_BASE'] = 'https://crm.example.com'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT, TEXTS = [], []
notifications.send_sms = lambda to, msg, *a, **k: (TEXTS.append((to, msg)), (True, 'ok'))[1]
notifications.send_email = lambda **k: (SENT.append(k), (True, 'ok'))[1]

from app import create_app
from extensions import db
from models import Booking, BusinessSetting

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

app = create_app()
with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Test Cleaning Co')
    BusinessSetting.set('email', 'owner@example.com')
    BusinessSetting.set('phone', '(407) 555-0142')
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    def pencilled_in(name, email):
        b = Booking(service_type='standard', name=name, email=email, phone='4075550199',
                    address='3 Vine St', bedrooms='3', bathrooms='2', price=165.0,
                    frequency='biweekly', status='pending',
                    preferred_date=(date.today() + timedelta(days=6)).isoformat(),
                    preferred_time='10:00 AM')
        db.session.add(b); db.session.commit()
        return b

    susan = pencilled_in('Susan Doyle', 'susan@example.com')

    print('\n1. The owner sees the offer before anyone else')
    page = c.get(f'/bookings/{susan.id}/proposal/preview').get_data(as_text=True)
    check(SENT == [] and TEXTS == [], 'previewing sends nothing')
    check('shall we book this in' in page, 'the email asks plainly')
    check('$165.00' in page, 'showing her real price')
    check('every 2 weeks' in page, 'and that it repeats fortnightly')
    check('nothing is booked until you say so' in page.lower(), 'and that she is not committed')
    check('4075550199' in page, 'the text message is shown too')

    print('\n2. A test goes to the owner, not the customer')
    SENT.clear()
    c.post(f'/bookings/{susan.id}/proposal/send', data={'to': 'me'}, follow_redirects=True)
    check(len(SENT) == 1 and SENT[0]['to_email'] == 'owner@example.com', 'it lands in her own inbox')
    check(SENT[0]['subject'].startswith('[TEST]'), 'marked as a test')
    db.session.expire_all()
    check(Booking.query.get(susan.id).confirm_sent_at is None,
          'and a test does not count as having asked the customer')

    print('\n3. Sending for real reaches her by email and text')
    SENT.clear(); TEXTS.clear()
    c.post(f'/bookings/{susan.id}/proposal/send', data={'to': 'customer'}, follow_redirects=True)
    check(SENT[0]['to_email'] == 'susan@example.com', 'the email went to her')
    check(TEXTS and '/confirm/' in TEXTS[0][1], 'and a text with the link')
    check('Reply STOP' in TEXTS[0][1], 'with an opt-out')
    db.session.expire_all(); susan = Booking.query.get(susan.id)
    check(susan.confirm_sent_at is not None, 'the ask is recorded')
    check(susan.status == 'pending', 'and nothing is booked yet')

    print('\n4. A link scanner cannot answer on her behalf')
    token = susan.confirm_token
    pub = app.test_client()
    body = pub.get(f'/confirm/{token}').get_data(as_text=True)
    check('shall we book this in' in body.lower(), 'the link opens a page')
    check('Yes — book it in' in body, 'with a Yes button')
    check('No thanks' in body, 'and a No button')
    db.session.expire_all()
    check(Booking.query.get(susan.id).confirm_response is None,
          'and simply opening it answers nothing — this is the point')
    check(pub.get(f'/confirm/{token}/respond').status_code == 405,
          'the decision cannot be made by fetching a URL')

    print('\n5. She says yes')
    SENT.clear(); TEXTS.clear()
    r = pub.post(f'/confirm/{token}/respond', data={'answer': 'yes'}, follow_redirects=True)
    body = r.get_data(as_text=True)
    check("You're booked in" in body, 'she is told it is booked')
    db.session.expire_all(); susan = Booking.query.get(susan.id)
    check(susan.confirm_response == 'yes', 'the answer is recorded')
    check(susan.status == 'confirmed', 'and the job is confirmed')
    check(any('CONFIRMED' in (s.get('subject') or '') for s in SENT), 'the owner is emailed')
    check(any('✅' in m for _, m in TEXTS), 'and texted')

    print('\n6. Answering twice changes nothing')
    pub.post(f'/confirm/{token}/respond', data={'answer': 'no'}, follow_redirects=True)
    db.session.expire_all()
    check(Booking.query.get(susan.id).status == 'confirmed',
          'a second press cannot undo a confirmed booking')

    print('\n7. Miriam says no, and that is useful too')
    miriam = pencilled_in('Miriam Vance', 'miriam@example.com')
    c.post(f'/bookings/{miriam.id}/proposal/send', data={'to': 'customer'}, follow_redirects=True)
    db.session.expire_all(); miriam = Booking.query.get(miriam.id)
    SENT.clear()
    body = pub.post(f'/confirm/{miriam.confirm_token}/respond', data={'answer': 'no'},
                    follow_redirects=True).get_data(as_text=True)
    check('No problem at all' in body, 'she gets a gracious reply, not a guilt trip')
    check('(407) 555-0142' in body, 'with a number if she changes her mind')
    db.session.expire_all(); miriam = Booking.query.get(miriam.id)
    check(miriam.confirm_response == 'no', 'the no is recorded')
    check(miriam.status == 'cancelled', 'the job comes off the calendar')
    check(any('declined' in (s.get('subject') or '') for s in SENT),
          'and the owner is told — a silent no is just more silence')

print('\n🎉 A date, a price, two buttons — and the owner hears back either way.')
