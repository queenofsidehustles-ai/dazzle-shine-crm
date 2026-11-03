"""A missed day is caught up once, safely, and a failed charge is visible.

The collector only looked at today's date, so a job whose day passed without
an attempt (late, missing or down hourly runs) was never tried. The catch-up
collects never-tried jobs from the last few days -- not declined ones, not
held, cancelled or already-pending ones -- and the reply counts failures so the
scheduler can fail instead of reporting a decline as success.
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


import itertools
_ids = itertools.count(1)


class _Intent:
    status = 'succeeded'

    def __init__(self):
        # Each charge is its own intent at Stripe, and is credited once.
        self.id = f'pi_test_single_run_{next(_ids)}'


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



import datetime as dt
TAG = secrets.token_hex(4)
SLUG = f'catchup{TAG}'
KEY = secrets.token_hex(16)
os.environ['REMINDER_API_KEY'] = KEY
HOST = {'Host': f'{SLUG}.akyehq.test', 'X-Api-Key': KEY}
URL = '/api/charge-balances'

with app.app_context():
    engine = provisioning._engine()
    import control_plane
    control_plane.ensure_table(engine)
    db.session.remove()
    provisioning.provision(SLUG, 'Catch Up Co',
                           owner_email=f'owner-{TAG}@example.com', quiet=True)
    db.session.remove()

    from models import Booking

    def day(n):
        return (scheduling.local_today() - dt.timedelta(days=n)).isoformat()

    def make(days_ago, **kw):
        db.session.remove()
        with tenancy.use_tenant(SLUG):
            automations.set_balance_mode('auto')
            fields = dict(service_type='deep', name='Ashley G', address='1 Main St',
                          email='a@example.com', phone='4079890063', price=400.0,
                          stripe_customer_id='cus_x', stripe_payment_method_id='pm_x',
                          status='confirmed', preferred_date=day(days_ago),
                          preferred_time='9:00 AM')
            fields.update(kw)
            b = Booking(**fields)
            db.session.add(b)
            db.session.commit()
            bid = b.id
        db.session.remove()
        return bid

    def get(bid, attr):
        db.session.remove()
        with tenancy.use_tenant(SLUG):
            v = getattr(db.session.get(Booking, bid), attr)
        db.session.remove()
        return v

    c = app.test_client()

    print('\n1. Yesterday\'s never-tried job is collected')
    y = make(1)
    CHARGES.clear()
    r = c.post(URL, headers=HOST)
    check(len(CHARGES) == 1, f'Stripe asked once (got {len(CHARGES)})')
    check(bool(get(y, 'paid_at')), 'and the job is settled')
    check(any(x.get('catch_up') for x in r.get_json()['results']), 'the reply says it was a catch-up')

    done = make(1, status='completed')
    CHARGES.clear()
    c.post(URL, headers=HOST)
    check(len(CHARGES) == 1 and bool(get(done, 'paid_at')),
          'a job closed out without collecting is collected too')

    print('\n2. It is tried once, not every hour')
    CHARGES.clear()
    c.post(URL, headers=HOST)
    check(len(CHARGES) == 0, 'a settled job is left alone')

    print('\n3. Too old, held, cancelled, pending and already-tried jobs are left alone')
    old = make(CATCH_DAYS := 9)
    held = make(1, status='on_hold')
    gone = make(1, status='cancelled')
    pend = make(1, charge_pending='{"key":"k"}')
    tried = make(1, charge_tried_at=dt.datetime.utcnow())
    nocard = make(1, stripe_payment_method_id=None)
    CHARGES.clear()
    c.post(URL, headers=HOST)
    check(len(CHARGES) == 0, f'no card was touched (got {len(CHARGES)})')

    print('\n4. A decline is recorded, reported, and not retried by the catch-up')
    payment_service.stripe.PaymentIntent = type('PI', (), {
        'create': staticmethod(lambda **kw: (_ for _ in ()).throw(
            payment_service.stripe.error.CardError('declined', 'card', 'card_declined')))})
    d = make(2)
    r = c.post(URL, headers=HOST)
    body = r.get_json()
    check(body['failed'] == 1, 'the reply counts the failed charge')
    check(r.status_code == 200 and body['ok'] is True, 'while the request itself still succeeded')
    check(get(d, 'charge_tried_at') is not None, 'the attempt is written down')
    payment_service.stripe.PaymentIntent = _PI
    CHARGES.clear()
    c.post(URL, headers=HOST)
    check(len(CHARGES) == 0, 'the next hour does not charge the declined card again')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ A missed day is caught up once, and a decline is not a quiet success.')
