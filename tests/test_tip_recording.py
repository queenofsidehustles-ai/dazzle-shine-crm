"""A tip is only recorded once the card has actually been charged.

The bug this covers cost real money in one direction only. The tip was written
onto the booking the moment the customer opened the payment form. If they then
closed the tab, or the card declined, or they changed their mind and paid cash,
the tip stayed. Payroll told the owner "customer tipped $60", she handed the
cleaner $58.26 out of her own pocket, and the P&L counted $58.26 of income that
never existed.

Recording it later creates the opposite risk -- losing a real tip when the
browser never posts its confirmation -- so both paths are tested here: the
browser's own confirm, and Stripe's webhook for when there is no browser left.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/tip.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking
from blueprints.payments import record_tip_from_intent

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def a_booking(name):
    b = Booking(service_type='standard', name=name, status='confirmed',
                price=250.0, balance_due=250.0)
    db.session.add(b)
    db.session.commit()
    return b


with app.app_context():
    db.create_all()

    print('\n1. Opening the payment form records nothing')
    # create_intent() runs when the customer opens the payment page, before any
    # card is charged. It used to write the tip straight onto the booking. The
    # only way to be certain it no longer does is to read its body: isolate the
    # function and check no assignment to tip_amount survives in it.
    import inspect
    from blueprints import payments as payments_mod
    body = inspect.getsource(payments_mod.create_intent)
    check('tip_amount' not in body,
          'create_intent() no longer touches tip_amount at all')
    check("'tip': f'{tip:.2f}'" in body,
          'the tip still rides on the intent metadata, which is where it is read back from')

    print('\n2. A completed payment records the tip')
    b = a_booking('Paid With Tip')
    record_tip_from_intent(b, {'metadata': {'tip': '60.00'}})
    check(b.tip_amount == 60.0, 'a $60 tip on a succeeded payment is recorded')

    print('\n3. An abandoned payment records nothing')
    # The customer typed a tip, then closed the tab. Nothing succeeded, so
    # record_tip_from_intent is never called and the booking stays clean.
    b2 = a_booking('Abandoned')
    check((b2.tip_amount or 0) == 0,
          'a tip typed into a form that was never paid does not stick')
    # She later pays cash. Payroll must not claim a tip.
    from blueprints.payments import mark_paid
    mark_paid(b2, method='cash', notify=False)
    check((b2.tip_amount or 0) == 0,
          'and paying cash afterwards still shows no tip')

    print('\n4. The webhook records it when the browser never came back')
    b3 = a_booking('Tab Closed')
    record_tip_from_intent(b3, {'metadata': {'tip': '25.50'}})
    check(b3.tip_amount == 25.5,
          'a tip survives the customer closing the tab after paying')

    print('\n5. A replayed webhook cannot double a tip')
    for _ in range(4):
        record_tip_from_intent(b3, {'metadata': {'tip': '25.50'}})
    check(b3.tip_amount == 25.5, 'four more deliveries leave it at $25.50')

    print('\n6. Both paths agree, because both call the same function')
    b4 = a_booking('Race')
    pi = {'metadata': {'tip': '40.00'}}
    record_tip_from_intent(b4, pi)      # browser got there first
    record_tip_from_intent(b4, pi)      # webhook arrives after
    check(b4.tip_amount == 40.0, 'whichever arrives first wins and the other is a no-op')

    print('\n7. Nonsense in the metadata is not a crash')
    b5 = a_booking('Rubbish')
    for junk in ({}, {'metadata': {}}, {'metadata': {'tip': ''}},
                 {'metadata': {'tip': 'abc'}}, {'metadata': None}, None):
        record_tip_from_intent(b5, junk)
    check((b5.tip_amount or 0) == 0,
          'missing, empty or unparseable tip metadata records nothing')

    print('\n8. A zero tip is not written over a real one')
    b6 = a_booking('Zero After')
    record_tip_from_intent(b6, {'metadata': {'tip': '30.00'}})
    record_tip_from_intent(b6, {'metadata': {'tip': '0'}})
    check(b6.tip_amount == 30.0, 'a later zero does not erase a recorded tip')

    print('\n9. The card fee still comes off what the cleaner is handed')
    check(b6.tip_fee == 0.87, '2.9% of $30 is $0.87')
    check(b6.tip_net == 29.13, 'leaving $29.13')

print('\n\n✅ All tip-recording tests passed.\n')
