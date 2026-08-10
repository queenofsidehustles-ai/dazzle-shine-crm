"""Customers who pay the morning of a cleaning cannot tip — they haven't seen the
work yet. The tip has to be offered afterwards, and the only thing that reaches
a customer after a job is the rating request.

Tips are the cleaner's money: never revenue, never labour, never part of margin.
"""
import os, sys, tempfile
from datetime import datetime, date
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/tip.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['CRM_BASE'] = 'https://crm.example.com'
os.environ['STRIPE_SECRET_KEY'] = 'sk_' + 'test_notareal0000004242'
os.environ['STRIPE_PUBLISHABLE_KEY'] = 'pk_' + 'test_notareal'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
TEXTS, EMAILS = [], []
notifications.send_sms = lambda to, msg, *a, **k: (TEXTS.append((to, msg)), (True, 'ok'))[1]
notifications.send_email = lambda **k: (EMAILS.append(k), (True, 'ok'))[1]

from app import create_app
from extensions import db
from models import Booking, Client, BookingRating, BusinessSetting
import finance

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

app = create_app()

# Stripe is never really called.
import blueprints.ratings as ratings_bp_mod
CHARGES = []
class _Intent:
    def __init__(self, amount): self.id, self.status, self.amount = 'pi_tip_1', 'succeeded', amount
    client_secret = 'cs_test_x'
class _PI:
    @staticmethod
    def create(**kw):
        CHARGES.append(kw)
        return _Intent(kw.get('amount', 0))
    @staticmethod
    def retrieve(pid):
        return _Intent(2500)

with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Dazzle & Shine Maids')
    BusinessSetting.set('phone', '(407) 555-0142')
    BusinessSetting.set('google_review_link', 'https://g.page/r/example/review')
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    def make(name, rating, paid=True, card=True, tip=0.0):
        cl = Client(name=name, email=f'{name.split()[0].lower()}@example.com',
                    phone='4075550111', zip_code='32801')
        db.session.add(cl); db.session.commit()
        b = Booking(client_id=cl.id, service_type='standard', name=name,
                    email=cl.email, phone=cl.phone, address='1 Lake St', price=180,
                    assigned_cleaner='Lauren Diaz', tip_amount=tip,
                    status='completed', preferred_date='2026-08-05',
                    paid_at=datetime(2026, 8, 5) if paid else None,
                    stripe_customer_id='cus_x' if card else None,
                    stripe_payment_method_id='pm_x' if card else None)
        db.session.add(b); db.session.commit()
        r = BookingRating(booking_id=b.id, token=f'tok-{b.id}')
        db.session.add(r); db.session.commit()
        return b, r, rating

    print('\n1. A happy customer is offered a tip, by their cleaner\'s name')
    b1, r1, _ = make('Renee Alvarez', 5)
    page = c.get(f'/rate/{r1.token}/5', follow_redirects=True).get_data(as_text=True)
    check('Add a tip for Lauren?' in page, 'the prompt names the cleaner, not the company')
    check('keeps 100% of it' in page, 'and says the money is hers')
    check('id="tip-amount"' in page, 'with a box to type any amount')
    check('$10' not in page and '18%' not in page, 'no suggested figures capping their generosity')

    print('\n2. The Google review button shows on the emailed star link')
    check('Leave a Google Review' in page,
          'which it never did before — only the form path passed the link')

    print('\n3. An unhappy customer is never asked for money')
    b2, r2, _ = make('Marcus Bell', 2)
    page2 = c.get(f'/rate/{r2.token}/2', follow_redirects=True).get_data(as_text=True)
    check('Add a tip' not in page2, 'no tip prompt after 2 stars')
    check('Leave a Google Review' not in page2, 'and no public review link either')
    check('(407) 555-0142' in page2, 'they get the phone number from Settings instead')

    print('\n4. Someone who already tipped is not asked twice')
    b3, r3, _ = make('Dana Reid', 5, tip=40.0)
    page3 = c.get(f'/rate/{r3.token}/5', follow_redirects=True).get_data(as_text=True)
    check('Add a tip' not in page3, 'no second ask when they tipped at payment')

    print('\n5. A prepay customer tips in one tap — their card is already on file')
    ratings_bp_mod.__dict__.setdefault('_x', None)
    import stripe as _stripe
    _stripe.PaymentIntent = _PI
    CHARGES.clear()
    res = c.post(f'/rate/{r1.token}/tip', json={'amount': 25})
    body = res.get_json()
    check(body['ok'] is True and body['done'] is True, 'the tip goes through immediately')
    check(len(CHARGES) == 1, 'exactly one charge')
    check(CHARGES[0]['amount'] == 2500, f"for $25 (got {CHARGES[0]['amount']} cents)")
    check(CHARGES[0]['off_session'] is True, 'against the saved card, off-session')
    check(CHARGES[0]['metadata']['kind'] == 'tip', 'and is marked as a tip, not a payment')

    print('\n6. It is recorded as the cleaner\'s money, not income')
    db.session.expire_all()
    b1 = Booking.query.get(b1.id)
    check(b1.tip_amount == 25.0, 'the tip is on the booking')
    check(b1.price == 180, 'the job price is untouched')
    start, end = finance.month_bounds(2026, 8)
    rev = finance.revenue_between(start, end)
    check(rev == 180 * 3, f'revenue counts the cleanings only, not the tip (${rev:,.0f})')
    tips = finance.tips_between(start, end)
    check(tips['collected'] == 65.0, f"tips are tracked separately (${tips['collected']})")
    check(tips['card_fee'] > 0, 'with the card fee taken off, so payroll shows what landed')

    print('\n7. A typo cannot take a fortune')
    res = c.post(f'/rate/{r1.token}/tip', json={'amount': 99999})
    check(res.get_json()['ok'] is False, 'an implausible amount is refused')
    res = c.post(f'/rate/{r1.token}/tip', json={'amount': 0})
    check(res.get_json()['ok'] is False, 'and so is nothing at all')
    res = c.post(f'/rate/{r1.token}/tip', json={'amount': 'twenty'})
    check(res.get_json()['ok'] is False, 'and so is text')

    print('\n8. A poor rating cannot be tipped even by calling the endpoint directly')
    CHARGES.clear()
    res = c.post(f'/rate/{r2.token}/tip', json={'amount': 20})
    check(res.get_json()['ok'] is False, 'refused for a 2-star job')
    check(CHARGES == [], 'and Stripe was never called')

    print('\n9. A customer with no card on file can still tip')
    b4, r4, _ = make('Owen Fry', 5, card=False)
    c.get(f'/rate/{r4.token}/5', follow_redirects=True)      # they rate first, as anyone would
    CHARGES.clear()
    res = c.post(f'/rate/{r4.token}/tip', json={'amount': 30})
    body = res.get_json()
    check(body['ok'] is True and body['done'] is False, 'they are asked for a card')
    check('client_secret' in body, 'and given a secret to enter it with')
    check('off_session' not in CHARGES[0], 'nothing was charged behind their back')
    res = c.post(f'/rate/{r4.token}/tip/confirm', json={'payment_intent_id': 'pi_tip_1'})
    check(res.get_json()['ok'] is True, 'confirming records the tip')
    db.session.expire_all()
    check(Booking.query.get(b4.id).tip_amount == 25.0,
          'at the amount Stripe reports, not the amount the browser claimed')

    print('\n10. The rating request now goes by text as well as email')
    TEXTS.clear(); EMAILS.clear()
    b5 = Booking(service_type='standard', name='Priya Shah', email='priya@example.com',
                 phone='4075550133', address='4 Bay St', price=200,
                 assigned_cleaner='Lauren Diaz', status='confirmed',
                 preferred_date='2026-08-06')
    db.session.add(b5); db.session.commit()
    c.post(f'/bookings/{b5.id}', data={'status': 'completed', 'price': '200'},
           follow_redirects=True)
    rate_texts = [m for _, m in TEXTS if '/rate/' in m]
    check(rate_texts, 'a text with the rating link went out')
    check('How did we do' in rate_texts[0], f'reading: "{rate_texts[0][:60]}…"')
    check('Reply STOP' in rate_texts[0], 'with an opt-out, as the law requires')
    check(any('How was your cleaning' in (e.get('subject') or '') for e in EMAILS),
          'and the email still goes too')

print('\n🎉 Tips are asked for after the work, only when it went well, and stay the cleaner\'s.')
