"""Paying partners through Stripe: the money moves once, and the books agree.

A transfer cannot be undone and a network can drop, so the interesting part is
not the happy path. What this checks:

  * the transfer is made from Akye's own account, for the right amount, with a
    key that makes sending twice send once;
  * two people pressing Pay at the same moment cannot pay the same commission
    twice;
  * a transfer Stripe REFUSES releases the commissions (nothing moved);
  * a transfer whose outcome is UNKNOWN releases nothing (it might have moved),
    and a retry finishes it without sending a second one;
  * a partner who has not finished Stripe setup is not paid, and says why;
  * the partner sets up payouts from their own page and Stripe's word, not a
    visit to a URL, decides whether they are ready;
  * the console shows partners in its main navigation, on the health page and
    in communications.

Stripe itself is faked at the module boundary: no network, no keys.
"""
import os
import secrets
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def postgres_url():
    from sqlalchemy import create_engine, text
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      'postgresql://app_user:localtest@127.0.0.1:5432/postgres',
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres'):
        if not candidate:
            continue
        try:
            e = create_engine(candidate)
            with e.connect() as c:
                c.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n  ⚠️  SKIPPED: no PostgreSQL server found.')
    sys.exit(0)

from sqlalchemy import create_engine, text

DB = 'dsm_partner_payouts_test'
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as conn:
    conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
    conn.execute(text(f'CREATE DATABASE {DB}'))
os.environ.update(DATABASE_URL=f'{PG.rsplit("/", 1)[0]}/{DB}', SECRET_KEY='payout-test',
                  BASE_DOMAIN='akyehq.test', SIGNUPS_OPEN='1',
                  STRIPE_PLATFORM_SECRET_KEY='sk_test_platform_only')
for k in ('ADMIN_USER', 'ADMIN_PASS', 'CANONICAL_HOST'):
    os.environ.pop(k, None)

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append((a, k)) or (True, 'stub'))
notifications.send_sms = lambda *a, **k: (True, 'stub')

import affiliates
import control_plane
import partner_payouts
import provisioning
from app import create_app

# ---- Stripe, faked at the boundary ---------------------------------------
CALLS = {'transfer': [], 'account': [], 'link': [], 'status': []}
BEHAVIOUR = {'transfer': 'ok', 'ready': True}
TRANSFERS = {}


def fake_create_account(email, name='', idempotency_key=None):
    CALLS['account'].append((email, name))
    return True, f'acct_{len(CALLS["account"])}'


def fake_link(account_id, refresh_url, return_url):
    CALLS['link'].append((account_id, refresh_url, return_url))
    return True, f'https://connect.stripe.test/setup/{account_id}'


def fake_status(account_id):
    CALLS['status'].append(account_id)
    return True, {'payouts_enabled': BEHAVIOUR['ready'], 'details_submitted': True}


def fake_transfer(account_id, amount_cents, description, idempotency_key):
    CALLS['transfer'].append((account_id, amount_cents, description, idempotency_key))
    if idempotency_key in TRANSFERS:                 # Stripe's own idempotency
        return True, TRANSFERS[idempotency_key], False
    mode = BEHAVIOUR['transfer']
    if mode == 'refuse':
        return False, 'Insufficient funds in your Stripe balance.', False
    if mode == 'drop':
        BEHAVIOUR['transfer'] = 'ok'                 # it went through; we never heard
        TRANSFERS[idempotency_key] = f'tr_{len(TRANSFERS) + 1}'
        return False, 'Connection reset', True
    TRANSFERS[idempotency_key] = f'tr_{len(TRANSFERS) + 1}'
    return True, TRANSFERS[idempotency_key], False


partner_payouts.create_account = fake_create_account
partner_payouts.onboarding_link = fake_link
partner_payouts.account_status = fake_status
partner_payouts.transfer = fake_transfer
FOUND = {'answer': (True, None), 'asked': []}


def fake_find_transfer(account_id, amount_cents, marker, since):
    FOUND['asked'].append((account_id, amount_cents, marker))
    return FOUND['answer']


partner_payouts.find_transfer = fake_find_transfer

try:
    app = create_app()
    PRODUCT = {'Host': 'akyehq.test'}
    TAG = secrets.token_hex(3)
    with app.app_context():
        engine = provisioning._engine()
        control_plane.ensure_table(engine)

    def entries(pid):
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(text(
                'select * from public.affiliate_commissions where affiliate_id=:i order by id'),
                {'i': pid}).mappings()]

    def seed(pid, slug, cents, paid_days_ago=40):
        """A commission already past its hold, for a company with no flag."""
        when = datetime.utcnow() - timedelta(days=paid_days_ago)
        with engine.begin() as conn:
            conn.execute(text(
                'insert into public.affiliate_commissions (affiliate_id, org_slug, '
                'stripe_invoice_id, invoice_paid_at, amount_cents, rate_bps, '
                'commission_cents, status, payable_at, created_at) values '
                '(:a,:s,:inv,:w,:amt,3000,:c,\'accrued\',:p,:w)'),
                {'a': pid, 's': slug, 'inv': f'in_{secrets.token_hex(4)}', 'w': when,
                 'amt': cents * 10 // 3, 'c': cents, 'p': when + timedelta(days=30)})

    print('\n1. Pay from Akye\'s account, never a cleaning company\'s')
    import inspect
    src = inspect.getsource(partner_payouts)
    check('billing.stripe_key()' in src and 'import integrations' not in src
          and 'from integrations' not in src,
          "the partner module uses the platform key, not a company's own")
    check('stripe.api_key =' not in src,
          'and never assigns the global key the cleaner-pay module sets')

    with app.app_context():
        ready = affiliates.create(engine, 'Ready Rae', f'rae{TAG}@partners.test', code=f'rae{TAG}')
        newbie = affiliates.create(engine, 'New Nell', f'nell{TAG}@partners.test', code=f'nell{TAG}')
        for i in range(3):
            seed(ready['id'], f'co{i}', 2370)             # 3 x $23.70 = $71.10
        seed(newbie['id'], 'conew', 6000)

    print('\n2. A partner who has not finished Stripe setup is not paid')
    with app.app_context():
        ok, msg, pay = affiliates.pay_via_stripe(engine, newbie['id'], 'staff@x')
    check(not ok and 'not set up payouts' in msg and not CALLS['transfer'],
          f'no account at all: {msg!r}')
    with app.app_context():
        affiliates.set_payout_account(engine, newbie['id'], 'acct_unfinished', ready=False)
        ok, msg, pay = affiliates.pay_via_stripe(engine, newbie['id'], 'staff@x')
    check(not ok and 'not finished' in msg and not CALLS['transfer'], f'account unfinished: {msg!r}')
    check(len([e for e in entries(newbie['id']) if e['status'] == 'accrued']) == 1,
          'and nothing was claimed')

    print('\n3. A ready partner is paid once, for the right amount')
    with app.app_context():
        affiliates.set_payout_account(engine, ready['id'], 'acct_ready', ready=True)
        under = affiliates.pay_via_stripe(engine, ready['id'], 'staff@x', minimum_cents=10000)
    check(not under[0] and 'rolls over' in under[1] and not CALLS['transfer'],
          'under the minimum: nothing is sent, and it says it rolls over')
    with app.app_context():
        ok, msg, pay = affiliates.pay_via_stripe(engine, ready['id'], 'staff@x')
    check(ok and pay['status'] == 'paid' and pay['amount_cents'] == 7110, f'sent {msg!r}')
    acct, cents, desc, key = CALLS['transfer'][-1]
    check(acct == 'acct_ready' and cents == 7110, f'to their account, in whole cents ({cents})')
    check(key == f'affiliate-payout-{pay["id"]}', f'with a key tied to the payout ({key})')
    check(pay['stripe_transfer_id'] == pay['reference'] and pay['reference'].startswith('tr_'),
          "Stripe's transfer id is kept as the reference")
    check({e['status'] for e in entries(ready['id'])} == {'paid'}, 'every commission is paid')
    with app.app_context():
        again = affiliates.pay_via_stripe(engine, ready['id'], 'staff@x')
    check(not again[0] and len(CALLS['transfer']) == 1,
          'pressing again sends nothing more')

    print('\n3b. A refund after payout is netted off the next Stripe transfer')
    with app.app_context():
        dee = affiliates.create(engine, 'Debit Dee', f'dee{TAG}@partners.test', code=f'dee{TAG}')
        affiliates.set_payout_account(engine, dee['id'], 'acct_dee', ready=True)
        for i in range(3):
            seed(dee['id'], f'dee{i}', 2370)
        first_pay = affiliates.pay_via_stripe(engine, dee['id'], 'staff@x')
        paid_one = [e for e in entries(dee['id']) if e['status'] == 'paid'][0]
        result = affiliates.reverse(engine, paid_one['stripe_invoice_id'])
        for i in range(4):
            seed(dee['id'], f'deemore{i}', 2370)         # +$94.80 earned since
        before = len(CALLS['transfer'])
        ok, msg, pay = affiliates.pay_via_stripe(engine, dee['id'], 'staff@x')
    check(first_pay[0], 'Dee is paid the first $71.10')
    check(result == 'debited', f'the refund of a paid commission becomes a debit ({result})')
    check(ok and pay['amount_cents'] == 9480 - 2370,
          f'the transfer is the net, $71.10 not $94.80 ({msg!r})')
    check(len(CALLS['transfer']) == before + 1 and CALLS['transfer'][-1][1] == 7110,
          'and that is what Stripe is asked to send')
    check(not [e for e in entries(dee['id']) if e['status'] in ('accrued', 'paying')],
          'the debit is settled with the payout, not left to be netted twice')
    del CALLS['transfer'][before - 1:]      # keep the later sections' transfer counts about their own payouts
    for p_ in (first_pay[2], pay):
        TRANSFERS.pop(f"affiliate-payout-{p_['id']}", None)

    print('\n4. Stripe refuses: nothing moved, so everything is released')
    with app.app_context():
        seed(ready['id'], 'co9', 6000)
    BEHAVIOUR['transfer'] = 'refuse'
    with app.app_context():
        ok, msg, pay = affiliates.pay_via_stripe(engine, ready['id'], 'staff@x')
    check(not ok and 'refused' in msg and 'Insufficient funds' in msg, f'said so plainly: {msg!r}')
    check(pay['status'] == 'failed' and 'Insufficient' in (pay['failure'] or ''), 'the payout is marked failed')
    open_ = [e for e in entries(ready['id']) if e['status'] == 'accrued']
    check(len(open_) == 1 and open_[0]['payout_id'] is None, 'and the commission is payable again')
    BEHAVIOUR['transfer'] = 'ok'

    print('\n5. The answer is unknown: release nothing, retry safely')
    BEHAVIOUR['transfer'] = 'drop'
    with app.app_context():
        ok, msg, pay = affiliates.pay_via_stripe(engine, ready['id'], 'staff@x')
    check(not ok and 'Could not confirm' in msg, f'told it is unconfirmed: {msg!r}')
    check(pay['status'] == 'pending', 'the payout stays pending')
    check([e['status'] for e in entries(ready['id']) if e['payout_id'] == pay['id']] == ['paying'],
          'and the commission stays claimed, so nobody can pay it again')
    with app.app_context():
        blocked = affiliates.pay_via_stripe(engine, ready['id'], 'staff@x')
    check(not blocked[0] and len(CALLS['transfer']) == 3, 'a second Pay in the meantime sends nothing')
    before = len(CALLS['transfer'])
    with app.app_context():
        ok, msg, done = affiliates.retry_payout(engine, pay['id'])
    check(ok and done['status'] == 'paid', f'retry finishes it ({msg!r})')
    check(CALLS['transfer'][-1][3] == CALLS['transfer'][-2][3],
          'with the same key, so Stripe returns the first transfer instead of a second')
    check(len(TRANSFERS) == 2, 'two transfers exist in total: one per payout, never two for one')
    with app.app_context():
        late = affiliates.retry_payout(engine, pay['id'])
    check(not late[0] and len(CALLS['transfer']) == before + 1, 'a finished payout cannot be retried')

    print('\n6. Two people pressing Pay at once')
    import threading
    with app.app_context():
        seed(ready['id'], 'co10', 6000)
    results = []
    gate = threading.Barrier(2)

    def press():
        with app.app_context():
            gate.wait()
            results.append(affiliates.pay_via_stripe(engine, ready['id'], 'staff@x'))

    threads = [threading.Thread(target=press) for _ in range(2)]
    n_before = len(CALLS['transfer'])
    [t.start() for t in threads]
    [t.join() for t in threads]
    check(sum(1 for r in results if r[0]) == 1 and len(CALLS['transfer']) == n_before + 1,
          'exactly one wins and one transfer is made')

    print('\n7. The partner sets up payouts on their own page')
    c = app.test_client()
    with app.app_context():
        tok = affiliates.issue_login(engine, newbie['id'])
        affiliates.set_payout_account(engine, newbie['id'], None, ready=False)
    c.post(f'/partners/login/{tok}', headers=PRODUCT)
    body = c.get('/partners', headers=PRODUCT).data.decode()
    check('Set up payouts' in body, 'the page offers to set up payouts')
    r = c.post('/partners/payouts/setup', headers=PRODUCT)
    check(r.status_code == 302 and r.headers['Location'].startswith('https://connect.stripe.test/setup/'),
          'and sends them to Stripe')
    check(CALLS['account'][-1][0] == newbie['email'], 'having made them an account')
    refresh, back = CALLS['link'][-1][1], CALLS['link'][-1][2]
    check(refresh.endswith('/partners/payouts/setup') and back.endswith('/partners/payouts/return'),
          'with a refresh link and a return link')
    BEHAVIOUR['ready'] = False
    r = c.get('/partners/payouts/return', headers=PRODUCT, follow_redirects=True)
    body = r.data.decode()
    check('still needs a few details' in body and 'Continue setup' in body,
          'coming back unfinished is not mistaken for finished')
    with app.app_context():
        check(not affiliates.find(engine, newbie['id'])['payout_ready'], 'and is not recorded as ready')
    BEHAVIOUR['ready'] = True
    r = c.get('/partners/payouts/return', headers=PRODUCT, follow_redirects=True)
    check('Payouts are set up' in r.data.decode(), 'once Stripe says so, it is ready')
    with app.app_context():
        check(affiliates.find(engine, newbie['id'])['payout_ready'], 'and recorded as ready')
    n = len(CALLS['account'])
    c.post('/partners/payouts/setup', headers=PRODUCT)
    check(len(CALLS['account']) == n, 'setting up again does not make a second Stripe account')
    guest = app.test_client()
    check(guest.post('/partners/payouts/setup', headers=PRODUCT).status_code == 302
          and len(CALLS['account']) == n, 'and a signed-out visitor cannot start one')

    print('\n8. The console')
    mgr, mpass = f'mgr-{TAG}@example.com', 'a-real-console-password-1'
    hlp, hpass = f'hlp-{TAG}@example.com', 'a-real-console-password-2'
    with app.app_context():
        control_plane.add_console_user(engine, mgr, 'Manager', mpass, role='manager')
        control_plane.add_console_user(engine, hlp, 'Helper', hpass, role='helper')
        seed(ready['id'], 'co11', 6000)
    cc = app.test_client()
    cc.post('/console/login', data={'email': mgr, 'password': mpass})
    page = cc.get('/console/companies').data.decode()
    check('>Partners<' in page.replace('<span', '<') or 'Partners' in page,
          'Partners is in the console navigation, not buried under Funnel')
    check('title="Partners to approve, or with a balance ready to pay"' in page,
          'with a count of partners who need somebody')
    detail = cc.get(f'/console/affiliates/{ready["id"]}').data.decode()
    check('Pay $60.00 by Stripe transfer' in detail, 'the partner page offers to pay by transfer')
    check('ready</span> Stripe can pay' in detail, 'and shows their payout account is ready')
    detail_new = cc.get(f'/console/affiliates/{newbie["id"]}').data.decode()
    check('Pay $60.00' in detail_new, 'a ready partner over the minimum can be paid')

    h = app.test_client()
    h.post('/console/login', data={'email': hlp, 'password': hpass})
    n = len(CALLS['transfer'])
    h.post(f'/console/affiliates/{ready["id"]}/stripe')
    check(len(CALLS['transfer']) == n, 'a helper cannot send money')

    SENT.clear()
    r = cc.post(f'/console/affiliates/{ready["id"]}/stripe', follow_redirects=True)
    check(len(CALLS['transfer']) == n + 1 and 'Sent $60.00' in r.data.decode(),
          'a manager can, and is told')
    check(any(ready['email'] == a[0][0] and 'sent you $60.00' in a[0][2] for a in SENT),
          'and the partner is emailed that it was sent')
    with app.app_context():
        record = [r['action'] for r in control_plane.console_log_all(engine)]
    check('partner payout sent' in record, 'and it is in the console Record')

    health = cc.get('/console/health').data.decode()
    check('Partner payouts' in health and 'Stripe is set up for payouts' in health
          and 'charge.refunded' in health, 'Health reports payout readiness and the webhook events')
    comms = cc.get('/console/communications').data.decode()
    check('To affiliate partners' in comms and 'Your partner page sign-in link' in comms,
          'Communications lists the partner emails')
    prev = cc.get('/console/communications/preview/partner_paid')
    check(prev.status_code == 200 and b'$118.50' in prev.data, 'and previews them')
    check(cc.get('/console/communications/preview/partner_login').status_code == 200,
          'including the sign-in link')
    print('\n9. Review findings: the cases that were wrong')
    # (a) A reversal cannot reach a commission already claimed for a transfer.
    with app.app_context():
        seed(ready['id'], 'co20', 6000)
        BEHAVIOUR['transfer'] = 'drop'
        ok, msg, held = affiliates.pay_via_stripe(engine, ready['id'], 'staff@x')
        BEHAVIOUR['transfer'] = 'ok'
        claimed = [e for e in entries(ready['id']) if e['payout_id'] == held['id']][0]
        got = affiliates.reverse(engine, claimed['stripe_invoice_id'])
    check(held['status'] == 'pending' and got == 'being paid',
          'a commission claimed for a transfer cannot be reversed underneath it')
    check([e['status'] for e in entries(ready['id']) if e['id'] == claimed['id']] == ['paying'],
          'and it stays claimed')

    # (b) The pending payout counts as needing staff, even with no balance.
    with app.app_context():
        flagged = affiliates.waiting_count(engine)
        no_balance = affiliates.payable_cents(engine, ready['id'])
    check(no_balance < affiliates.MIN_PAYOUT_CENTS and flagged >= 1,
          'an unconfirmed transfer is counted in the console badge')

    # (c) Retry is bound to the partner in the URL.
    with app.app_context():
        wrong = affiliates.retry_payout(engine, held['id'], affiliate_id=newbie['id'])
    check(not wrong[0] and 'different partner' in wrong[1]
          and affiliates.payout(engine, held['id'])['status'] == 'pending',
          "retrying one partner's payout through another's page does nothing")

    # (d) Two simultaneous retries: one transfer, one email, one record.
    SENT.clear()
    gate2 = threading.Barrier(2)
    outs = []

    def retry():
        with app.app_context():
            gate2.wait()
            outs.append(affiliates.retry_payout(engine, held['id'], affiliate_id=ready['id']))

    ts = [threading.Thread(target=retry) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check(all(o[0] for o in outs) and sum(1 for o in outs if o[2].get('finished_now')) == 1,
          'both retries succeed but only one is the one that finished it')
    check(affiliates.payout(engine, held['id'])['status'] == 'paid'
          and [e['status'] for e in entries(ready['id']) if e['payout_id'] == held['id']] == ['paid'],
          'the payout and its commissions end up paid, once')

    # (e) The real Stripe exception classes are told apart correctly.
    import stripe
    real_create = stripe.Transfer.create
    importlib_reload = None
    for exc, expect_uncertain in (
            (stripe.InvalidRequestError('Insufficient funds', param=None), False),
            (stripe.APIConnectionError('reset'), True),
            (stripe.APIError('Internal server error', http_status=500), True),
            (RuntimeError('a bug of ours'), True)):
        def boom(*a, **k):
            raise exc
        stripe.Transfer.create = boom
        try:
            real_transfer = type(partner_payouts)('real')
            exec(compile(src, 'partner_payouts_real', 'exec'), real_transfer.__dict__)
            ok, value, uncertain = real_transfer.transfer('acct_x', 100, 'd', 'k')
        finally:
            stripe.Transfer.create = real_create
        check(not ok and uncertain is expect_uncertain,
              f'{type(exc).__name__}: ' + ('unknown outcome, keep it pending' if expect_uncertain
                                           else 'a definite refusal, release it'))

    # (f) One Stripe account however many times setup is pressed.
    with app.app_context():
        solo = affiliates.create(engine, 'Solo Sam', f'sam{TAG}@partners.test', code=f'sam{TAG}')
    made = []

    def slow_create(email, name):
        import time
        made.append(email)
        time.sleep(0.4)
        return True, f'acct_once_{len(made)}'

    gate3 = threading.Barrier(2)
    got_ids = []

    def setup():
        with app.app_context():
            gate3.wait()
            got_ids.append(affiliates.ensure_payout_account(engine, solo['id'], slow_create))

    ts = [threading.Thread(target=setup) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check(len(made) == 1 and got_ids[0] == got_ids[1] == (True, 'acct_once_1'),
          'two overlapping setups create one Stripe account and both get it')


    print('\n10. A retry older than Stripe remembers the key asks Stripe first')
    def aged_pending(co, days):
        with app.app_context():
            seed(ready['id'], co, 6000)
        BEHAVIOUR['transfer'] = 'drop'
        with app.app_context():
            ok_, msg_, p_ = affiliates.pay_via_stripe(engine, ready['id'], 'staff@x')
        with engine.begin() as conn:
            conn.execute(text('UPDATE affiliate_payouts SET paid_at = :t WHERE id = :i'),
                         {'t': datetime.utcnow() - timedelta(days=days), 'i': p_['id']})
        return p_

    young = aged_pending('co11', 0)
    FOUND['asked'].clear()
    with app.app_context():
        ok, msg, done = affiliates.retry_payout(engine, young['id'])
    check(ok and not FOUND['asked'], 'a retry within a day leans on the key and does not ask Stripe')

    old = aged_pending('co12', 2)
    FOUND['asked'].clear()
    FOUND['answer'] = (True, 'tr_already_sent')
    before = len(CALLS['transfer'])
    with app.app_context():
        ok, msg, done = affiliates.retry_payout(engine, old['id'])
    check(ok and done['status'] == 'paid' and done['stripe_transfer_id'] == 'tr_already_sent',
          f'an old payout Stripe already sent is marked paid with its transfer ({msg!r})')
    check(len(CALLS['transfer']) == before, 'and nothing is sent a second time')
    check(FOUND['asked'] and f'(payout {old["id"]})' in FOUND['asked'][0][2],
          'Stripe was asked about that payout by its own marker')

    old2 = aged_pending('co13', 2)
    FOUND['answer'] = (False, 'Stripe is down')
    before = len(CALLS['transfer'])
    with app.app_context():
        ok, msg, held = affiliates.retry_payout(engine, old2['id'])
    check(not ok and 'Nothing was sent' in msg and len(CALLS['transfer']) == before,
          'if Stripe cannot be asked, an old payout is not retried')
    check(held['status'] == 'pending', 'it stays pending, commissions still claimed')

    FOUND['answer'] = (True, None)
    BEHAVIOUR['transfer'] = 'ok'
    with app.app_context():
        ok, msg, done = affiliates.retry_payout(engine, old2['id'])
    check(ok and done['status'] == 'paid' and len(CALLS['transfer']) == before + 1,
          'once Stripe says no such transfer exists, the retry sends it')

    print('\n11. The payout switch fails closed')
    import platform_switches
    partner_ok = {'name': 'Rae', 'payout_account_id': 'acct_1', 'payout_ready': True}
    platform_switches.clear_cache()
    check(affiliates.can_pay_by_stripe(partner_ok)[0], 'readable, never turned off: payouts are allowed')
    real_checked = control_plane.switches_checked

    def unreadable(engine_):
        raise RuntimeError('control plane unreachable')

    control_plane.switches_checked = unreadable
    platform_switches.clear_cache()
    allowed, why = affiliates.can_pay_by_stripe(partner_ok)
    check(not allowed and 'switched off' in why, 'switches unreadable: nobody is paid')
    check(platform_switches.is_on('ai') and platform_switches.is_on('sms'),
          'while the other switches still fail open')
    control_plane.switches_checked = real_checked
    platform_switches.clear_cache()
    check(affiliates.can_pay_by_stripe(partner_ok)[0], 'readable again: payouts resume')
    os.environ['PARTNER_PAYOUTS_OPEN'] = '0'
    platform_switches.clear_cache()
    check(not affiliates.can_pay_by_stripe(partner_ok)[0],
          'PARTNER_PAYOUTS_OPEN=0 stops payouts whatever the console says')
    del os.environ['PARTNER_PAYOUTS_OPEN']
    platform_switches.clear_cache()


    print('\n12. Review findings on the retry and the switch')
    import importlib.util
    spec = importlib.util.spec_from_file_location('partner_payouts_real',
                                                  os.path.join(ROOT, 'partner_payouts.py'))
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)

    class Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    sent = {}

    class FakeStripe:
        class Transfer:
            @staticmethod
            def create(**kw):
                sent.update(kw)
                return Obj(id='tr_new')

            @staticmethod
            def list(**kw):
                return Obj(has_more=False, data=[Obj(
                    id='tr_back', amount=6000, description='x (payout 99)',
                    reversed=BEHAVIOUR.get('reversed', False),
                    amount_reversed=BEHAVIOUR.get('amount_reversed', 0))])

    real._stripe = lambda: FakeStripe
    real.transfer('acct_1', 6000, 'd', 'affiliate-payout-5')
    check(set(sent) == {'api_key', 'amount', 'currency', 'destination', 'description',
                        'idempotency_key'},
          'a transfer sends the same parameters it always did, so a payout pending from '
          'before this release can be retried with its old key')
    check(real.find_transfer('acct_1', 6000, '(payout 99)', datetime.utcnow()) == (True, 'tr_back'),
          'a matching, intact transfer is found')
    for label, key, val in (('fully reversed', 'reversed', True),
                            ('partly reversed', 'amount_reversed', 1500)):
        BEHAVIOUR[key] = val
        ok_, why_ = real.find_transfer('acct_1', 6000, '(payout 99)', datetime.utcnow())
        check(not ok_ and 'reversed' in why_, f'a {label} transfer is not accepted as a completed payment')
        BEHAVIOUR.pop(key)

    platform_switches.clear_cache()
    rows = {s_['key']: s_ for s_ in platform_switches.states(engine)}
    check(rows['partner_payouts']['on'] and not rows['partner_payouts']['unreadable'],
          'Health: readable, payouts show on')
    real_engine_connect = engine.connect

    class Broken:
        def connect(self):
            raise RuntimeError('db down')

    rows = {s_['key']: s_ for s_ in platform_switches.states(Broken())}
    check(not rows['partner_payouts']['on'] and rows['partner_payouts']['unreadable'],
          'Health: unreadable, payouts show OFF with a reason, matching what is enforced')
    check(rows['ai']['on'] and not rows['ai']['unreadable'], 'and the fail-open switches still show on')

    # (g) Partner emails are findable in Communications history.
    cc2 = app.test_client()
    cc2.post('/console/login', data={'email': mgr, 'password': mpass})
    with app.app_context():
        import partner_mail
        partner_mail.deliver(ready, 'Your Akye partner page', '<p>x</p>', 'partner_login', engine)
    page = cc2.get(f'/console/communications?q={ready["email"]}').data.decode()
    check('Partners:' in page and 'Ready Rae' in page and 'Your partner page sign-in link' in page,
          "searching a partner's email finds the partner and what was sent to them")
finally:
    try:
        from extensions import db
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        provisioning._engine().dispose()
    except Exception:
        pass
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
    admin.dispose()

if failures:
    print(f'\n❌ {len(failures)} partner payout check(s) failed.')
    sys.exit(1)
print('\n✅ A partner is paid once, from the right account, and the books always agree with Stripe.')
