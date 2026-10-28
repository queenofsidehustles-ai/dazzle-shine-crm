"""One successful charge and one credit per obligation (AKY-001/002/003).

The hourly charge run has two passes: the balance pass charges a job's own
saved card, then the auto-pay pass charges jobs whose customer has auto-pay on.
They sent Stripe different idempotency keys for the same money. So when the
balance charge timed out -- Stripe took the money, the answer never came back
-- the job was still unpaid when the auto-pay pass reached it a moment later,
and it charged the card again under a key Stripe had never seen.

And the webhook that records a charge whose answer never arrived compared the
intent only against the booking's latest one, so an older payment's event,
replayed after a newer charge on the same job, was credited a second time.

What has to hold, each against a fake Stripe that keeps its idempotency keys
the way the real one does:
  1. a timeout in the balance pass is not charged again by the auto-pay pass,
     in that run or the next, and settles on the retry;
  2. the balance and auto-pay paths send the same request for the same job;
  3. an unanswered charge is repeated exactly (same key, same amount) even
     after the price moves, and what it took is credited, not "paid in full";
  4. webhooks: duplicate, stale (replayed after a newer charge), out of order
     (arriving before the charge's own answer) and for a job already paid --
     each credits at most once, and money on a paid job is flagged, not booked;
  5. an unanswered charge older than Stripe's 24-hour key memory is looked
     up, not repeated, and one Stripe never received is dropped and recharged;
  6. a charge left pending on a past job is settled by the hourly run.
"""
import itertools
import os
import sys
import tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/obligation.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['REMINDER_API_KEY'] = 'cron-key'
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_fake'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda *a, **k: (True, 'ok')

from app import create_app
from extensions import db
from models import Booking, Client, PaymentCredit
import stripe
import integrations
import payment_service
import scheduling

integrations.stripe_secret_key = lambda *a, **k: 'sk_test_fake'
app = create_app()

SMS, EMAILS = [], []
payment_service.send_sms = lambda to, body, *a, **k: SMS.append(body) or (True, 'ok')
payment_service.send_email = lambda *a, **k: EMAILS.append(k.get('subject', '')) or True

# A fake Stripe. Keys are remembered as Stripe does: the same key gets the first
# answer back and charges nothing. A different set of parameters under a known
# key is refused, as Stripe refuses it. Every intent is kept so it can be listed.
KEYS = {}          # key -> (params, intent)
INTENTS = []       # every intent created, in order
_ids = itertools.count(1)
MODE = {'next': 'ok'}


class _Intent(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)


class _List:
    def __init__(self, items):
        self.items = items

    def auto_paging_iter(self):
        return iter(self.items)


class _PI:
    @staticmethod
    def create(**kw):
        key = kw.pop('idempotency_key')
        if key in KEYS:
            params, intent = KEYS[key]
            if params != kw:
                raise stripe.error.IdempotencyError('Keys for idempotent requests '
                                                    'can only be used with the same parameters')
            return intent
        mode, MODE['next'] = MODE['next'], 'ok'
        if mode == 'never_arrived':          # dropped before Stripe saw it
            raise stripe.error.APIConnectionError('Connection reset')
        intent = _Intent(id=f'pi_{next(_ids)}', status='succeeded',
                         amount=kw['amount'], amount_received=kw['amount'],
                         currency='usd', customer=kw['customer'],
                         metadata=dict(kw['metadata']), created=0)
        KEYS[key] = (dict(kw), intent)
        INTENTS.append(intent)
        if mode == 'timeout':                 # charged, answer lost
            raise stripe.error.APIConnectionError('Request timed out')
        return intent

    @staticmethod
    def list(**kw):
        return _List([i for i in INTENTS if i['customer'] == kw.get('customer')])


payment_service.stripe.PaymentIntent = _PI
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def charged(bid):
    return [i for i in INTENTS if i['metadata'].get('booking_id') == str(bid)]


def fresh(bid):
    db.session.expire_all()
    return db.session.get(Booking, bid)


def job(price=400, autopay_client=True, booking_card=True, date=None):
    client = Client(name='Ashley G', email='a@example.com', autopay=autopay_client,
                    stripe_customer_id='cus_x', stripe_payment_method_id='pm_x')
    db.session.add(client)
    db.session.flush()
    b = Booking(service_type='deep', name='Ashley G', address='280 Ballow Dr',
                email='a@example.com', phone='4079890063', price=price,
                client_id=client.id,
                stripe_customer_id='cus_x' if booking_card else None,
                stripe_payment_method_id='pm_x' if booking_card else None,
                status='confirmed', preferred_time='12:00 AM',
                preferred_date=date or scheduling.local_today().isoformat())
    db.session.add(b)
    db.session.commit()
    return b.id


def run():
    return app.test_client().post('/api/charge-balances',
                                  headers={'X-Api-Key': 'cron-key'})


import blueprints.api as api
api.integrations.stripe_webhook_secret = lambda *a, **k: 'whsec_test'


def deliver(pi):
    event = {'type': 'payment_intent.succeeded', 'data': {'object': dict(pi)}}
    keep = api.stripe.Webhook.construct_event
    api.stripe.Webhook.construct_event = lambda *a, **k: event
    try:
        return app.test_client().post('/api/stripe-webhook', data='{}',
                                      headers={'Stripe-Signature': 't=1,v1=x'})
    finally:
        api.stripe.Webhook.construct_event = keep


with app.app_context():
    db.create_all()
    import automations
    automations.set_balance_mode('auto')
    db.session.commit()

    print('\n1. A timeout in the balance pass is not charged again by auto-pay')
    bid = job()
    SMS.clear(); EMAILS.clear()
    MODE['next'] = 'timeout'
    r = run()
    check(r.status_code == 200, 'the run is answered')
    check(len(charged(bid)) == 1, f'the card was charged once (got {len(charged(bid))})')
    check(not fresh(bid).paid_at, 'the job is not marked paid on an unknown outcome')
    check(fresh(bid).charge_pending, 'the unanswered request is held')
    check(not [s for s in SMS if "didn't go through" in s], 'the customer is not told it failed')
    check(sum('not confirmed' in e for e in EMAILS) == 1, 'the owner is told once to wait')
    r = run()
    check(len(charged(bid)) == 1, f'the next run charged nothing more (got {len(charged(bid))})')
    b = fresh(bid)
    check(b.paid_at and not b.charge_pending, 'and the job settles on the retry')
    check(PaymentCredit.query.filter_by(booking_id=bid).count() == 1, 'credited once')
    run()
    check(len(charged(bid)) == 1, 'a third run takes nothing')

    print('\n2. Both paths send the same request for the same job')
    a, c = job(), job()
    MODE['next'] = 'timeout'
    payment_service.charge_balance(fresh(a))
    pending_a = fresh(a).charge_pending
    MODE['next'] = 'timeout'
    payment_service.autocharge(fresh(c))
    import json
    pa, pc = json.loads(pending_a), json.loads(fresh(c).charge_pending)
    check(pa['key'].startswith('akye-balance-') and pc['key'].startswith('akye-balance-'),
          'one key kind for the balance and auto-pay paths')
    check(pa['description'].startswith('Balance for Booking') and
          pc['description'].startswith('Balance for Booking'),
          'and the same description, so the request is identical')
    # And on the same job, auto-pay after a balance timeout is Stripe's first answer.
    ok, err = payment_service.autocharge(fresh(a))
    check(ok and len(charged(a)) == 1, f'auto-pay after a balance timeout charges nothing more ({err})')
    ok, err = payment_service.charge_balance(fresh(c))
    check(ok and len(charged(c)) == 1, f'and the other way round ({err})')

    print('\n3. An unanswered charge is repeated exactly, even after the price moves')
    bid = job()
    MODE['next'] = 'timeout'
    payment_service.charge_balance(fresh(bid))
    b = fresh(bid)
    b.price = 450
    db.session.commit()
    ok, err = payment_service.charge_balance(fresh(bid))
    check(len(charged(bid)) == 1, f'the retry was Stripe\'s first answer, not a $450 charge (got {len(charged(bid))})')
    b = fresh(bid)
    check(ok and float(b.amount_collected) == 400.0, f'the $400 it took is credited (collected {b.amount_collected})')
    check(not b.paid_at, 'and the job is not called paid in full')
    ok, err = payment_service.charge_balance(fresh(bid))
    check(ok and len(charged(bid)) == 2 and charged(bid)[-1]['amount'] == 5000,
          'the $50 difference is then a charge of its own')
    check(fresh(bid).paid_at, 'and the job is settled')

    print('\n4. Webhooks credit each payment at most once')
    bid = job()
    MODE['next'] = 'timeout'
    payment_service.charge_balance(fresh(bid))
    first = charged(bid)[0]
    # Out of order: the webhook arrives before the charge's own retry.
    deliver(first)
    b = fresh(bid)
    check(b.paid_at and float(b.amount_collected) == 400.0, 'the webhook records the charge whose answer was lost')
    check(not b.charge_pending, 'and the held request is cleared')
    ok, err = payment_service.charge_balance(fresh(bid))
    check(not ok and len(charged(bid)) == 1, 'the retry then finds nothing owed and charges nothing')
    # Duplicate.
    deliver(first)
    check(float(fresh(bid).amount_collected) == 400.0, 'a duplicate webhook credits nothing more')
    # Stale: a newer charge on the same job, then the older event replayed.
    b = fresh(bid)
    b.price = 500
    db.session.commit()
    ok, err = payment_service.charge_balance(fresh(bid))
    second = charged(bid)[-1]
    check(ok and second['amount'] == 10000 and fresh(bid).stripe_payment_intent == second['id'],
          'a $100 price rise is charged as a second payment')
    deliver(first)
    b = fresh(bid)
    check(float(b.amount_collected) == 500.0,
          f'the older payment replayed after it is not credited again (collected {b.amount_collected})')
    deliver(second)
    check(float(fresh(bid).amount_collected) == 500.0, 'nor the newer one')
    check(PaymentCredit.query.filter_by(booking_id=bid).count() == 2, 'two payments, two credits')
    # Money on a job already paid, from a payment this system never credited.
    EMAILS.clear()
    stray = dict(first, id='pi_stray', amount_received=40000)
    deliver(stray)
    deliver(stray)
    check(float(fresh(bid).amount_collected) == 500.0, 'a payment on a job already paid is not booked as income')
    check(sum(e.startswith('Paid twice?') for e in EMAILS) == 1,
          f'the owner is told once to refund one ({EMAILS})')

    print('\n5. Past Stripe\'s 24-hour key memory, look it up rather than repeat it')
    bid = job()
    MODE['next'] = 'timeout'
    payment_service.charge_balance(fresh(bid))
    b = fresh(bid)
    p = json.loads(b.charge_pending)
    p['at'] = (datetime.utcnow() - timedelta(hours=30)).isoformat(timespec='seconds')
    b.charge_pending = json.dumps(p)
    db.session.commit()
    KEYS.pop(p['key'])                        # Stripe has forgotten the key
    ok, err = payment_service.charge_balance(fresh(bid))
    check(ok and len(charged(bid)) == 1, f'the charge that did go through is found and recorded ({err})')
    check(fresh(bid).paid_at, 'and the job is settled without a second charge')

    bid = job()
    MODE['next'] = 'never_arrived'
    payment_service.charge_balance(fresh(bid))
    b = fresh(bid)
    p = json.loads(b.charge_pending)
    p['at'] = (datetime.utcnow() - timedelta(hours=30)).isoformat(timespec='seconds')
    b.charge_pending = json.dumps(p)
    db.session.commit()
    check(len(charged(bid)) == 0, 'a request Stripe never received charged nothing')
    ok, err = payment_service.charge_balance(fresh(bid))
    check(ok and len(charged(bid)) == 1, f'it is dropped after a lookup, and charged once ({err})')

    print('\n6. A charge left pending on a past job is settled by the hourly run')
    yesterday = (scheduling.local_today() - timedelta(days=1)).isoformat()
    bid = job(date=yesterday)
    MODE['next'] = 'timeout'
    payment_service.charge_balance(fresh(bid))
    check(fresh(bid).charge_pending and not fresh(bid).paid_at, 'yesterday\'s charge is unanswered')
    r = run()
    check(fresh(bid).paid_at and not fresh(bid).charge_pending,
          'the run finds it went through and records it')
    check(len(charged(bid)) == 1, 'without charging it again')
    check(any(x.get('settled') for x in r.get_json()['results']), 'and reports it as settled')

    print('\n7. A request still in flight elsewhere is not a decline')
    bid = job()
    SMS.clear()
    keep = _PI.create

    def _busy(**kw):
        raise stripe.error.IdempotencyError('There is currently another in-progress request')
    _PI.create = staticmethod(_busy)
    try:
        ok, err = payment_service.charge_balance(fresh(bid))
    finally:
        _PI.create = keep
    check(not ok and 'may or may not' in err, 'reported as unknown, not as failed')
    check(not SMS, 'and the customer is not texted that it failed')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print('   -', f)
    sys.exit(1)
print('\n🎉 One charge and one credit per obligation, whatever order things arrive in.')
