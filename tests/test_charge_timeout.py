"""A charge whose answer never came back is not a charge that failed.

When Stripe times out, or the connection drops, or Stripe answers 500, the
card may or may not have been charged -- nobody here knows yet. The off-session
charges in payment_service treated every StripeError as a decline: the owner
was told PAYMENT FAILED, collect it manually, and the customer was texted that
her payment didn't go through. If Stripe had in fact taken it, that is the
road to taking the same balance twice, once by card and once by hand.

What has to hold instead:
  - a decline (CardError) is a failure, and both are told, as before;
  - an unknown outcome tells the customer nothing and tells the owner to wait,
    not to collect;
  - the booking stays unpaid, and the next attempt sends the SAME idempotency
    key, so Stripe hands back the first result rather than charging again;
  - a charge that succeeded at Stripe but never got recorded here (the process
    died after Stripe answered) is recorded on the retry, or by the
    payment_intent.succeeded webhook, without a second charge.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/to.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_fake'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda *a, **k: (True, 'ok')
from app import create_app
from extensions import db
from models import Booking
app = create_app()

import stripe
import payment_service
import integrations
integrations.stripe_secret_key = lambda *a, **k: 'sk_test_fake'

SMS, EMAILS, CHARGES = [], [], []
payment_service.send_sms = lambda to, body, *a, **k: SMS.append((to, body)) or (True, 'ok')
payment_service.send_email = lambda *a, **k: EMAILS.append(k.get('subject', '')) or True

# Stripe as a dictionary of idempotency key -> the intent it created. A repeat
# key returns the stored intent and charges nothing, as Stripe does for 24h.
STRIPE = {}
MODE = {'next': 'ok'}


class _Intent:
    def __init__(self, n):
        self.id, self.status = f'pi_{n}', 'succeeded'


class _PI:
    @staticmethod
    def create(**kw):
        key = kw.get('idempotency_key')
        if key in STRIPE:
            return STRIPE[key]
        CHARGES.append(kw)                       # money moved
        STRIPE[key] = _Intent(len(CHARGES))
        mode, MODE['next'] = MODE['next'], 'ok'
        if mode == 'timeout_after_charge':
            raise stripe.error.APIConnectionError('Request timed out')
        if mode == 'server_error_after_charge':
            raise stripe.error.APIError('Internal error', http_status=500)
        return STRIPE[key]


payment_service.stripe.PaymentIntent = _PI
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def booking(**kw):
    b = Booking(service_type='deep', name='Ashley G', address='280 Ballow Dr',
                email='a@example.com', phone='4079890063', price=400,
                stripe_customer_id='cus_x', stripe_payment_method_id='pm_x',
                status='confirmed', preferred_date='2026-08-05', **kw)
    db.session.add(b)
    db.session.commit()
    return b


def failed_texts():
    return [s for s in SMS if "didn't go through" in s[1]]


with app.app_context():
    db.create_all()

    for fn, label in ((payment_service.charge_balance, 'balance'),
                      (payment_service.autocharge, 'auto-pay')):
        for mode, what in (('timeout_after_charge', 'times out'),
                           ('server_error_after_charge', 'answers 500')):
            print(f'\n{label}: Stripe takes the money, then {what}')
            b = booking()
            SMS.clear(); EMAILS.clear(); CHARGES.clear()
            MODE['next'] = mode
            ok, err = fn(b)
            db.session.expire_all()
            check(len(CHARGES) == 1, 'the card was charged once at Stripe')
            check(not ok and not Booking.query.get(b.id).paid_at,
                  'the job is not marked paid on an unknown outcome')
            check(not failed_texts(),
                  f'the customer is NOT texted that her payment failed (got {len(failed_texts())})')
            check(not any(s.startswith('PAYMENT FAILED') for s in EMAILS),
                  f'the owner is NOT told it failed and to collect by hand (got {EMAILS})')

            print(f'  ...then the retry')
            ok2, err2 = fn(Booking.query.get(b.id))
            db.session.expire_all()
            check(len(CHARGES) == 1, f'the retry charged nothing more (Stripe asked {len(CHARGES)} times)')
            check(ok2 and Booking.query.get(b.id).paid_at,
                  f'and the job is now recorded as paid ({err2 or "ok"})')

    print('\nA real decline is still a decline')
    b = booking()
    SMS.clear(); EMAILS.clear()

    def _decline(**kw):
        raise stripe.error.CardError('Your card was declined.', 'card', 'card_declined')
    keep = _PI.create
    _PI.create = staticmethod(_decline)
    try:
        ok, err = payment_service.charge_balance(b)
    finally:
        _PI.create = keep
    check(not ok and 'declined' in err.lower(), 'the owner sees the decline')
    check(len(failed_texts()) == 1, 'and the customer is told, as before')

    print('\nCharged at Stripe, never recorded here: the webhook settles it')
    b = booking()
    CHARGES.clear()
    MODE['next'] = 'timeout_after_charge'
    payment_service.charge_balance(b)
    pi_id = STRIPE[CHARGES[0]['idempotency_key']].id
    import blueprints.api as api
    api.integrations.stripe_webhook_secret = lambda *a, **k: 'whsec_test'
    event = {'type': 'payment_intent.succeeded',
             'data': {'object': {'id': pi_id, 'amount_received': 40000,
                                 'metadata': {'booking_id': str(b.id), 'kind': 'balance'}}}}
    keep_ce = api.stripe.Webhook.construct_event
    api.stripe.Webhook.construct_event = lambda *a, **k: event
    try:
        app.test_client().post('/api/stripe-webhook', data='{}',
                               headers={'Stripe-Signature': 't=1,v1=x'})
    finally:
        api.stripe.Webhook.construct_event = keep_ce
    db.session.expire_all()
    check(Booking.query.get(b.id).paid_at is not None,
          'a succeeded off-session balance charge marks the job paid from the webhook')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 An unknown outcome is never reported as a failure, and never charged twice.')
