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


# ── Her own words. ───────────────────────────────────────────────────────────
with app.app_context():
    print('\n8. She can write the opening herself')
    dara = pencilled_in('Dara Mensah', 'dara@example.com')
    note = ("Hi Dara, lovely speaking last Tuesday!\n"
            "I've held the Thursday slot for you as promised.")
    page = c.post(f'/bookings/{dara.id}/proposal/preview',
                  data={'confirm_note': note}).get_data(as_text=True)
    check('lovely speaking last Tuesday' in page, 'her words are in the preview')
    check("I've held the Thursday slot" in page, 'both lines of them')
    check('$165.00' in page, 'the price is still there')
    check('Confirm or decline' in page, 'and the buttons')
    check("didn't want to keep chasing you" not in page,
          'the stock opening is replaced, not stacked on top')

    print('\n9. What she previewed is what sends')
    db.session.expire_all()
    check(Booking.query.get(dara.id).confirm_note == note.strip(), 'the note is kept')
    SENT.clear()
    c.post(f'/bookings/{dara.id}/proposal/send', data={'to': 'customer'}, follow_redirects=True)
    check('lovely speaking last Tuesday' in SENT[0]['html'], 'the sent email carries her words')

    print('\n10. The text message stays short')
    db.session.expire_all(); dara = Booking.query.get(dara.id)
    sent_text = [m for _, m in TEXTS if '/confirm/' in m][-1]
    check('lovely speaking last Tuesday' not in sent_text,
          'a long note does not turn into a long text message')
    check(len(sent_text) < 320, f'the text stays to two segments ({len(sent_text)} chars)')

    print('\n11. Leaving it blank falls back to sensible wording')
    ola = pencilled_in('Ola Bright', 'ola@example.com')
    page = c.post(f'/bookings/{ola.id}/proposal/preview',
                  data={'confirm_note': '   '}).get_data(as_text=True)
    check("didn't want to keep chasing you" in page, 'the default opening is used')
    db.session.expire_all()
    check(Booking.query.get(ola.id).confirm_note is None, 'and blank is stored as nothing')

print('\n🎉 Her words, her price, her date — previewed before any of it leaves.')


# ── Susan wants monthly; Miriam wants twice a month. Neither answered a call. ──
with app.app_context():
    print('\n12. The offer is composed on the card, not somewhere else first')
    susan2 = Booking(service_type='standard', name='Susan Doyle', email='susan2@example.com',
                     phone='4075550188', address='3 Vine St', bedrooms='3', bathrooms='2',
                     status='pending')
    db.session.add(susan2); db.session.commit()
    page = c.post(f'/bookings/{susan2.id}/proposal/preview', data={
        'plan_frequency': 'monthly', 'plan_price': '185',
        'plan_date': '2026-08-28', 'plan_time': '9:00 AM',
        'confirm_note': 'Hi Susan, we spoke about monthly cleaning — I have kept this slot for you.'
    }).get_data(as_text=True)
    check('we spoke about monthly cleaning' in page, 'her words are in it')
    check('$185.00' in page, 'the price she just typed')
    check('2026-08-28' in page and '9:00 AM' in page, 'the date and time she just chose')
    check('every month' in page, 'and that it repeats monthly')

    db.session.expire_all(); susan2 = Booking.query.get(susan2.id)
    check(susan2.frequency == 'monthly', 'the booking now says monthly')
    check(susan2.price == 185.0 and susan2.preferred_date == '2026-08-28',
          'with the price and date saved — no separate trip to edit it')

    print('\n13. Miriam wants twice a month')
    miriam2 = Booking(service_type='standard', name='Miriam Vance', email='miriam2@example.com',
                      phone='4075550177', address='8 Elm Ct', status='pending')
    db.session.add(miriam2); db.session.commit()
    page = c.post(f'/bookings/{miriam2.id}/proposal/preview', data={
        'plan_frequency': 'biweekly', 'plan_price': '150',
        'plan_date': '2026-08-27', 'plan_time': 'Morning'}).get_data(as_text=True)
    check('every 2 weeks' in page, 'the email says every 2 weeks')
    db.session.expire_all()
    check(Booking.query.get(miriam2.id).frequency == 'biweekly', 'and the booking agrees')

    print('\n14. A customer can want the cleaning but not that day')
    c.post(f'/bookings/{susan2.id}/proposal/send', data={'to': 'customer'}, follow_redirects=True)
    db.session.expire_all(); susan2 = Booking.query.get(susan2.id)
    body = pub.get(f'/confirm/{susan2.confirm_token}').get_data(as_text=True)
    check('Another day or time would suit me better' in body, 'there is a third option')
    check('No thanks' in body, 'as well as a plain no')

    SENT.clear(); TEXTS.clear()
    body = pub.post(f'/confirm/{susan2.confirm_token}/respond', data={
        'answer': 'other', 'alt_date': '2026-09-04', 'alt_time': 'Morning',
        'alt_note': 'Fridays are best for me'}, follow_redirects=True).get_data(as_text=True)
    check("we'll find a better time" in body, 'she is thanked, not turned away')
    db.session.expire_all(); susan2 = Booking.query.get(susan2.id)
    check(susan2.confirm_response == 'other', 'the answer is recorded as a maybe-later')
    check(susan2.status != 'cancelled',
          'and the booking is NOT cancelled — she is trying to say yes')
    check('2026-09-04' in (susan2.confirm_alt or ''), 'her date came through')
    check('Fridays are best' in (susan2.confirm_alt or ''), 'and her note')

    print('\n15. The owner is told what they asked for')
    check(any('different time' in (s.get('subject') or '') for s in SENT),
          'an email lands saying they want a different time')
    body = [s for s in SENT if 'different time' in (s.get('subject') or '')][0]['html']
    check('Fridays are best' in body, 'quoting exactly what they said')
    check(any('Fridays are best' in m for _, m in TEXTS), 'and a text with the same')

print('\n🎉 Confirm, suggest another time, or decline — and none of it needs a second trip.')


# ── It should not offer to ask about a job that already happened. ────────────
with app.app_context():
    print('\n16. No confirm card on a job that is done or cancelled')
    done = pencilled_in('Past Customer', 'past@example.com')
    done.status = 'completed'; db.session.commit()
    page = c.get(f'/bookings/{done.id}').get_data(as_text=True)
    check('Waiting On The Customer' not in page,
          'a completed cleaning is not offered up for confirmation')

    gone = pencilled_in('Cancelled Customer', 'gone@example.com')
    gone.status = 'cancelled'; db.session.commit()
    page = c.get(f'/bookings/{gone.id}').get_data(as_text=True)
    check('Waiting On The Customer' not in page, 'nor a cancelled one')

    live = pencilled_in('Still Deciding', 'live@example.com')
    page = c.get(f'/bookings/{live.id}').get_data(as_text=True)
    check('Waiting On The Customer' in page, 'but a pending job still offers it')

print('\n🎉 Only jobs still ahead of you can be sent for confirmation.')
