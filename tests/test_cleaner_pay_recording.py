"""Cleaner pay gets written down, and reaches the P&L as a cost.

Completing a job used to leave no trace of what it cost. Revenue counted the
customer's $290; labor counted nothing at all, because a ContractorPayment only
appeared when the owner remembered to press Pay on the payroll screen. Every job
therefore looked far more profitable than it was, and no screen anywhere
answered "what do I owe this cleaner?"

And the cleaner's own page printed booking.price — the CUSTOMER's price — under
her name, so a cleaner earning half a $290 job appeared to have been paid $290.

What is protected here is the accounting: a queued payment is a to-do with the
arithmetic done, NOT money the P&L believes has left the bank. It becomes a cost
on the day it is actually paid, and never twice.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/pay.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications

SENT = {'email': [], 'sms': []}
notifications.send_email = lambda **k: (SENT['email'].append(k) or (True, 'stub'))
notifications.send_sms = lambda to, msg: (SENT['sms'].append((to, msg)) or (True, 'stub'))

from app import create_app
from extensions import db
from models import Booking, BookingCrew, Staff, ContractorPayment
import contractor_pay
import finance
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    gen = Staff(name='Genesis Marte', email='genesis@example.com',
                phone='4075550101', is_active=True, pay_type='percent', pay_rate=50.0)
    ana = Staff(name='Ana Ruiz', email='ana@example.com', phone='4075550102',
                is_active=True, pay_type='percent', pay_rate=50.0)
    db.session.add_all([gen, ana]); db.session.commit()

    print('\n1. Completing a solo job writes down what it cost')
    b = Booking(service_type='deep', name='Miriam Clifford', address='1 St',
                price=290.0, assigned_cleaner='Genesis Marte', status='confirmed',
                preferred_date='2026-09-01')
    db.session.add(b); db.session.commit()
    check(ContractorPayment.query.count() == 0, 'nothing recorded before the job is done')
    c.post(f'/bookings/{b.id}', data={'status': 'completed', 'price': '290',
                                      'assigned_cleaner': 'Genesis Marte'},
           follow_redirects=True)
    db.session.expire_all()
    pay = ContractorPayment.query.filter_by(booking_id=b.id).first()
    check(pay is not None, 'a payment row now exists for the job')
    check(pay.status == 'pending', "and it is 'pending' — queued, not paid")
    check(pay.amount == Booking.query.get(b.id).pay_for(gen),
          f'for what she earns (${pay.amount:.2f}), not the ${b.price:.0f} the customer paid')

    print('\n2. A queued payment is NOT money the P&L thinks has gone')
    start, end = finance.month_bounds(2026, 9)
    check(finance.contractor_pay_between(start, end) == 0.0,
          'labor cost is still $0 — nothing has actually been paid')

    print('\n3. Completing it again does not queue a second payment')
    c.post(f'/bookings/{b.id}', data={'status': 'completed', 'price': '290',
                                      'assigned_cleaner': 'Genesis Marte'},
           follow_redirects=True)
    check(ContractorPayment.query.filter_by(booking_id=b.id).count() == 1,
          'still exactly one row for this job')

    print('\n4. Her page shows what SHE earned, and what is owed')
    page = c.get(f'/contractors/team/{gen.id}').get_data(as_text=True)
    earned = Booking.query.get(b.id).pay_for(gen)
    check(f'${earned:.2f}' in page, f'her ${earned:.2f} is on the page')
    check('$290.00' not in page, "and the customer's $290 is NOT shown as her money")
    check('Still owed' in page and 'queued to pay' in page, 'it says what is outstanding')

    print('\n5. Paying it settles the SAME row and tells her, by email and text')
    SENT['email'].clear(); SENT['sms'].clear()
    c.post(f'/contractors/payroll/pay-job/{b.id}',
           data={'method': 'zelle', 'paid_on': '2026-09-02'}, follow_redirects=True)
    db.session.expire_all()
    rows = ContractorPayment.query.filter_by(booking_id=b.id).all()
    check(len(rows) == 1, 'still one row — the queued one was settled, not duplicated')
    check(rows[0].status == 'paid' and rows[0].method == 'zelle', 'now paid, via Zelle')
    check(len(SENT['email']) == 1, 'she was emailed')
    check(len(SENT['sms']) == 1, 'and texted')
    body = SENT['sms'][0][1]
    check(f'${earned:.2f}' in body, f'the text quotes ${earned:.2f}')
    check('Zelle' in body, 'and says how it was sent')
    check('STOP' not in body, 'wages are transactional — no marketing opt-out on them')

    print('\n6. NOW it is a cost, dated the day the money moved')
    check(finance.contractor_pay_between(start, end) == earned,
          f'the P&L counts ${earned:.2f} of labor in September')
    check(rows[0].created_at.strftime('%Y-%m-%d') == '2026-09-02',
          'dated when she paid it, not when she clicked')

    print('\n7. Paying cannot happen twice')
    c.post(f'/contractors/payroll/pay-job/{b.id}',
           data={'method': 'cash'}, follow_redirects=True)
    db.session.expire_all()
    check(ContractorPayment.query.filter_by(booking_id=b.id).count() == 1,
          'a job already paid stays at one payment')
    check(finance.contractor_pay_between(start, end) == earned,
          'and the cost is not counted twice')

    print('\n8. Crew jobs queue one payment per person, at their own split')
    b2 = Booking(service_type='standard', name='Ron Theison', address='2 St',
                 price=400.0, status='confirmed', preferred_date='2026-09-01')
    db.session.add(b2); db.session.commit()
    db.session.add_all([BookingCrew(booking_id=b2.id, staff_id=gen.id, pay_amount=120.0),
                        BookingCrew(booking_id=b2.id, staff_id=ana.id, pay_amount=80.0)])
    db.session.commit()
    c.post(f'/bookings/{b2.id}', data={'status': 'completed', 'price': '400'},
           follow_redirects=True)
    db.session.expire_all()
    crew_rows = {p.staff_id: p for p in ContractorPayment.query.filter_by(booking_id=b2.id).all()}
    check(len(crew_rows) == 2, 'two payments queued, one each')
    check(crew_rows[gen.id].amount == 120.0 and crew_rows[ana.id].amount == 80.0,
          'each at their own share, not the $400 job price')

    print('\n9. A crew job appears on the cleaner\'s own page')
    page = c.get(f'/contractors/team/{ana.id}').get_data(as_text=True)
    check('Ron Theison' in page, "the crew job is on Ana's page at all — it never used to be")
    check('$80.00' in page, 'at her $80 share')

    print('\n10. Nobody is silently dropped from payroll')
    orphan = Booking(service_type='standard', name='Sasha Gockov', address='3 St',
                     price=200.0, assigned_cleaner='Genesys Martay',   # misspelt
                     status='completed', preferred_date='2026-09-01')
    db.session.add(orphan); db.session.commit()
    page = c.get('/contractors/payroll?start=2026-09-01&end=2026-09-07').get_data(as_text=True)
    check("can't be matched to a team member" in page, 'the mismatch is reported, not swallowed')
    check('Genesys Martay' in page, 'and it quotes the name so it can be corrected')

    print('\n11. A cleaner who leaves is still owed what she is owed')
    gen.is_active = False
    db.session.commit()
    b3 = Booking(service_type='standard', name='Late Job', address='4 St', price=180.0,
                 assigned_cleaner='Genesis Marte', status='completed',
                 preferred_date='2026-09-03')
    db.session.add(b3); db.session.commit()
    page = c.get('/contractors/payroll?start=2026-09-01&end=2026-09-07').get_data(as_text=True)
    check('Late Job' in page, 'her unpaid job is still on payroll after she is deactivated')
    check("can't be matched" not in page or 'Genesis Marte' not in page.split("can't be matched")[1][:400],
          'and she is matched properly rather than reported as unmatchable')

    print('\n12. A lump-sum payment from her page tells them too')
    SENT['email'].clear(); SENT['sms'].clear()
    c.post(f'/contractors/team/{ana.id}/pay-manual',
           data={'amount': '60', 'method': 'cash'}, follow_redirects=True)
    check(len(SENT['email']) == 1 and len(SENT['sms']) == 1,
          'Ana was emailed and texted about the $60')
    check('$60.00' in SENT['sms'][0][1] and 'cash' in SENT['sms'][0][1],
          'quoting the amount and how it was paid')

print('\n🎉 Pay is recorded when earned, costs the business when paid, and never twice.')
