"""The BrightNest demo company: coherent, rebuilt in place, and unable to reach anybody.

demo_company.py builds a fictional cleaning business that prospects are shown
and may be handed a login to. What would make that dangerous or embarrassing:

  * a rebuild touching anything but the demo's own schema -- another company's
    data, another company's registry row, or a real company that happens to
    hold the demo's address;
  * a failed rebuild leaving no demo, or half of one;
  * two rebuilds at once pulling each other's work apart;
  * the demo sending an email or a text, or reaching Stripe -- even though the
    deployment has keys in its environment that a company with none of its
    own falls back to;
  * the demo's numbers counting as a real customer in the funnel and sales;
  * its daily automations running and moving it off the state it shows;
  * a visitor changing its password, turning on two-factor, or saving keys,
    and so locking out or exposing the next visitor;
  * a demo login reaching another company or Akye's own console;
  * the story on screen not adding up (demo_company.verify() is the list).

Requires PostgreSQL: the demo is one schema per company, like everything else.
The database is created here and dropped afterwards.
"""
import hashlib
import os

import pytest
from sqlalchemy import create_engine, text

DB_NAME = 'dsm_demo_company_test'
REAL = 'realco'
HOST = 'akye.test'
DEMO_PW = 'demo-owner-test-pass-1'
FAKE_KEYS = {
    # What a deployment has in its environment. A company with no keys of its
    # own falls back to these, so without the guard the demo would use them.
    'STRIPE_SECRET_KEY': 'sk_test_demo_guard_should_never_use_this',
    'STRIPE_PUBLISHABLE_KEY': 'pk_test_demo_guard_should_never_use_this',
    'TWILIO_ACCOUNT_SID': 'AC_demo_guard_should_never_use_this',
    'TWILIO_AUTH_TOKEN': 'demo_guard_should_never_use_this',
    'TWILIO_PHONE': '+15125550000',
    'RESEND_API_KEY': 're_demo_guard_should_never_use_this',
    'MAILERLITE_API_KEY': 'ml_demo_guard_should_never_use_this',
    # And Akye's own Stripe, where companies subscribe.
    'STRIPE_PLATFORM_SECRET_KEY': 'sk_test_platform_demo_guard_should_never_use_this',
    'STRIPE_PRICE_PRO': 'price_pro_test',
    'STRIPE_PRICE_SCALE': 'price_scale_test',
}


def _postgres_admin_url():
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres',
                      'postgresql://app_user:localtest@127.0.0.1:5432/postgres'):
        if not candidate:
            continue
        try:
            engine = create_engine(candidate)
            with engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            engine.dispose()
            return candidate
        except Exception:
            continue
    return None


class Network:
    """Every way out of the process, replaced by a list of what was attempted."""

    def __init__(self):
        self.calls = []

    def post(self, url, *a, **k):
        self.calls.append(url)
        raise AssertionError(f'network call attempted: {url}')

    get = post


@pytest.fixture(scope='module')
def env():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('the demo company needs PostgreSQL')
    original = dict(os.environ)
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))
    os.environ.update({
        'DATABASE_URL': f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}',
        'SECRET_KEY': 'demo-company-test-secret-12345',
        'BASE_DOMAIN': HOST,
        'SIGNUPS_OPEN': '0',
        'DEMO_OWNER_PASSWORD': DEMO_PW,
        'DEMO_OPS_PASSWORD': 'demo-ops-test-pass-1',
        'PRODUCT_SUPPORT_EMAIL': 'support@akye.test',
        **FAKE_KEYS,
    })
    os.environ.pop('DEMO_SLUG', None)

    import requests
    import notifications
    net = Network()
    saved = (requests.post, requests.get, notifications.http_requests.post)
    requests.post = requests.get = net.post
    notifications.http_requests.post = net.post
    import stripe

    def no_stripe(*a, **k):
        net.calls.append('stripe')
        raise AssertionError('Stripe was called')
    stripe_saved = (stripe.checkout.Session.create, stripe.Account.retrieve)
    stripe.checkout.Session.create = no_stripe
    stripe.Account.retrieve = no_stripe

    # A real company next door, with data of its own.
    import provisioning
    import tenancy
    from app import create_app
    from extensions import db
    from models import Booking, Client, User
    provisioning.provision(REAL, 'Real Cleaning Co', quiet=True)
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context(), tenancy.use_tenant(REAL):
        u = User(id=9901, name='Real Owner', username='owner@realco.test', role='owner', active=True)
        u.set_password('real-owner-password-1')
        db.session.add_all([u, Client(id=9902, name='REAL-CLIENT', email='c@realco.test'),
                            Booking(id=9903, name='REAL-BOOKING', service_type='standard',
                                    price=321.0, status='confirmed')])
        db.session.commit()
        db.session.remove()

    import demo_company
    first = demo_company.build(say=lambda *a: None)
    try:
        yield {'app': app, 'net': net, 'first': first, 'demo': demo_company}
    finally:
        requests.post, requests.get, notifications.http_requests.post = saved
        stripe.checkout.Session.create, stripe.Account.retrieve = stripe_saved
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            provisioning._engine().dispose()
        except Exception:
            pass
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        admin.dispose()
        os.environ.clear()
        os.environ.update(original)


def _engine():
    import provisioning
    return provisioning._engine()


def _fingerprint(schema):
    """Everything a viewer sees, reduced to one hash: jobs, people, money, words."""
    h = hashlib.sha256()
    with _engine().connect() as c:
        for q in (f'SELECT name, email, phone FROM "{schema}".client ORDER BY id',
                  f'SELECT name, preferred_date, preferred_time, service_type, price, status, '
                  f'amount_collected, assigned_cleaner FROM "{schema}".booking ORDER BY id',
                  f'SELECT name FROM "{schema}".staff ORDER BY id',
                  f'SELECT rating, comment, rated_at FROM "{schema}".booking_rating ORDER BY id'):
            for row in c.execute(text(q)):
                h.update(repr(tuple(row)).encode())
    return h.hexdigest()


def _real_state():
    import control_plane
    org = dict(control_plane.find(_engine(), REAL))
    with _engine().connect() as c:
        rows = c.execute(text(f'SELECT id, name, price, status FROM tenant_{REAL}.booking '
                              f'ORDER BY id')).all()
        clients = c.execute(text(f'SELECT id, name FROM tenant_{REAL}.client ORDER BY id')).all()
    return org, [tuple(r) for r in rows], [tuple(r) for r in clients]


def _schemas():
    with _engine().connect() as c:
        return set(c.execute(text('SELECT schema_name FROM information_schema.schemata')).scalars())


def _demo_client(app):
    c = app.test_client()
    base = f'https://brightnest.{HOST}'
    r = c.post('/login', base_url=base,
               data={'username': 'sarah@brightnest.example', 'password': DEMO_PW})
    assert r.status_code in (302, 303), r.status_code
    return c, base


# ── The seed ──────────────────────────────────────────────────────────────────

def test_every_coherence_check_passes(env):
    import tenancy
    from extensions import db
    demo = env['demo']
    with env['app'].app_context(), tenancy.use_tenant('brightnest'):
        db.session.remove()
        results = demo.verify()
        db.session.remove()
    failed = [(n, d) for n, ok, d in results if not ok]
    assert not failed
    assert len(results) >= 25


def test_it_is_a_sizeable_believable_business(env):
    c = env['first']
    assert c['team'] == 6 and c['customers'] >= 50 and c['users'] == 2
    assert c['completed'] >= 100 and c['today'] >= 4 and c['upcoming'] >= 10
    assert c['reviews'] >= 15 and c['invoices'] >= 100 and c['leads'] >= 10


def test_no_real_contact_details(env):
    """Only reserved example domains and 555-01xx numbers, which reach nobody."""
    import re
    with _engine().connect() as c:
        emails = [e for (e,) in c.execute(text(
            'SELECT email FROM tenant_brightnest.client UNION ALL '
            'SELECT email FROM tenant_brightnest.staff UNION ALL '
            'SELECT email FROM tenant_brightnest.lead UNION ALL '
            'SELECT username FROM tenant_brightnest."user"')) if e]
        phones = [p for (p,) in c.execute(text(
            'SELECT phone FROM tenant_brightnest.client UNION ALL '
            'SELECT phone FROM tenant_brightnest.staff UNION ALL '
            'SELECT phone FROM tenant_brightnest.lead')) if p]
    assert emails and phones
    assert all(e.endswith(('@example.com', '@brightnest.example', '.example')) for e in emails), \
        [e for e in emails if not e.endswith(('.example', '@example.com'))]
    assert all(re.sub(r'\D', '', p)[-7:-2] == '55501' for p in phones), phones[:5]


def test_it_is_marked_demo_and_test(env):
    import control_plane
    org = control_plane.find(_engine(), 'brightnest')
    assert org['is_demo'] and org['is_test']


# ── Rebuilding ────────────────────────────────────────────────────────────────

def test_a_rebuild_is_identical_and_touches_nothing_else(env):
    before_real = _real_state()
    before_demo = _fingerprint('tenant_brightnest')
    again = env['demo'].build(say=lambda *a: None)
    assert again == env['first']
    assert _fingerprint('tenant_brightnest') == before_demo
    assert _real_state() == before_real
    assert 'tenant_brightnest__next' not in _schemas()


def test_a_failed_rebuild_leaves_the_live_demo_as_it_was(env, monkeypatch):
    demo = env['demo']
    before = _fingerprint('tenant_brightnest')

    def broken(self):
        raise demo.SeedError('money', RuntimeError('boom'))
    monkeypatch.setattr(demo.Builder, 'run', broken)
    with pytest.raises(demo.SeedError):
        demo.build(say=lambda *a: None)
    assert _fingerprint('tenant_brightnest') == before
    assert 'tenant_brightnest__next' not in _schemas()


def test_a_rebuild_that_fails_verification_is_not_swapped_in(env, monkeypatch):
    demo = env['demo']
    before = _fingerprint('tenant_brightnest')
    monkeypatch.setattr(demo, 'verify', lambda: [('a planted failure', False, 'test')])
    with pytest.raises(demo.SeedError):
        demo.build(say=lambda *a: None)
    assert _fingerprint('tenant_brightnest') == before
    assert 'tenant_brightnest__next' not in _schemas()


def test_it_refuses_an_address_a_real_company_holds(env, monkeypatch):
    demo = env['demo']
    before = _real_state()
    monkeypatch.setattr(demo, 'DEMO_SLUG', REAL)
    with pytest.raises(RuntimeError, match='not the demo'):
        demo.build(say=lambda *a: None)
    assert _real_state() == before
    assert f'tenant_{REAL}__next' not in _schemas()


def test_two_rebuilds_cannot_run_at_once(env):
    demo = env['demo']
    before = _fingerprint('tenant_brightnest')
    with _engine().connect() as holder:
        holder.execute(text('SELECT pg_advisory_lock(hashtext(:k))'),
                       {'k': 'akye:demo-company:brightnest'})
        try:
            with pytest.raises(RuntimeError, match='Another rebuild'):
                demo.build(say=lambda *a: None)
        finally:
            holder.execute(text('SELECT pg_advisory_unlock(hashtext(:k))'),
                           {'k': 'akye:demo-company:brightnest'})
    assert _fingerprint('tenant_brightnest') == before


# ── Nothing leaves ────────────────────────────────────────────────────────────

def test_keys_are_blank_for_the_demo_and_only_the_demo(env):
    import demo_guard
    import integrations
    import tenancy
    with env['app'].app_context():
        demo_guard.forget_cache()
        with tenancy.use_tenant(REAL):
            # The control: the next-door company does reach the environment's
            # keys, so it is the guard -- not a missing key -- that stops the demo.
            assert integrations.stripe_secret_key() == FAKE_KEYS['STRIPE_SECRET_KEY']
        with tenancy.use_tenant('brightnest'):
            for name in ('stripe_secret_key', 'stripe_publishable_key', 'stripe_webhook_secret',
                         'twilio_account_sid', 'twilio_auth_token', 'twilio_phone',
                         'resend_api_key'):
                assert integrations.get(name) == '', name
        with demo_guard.forced():
            assert integrations.stripe_secret_key() == ''


def test_sends_are_refused_and_written_to_the_sent_log(env):
    import demo_guard
    import notifications
    import tenancy
    from extensions import db
    from models import OutboundLog
    net = env['net']
    before = len(net.calls)
    with env['app'].app_context(), tenancy.use_tenant('brightnest'):
        db.session.remove()
        demo_guard.forget_cache()
        n0 = OutboundLog.query.count()
        assert notifications.send_email('a@example.com', 'A', 'Hi', '<p>x</p>') == \
            (False, demo_guard.BLOCKED_DETAIL)
        # Even with a key handed straight in, as product mail does.
        assert notifications.send_email('a@example.com', 'A', 'Hi', '<p>x</p>',
                                         api_key='re_explicit')[0] is False
        assert notifications.send_sms('5125550101', 'hello') == (False, demo_guard.BLOCKED_DETAIL)
        assert notifications.send_marketing_sms('5125550101', 'hello')[0] is False
        assert notifications.add_to_mailerlite('a@example.com', 'A') is None
        rows = OutboundLog.query.order_by(OutboundLog.id).all()[n0:]
        # The one exception: Akye's own crash alert about the demo, to Akye.
        notifications.send_email('support@akye.test', 'Akye', 'Crash', '<p>x</p>', api_key='re_ours')
        db.session.remove()
    assert len(rows) == 4 and all(r.status == 'failed' and r.detail == demo_guard.BLOCKED_DETAIL
                                  for r in rows)
    assert net.calls[before:] == ['https://api.resend.com/emails']


def test_the_demo_never_subscribes(env):
    import billing
    import control_plane
    import demo_guard
    org = control_plane.find(_engine(), 'brightnest')
    with pytest.raises(demo_guard.DemoBlocked):
        billing.checkout_session(org, 'pro', 'https://x/ok', 'https://x/no')
    with pytest.raises(demo_guard.DemoBlocked):
        billing.portal_session(org, 'https://x/back')


def test_pressing_the_buttons_sends_nothing(env):
    """The same, through the pages a visitor would actually use."""
    import demo_guard
    from models import Booking, OutboundLog
    import tenancy
    from extensions import db
    net = env['net']
    before = len(net.calls)
    c, base = _demo_client(env['app'])
    with env['app'].app_context(), tenancy.use_tenant('brightnest'):
        booking = Booking.query.filter_by(status='confirmed').first().id
        n0 = OutboundLog.query.count()
        db.session.remove()
    r = c.post(f'/bookings/{booking}/send-confirmation', base_url=base, data={'pay_kind': 'deposit'},
               follow_redirects=True)
    # The page says so, even where it would otherwise report "Sent".
    assert r.status_code == 200 and 'nothing was actually sent' in r.get_data(as_text=True)
    r = c.post('/messages/thread/5125550101/send', base_url=base, data={'body': 'On our way!'})
    assert r.status_code in (302, 303)
    r = c.post('/billing/checkout/pro', base_url=base, follow_redirects=True)
    assert r.status_code == 200 and 'no card is ever taken' in r.get_data(as_text=True)
    with env['app'].app_context(), tenancy.use_tenant('brightnest'):
        rows = OutboundLog.query.order_by(OutboundLog.id).all()[n0:]
        db.session.remove()
    assert rows and all(r.detail == demo_guard.BLOCKED_DETAIL for r in rows)
    assert len(net.calls) == before
    page = c.get('/messages/sent', base_url=base, follow_redirects=True)
    assert page.status_code == 200


def test_a_visitor_cannot_lock_out_the_next_one(env):
    import tenancy
    from extensions import db
    from models import User
    import integrations
    c, base = _demo_client(env['app'])
    c.post('/account/password', base_url=base,
           data={'current_password': DEMO_PW, 'new_password': 'a-new-password-99',
                 'confirm_password': 'a-new-password-99'})
    c.post('/account/2fa/start', base_url=base)
    c.post('/settings/connections', base_url=base,
           data={'stripe_secret_key': 'sk_live_somebody_real', 'resend_api_key': 're_real'})
    with env['app'].app_context(), tenancy.use_tenant('brightnest'):
        u = User.query.filter_by(username='sarah@brightnest.example').first()
        assert u.check_password(DEMO_PW)
        assert not u.totp_secret and not u.totp_enabled
        assert integrations.source('stripe_secret_key') != 'company'
        db.session.remove()
    _demo_client(env['app'])          # and the next visitor still gets in


# ── Staying in its lane ───────────────────────────────────────────────────────

def test_a_demo_login_reaches_only_the_demo(env):
    c, base = _demo_client(env['app'])
    assert c.get('/', base_url=base).status_code == 200
    r = c.get('/bookings/9903', base_url=base)
    assert r.status_code == 404 and b'REAL-BOOKING' not in r.data
    other = c.get('/', base_url=f'https://{REAL}.{HOST}')
    assert other.status_code in (302, 303) and '/login' in other.headers['Location']
    console = c.get('/console/', base_url=f'https://{HOST}')
    assert console.status_code != 200 or b'Companies' not in console.data


def test_the_scheduler_skips_it(env):
    import scheduler
    slugs = {o['slug'] for o in scheduler.companies()}
    assert REAL in slugs and 'brightnest' not in slugs


def test_it_is_left_out_of_the_funnel_and_sales(env):
    import control_plane
    import funnel
    orgs = control_plane.all_orgs(_engine())
    report = funnel.compute(orgs, [])
    assert report['test_excluded'] >= 1
    assert 'sarah@brightnest.example' not in repr(report)


def test_it_stays_a_test_account(env):
    import control_plane
    control_plane.set_test_account(_engine(), 'brightnest', False)
    assert control_plane.find(_engine(), 'brightnest')['is_test']
    control_plane.set_test_account(_engine(), REAL, True)
    assert control_plane.find(_engine(), REAL)['is_test']
    control_plane.set_test_account(_engine(), REAL, False)
    assert not control_plane.find(_engine(), REAL)['is_test']


def test_the_real_company_is_as_it_was(env):
    org, bookings, clients = _real_state()
    assert not org.get('is_demo')
    assert bookings == [(9903, 'REAL-BOOKING', 321.0, 'confirmed')]
    assert clients == [(9902, 'REAL-CLIENT')]


def test_a_forged_stripe_event_is_refused(env):
    """The demo has no webhook secret, and an HMAC with an empty key is one
    anybody can compute. Without a secret the webhook must refuse outright."""
    import hashlib as _h
    import hmac
    import json
    import time
    import tenancy
    from extensions import db
    from models import Booking
    with env['app'].app_context(), tenancy.use_tenant('brightnest'):
        b = Booking.query.filter(Booking.paid_at.is_(None), Booking.status == 'confirmed').first()
        b.stripe_payment_intent = 'pi_forged_demo'
        db.session.commit()
        bid = b.id
        db.session.remove()
    payload = json.dumps({'id': 'evt_forged', 'object': 'event', 'type': 'payment_intent.succeeded',
                          'data': {'object': {'id': 'pi_forged_demo', 'amount_received': 100}}})
    t = int(time.time())
    sig = hmac.new(b'', f'{t}.{payload}'.encode(), _h.sha256).hexdigest()
    r = env['app'].test_client().post('/api/stripe-webhook', base_url=f'https://brightnest.{HOST}',
                                      data=payload, content_type='application/json',
                                      headers={'Stripe-Signature': f't={t},v1={sig}'})
    assert r.status_code == 400
    with env['app'].app_context(), tenancy.use_tenant('brightnest'):
        assert db.session.get(Booking, bid).paid_at is None
        db.session.remove()


# ── Public-demo API cost boundary ─────────────────────────────────────────────

def test_demo_never_spends_platform_ai_places_translation_or_speech(env, monkeypatch):
    """A public demo visitor can click the expensive features without making a
    billable provider request. Places stays demonstrable using local fixtures;
    translation falls back to the source text; Nana has no provider key; voice
    falls back to the browser speech engine."""
    import assistant
    import places_finder
    import speech
    import translate
    import demo_guard

    monkeypatch.setenv('OPENROUTER_API_KEY', 'platform-openrouter-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'platform-openai-key')
    monkeypatch.setenv('GOOGLE_PLACES_API_KEY', 'platform-places-key')

    def network_must_not_run(*args, **kwargs):
        raise AssertionError('demo attempted a paid external API request')

    monkeypatch.setattr(places_finder.requests, 'post', network_must_not_run)
    monkeypatch.setattr(translate.requests, 'post', network_must_not_run)

    with demo_guard.forced():
        assert assistant._api_key() == ''
        assert speech.provider() is None
        assert places_finder.api_key_present() is False
        ok, rows, error = places_finder.search_businesses('medical_office', 'Austin, TX')
        assert ok and len(rows) == 5 and not error
        assert all(row['place_id'].startswith('demo-medical_office-') for row in rows)
        source = 'Please bring the blue supplies.'
        assert translate.translate(source, target='es') == source


def test_demo_enter_authenticates_only_inside_demo_tenant(env):
    import tenancy
    from models import User
    app = env['app']
    c = app.test_client()
    # The same route on a real tenant is not an authentication back door.
    real = c.get('/demo-enter', base_url=f'https://{REAL{"}"}.{HOST{"}"}')
    assert real.status_code == 404
    # BrightNest can be entered without exposing or posting its password.
    entered = c.get('/demo-enter?tour=today', base_url=f'https://brightnest.{HOST{"}"}')
    assert entered.status_code in (302, 303)
    assert entered.headers['Location'].endswith('/')
    home = c.get('/', base_url=f'https://brightnest.{HOST{"}"}')
    assert home.status_code == 200

