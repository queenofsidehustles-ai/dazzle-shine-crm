"""Sales in money, and discount codes for Akye's own plans.

Three layers, each with exact numbers:
  1. billing.monthly_cents turns what Stripe sends into a monthly figure.
  2. funnel.sales adds companies up into MRR, movement, pipeline and discounts.
  3. Against real Postgres: the webhook writes the money down, the console
     shows it, and discount codes are made in (a stand-in for) Stripe, with
     only managers allowed to make or switch them.
"""
import os
import secrets
import sys
from datetime import datetime, timedelta

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
os.environ['STRIPE_PLATFORM_SECRET_KEY'] = 'sk_test_fake'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import billing
import entitlements
import funnel

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def sub(amount, interval='month', qty=1, discount=None):
    s = {'items': {'data': [{'quantity': qty, 'price': {
        'unit_amount': amount, 'recurring': {'interval': interval, 'interval_count': 1}}}]}}
    if discount:
        s['discount'] = discount
    return s


NOW = datetime(2026, 9, 24, 12)
future = int((NOW + timedelta(days=60)).timestamp())
past = int((NOW - timedelta(days=1)).timestamp())

print('\n1. What Stripe sends becomes a monthly figure')
check(billing.monthly_cents(sub(7900)) == 7900, '$79 a month is $79')
check(billing.monthly_cents(sub(79000, 'year')) == 6583, '$790 a year is $65.83 a month')
check(billing.monthly_cents(sub(7900, qty=2)) == 15800, 'two seats count twice')
check(billing.monthly_cents(sub(7900, discount={'coupon': {'duration': 'forever', 'percent_off': 50}}))
      == 3950, 'a forever 50% code halves it')
check(billing.monthly_cents(sub(7900, discount={'coupon': {'duration': 'repeating', 'percent_off': 25},
                                                'end': future}), now=NOW) == 5925,
      'a 3-month 25% code still running takes 25% off')
check(billing.monthly_cents(sub(7900, discount={'coupon': {'duration': 'repeating', 'percent_off': 25},
                                                'end': past}), now=NOW) == 7900,
      'and once it has ended, nothing')
check(billing.monthly_cents(sub(7900, discount={'coupon': {'duration': 'once', 'amount_off': 2000}}))
      == 7900, 'a first-payment-only code is not recurring revenue lost')
check(billing.monthly_cents(sub(7900, discount={'coupon': {'duration': 'forever', 'amount_off': 9000}}))
      == 0, 'a dollar code bigger than the price stops at zero')
check(billing.monthly_cents({'items': {'data': []}}) is None,
      'no prices at all is "unknown", not $0')


def org(slug, **kw):
    row = {'slug': slug, 'name': slug.title(), 'plan': 'pro', 'status': 'active',
           'subscription_status': 'trialing', 'created_at': NOW - timedelta(days=40),
           'trial_ends_at': NOW + timedelta(days=5), 'activated_at': None,
           'stripe_subscription_id': None, 'grandfathered': False, 'mrr_cents': None,
           'paid_since': None, 'canceled_at': None, 'discount_code': None,
           'owner_email': f'{slug}@x.test'}
    row.update(kw)
    return row


ORGS = [
    org('dazzle', grandfathered=True, subscription_status='active', stripe_subscription_id='s0',
        mrr_cents=24900, paid_since=NOW - timedelta(days=300)),
    # Pro, paying $79 for 100 days.
    org('alpha', subscription_status='active', stripe_subscription_id='s1', mrr_cents=7900,
        paid_since=NOW - timedelta(days=100)),
    # Scale, started paying 10 days ago with a forever 20% code: $199.20.
    org('bravo', plan='scale', subscription_status='active', stripe_subscription_id='s2',
        mrr_cents=19920, paid_since=NOW - timedelta(days=10), discount_code='FOUNDING20'),
    # Paying, but the webhook has not priced it yet: counted at Pro list price.
    org('charlie', subscription_status='active', stripe_subscription_id='s3',
        paid_since=NOW - timedelta(days=5)),
    # Card failing on $79.
    org('delta', subscription_status='past_due', stripe_subscription_id='s4', mrr_cents=7900,
        paid_since=NOW - timedelta(days=200)),
    # Left 20 days ago, was paying $249.
    org('echo', plan='scale', subscription_status='canceled', stripe_subscription_id='s5',
        mrr_cents=24900, paid_since=NOW - timedelta(days=150), canceled_at=NOW - timedelta(days=20)),
    # Two live trials and one that ran out.
    org('fox'), org('golf'), org('hotel', trial_ends_at=NOW - timedelta(days=1)),
]

print('\n2. The sales numbers add up, exactly')
s = funnel.sales(ORGS, entitlements.PLANS, now=NOW, days=30)
check(s['paying'] == 3 and s['mrr'] == 7900 + 19920 + 7900,
      f"MRR is the three paying companies, $357.20 ({s['mrr']})")
check(s['arr'] == s['mrr'] * 12 and s['arpa'] == round(s['mrr'] / 3), 'ARR and average per company')
check(s['estimated'] == 1, 'the one not yet priced by Stripe is flagged as list price')
check([(k, n, c) for k, _l, n, c, _p in s['by_plan']] == [('scale', 1, 19920), ('pro', 2, 15800)],
      f"by plan, biggest first ({s['by_plan']})")
check(s['new'] == 2 and s['new_mrr'] == 19920 + 7900, 'new in 30 days: Bravo and Charlie')
check(s['lost'] == 1 and s['lost_mrr'] == 24900, 'lost in 30 days: Echo, $249')
check(s['net_new_mrr'] == 19920 + 7900 - 24900, 'net new is new minus lost')
check(s['past_due'] == 1 and s['past_due_mrr'] == 7900, 'at risk: Delta, $79')
check(s['trials'] == 2, 'two live trials; the expired one is not pipeline')
check(s['paid_rate'] == 62, f"5 of 8 non-grandfathered companies have ever paid ({s['paid_rate']}%)")
check(s['pipeline_if_all'] == round(2 * s['mrr'] / 3), 'every trial valued at the average customer')
check(s['pipeline_expected'] == round(2 * s['mrr'] / 3 * 5 / 8), 'and weighted by the paid rate')
check(s['discount_cost'] == 24900 - 19920, 'Bravo\'s code costs $49.80 a month against list')
check(s['codes'] == {'FOUNDING20': {'used': 1, 'paying': 1, 'mrr': 19920}}, 'usage per code')
check('dazzle' not in [c['slug'] for c in s['customers']], 'grandfathered is left out')
s_all = funnel.sales(ORGS, entitlements.PLANS, now=NOW, days=None)
check(s_all['new'] == 5 and s_all['lost'] == 1, 'all time: everyone who ever started paying')
check(s_all['net_new_mrr'] == s_all['mrr'] + s_all['past_due_mrr'],
      'and over all time, new minus lost is exactly what is billed today')
empty = funnel.sales([], entitlements.PLANS, now=NOW, days=30)
check(empty['mrr'] == 0 and empty['arpa'] is None and empty['pipeline_expected'] is None,
      'no data: zero MRR, no average, no made-up forecast')


# --------------------------------------------------------------------------
# The webhook, the pages and the codes, against real Postgres

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

import stripe
from sqlalchemy import text

from app import create_app
from extensions import db
import control_plane
import provisioning

STRIPE = {'coupons': [], 'promos': [], 'deleted': [], 'modified': [], 'fail_promo': False}


class _Obj(dict):
    pass


def _coupon_create(**kw):
    STRIPE['coupons'].append(kw)
    return _Obj(id=f'co_{len(STRIPE["coupons"])}')


def _promo_create(**kw):
    if STRIPE['fail_promo']:
        raise stripe.error.InvalidRequestError('That code is already in use.', 'code')
    STRIPE['promos'].append(kw)
    return _Obj(id=f'promo_{len(STRIPE["promos"])}')


stripe.Coupon.create = staticmethod(_coupon_create)
stripe.Coupon.delete = staticmethod(lambda cid: STRIPE['deleted'].append(cid))
stripe.PromotionCode.create = staticmethod(_promo_create)
stripe.PromotionCode.modify = staticmethod(
    lambda pid, **kw: STRIPE['modified'].append((pid, kw)))


class _List:
    def auto_paging_iter(self):
        return iter([{'id': 'promo_1', 'times_redeemed': 3}])


stripe.PromotionCode.list = staticmethod(lambda **kw: _List())

app = create_app()
TAG = secrets.token_hex(3)
A = f'e2esalesa{TAG}'
HELPER, MANAGER = f'shelper-{TAG}@example.com', f'smanager-{TAG}@example.com'
PASSWORD = 'a-real-console-password-1'
CODE = f'T{TAG.upper()}50'


def signed_in(email):
    c = app.test_client()
    r = c.post('/console/login', data={'email': email, 'password': PASSWORD})
    db.session.remove()
    assert r.status_code == 302
    return c


def get(c, path):
    r = c.get(path)
    db.session.remove()
    return r


def post(c, path, data=None):
    r = c.post(path, data=data or {})
    db.session.remove()
    return r


with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    control_plane.create(engine, A, f'Sales Alpha {TAG}', f'a-{TAG}@example.com')
    control_plane.add_console_user(engine, HELPER, 'Helper', PASSWORD, role='helper')
    control_plane.add_console_user(engine, MANAGER, 'Manager', PASSWORD, role='manager')
    db.session.remove()
    helper, manager = signed_in(HELPER), signed_in(MANAGER)

    print('\n3. Discount codes: only managers make them, and only valid ones')
    body = get(helper, '/console/discounts').data.decode()
    check('New code' not in body, 'a helper sees no form')
    post(helper, '/console/discounts', {'code': CODE, 'kind': 'percent', 'percent': '50',
                                        'duration': 'forever'})
    check(STRIPE['coupons'] == [], 'and posting at it makes nothing in Stripe')
    for bad, why in (({'code': 'x', 'percent': '10'}, 'too short'),
                     ({'code': CODE, 'percent': '0'}, '0%'),
                     ({'code': CODE, 'percent': '101'}, '101%'),
                     ({'code': CODE, 'kind': 'amount', 'amount': '-5'}, 'negative dollars'),
                     ({'code': CODE, 'percent': '10', 'duration': 'repeating'}, 'months missing'),
                     ({'code': CODE, 'percent': '10', 'expires': '2020-01-01'}, 'expiry in the past'),
                     ({'code': 'BAD CODE!', 'percent': '10'}, 'spaces and punctuation')):
        post(manager, '/console/discounts', dict({'kind': 'percent', 'duration': 'once'}, **bad))
    check(STRIPE['coupons'] == [], 'nothing invalid reaches Stripe (7 kinds of bad input)')

    r = post(manager, '/console/discounts', {
        'code': CODE.lower(), 'kind': 'percent', 'percent': '50', 'duration': 'repeating',
        'months': '3', 'max_redemptions': '20', 'expires': '2099-12-31', 'note': 'founding cohort'})
    check(STRIPE['coupons'] == [{'duration': 'repeating', 'name': CODE,
                                 'metadata': {'source': 'akye-console'},
                                 'percent_off': 50, 'duration_in_months': 3}],
          f"the coupon Stripe gets: 50% for 3 months ({STRIPE['coupons']})")
    promo = STRIPE['promos'][0] if STRIPE['promos'] else {}
    check(promo.get('code') == CODE and promo.get('max_redemptions') == 20
          and promo.get('coupon') == 'co_1' and promo.get('expires_at'),
          'and the code a customer types, uppercased, limited and expiring')
    row = control_plane.find_promo_code(engine, code=CODE)
    check(row and row['stripe_promotion_id'] == 'promo_1' and row['created_by'] == MANAGER,
          'recorded with its Stripe ids and who made it')
    post(manager, '/console/discounts', {'code': CODE, 'kind': 'percent', 'percent': '10',
                                         'duration': 'once'})
    check(len(STRIPE['coupons']) == 1, 'the same code twice is refused before Stripe')

    STRIPE['fail_promo'] = True
    other = f'U{TAG.upper()}10'
    r = post(manager, '/console/discounts', {'code': other, 'kind': 'amount', 'amount': '10',
                                             'duration': 'once'})
    STRIPE['fail_promo'] = False
    check(control_plane.find_promo_code(engine, code=other) is None,
          'if Stripe refuses the code, nothing is recorded')
    check(STRIPE['deleted'] == ['co_2'], 'and the orphan coupon is deleted from Stripe')

    body = get(helper, '/console/discounts').data.decode()
    check(CODE in body and '50% off 3 months' in body and 'Stripe: 3 redemptions' in body,
          'the list shows the code, its terms and Stripe\'s redemption count')

    post(helper, f'/console/discounts/{CODE}/active', {'on': '0'})
    check(STRIPE['modified'] == [], 'a helper cannot switch it off')
    post(manager, f'/console/discounts/{CODE}/active', {'on': '0'})
    check(STRIPE['modified'] == [('promo_1', {'active': False})]
          and control_plane.find_promo_code(engine, code=CODE)['active'] is False,
          'a manager can, in Stripe and here')

    print('\n4. The webhook writes the money down')
    event = {'type': 'customer.subscription.updated', 'data': {'object': {
        'id': 'sub_x', 'customer': 'cus_x', 'status': 'active', 'metadata': {'slug': A, 'plan': 'scale'},
        'items': {'data': [{'quantity': 1, 'price': {'id': 'price_s', 'unit_amount': 24900,
                                                     'recurring': {'interval': 'month'}}}]},
        'discount': {'promotion_code': 'promo_1',
                     'coupon': {'duration': 'forever', 'percent_off': 50}}}}}
    ok, _ = billing.apply_event(event)
    o = control_plane.find(engine, A)
    check(ok and o['mrr_cents'] == 12450, f"$249 at 50% is $124.50 a month ({o['mrr_cents']})")
    check(o['discount_code'] == CODE, 'the code is recorded as the person would know it')
    first_paid = o['paid_since']
    check(first_paid is not None, 'and when they started paying')
    billing.apply_event(event)
    check(control_plane.find(engine, A)['paid_since'] == first_paid,
          'a replayed event does not move the start date')
    billing.apply_event(dict(event, type='customer.subscription.deleted'))
    o = control_plane.find(engine, A)
    check(o['subscription_status'] == 'canceled' and o['canceled_at'] is not None
          and o['mrr_cents'] == 12450, 'cancelling records when, and keeps what they paid')
    billing.apply_event({'type': 'invoice.paid', 'data': {'object': {
        'customer': 'cus_x', 'metadata': {'slug': A}}}})
    o = control_plane.find(engine, A)
    check(o['canceled_at'] is None and o['paid_since'] == first_paid, 'paying again clears "left"')

    print('\n5. The sales page shows it')
    body = get(helper, '/console/funnel/sales?window=all').data.decode()
    check('$124' in body and f'Sales Alpha {TAG}' in body and CODE in body,
          'the company, what it pays and its code are on the page')
    check('>Sales</a>' in body and '>Discount codes</a>' in body, 'tabs to Funnel, Sales and codes')
    check(get(helper, '/console/funnel/sales?window=bad').status_code == 200,
          'an unknown window falls back')

    with engine.begin() as conn:
        conn.execute(text('DELETE FROM public.organizations WHERE slug = :s'), {'s': A})
        conn.execute(text('DELETE FROM public.promo_codes WHERE code IN (:a, :b)'),
                     {'a': CODE, 'b': other})
        for who in (HELPER, MANAGER):
            conn.execute(text('DELETE FROM public.console_log WHERE actor = :e'), {'e': who})
            conn.execute(text('DELETE FROM public.console_users WHERE email = :e'), {'e': who})

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ The money adds up, and discount codes are made safely.')
