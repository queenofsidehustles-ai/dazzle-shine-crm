"""Booking #59: a customer could not pay, and Stripe showed nothing at all.

The address on the booking was `duffytyler96@gmail` — no `.com`. Stripe
validates the address when the customer record is created, and that happens
one line before the payment intent, so the whole call threw and no charge was
ever attempted. The customer saw a raw Stripe request id; the owner saw an
empty dashboard and no way to tell a typo from an outage.

Two things are protected here. An address that cannot be delivered to is
refused where it is typed, and — because one will get through anyway, from an
import or a booking taken before this existed — it can no longer stop somebody
paying.

Also covered: the deposit page quoting the balance. It printed
`booking.balance_due`, a column only ever written by the price-correction
route, so every ordinary booking told the customer they would owe $0.00 after
the cleaning and then received an invoice for the rest.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/typo.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from notifications import looks_like_email
from app import create_app
from extensions import db
from models import Booking, PricingSetting
import blueprints.bookings as bk
bk._send_booking_confirmation = lambda b: None
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


print('\n1. What counts as an address somebody can be reached at')
for good in ('duffytyler96@gmail.com', 'a.b+tag@sub.domain.co.uk', 'X@Y.IO'):
    check(looks_like_email(good), f'{good} is accepted')
for bad in ('duffytyler96@gmail', 'duffytyler96', '@gmail.com', 'a b@c.com',
            'a@b.', '', None):
    check(not looks_like_email(bad), f'{bad!r} is refused')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n2. The booking form will not store an address with no .com')
    c.post('/bookings/new', data={
        'name': 'Duffy Tyler', 'address': '3320 Lila drive, Orlando 32806',
        'service_type': 'moveout', 'bedrooms': '2', 'bathrooms': '1',
        'cleaning_price': '290', 'email': 'duffytyler96@gmail',
        'phone': '7036736816'}, follow_redirects=True)
    check(Booking.query.count() == 0, 'the booking was refused, not saved broken')

    c.post('/bookings/new', data={
        'name': 'Duffy Tyler', 'address': '3320 Lila drive, Orlando 32806',
        'service_type': 'moveout', 'bedrooms': '2', 'bathrooms': '1',
        'cleaning_price': '290', 'email': 'duffytyler96@gmail.com',
        'phone': '7036736816'}, follow_redirects=True)
    check(Booking.query.count() == 1, 'the corrected address goes through')

    print('\n3. A bad address already on file cannot stop the payment')
    # Exactly the state booking #59 was in.
    b = Booking(service_type='moveout', name='Duffy Tyler', address='3320 Lila drive',
                email='duffytyler96@gmail', phone='7036736816', price=290.0,
                deposit_token='dep-typo', pay_token='pay-typo')
    db.session.add(b); db.session.commit()

    sent = {}

    class FakeCustomer:
        id = 'cus_typo'

    def fake_create(**kw):
        sent.update(kw)
        return FakeCustomer()

    import stripe
    from blueprints.payments import stripe_customer_id_for
    real_create = stripe.Customer.create
    stripe.Customer.create = fake_create
    try:
        cid = stripe_customer_id_for(b)
    finally:
        stripe.Customer.create = real_create

    check(cid == 'cus_typo', 'a Stripe customer is still created')
    check('email' not in sent,
          'the undeliverable address is withheld from Stripe rather than failing the call')
    check(sent.get('name') == 'Duffy Tyler', 'the name still goes')
    check(b.email == 'duffytyler96@gmail',
          'and it stays on the booking, so it can be corrected and receipted later')

    print('\n4. The deposit page quotes the real balance, not a dead column')
    PricingSetting.set('deposit_amount', 50)
    db.session.commit()
    check((b.balance_due or 0) == 0, 'balance_due is still the unwritten column it always was')
    pub = app.test_client()
    page = pub.get('/pay-deposit/dep-typo').get_data(as_text=True)
    check('$240.00' in page, '$290 total less the $50 deposit is shown as $240.00')
    check('Balance after cleaning</span><span class="v">$0.00' not in page,
          'and never as $0.00')

    print('\n5. The heading follows the deposit setting')
    PricingSetting.set('deposit_amount', 75)
    db.session.commit()
    page = pub.get('/pay-deposit/dep-typo').get_data(as_text=True)
    check('Pay your $75 deposit to confirm' in page, 'the title asks for $75')
    check('$215.00' in page, 'and the balance follows it to $215.00')

print('\n🎉 A mistyped address is caught where it is typed, and can never again '
      'stop a customer paying.')
