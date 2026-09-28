"""Where a company came from: tracking tags and referral links, end to end.

The week-one plan sends people out on tagged links (newsletter, texts,
Facebook groups) and asks every owner to pass on a referral link. None of that
is worth doing if the Funnel cannot say which link a signup came in on. So
this checks the whole path on a real PostgreSQL: a visitor lands on a tagged
link, wanders to the signup form, signs up -- and the company in the console
says where it came from, and who referred it.

The ways it could go wrong that would matter:

  * a later visit overwriting the first link (the channel that did the work
    loses the credit);
  * a made-up or self-naming ?ref= crediting a referral nobody made;
  * a tampered cookie being believed;
  * tags being picked up on a customer's own CRM address.
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


import attribution
import funnel

SECRET = 'attribution-test-secret'

print('\n1. A request says where the visitor came from')
got = attribution.from_request(
    {'utm_source': 'Newsletter', 'utm_medium': 'Email',
     'utm_campaign': 'Founding<script>', 'utm_term': 'ignored'},
    '', 'akyehq.test', '/pricing')
check(got == {'source': 'newsletter', 'medium': 'email', 'campaign': 'foundingscript',
              'landing': '/pricing'},
      f'tags are lower-cased, cleaned, and only the three kept ({got})')
got = attribution.from_request({'ref': 'Sparkle-Co!'}, '', 'akyehq.test', '/')
check(got.get('ref') == 'sparkle-co', 'a referral is cleaned to address characters')
got = attribution.from_request({}, 'https://www.google.com/search?q=x', 'akyehq.test', '/')
check(got.get('referrer') == 'google.com', 'no tags: the site they came from')
check(attribution.from_request({}, 'https://akyehq.test/pricing', 'akyehq.test', '/') == {},
      'a click from our own page is not a source')
check(attribution.from_request({}, 'https://acme.akyehq.test/', 'www.akyehq.test', '/') == {},
      'nor is a click from a customer subdomain')
check(attribution.from_request({}, '', 'akyehq.test', '/') == {},
      'a plain direct visit writes nothing')

print('\n2. First touch wins; a referral can still be added')
first = {'source': 'newsletter', 'campaign': 'founding'}
check(attribution.merge({}, first) == first, 'nothing stored: the first link is kept')
check(attribution.merge(first, {'source': 'facebook'}) is None,
      'a later link does not overwrite it')
check(attribution.merge(first, {'ref': 'sparkle'}) == dict(first, ref='sparkle'),
      'but a referral is added to it')
check(attribution.merge(dict(first, ref='a'), {'ref': 'b'}) is None,
      'and the first referral is the one kept')

print('\n3. The cookie is signed')
from flask import Flask, make_response
fapp = Flask(__name__)
with fapp.test_request_context():
    resp = attribution.write(make_response('x'), first, SECRET, secure=False)
    raw = resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1]
    check('HttpOnly' in resp.headers['Set-Cookie'], 'HttpOnly')
check(attribution.read({attribution.COOKIE: raw}, SECRET) == first, 'reads back what was written')
check(attribution.read({attribution.COOKIE: raw}, 'another-secret') == {},
      'signed with another key: ignored')
check(attribution.read({attribution.COOKIE: raw[:-3] + 'abc'}, SECRET) == {},
      'edited: ignored')
check(attribution.read({attribution.COOKIE: 'garbage'}, SECRET) == {}, 'garbage: ignored')

print('\n4. One label per company')
check(attribution.label({'signup_source': 'newsletter', 'signup_campaign': 'founding'})
      == 'newsletter · founding', 'source and campaign')
check(attribution.label({'signup_source': 'sms'}) == 'sms', 'source alone')
check(attribution.label({'signup_source': 'sms', 'referred_by': 'sparkle'}) == 'referral',
      'a referral wins over its tags')
check(attribution.label({'signup_referrer': 'google.com'}) == 'google.com', 'the site they came from')
check(attribution.label({}) == 'direct', 'nothing known: direct')
check(funnel.lead_source('campaign:newsletter · founding') == 'newsletter · founding',
      'an early-access lead from a tagged link is grouped by its label')

print('\n5. The funnel counts signups by channel, and referrals by referrer')
NOW = datetime(2026, 9, 26, 12, 0)


def org(slug, **kw):
    row = {'slug': slug, 'name': slug.title(), 'owner_email': f'{slug}@x.test',
           'status': 'active', 'subscription_status': 'trialing',
           'created_at': NOW - timedelta(days=3),
           'trial_ends_at': NOW + timedelta(days=27), 'activated_at': None,
           'stripe_subscription_id': None, 'grandfathered': False, 'plan': 'scale'}
    row.update(kw)
    return row


ORGS = [
    org('sparkle', signup_source='newsletter', signup_campaign='founding',
        activated_at=NOW - timedelta(days=2), stripe_subscription_id='sub_1',
        subscription_status='active'),
    org('shine', signup_source='newsletter', signup_campaign='founding'),
    org('mop', referred_by='sparkle', signup_source='sms', activated_at=NOW),
    org('broom', referred_by='sparkle'),
    org('dust'),
    org('testco', signup_source='newsletter', is_test=True),
]
f = funnel.compute(ORGS, [], now=NOW, days=30)
ch = dict(f['channels'])
check(ch.get('newsletter · founding') == {'signed_up': 2, 'activated': 1, 'paying': 1},
      f'newsletter: 2 signed up, 1 activated, 1 paying ({ch.get("newsletter · founding")})')
check(ch.get('referral') == {'signed_up': 2, 'activated': 1, 'paying': 0},
      'referral: 2 signed up, 1 activated')
check(ch.get('direct', {}).get('signed_up') == 1, 'one direct')
check(sum(c['signed_up'] for c in ch.values()) == 5, 'the test account is not counted')
check(f['channels'][0][0] in ('newsletter · founding', 'referral'), 'busiest first')
refs = f['referrals']
check(len(refs) == 1 and refs[0]['slug'] == 'sparkle'
      and [c['slug'] for c in refs[0]['companies']] == ['mop', 'broom'],
      'sparkle is credited with mop and broom')

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
    from sqlalchemy import create_engine, text
    DB = 'dsm_attribution_test'
    admin = create_engine(PG, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB}'))
    os.environ.update(DATABASE_URL=f'{PG.rsplit("/", 1)[0]}/{DB}', SECRET_KEY=SECRET,
                      BASE_DOMAIN='akyehq.test', SIGNUPS_OPEN='1')
    os.environ.pop('ADMIN_USER', None)
    os.environ.pop('ADMIN_PASS', None)
    os.environ.pop('CANONICAL_HOST', None)

    import notifications
    notifications.send_email = lambda *a, **k: (True, 'stub')
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    from app import create_app
    import control_plane
    import provisioning

    try:
        app = create_app()
        PRODUCT = {'Host': 'akyehq.test'}
        TAG = secrets.token_hex(3)

        def signup(c, slug):
            return c.post('/signup', headers=PRODUCT, data={
                'business': f'{slug.title()} Cleaning', 'slug': slug,
                'name': 'Owner Person', 'email': f'{slug}@example.com',
                'password': 'a-perfectly-fine-password'})

        def cookie_of(response):
            for h in response.headers.getlist('Set-Cookie'):
                if h.startswith(attribution.COOKIE + '='):
                    return h
            return None

        print('\n6. A tagged link is remembered, and the first one kept')
        c = app.test_client()
        r = c.get('/?utm_source=newsletter&utm_medium=email&utm_campaign=founding',
                  headers=PRODUCT)
        check(r.status_code == 200 and cookie_of(r), 'the landing page sets the cookie')
        r = c.get('/pricing?utm_source=facebook', headers=PRODUCT)
        check(cookie_of(r) is None, 'a second tagged visit does not overwrite it')

        print('\n7. Signup writes it onto the company, then forgets it')
        first_slug = f'first{TAG}'
        r = signup(c, first_slug)
        check(r.status_code == 302, f'signup succeeds ({r.status_code})')
        welcome = (r.headers.get('Location') or '').split(f'{first_slug}.akyehq.test')[-1]
        forgot = cookie_of(r) or ''
        check('Expires=Thu, 01 Jan 1970' in forgot or 'Max-Age=0' in forgot,
              'and clears the cookie for the next company from this browser')
        with app.app_context():
            engine = provisioning._engine()
            o = control_plane.find(engine, first_slug)
        check(o and o['signup_source'] == 'newsletter' and o['signup_medium'] == 'email'
              and o['signup_campaign'] == 'founding' and o['signup_landing'] == '/',
              'source, medium, campaign and landing page are recorded')
        check(o and not o.get('referred_by'), 'no referral')

        print('\n8. A referral link credits the company that sent it')
        c2 = app.test_client()
        r = c2.get(f'/r/{first_slug}', headers=PRODUCT)
        check(r.status_code == 302 and (r.headers.get('Location') or '').endswith('/'),
              '/r/<address> sends them to the home page')
        check(cookie_of(r), 'with the referral remembered')
        second_slug = f'second{TAG}'
        check(signup(c2, second_slug).status_code == 302, 'the referred owner signs up')
        with app.app_context():
            o2 = control_plane.find(engine, second_slug)
            sent = control_plane.referred_by(engine, first_slug)
        check(o2 and o2['referred_by'] == first_slug, 'referred_by names the referrer')
        check([s['slug'] for s in sent] == [second_slug], 'and the referrer can list them')

        print('\n9. A referral nobody made is not credited')
        c3 = app.test_client()
        c3.get('/?ref=no-such-company', headers=PRODUCT)
        ghost = f'ghost{TAG}'
        signup(c3, ghost)
        c4 = app.test_client()
        selfie = f'selfie{TAG}'
        c4.get(f'/r/{selfie}', headers=PRODUCT)
        signup(c4, selfie)
        with app.app_context():
            check(not control_plane.find(engine, ghost).get('referred_by'),
                  'a made-up company is dropped')
            check(not control_plane.find(engine, selfie).get('referred_by'),
                  'a company cannot refer itself')

        print('\n10. Only on the product site')
        r = app.test_client().get('/?utm_source=x', headers={'Host': f'{first_slug}.akyehq.test'})
        check(cookie_of(r) is None, "tags on a customer's CRM address are ignored")
        r = app.test_client().get(f'/r/{first_slug}', headers={'Host': f'{first_slug}.akyehq.test'})
        check(r.status_code == 404, '/r/ does not exist there')

        print("\n11. The owner sees their link; the console sees the source")
        with app.test_request_context(headers={'Host': f'{first_slug}.akyehq.test'}):
            from blueprints.billing_routes import _referral
            url, referred = _referral(control_plane.find(engine, first_slug))
        check(url == f'https://akyehq.test/r/{first_slug}', f'the link is on the product site ({url})')
        check([x['slug'] for x in referred] == [second_slug], 'with who used it')
        owner = app.test_client()
        TENANT = {'Host': f'{first_slug}.akyehq.test'}
        owner.get(welcome, headers=TENANT)
        r = owner.get('/billing', headers=TENANT)
        body = r.data.decode()
        check(r.status_code == 200 and f'value="https://akyehq.test/r/{first_slug}"' in body
              and 'Copy link' in body, f'the owner\'s Billing page shows it ({r.status_code})')
        check('1 company has' in body, 'and says one company signed up with it')

        email, password = f'console-{TAG}@example.com', 'a-real-console-password-1'
        with app.app_context():
            control_plane.add_console_user(engine, email, 'Tester', password, role='helper')
        cc = app.test_client()
        cc.post('/console/login', data={'email': email, 'password': password})
        body = cc.get('/console/funnel?window=all').data.decode()
        check('Where signups came from' in body and 'newsletter · founding' in body,
              'the Funnel counts the newsletter signup')
        check('Referrals' in body and f'{second_slug.title()} Cleaning' in body,
              'and lists who the first company referred')
        body = cc.get(f'/console/companies/{second_slug}').data.decode()
        check('Came from: <strong>referral</strong>' in body and f'referred by' in body,
              'the company page says it was referred, and by whom')
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
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Every signup says which link brought it, and every referral who sent it.')
