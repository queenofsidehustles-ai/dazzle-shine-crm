"""Two charging runs at once must not debit the same card twice.

The endpoint selects every booking whose balance is outstanding, then charges
them one at a time. The flag saying a booking is settled is written as each
charge succeeds, so a second run starting while the first is partway down its
list selects the bookings the first has not reached yet and charges them again.
Nothing in either request knew about the other.

That was survivable while exactly one timetable existed. It stops being
survivable the moment the clock moves, because a handover means a window with
two clocks running, and a card charged twice is the one fault here that cannot
be put right by correcting a record.

Against a real disposable Postgres: the guard is a Postgres advisory lock, so
SQLite cannot exercise it at all.
"""
import os
import secrets
import sys

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_fake'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from sqlalchemy import text

from app import create_app
from extensions import db
import automations
import integrations
import payment_service
import provisioning
import scheduling
import tenancy

# Nothing real is called; every attempt is counted.
CHARGES = []


class _Intent:
    status = 'succeeded'
    id = 'pi_test_single_run'


class _PI:
    @staticmethod
    def create(**kw):
        CHARGES.append(kw)
        return _Intent()


payment_service.stripe.PaymentIntent = _PI
payment_service.send_email = lambda *a, **k: True
integrations.stripe_secret_key = lambda *a, **k: 'sk_test_fake'

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


TAG = secrets.token_hex(4)
SLUG = f'chargelock{TAG}'
KEY = secrets.token_hex(16)
os.environ['REMINDER_API_KEY'] = KEY
HOST = {'Host': f'{SLUG}.akyehq.test', 'X-Api-Key': KEY}
URL = '/api/charge-balances'

with app.app_context():
    engine = provisioning._engine()
    import control_plane
    control_plane.ensure_table(engine)
    db.session.remove()
    provisioning.provision(SLUG, 'Charge Lock Co',
                           owner_email=f'owner-{TAG}@example.com', quiet=True)
    db.session.remove()

    SCHEMA = tenancy.schema_for(SLUG)
    LOCK = f'akye:charge-balances:{SCHEMA}'

    def make_booking():
        """One job, today, with a card on file and the whole price outstanding."""
        from models import Booking
        db.session.remove()
        with tenancy.use_tenant(SLUG):
            automations.set_balance_mode('auto')
            b = Booking(service_type='deep', name='Ashley G',
                        address='280 Ballow Dr', email='a@example.com',
                        phone='4079890063', price=400.0,
                        stripe_customer_id='cus_x',
                        stripe_payment_method_id='pm_x',
                        status='confirmed',
                        preferred_date=scheduling.local_today().isoformat(),
                        preferred_time='12:00 AM')
            db.session.add(b)
            db.session.commit()
            bid = b.id
        db.session.remove()
        return bid

    def paid(bid):
        from models import Booking
        db.session.remove()
        with tenancy.use_tenant(SLUG):
            b = db.session.get(Booking, bid)
            out = bool(b and b.paid_at)
        db.session.remove()
        return out

    c = app.test_client()

    print('\n1. One run charges the card once')
    bid = make_booking()
    CHARGES.clear()
    r = c.post(URL, headers=HOST)
    check(r.status_code == 200, 'the run is accepted')
    check(len(CHARGES) == 1, f'Stripe was asked exactly once (got {len(CHARGES)})')
    check(r.get_json().get('charged') == 1, 'and the run reports one charge')
    check(paid(bid), 'the booking is recorded as paid')

    print('\n2. Running it again takes nothing more')
    CHARGES.clear()
    r = c.post(URL, headers=HOST)
    check(len(CHARGES) == 0, 'a settled booking is not charged a second time')

    print('\n3. The lock is released when a run finishes')
    with engine.connect() as probe:
        got = probe.execute(text('SELECT pg_try_advisory_lock(hashtext(:k))'),
                            {'k': LOCK}).scalar()
        check(bool(got), 'the next hour can take the lock')
        if got:
            probe.execute(text('SELECT pg_advisory_unlock(hashtext(:k))'), {'k': LOCK})
            probe.commit()

    print('\n4. A second clock, while the first run holds the lock')
    bid2 = make_booking()
    CHARGES.clear()
    held = engine.connect()
    held.execute(text('SELECT pg_advisory_lock(hashtext(:k))'), {'k': LOCK})
    held.commit()
    try:
        r = c.post(URL, headers=HOST)
        body = r.get_json()
        check(r.status_code == 200, 'the second run is answered, not left hanging')
        check(body.get('skipped') == 'another run is already in progress',
              'and says why it did nothing')
        check(len(CHARGES) == 0,
              f'no card was touched by the overlapping run (got {len(CHARGES)})')
        check(not paid(bid2), 'the booking is still outstanding, not double-charged')
    finally:
        held.execute(text('SELECT pg_advisory_unlock(hashtext(:k))'), {'k': LOCK})
        held.commit()
        held.close()

    print('\n5. Once the first run is done, the next one collects')
    CHARGES.clear()
    r = c.post(URL, headers=HOST)
    check(len(CHARGES) == 1, 'the booking the overlap skipped is charged now')
    check(paid(bid2), 'and settled')

    print('\n6. One company waiting does not hold up another')
    other = f'chargelockb{TAG}'
    provisioning.provision(other, 'Other Co',
                           owner_email=f'other-{TAG}@example.com', quiet=True)
    db.session.remove()
    held = engine.connect()
    held.execute(text('SELECT pg_advisory_lock(hashtext(:k))'), {'k': LOCK})
    held.commit()
    try:
        r = c.post(URL, headers={'Host': f'{other}.akyehq.test', 'X-Api-Key': KEY})
        check(r.status_code == 200 and 'already in progress' not in str(r.get_json()),
              'a different company runs while this one is locked')
    finally:
        held.execute(text('SELECT pg_advisory_unlock(hashtext(:k))'), {'k': LOCK})
        held.commit()
        held.close()

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 Two clocks cannot charge one card twice.')
