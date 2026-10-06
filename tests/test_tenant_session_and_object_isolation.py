"""Application-layer tenant isolation falsification.

Database search_path isolation is necessary but not sufficient. A signed Flask
session is portable bytes; a determined tenant can copy its own cookie and send
it manually to another Akye subdomain. Before tenant binding, login_required()
accepted that cookie because it proved only that Akye signed it, not which
company it belonged to.

These tests prove three boundaries on real PostgreSQL:
* a session issued for tenant A is rejected when replayed on tenant B;
* numeric object IDs resolve only inside the host-selected tenant schema;
* deployment-wide ADMIN_USER/ADMIN_PASS cannot become a master tenant login.
"""
import os

import pytest
from sqlalchemy import create_engine, text


DB_NAME = 'dsm_tenant_session_object_test'


def _postgres_admin_url():
    for candidate in (
        os.environ.get('TEST_POSTGRES_URL'),
        f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres',
    ):
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


@pytest.fixture(scope='module')
def tenant_app():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('tenant application isolation requires PostgreSQL')

    original = dict(os.environ)
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    os.environ['DATABASE_URL'] = test_url
    os.environ['SECRET_KEY'] = 'tenant-session-object-secret'
    os.environ['BASE_DOMAIN'] = 'akye.test'
    os.environ['SIGNUPS_OPEN'] = '0'
    # Deliberately set these: hosted Akye must ignore a deployment-wide owner
    # credential rather than turn it into a master key for every tenant.
    os.environ['ADMIN_USER'] = 'global-owner'
    os.environ['ADMIN_PASS'] = 'A-strong-global-password-123!'

    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    notifications.send_email = lambda *a, **k: (True, 'stub')

    import provisioning
    for slug, name in (('alpha', 'Alpha Cleaning'), ('bravo', 'Bravo Cleaning')):
        provisioning.provision(slug, name, quiet=True)

    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)

    import tenancy
    from extensions import db
    from models import Booking, Staff, User

    with app.app_context():
        with tenancy.use_tenant('alpha'):
            owner = User(id=11, name='Alpha Owner', username='alpha-owner@example.test',
                         role='owner', active=True)
            owner.set_password('alpha-password-123')
            db.session.add_all([
                owner,
                Staff(id=101, name='ALPHA-ONLY-STAFF'),
                Booking(id=201, service_type='standard', name='ALPHA-ONLY-BOOKING',
                        price=111.0),
            ])
            db.session.commit()
            db.session.remove()
        with tenancy.use_tenant('bravo'):
            owner = User(id=12, name='Bravo Owner', username='bravo-owner@example.test',
                         role='owner', active=True)
            owner.set_password('bravo-password-123')
            db.session.add_all([
                owner,
                Staff(id=102, name='BRAVO-ONLY-STAFF'),
                Booking(id=202, service_type='standard', name='BRAVO-ONLY-BOOKING',
                        price=222.0),
            ])
            db.session.commit()
            db.session.remove()

    try:
        yield app
    finally:
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        except Exception:
            pass
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        admin.dispose()
        os.environ.clear()
        os.environ.update(original)


def _session_cookie(app, slug, user_id, name):
    """Create exactly the signed cookie a successful tenant login would issue.

    Login also binds the cookie to the credential version of the account that
    issued it (``auth.authenticate``'s ``auth_fingerprint``), so a
    hand-assembled cookie has to carry the same binding or
    ``session_matches_current_user`` rejects it as stale before the test ever
    reaches the cross-tenant replay it means to exercise.
    """
    from flask import g, session
    from auth import bind_session_to_current_tenant, _auth_fingerprint
    import tenancy
    from models import User

    with app.test_request_context('/', base_url=f'https://{slug}.akye.test'):
        g.tenant_slug = slug
        with tenancy.use_tenant(slug):
            user = User.query.get(user_id)
        session.clear()
        session.permanent = True
        bind_session_to_current_tenant()
        session['logged_in'] = True
        session['role'] = 'owner'
        session['user_id'] = user_id
        session['user_name'] = name
        session['auth_fingerprint'] = _auth_fingerprint(user.password_hash)
        serializer = app.session_interface.get_signing_serializer(app)
        return serializer.dumps(dict(session))


def _set_cookie(client, app, host, value):
    name = app.config.get('SESSION_COOKIE_NAME', 'session')
    try:  # Flask/Werkzeug 3.x
        client.set_cookie(name, value, domain=host)
    except TypeError:  # Older Werkzeug signature
        client.set_cookie(host, name, value)


def test_replayed_tenant_session_is_rejected_on_other_host(tenant_app):
    app = tenant_app
    cookie = _session_cookie(app, 'alpha', 11, 'Alpha Owner')

    # Sanity: the cookie works where it was issued.
    alpha = app.test_client()
    _set_cookie(alpha, app, 'alpha.akye.test', cookie)
    own = alpha.get('/staff/', base_url='https://alpha.akye.test')
    assert own.status_code == 200
    assert b'ALPHA-ONLY-STAFF' in own.data
    assert b'BRAVO-ONLY-STAFF' not in own.data

    # Attack: manually replay the exact same valid Akye-signed cookie on Bravo.
    # Browser host scoping is bypassed on purpose; authorization must still hold.
    replay = app.test_client()
    _set_cookie(replay, app, 'bravo.akye.test', cookie)
    response = replay.get('/staff/', base_url='https://bravo.akye.test',
                          follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert b'BRAVO-ONLY-STAFF' not in response.data


def test_foreign_numeric_object_ids_do_not_cross_tenant_host(tenant_app):
    app = tenant_app

    alpha_cookie = _session_cookie(app, 'alpha', 11, 'Alpha Owner')
    alpha = app.test_client()
    _set_cookie(alpha, app, 'alpha.akye.test', alpha_cookie)

    # Local IDs work; IDs that exist only in Bravo are 404 in Alpha.
    own_staff = alpha.get('/staff/101', base_url='https://alpha.akye.test')
    assert own_staff.status_code == 200
    assert b'ALPHA-ONLY-STAFF' in own_staff.data
    foreign_staff = alpha.get('/staff/102', base_url='https://alpha.akye.test')
    assert foreign_staff.status_code == 404
    assert b'BRAVO-ONLY-STAFF' not in foreign_staff.data

    own_booking = alpha.get('/bookings/201', base_url='https://alpha.akye.test')
    assert own_booking.status_code == 200
    assert b'ALPHA-ONLY-BOOKING' in own_booking.data
    foreign_booking = alpha.get('/bookings/202', base_url='https://alpha.akye.test')
    assert foreign_booking.status_code == 404
    assert b'BRAVO-ONLY-BOOKING' not in foreign_booking.data

    # Reverse the attack so this is not an accidental one-way property.
    bravo_cookie = _session_cookie(app, 'bravo', 12, 'Bravo Owner')
    bravo = app.test_client()
    _set_cookie(bravo, app, 'bravo.akye.test', bravo_cookie)
    assert bravo.get('/staff/101', base_url='https://bravo.akye.test').status_code == 404
    assert bravo.get('/bookings/201', base_url='https://bravo.akye.test').status_code == 404


def test_hosted_product_disables_deployment_wide_owner_login(tenant_app):
    # ADMIN_USER and ADMIN_PASS are deliberately set by the fixture. A shared
    # deployment must still report the env login unavailable.
    from auth import env_login_configured
    assert env_login_configured() is False
