"""Changing the deposit changes what is charged — and not what was already paid.

Settings → Pricing has always had a deposit field. It wrote a setting that only
the public price page ever read: every path that actually took money, credited
it against a balance, or put it on an invoice used a hardcoded $50. So an owner
could set the deposit to $75, watch her quote page say $75, and have her
customers charged $50 — with the invoice crediting a third figure.

Making the setting real introduces the opposite risk, which is the more
expensive one: a booking that paid $50 must not start being credited $75 the
day the setting changes, or every old job collects the difference too little.
That is most of what is tested here.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/dep.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, PricingSetting
from blueprints.payments import amount_due, mark_deposit_paid
import pricing

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def set_deposit(v):
    PricingSetting.set('deposit_amount', v)
    db.session.commit()


def a_booking(name, price=300.0, **kw):
    b = Booking(service_type='standard', name=name, status='confirmed',
                price=price, balance_due=price, **kw)
    db.session.add(b)
    db.session.commit()
    return b


with app.app_context():
    db.create_all()

    print('\n1. The shipped default is unchanged')
    check(pricing.get_deposit() == 50, 'with nothing set, the deposit is $50')

    print('\n2. Changing the setting changes what a customer owes')
    b = a_booking('Standard Deposit')
    check(amount_due(b) == 300.0, 'nothing paid yet, so the whole $300 is due')
    mark_deposit_paid(b, amount_cents=5000)
    check(amount_due(b) == 250.0, 'after a $50 deposit, $250 is left')

    set_deposit(75)
    check(pricing.get_deposit() == 75, 'the setting now reads $75')
    later = a_booking('Bigger Deposit')
    mark_deposit_paid(later, amount_cents=7500)
    check(amount_due(later) == 225.0,
          'a new booking pays $75 and owes $225 — the setting reached the money')

    print('\n3. And does NOT change what an older booking already paid')
    # The expensive direction. This booking paid $50; the setting is now $75.
    check(b.deposit_amount_paid == 50.0, 'the $50 it paid is recorded on it')
    check(amount_due(b) == 250.0,
          'so it still owes $250, not the $225 the new setting would imply')

    print('\n4. A booking from before the column existed falls back sensibly')
    old = a_booking('Legacy', deposit_paid=True)
    old.deposit_amount_paid = None          # as every pre-migration row will be
    db.session.commit()
    check(amount_due(old) == 225.0,
          'it credits the deposit in force, which is all there is to go on')

    print('\n5. What was paid is written once and never revised')
    set_deposit(120)
    check(b.deposit_amount_paid == 50.0, 'the old booking still records $50')
    mark_deposit_paid(b, amount_cents=12000)   # a second, later call
    check(b.deposit_amount_paid == 50.0,
          'and a repeat notification does not overwrite it')
    check(amount_due(b) == 250.0, 'so what it owes has not moved either')

    print('\n6. An odd deposit converts to cents without losing one')
    # int(49.99 * 100) is 4998 in binary floating point. Every other charge in
    # the codebase rounds; this one is a setting now, so it can be any value.
    set_deposit(49.99)
    check(int(round(pricing.get_deposit() * 100)) == 4999,
          '$49.99 is 4999 cents, not 4998')

    print('\n7. A job paid in full owes nothing, whatever the deposit is')
    set_deposit(50)
    paid = a_booking('Settled', paid_at=datetime.utcnow())
    check(amount_due(paid) == 0.0, 'a settled job is settled')

    print('\n8. No path still quotes a hardcoded deposit')
    import pathlib
    root = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    offenders = []
    for f in list((root / 'blueprints').glob('*.py')) + \
             [root / 'invoicing.py', root / 'quoting.py']:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if 'DEPOSIT_AMOUNT' not in line or line.strip().startswith('#'):
                continue
            # The import itself is fine; it is still the default behind the
            # setting. What must not survive is arithmetic on the constant.
            if any(k in line for k in ('amount=', 'balance_due', "'deposit'",
                                       'abs(', 'paid = ')):
                offenders.append(f'{f.name}:{i}')
    check(not offenders, f'nothing charges or credits the constant ({offenders})')

print('\n\n✅ All deposit tests passed.\n')
