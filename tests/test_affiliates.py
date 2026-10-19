"""Affiliate partners, end to end: the link, the credit, the money, the page.

A partner recommends the product and earns a share of what the companies they
bring pay. The ways this could go wrong that matter:

  * credit going to the wrong place -- a made-up code, a paused partner, a
    partner opening a company of their own, a later partner replacing the first;
  * money -- a webhook delivered twice paying twice, tax being commissioned, a
    refunded invoice still being paid out, a payout recorded twice;
  * privacy -- a partner seeing another partner's numbers, or a referred
    company's email address;
  * access -- a sign-in link that works twice, that a mail scanner can spend, or
    that works for somebody who has been ended.

Runs against a real PostgreSQL: the control plane lives in the `public` schema.
"""
import os
import re
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


import attribution

SECRET = 'affiliate-test-secret'

print('\n1. A partner code is read from a link, and kept apart from a referral')
got = attribution.from_request({'aff': 'Dana-Coach!'}, '', 'akyehq.test', '/')
check(got.get('aff') == 'dana-coach', f'cleaned to code characters ({got})')
check('ref' not in got, 'and is not mistaken for a company referral')
check(attribution.merge({'source': 'newsletter'}, {'aff': 'dana'}) ==
      {'source': 'newsletter', 'aff': 'dana'},
      'a partner is added to a cookie that holds only tags')
check(attribution.merge({'aff': 'dana'}, {'aff': 'other'}) is None,
      'the first partner is the one kept')
check(attribution.merge({'ref': 'sparkle'}, {'aff': 'dana'}) ==
      {'ref': 'sparkle', 'aff': 'dana'}, 'a partner and a referral can both be held')
check(attribution.label({'aff': 'dana', 'ref': 'sparkle'}) == 'partner · dana',
      'the partner is the channel, ahead of a referral')
check(attribution.label({'affiliate_code': 'dana', 'referred_by': 'x'}) == 'partner · dana',
      'for a company row too')
check(attribution.label({'ref': 'sparkle'}) == 'referral', 'a bare referral is still a referral')

import affiliates

print('\n2. Money arithmetic')
check(affiliates._invoice_base_cents({'amount_paid': 7900}) == 7900,
      'what was paid is the base')
check(affiliates._invoice_base_cents({'amount_paid': 8500, 'tax': 600}) == 7900,
      'less tax when only the tax is given')
check(affiliates._invoice_base_cents({'amount_paid': 8500, 'total_excluding_tax': 7900}) == 7900,
      'or the total before tax when that is given')
check(affiliates._invoice_base_cents({'amount_paid': 0}) == 0,
      'a free invoice earns nothing')
check(affiliates.money(123456) == '$1,234.56' and affiliates.money(5) == '$0.05',
      'cents are shown as dollars')
check(affiliates.suggest_code('Dana Lee Coaching!') == 'dana-lee-coaching', 'a code from a name')
check(not affiliates.valid_code('admin') and not affiliates.valid_code('a'),
      'a reserved word or a one-letter code is refused')

print('\n2b. Is a signup the partner introducing themselves?')
sr = affiliates.self_referral
check(sr('dana@gmail.com', 'Dana@Gmail.com') == 'same', 'the same address in another case')
check(sr('dana@gmail.com', 'd.ana+akye@gmail.com') == 'same', 'a Gmail address with dots and a +tag')
check(sr('dana@coach.com', 'dana+x@coach.com') == 'same', 'a +tag on any provider')
check(sr('dana@coach.com', 'sam@coach.com') == 'review',
      'a colleague on the same business domain is credited but checked')
check(sr('dana@gmail.com', 'sam@gmail.com') is None, 'two strangers on a free provider are not')
check(sr('dana@coach.com', 'sam@sparkle.com') is None, 'nor are different businesses')
check(sr('dana.x@gmail.com', 'danax@gmail.com') == 'same', 'Gmail ignores dots')
check(sr('dana@yahoo.com', 'dana.x@yahoo.com') is None, 'but Yahoo does not')

# --------------------------------------------------------------------------
# End to end, on a disposable PostgreSQL database


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
    print('\n  ⚠️  SKIPPED the end-to-end half: no PostgreSQL server found.')
else:
    from sqlalchemy import create_engine, select, text
    DB = 'dsm_affiliates_test'
    admin = create_engine(PG, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB}'))
    os.environ.update(DATABASE_URL=f'{PG.rsplit("/", 1)[0]}/{DB}', SECRET_KEY=SECRET,
                      BASE_DOMAIN='akyehq.test', SIGNUPS_OPEN='1')
    for k in ('ADMIN_USER', 'ADMIN_PASS', 'CANONICAL_HOST'):
        os.environ.pop(k, None)

    import notifications
    SENT = []
    notifications.send_email = lambda *a, **k: (SENT.append((a, k)) or (True, 'stub'))
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    from app import create_app
    import billing
    import control_plane
    import provisioning

    try:
        app = create_app()
        PRODUCT = {'Host': 'akyehq.test'}
        TAG = secrets.token_hex(3)
        with app.app_context():
            engine = provisioning._engine()
            control_plane.ensure_table(engine)

        def signup(c, slug, email=None):
            return c.post('/signup', headers=PRODUCT, data={
                'business': f'{slug.title()} Cleaning', 'slug': slug,
                'name': 'Owner Person', 'email': email or f'{slug}@example.com',
                'password': 'a-perfectly-fine-password', 'terms_accepted': '1'})

        def cookie_of(response):
            for h in response.headers.getlist('Set-Cookie'):
                if h.startswith(attribution.COOKIE + '='):
                    return h
            return None

        def clicks(pid):
            with engine.connect() as conn:
                return conn.execute(text(
                    'select count(*) from public.affiliate_clicks where affiliate_id=:i'),
                    {'i': pid}).scalar()

        def paid_invoice(inv, slug_customer, cents=7900, tax=0, when=None):
            when = when or datetime.utcnow()
            return {'type': 'invoice.paid', 'data': {'object': {
                'id': inv, 'customer': slug_customer, 'amount_paid': cents + tax,
                'total_excluding_tax': cents, 'tax': tax,
                'status_transitions': {'paid_at': int(when.timestamp())}}}}

        print('\n3. A partner is added, with sensible refusals')
        with app.app_context():
            dana = affiliates.create(engine, 'Dana Lee', f'dana{TAG}@partners.test',
                                     code=f'dana{TAG}')
        check(dana['status'] == 'active' and dana['commission_bps'] == 3000
              and dana['commission_months'] == 12 and dana['hold_days'] == 30,
              '30% for 12 months, held 30 days, by default')
        for label, kwargs in (
                ('a duplicate code', dict(name='X', email='x@example.com', code=f'dana{TAG}')),
                ('a duplicate email', dict(name='X', email=f'DANA{TAG}@partners.test', code='other-one')),
                ('a reserved code', dict(name='X', email='y@example.com', code='admin')),
                ('a bad email', dict(name='X', email='nope', code='fine-code')),
                ('a rate over 100%', dict(name='X', email='z@example.com', code='fine-code', rate_bps=20000))):
            try:
                with app.app_context():
                    affiliates.create(engine, **kwargs)
                check(False, f'{label} is refused')
            except ValueError:
                check(True, f'{label} is refused')

        print('\n4. A partner link is remembered, and a click counts once')
        c = app.test_client()
        r = c.get(f'/p/{dana["code"]}?utm_campaign=October-News', headers=PRODUCT)
        check(r.status_code == 302 and r.headers['Location'].endswith('/'),
              'sends the visitor to the home page')
        first_cookie = cookie_of(r)
        check(first_cookie, 'with the partner remembered')
        check(clicks(dana['id']) == 1, 'one click recorded')
        r = c.get(f'/p/{dana["code"]}', headers=PRODUCT)
        check(clicks(dana['id']) == 1, 'a refresh from the same browser is not another click')
        value = first_cookie.split(';')[0].split('=', 1)[1].strip('"')
        stored = attribution.read({attribution.COOKIE: value}, SECRET)
        check(stored.get('aff') == dana['code'] and stored.get('campaign') == 'october-news',
              f'the cookie holds the partner and the campaign tag ({stored})')
        r = app.test_client().get('/p/no-such-partner', headers=PRODUCT)
        check(r.status_code == 302 and not cookie_of(r), 'an unknown code lands on the home page, remembered as nothing')
        print('  (company-address check runs after sign-up, below)')

        print('\n5. Signup credits the partner, with the same care as a referral')
        first = f'first{TAG}'
        check(signup(c, first).status_code == 302, 'an owner signs up through the link')
        with app.app_context():
            o = control_plane.find(engine, first)
        check(o and o['affiliate_code'] == dana['code'], 'the company carries the partner code')
        check(o and o['signup_campaign'] == 'october-news', 'and the tag it came in on')
        check(attribution.label(o) == f'partner · {dana["code"]}', 'the Funnel labels the channel')

        paused = affiliates.create if False else None
        with app.app_context():
            pat = affiliates.create(engine, 'Pat Paused', f'pat{TAG}@partners.test',
                                    code=f'pat{TAG}', status='pending')
        c2 = app.test_client()
        c2.get(f'/p/{pat["code"]}', headers=PRODUCT)
        slug = f'pending{TAG}'
        signup(c2, slug)
        with app.app_context():
            check(not control_plane.find(engine, slug).get('affiliate_code'),
                  'a partner who is not active earns nothing, and the link is not remembered')

        c3 = app.test_client()
        c3.get(f'/?aff=made-up-{TAG}', headers=PRODUCT)
        slug = f'ghost{TAG}'
        signup(c3, slug)
        with app.app_context():
            check(not control_plane.find(engine, slug).get('affiliate_code'),
                  'a made-up code is dropped')

        c4 = app.test_client()
        c4.get(f'/p/{dana["code"]}', headers=PRODUCT)
        slug = f'self{TAG}'
        d_local, d_dom = dana['email'].split('@')
        signup(c4, slug, email=f'{d_local}+mine@{d_dom}')
        with app.app_context():
            check(not control_plane.find(engine, slug).get('affiliate_code'),
                  'a partner opening their own company, even with a +tag, is not paid for it')

        with app.app_context():
            colleague = affiliates.create(engine, 'Cass Coach', f'cass{TAG}@coachco.com',
                                          code=f'cass{TAG}')
        c4b = app.test_client()
        c4b.get(f'/p/{colleague["code"]}', headers=PRODUCT)
        slug = f'colleague{TAG}'
        signup(c4b, slug, email=f'sam{TAG}@coachco.com')
        with app.app_context():
            o = control_plane.find(engine, slug)
        check(o['affiliate_code'] == colleague['code'] and o['affiliate_flag'],
              'a colleague on the same business domain is credited but flagged for review')
        with app.app_context():
            control_plane.set_billing(engine, slug, stripe_customer_id=f'cusc_{TAG}')
            billing.apply_event(paid_invoice(f'in_{TAG}_c1', f'cusc_{TAG}'))
            later = datetime.utcnow() + timedelta(days=31)
            held = affiliates.payable_cents(engine, colleague['id'], later)
            shown = affiliates.portal(engine, colleague, later)
        check(held == 0 and shown['payable_cents'] == 0 and shown['pending_cents'] == 2370,
              'its commission is earned but not payable while it is in review')
        check(shown['ledger'][0]['state'] == 'in review', 'and the partner is told it is being checked')
        with app.app_context():
            check(affiliates.record_payout(engine, colleague['id'], 'staff@x', now=later) is None,
                  'a payout skips it')
            control_plane.clear_affiliate_flag(engine, slug)
            check(affiliates.payable_cents(engine, colleague['id'], later) == 2370,
                  'and pays once a person clears it')

        with app.app_context():
            erin = affiliates.create(engine, 'Erin Coach', f'erin{TAG}@partners.test',
                                     code=f'erin{TAG}')
        c5 = app.test_client()
        c5.get(f'/p/{dana["code"]}', headers=PRODUCT)
        c5.get(f'/p/{erin["code"]}', headers=PRODUCT)
        slug = f'second{TAG}'
        signup(c5, slug)
        with app.app_context():
            check(control_plane.find(engine, slug)['affiliate_code'] == dana['code'],
                  'a later partner does not replace the first')
        check(clicks(erin['id']) == 1, 'though the later partner still gets their click')

        c6 = app.test_client()
        c6.get(f'/r/{first}', headers=PRODUCT)
        c6.get(f'/p/{dana["code"]}', headers=PRODUCT)
        slug = f'both{TAG}'
        signup(c6, slug)
        with app.app_context():
            o = control_plane.find(engine, slug)
        check(o['affiliate_code'] == dana['code'] and o['referred_by'] == first,
              'a partner and a customer referral are both recorded')

        c7 = app.test_client()
        c7.get('/?aff=nonsense-code', headers=PRODUCT)
        c7.get(f'/p/{dana["code"]}', headers=PRODUCT)
        slug = f'real{TAG}'
        signup(c7, slug)
        with app.app_context():
            check(control_plane.find(engine, slug).get('affiliate_code') == dana['code'],
                  'a made-up ?aff= on a page does not block the real partner link later')

        c8 = app.test_client()
        c8.get('/?utm_source=facebook&utm_campaign=oldad', headers=PRODUCT)
        c8.get(f'/p/{dana["code"]}?utm_campaign=Newsletter', headers=PRODUCT)
        slug = f'tagged{TAG}'
        signup(c8, slug)
        with app.app_context():
            o = control_plane.find(engine, slug)
        check(o['affiliate_code'] == dana['code'] and o['signup_campaign'] == 'newsletter',
              f"the partner's own tag replaces an older ad's, so click and signup agree ({o['signup_campaign']})")

        c5.get(f'/p/{erin["code"]}', headers=PRODUCT)
        c5.get(f'/p/{erin["code"]}', headers=PRODUCT)
        check(clicks(erin['id']) == 1,
              'refreshing a second partner link is not another click, even when the first partner holds the credit')

        c9 = app.test_client()
        c9.get('/?utm_source=facebook&utm_campaign=oldad&utm_content=ad7', headers=PRODUCT)
        c9.get(f'/p/{dana["code"]}', headers=PRODUCT)
        slug = f'untagged{TAG}'
        signup(c9, slug)
        with app.app_context():
            o = control_plane.find(engine, slug)
        check(o['affiliate_code'] == dana['code'] and not o.get('signup_campaign')
              and not o.get('signup_source') and not o.get('signup_content'),
              'a partner link with no tags clears an older ad, so the signup matches the click')

        from blueprints.partners import _trusted_url
        with app.test_request_context('/partners/login', headers={'Host': 'evil.test'}):
            link = _trusted_url('partners.confirm', token='abc')
        check(link.startswith('https://akyehq.test/') and 'evil.test' not in link,
              f'a sign-in link is built from the product host, not the request host ({link})')

        print('\n6. Money follows a paid invoice, and only once')
        with app.app_context():
            control_plane.set_billing(engine, first, stripe_customer_id=f'cus_{TAG}',
                                      stripe_subscription_id=f'sub_{TAG}',
                                      subscription_status='active')
            ev = paid_invoice(f'in_{TAG}_1', f'cus_{TAG}', cents=7900, tax=600)
            ok, msg = billing.apply_event(ev)
            billing.apply_event(ev)
            billing.apply_event(dict(ev, type='invoice.payment_succeeded'))
            with engine.connect() as conn:
                rows = [dict(r) for r in conn.execute(text(
                    'select * from public.affiliate_commissions where affiliate_id=:i order by id'),
                    {'i': dana['id']}).mappings()]
        check(ok and len(rows) == 1, f'the same invoice delivered three ways earns once ({len(rows)})')
        r0 = rows[0]
        check(r0['amount_cents'] == 7900 and r0['commission_cents'] == 2370,
              f'30% of $79.00 before tax is $23.70 ({r0["commission_cents"]})')
        check(r0['status'] == 'accrued' and
              timedelta(days=29, hours=23) < r0['payable_at'] - r0['invoice_paid_at'] < timedelta(days=30, hours=1),
              'held for 30 days')

        with app.app_context():
            billing.apply_event(paid_invoice(f'in_{TAG}_free', f'cus_{TAG}', cents=0))
            with engine.connect() as conn:
                n = conn.execute(text('select count(*) from public.affiliate_commissions where affiliate_id=:i'), {'i': dana['id']}).scalar()
        check(n == 1, 'a free invoice earns nothing')

        with app.app_context():
            control_plane.set_billing(engine, f'second{TAG}', stripe_customer_id=f'cus2_{TAG}')
            plain = control_plane.find(engine, f'ghost{TAG}')
            control_plane.set_billing(engine, plain['slug'], stripe_customer_id=f'cus3_{TAG}')
            billing.apply_event(paid_invoice(f'in_{TAG}_nopartner', f'cus3_{TAG}'))
            with engine.connect() as conn:
                n = conn.execute(text('select count(*) from public.affiliate_commissions where affiliate_id=:i'), {'i': dana['id']}).scalar()
        check(n == 1, 'a company with no partner earns nobody anything')

        with app.app_context():
            base = datetime.utcnow()
            affiliates.accrue(engine, first, {'id': f'in_{TAG}_m6', 'amount_paid': 7900},
                              now=base + timedelta(days=180))
            late = affiliates.accrue(engine, first, {'id': f'in_{TAG}_m13', 'amount_paid': 7900},
                                     now=base + timedelta(days=13 * 31))
        check(late is None, 'a payment after the 12 months earns nothing')
        with app.app_context():
            with engine.connect() as conn:
                n = conn.execute(text('select count(*) from public.affiliate_commissions where affiliate_id=:i'), {'i': dana['id']}).scalar()
        check(n == 2, 'but one inside them does')
        with app.app_context():
            with engine.connect() as conn:
                first_paid = conn.execute(text(
                    'select min(invoice_paid_at) from public.affiliate_commissions '
                    'where affiliate_id=:i and status != :s'), {'i': dana['id'], 's': 'reversed'}).scalar()
            anniversary = affiliates.add_months(first_paid, 12)
            check(affiliates.accrue(engine, first, {'id': f'in_{TAG}_m13b', 'amount_paid': 7900},
                                    now=anniversary) is None,
                  'the payment exactly a year after the first is the thirteenth, and earns nothing')
            check(affiliates.add_months(datetime(2026, 1, 31), 1) == datetime(2026, 2, 28),
                  'months are calendar months, clamped to the end of a short one')
            control_plane.set_test_account(engine, f'both{TAG}', True)
            check(affiliates.accrue(engine, f'both{TAG}', {'id': f'in_{TAG}_test', 'amount_paid': 7900}) is None,
                  'a test company never earns a partner anything')
            control_plane.set_test_account(engine, f'both{TAG}', False)
            try:
                bad = dict(engine=None)
                affiliates.accrue(None, first, {'id': f'in_{TAG}_boom', 'amount_paid': 7900})
                check(False, 'a ledger error is raised so Stripe retries')
            except Exception:
                check(True, 'a ledger error is raised so Stripe retries, not swallowed')

        print('\n7. A refund cancels a commission that has not been paid')
        with app.app_context():
            ok, msg = billing.apply_event({'type': 'charge.refunded', 'data': {'object': {
                'id': 'ch_1', 'customer': f'cus_{TAG}', 'invoice': f'in_{TAG}_m6',
                'refunded': True}}})
            before = affiliates.reverse(engine, f'in_{TAG}_m6')
            partial = billing.apply_event({'type': 'charge.refunded', 'data': {'object': {
                'id': 'ch_2', 'customer': f'cus_{TAG}', 'invoice': f'in_{TAG}_1',
                'refunded': False}}})
        check(ok and 'reversed' in msg, f'a fully refunded invoice is reversed ({msg})')
        check(before == 'already reversed', 'and reversing twice does nothing more')
        check(partial[0] is False, 'a partial refund is left for a person')
        with app.app_context():
            wrong = affiliates.reverse(engine, f'in_{TAG}_1', affiliate_id=erin['id'])
        check(wrong == 'none', 'a reversal scoped to another partner finds nothing')

        with app.app_context():
            early = paid_invoice(f'in_{TAG}_order', f'cus_unseen_{TAG}')
            early['data']['object']['subscription_details'] = {'metadata': {'slug': first}}
            ok, msg = billing.apply_event(early)
            with engine.connect() as conn:
                got = conn.execute(text('select count(*) from affiliate_commissions '
                                        'where stripe_invoice_id=:i'),
                                   {'i': f'in_{TAG}_order'}).scalar()
            affiliates.reverse(engine, f'in_{TAG}_order', 'test cleanup')
        check(ok and got == 1,
              'an invoice that arrives before the checkout is matched by its subscription metadata')



        with app.app_context():
            billing.apply_event({'type': 'charge.refunded', 'data': {'object': {
                'id': 'ch_early', 'customer': f'cus_{TAG}', 'invoice': f'in_{TAG}_early',
                'refunded': True}}})
            billing.apply_event(paid_invoice(f'in_{TAG}_early', f'cus_{TAG}'))
            with engine.connect() as conn:
                got = conn.execute(text(
                    'select status, commission_cents from public.affiliate_commissions '
                    'where stripe_invoice_id=:i'), {'i': f'in_{TAG}_early'}).all()
        check(got == [('reversed', 0)],
              'a refund that arrives before its payment still means no commission')

        print('\n8. Payouts: only what is ready, only once')
        with app.app_context():
            check(affiliates.payable_cents(engine, dana['id']) == 0, 'nothing is ready inside the hold')
            check(affiliates.record_payout(engine, dana['id'], 'staff@x') is None,
                  'so a payout has nothing to pay')
            later = datetime.utcnow() + timedelta(days=31)
            check(affiliates.payable_cents(engine, dana['id'], later) == 2370,
                  'after the hold it is $23.70 (the reversed one is not counted)')
            under = affiliates.record_payout(engine, dana['id'], 'staff@x', now=later)
            check(under is None, 'a balance under the $50 minimum rolls over, not paid in pieces')
            p1 = affiliates.record_payout(engine, dana['id'], 'staff@x', reference='tr_1',
                                          now=later, minimum_cents=0)
            p2 = affiliates.record_payout(engine, dana['id'], 'staff@x', reference='tr_1',
                                          now=later, minimum_cents=0)
        check(p1 and p1['amount_cents'] == 2370, 'the payout is recorded')
        check(p2 is None, 'and pressing the button again pays nothing twice')

        print('\n9. Signing in to the partner page')
        SENT.clear()
        guest = app.test_client()
        r = guest.get('/partners', headers=PRODUCT)
        check(r.status_code == 302 and '/partners/login' in r.headers['Location'],
              'signed out, the page asks you to sign in')
        r = guest.post('/partners/login', headers=PRODUCT, data={'email': 'nobody@example.com'})
        body = r.data.decode()
        check(r.status_code == 200 and 'on its way' in body and not SENT,
              'a stranger gets the same answer and no email')
        r = guest.post('/partners/login', headers=PRODUCT, data={'email': dana['email'].upper()})
        check('on its way' in r.data.decode() and len(SENT) == 1, 'a partner is emailed a link')
        mail = SENT[0][0][3]
        m = re.search(r'/partners/login/([A-Za-z0-9_\-]+)', mail)
        token = m.group(1) if m else ''
        check(bool(token), 'the email carries a link')
        with engine.connect() as conn:
            hashed = conn.execute(text('select token_hash from public.affiliate_logins')).scalars().all()
        check(token not in hashed and all(len(h) == 64 for h in hashed),
              'only a hash of it is stored')

        r = guest.get(f'/partners/login/{token}', headers=PRODUCT)
        check(r.status_code == 200 and 'Yes, sign me in' in r.data.decode(),
              'opening the link shows a button')
        check(guest.get('/partners', headers=PRODUCT).status_code == 302,
              'and opening it did not sign anyone in (a mail scanner would have)')
        r = guest.post(f'/partners/login/{token}', headers=PRODUCT)
        check(r.status_code == 302 and r.headers['Location'].rstrip('/').endswith('/partners'),
              f'pressing the button does ({r.status_code} {r.headers.get("Location")})')
        r = app.test_client().post(f'/partners/login/{token}', headers=PRODUCT)
        check(r.status_code == 410, 'a link works once')
        r = app.test_client().get('/partners/login/not-a-real-token', headers=PRODUCT)
        check(r.status_code == 410, 'and an unknown one is refused the same way')
        for _ in range(4):
            app.test_client().post('/partners/login', headers=PRODUCT, data={'email': dana['email']})
        check(len(SENT) <= 3, f'asking again and again stops after a few ({len(SENT)} emails)')

        print('\n10. What the partner sees')
        r = guest.get('/partners', headers=PRODUCT)
        body = r.data.decode()
        check(r.status_code == 200, 'the page opens')
        if os.environ.get('DUMP_PARTNER_PAGE'):
            open(os.environ['DUMP_PARTNER_PAGE'], 'w').write(body)
        check(f'/p/{dana["code"]}' in body, 'with their own link')
        check(f'{first.title()} Cleaning' in body, 'the company they brought, by name')
        check('$23.70' in body, 'the commission, in dollars')
        check('paid</span>' in body and 'tr_1' in body, 'the payment made to them, with its reference')
        check(f'{first}@example.com' not in body and 'Owner Person' not in body,
              "and never the owner's email or name")
        check(f'{erin["code"]}' not in body and 'Erin Coach' not in body,
              "nor another partner's anything")
        check('Second' not in body or 'Cleaning' in body, 'sanity')

        print('\n11. Partners cannot see each other, or sign in when ended')
        with app.app_context():
            tok = affiliates.issue_login(engine, erin['id'])
        e = app.test_client()
        e.post(f'/partners/login/{tok}', headers=PRODUCT)
        body = e.get('/partners', headers=PRODUCT).data.decode()
        check(f'/p/{erin["code"]}' in body and f'{first.title()} Cleaning' not in body
              and '$23.70' not in body, "Erin sees Erin's page, empty, not Dana's")
        with app.app_context():
            affiliates.set_status(engine, erin['id'], 'ended')
        check(e.get('/partners', headers=PRODUCT).status_code == 302,
              'ending a partner ends their open session')
        with app.app_context():
            tok = affiliates.issue_login(engine, erin['id'])
            check(affiliates.consume_login(engine, tok) is None, 'and a link no longer works for them')
        check(app.test_client().get('/partners', headers={'Host': f'{first}.akyehq.test'}).status_code == 404,
              "/partners does not exist on a company's address")
        check(app.test_client().get(f'/p/{dana["code"]}', headers={'Host': f'{first}.akyehq.test'}).status_code == 404,
              "nor does /p/")
        guest.post('/partners/logout', headers=PRODUCT)
        check(guest.get('/partners', headers=PRODUCT).status_code == 302, 'signing out works')

        print('\n12. The console')
        email, password = f'console-{TAG}@example.com', 'a-real-console-password-1'
        helper, hpass = f'helper-{TAG}@example.com', 'a-real-console-password-2'
        with app.app_context():
            control_plane.add_console_user(engine, email, 'Manager', password, role='manager')
            control_plane.add_console_user(engine, helper, 'Helper', hpass, role='helper')
        cc = app.test_client()
        cc.post('/console/login', data={'email': email, 'password': password})
        body = cc.get('/console/affiliates').data.decode()
        check('Dana Lee' in body and dana['code'] in body, 'the list shows the partner')
        r = cc.post('/console/affiliates', data={
            'name': 'Frank Bookkeeper', 'email': f'frank{TAG}@partners.test',
            'code': f'frank{TAG}', 'rate': '25', 'months': '6', 'hold': '14', 'active': '1'})
        with app.app_context():
            frank = affiliates.find_by_code(engine, f'frank{TAG}')
        check(r.status_code == 302 and frank and frank['commission_bps'] == 2500
              and frank['commission_months'] == 6 and frank['hold_days'] == 14,
              'a manager can add one with their own terms')
        r = cc.post('/console/affiliates', data={'name': 'Bad', 'email': 'nope'})
        check(r.status_code == 302, 'a bad form is bounced, not crashed')
        detail = cc.get(f'/console/affiliates/{dana["id"]}').data.decode()
        check('Companies' in detail and f'{first.title()} Cleaning' in detail
              and f'in_{TAG}_1' in detail, 'the detail page shows companies and invoices')
        SENT.clear()
        cc.post(f'/console/affiliates/{frank["id"]}/link')
        check(len(SENT) == 1, 'staff can email a sign-in link')
        cc.post(f'/console/affiliates/{dana["id"]}/status', data={'status': 'paused'})
        with app.app_context():
            check(affiliates.find(engine, dana['id'])['status'] == 'paused', 'status can be changed')
            check(affiliates.active_partner(engine, dana['code']) is None,
                  'a paused partner is no longer credited')
            gus = affiliates.create(engine, 'Gus Paused', f'gus{TAG}@partners.test', code=f'gus{TAG}')
            affiliates.set_status(engine, gus['id'], 'paused')
            check(affiliates.consume_login(engine, affiliates.issue_login(engine, gus['id'])) is not None,
                  'but a paused partner can still sign in to see what they earned')
        hc = app.test_client()
        hc.post('/console/login', data={'email': helper, 'password': hpass})
        r = hc.post(f'/console/affiliates/{dana["id"]}/status', data={'status': 'ended'})
        with app.app_context():
            check(affiliates.find(engine, dana['id'])['status'] == 'paused',
                  'a helper can read but not change')
        check(hc.get('/console/affiliates').status_code == 200, 'and can read')
        body = cc.get('/console/funnel?window=all').data.decode()
        check(f'partner · {dana["code"]}' in body, 'the Funnel counts the partner as a channel')

        print('\n13. A refund after the partner was paid takes the money back from their next payout')
        long_ago = datetime.utcnow() - timedelta(days=60)
        with app.app_context():
            ok, msg = billing.apply_event({'type': 'charge.refunded', 'data': {'object': {
                'id': 'ch_late', 'customer': f'cus_{TAG}', 'invoice': f'in_{TAG}_1',
                'refunded': True}}})
            again = affiliates.reverse(engine, f'in_{TAG}_1')
            owed = affiliates.payable_cents(engine, dana['id'], datetime.utcnow() + timedelta(days=31))
            nothing = affiliates.record_payout(engine, dana['id'], 'staff@x', minimum_cents=0,
                                               now=datetime.utcnow() + timedelta(days=31))
        check(ok and 'debited' in msg, f'a refund of a paid commission is recorded, not lost ({msg})')
        check(again == 'already debited', 'and the same refund twice debits once')
        check(owed == -2370, f'the partner now owes $23.70 against their next payout ({owed})')
        check(nothing is None, 'and is paid nothing until they have earned it back')
        with app.app_context():
            affiliates.accrue(engine, first, {'id': f'in_{TAG}_after1', 'amount_paid': 7900}, now=long_ago)
            affiliates.accrue(engine, first, {'id': f'in_{TAG}_after2', 'amount_paid': 7900}, now=long_ago)
            net = affiliates.payable_cents(engine, dana['id'])
            payout = affiliates.record_payout(engine, dana['id'], 'staff@x', minimum_cents=0)
            shown = affiliates.portal(engine, dana)
        check(net == 2370, f'two new payments earn $47.40, less the $23.70 debit ({net})')
        check(payout and payout['amount_cents'] == 2370, 'and the payout is the net')
        check(any(c['state'] == 'refund debit' for c in shown['ledger']),
              'the ledger shows the debit as a refund debit')
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
    print(f'\n❌ {len(failures)} affiliate check(s) failed.')
    sys.exit(1)
print('\n✅ Partners are credited for real introductions, paid once for real payments, and see only their own.')
