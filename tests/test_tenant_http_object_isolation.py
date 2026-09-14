"""TEN-02: falsify cross-tenant direct-object access through real HTTP routes.

The schema tests prove search_path isolation at the database boundary.  This file
proves the application cannot undo that guarantee when an authenticated tenant
supplies another tenant's numeric object IDs directly in URLs/forms.

Requires PostgreSQL because the property under test is tenant schema isolation.
The database created here is disposable and is dropped after the module.
"""
import os

import pytest
from sqlalchemy import create_engine, text


DB_NAME = 'dsm_tenant_http_object_isolation_test'
A = 'objecta'
B = 'objectb'


def _postgres_admin_url():
    candidates = [
        os.environ.get('TEST_POSTGRES_URL'),
        f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres',
    ]
    for candidate in candidates:
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
def boundary():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('TEN-02 HTTP object isolation requires PostgreSQL')

    original_env = dict(os.environ)
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    os.environ['DATABASE_URL'] = test_url
    os.environ['SECRET_KEY'] = 'tenant-http-object-isolation-secret-12345'
    os.environ['BASE_DOMAIN'] = 'akye.test'
    os.environ['SIGNUPS_OPEN'] = '0'
    os.environ['FLASK_ENV'] = 'development'
    os.environ.pop('ADMIN_USER', None)
    os.environ.pop('ADMIN_PASS', None)

    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    notifications.send_email = lambda *a, **k: (True, 'stub')

    import provisioning
    import tenancy
    from app import create_app
    from extensions import db
    from models import Booking, Client, Staff

    provisioning.provision(A, 'Object A Cleaning', quiet=True)
    provisioning.provision(B, 'Object B Cleaning', quiet=True)

    app = create_app()
    app.config.update(TESTING=True)

    # Deliberately non-overlapping high IDs.  If tenant A ever resolves an ID
    # globally instead of inside its own schema, these are easy to recognize.
    with app.app_context():
        with tenancy.use_tenant(A):
            db.session.add_all([
                Booking(id=9101, service_type='standard', name='A-BOOKING', price=101),
                Staff(id=9201, name='A-STAFF', is_active=True),
                Client(id=9301, name='A-CLIENT', email='a@example.test'),
            ])
            db.session.commit()
            db.session.remove()
        with tenancy.use_tenant(B):
            db.session.add_all([
                Booking(id=9102, service_type='standard', name='B-BOOKING', price=202),
                Staff(id=9202, name='B-STAFF', is_active=True),
                Client(id=9302, name='B-CLIENT', email='b@example.test'),
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
        os.environ.update(original_env)


def _authenticated_client(app, slug=A):
    client = app.test_client()
    base = f'https://{slug}.akye.test'
    with client.session_transaction(base_url=base) as sess:
        sess['logged_in'] = True
        sess['role'] = 'owner'
        sess['user_id'] = 1
        sess['user_name'] = 'Boundary Tester'
        # Hosted Akye sessions are deliberately tenant-bound.  These HTTP
        # object-isolation tests need a valid session for the source tenant so
        # they exercise object lookup, not the login redirect guard.
        sess['tenant_slug'] = slug
    return client, base


def test_foreign_booking_id_is_not_readable(boundary):
    client, base = _authenticated_client(boundary, A)
    response = client.get('/bookings/9102', base_url=base)
    assert response.status_code == 404
    assert b'B-BOOKING' not in response.data


def test_foreign_booking_id_cannot_be_mutated(boundary):
    client, base = _authenticated_client(boundary, A)
    response = client.post(
        '/bookings/9102',
        base_url=base,
        data={'status': 'cancelled', 'price': '1.00'},
    )
    assert response.status_code == 404

    import tenancy
    from extensions import db
    from models import Booking
    with boundary.app_context():
        with tenancy.use_tenant(B):
            target = db.session.get(Booking, 9102)
            assert target is not None
            assert target.name == 'B-BOOKING'
            assert target.price == 202
            assert target.status != 'cancelled'
        db.session.remove()


def test_foreign_staff_id_cannot_be_read_toggled_or_deleted(boundary):
    client, base = _authenticated_client(boundary, A)

    assert client.get('/staff/9202', base_url=base).status_code == 404
    assert client.post('/staff/9202/toggle', base_url=base).status_code == 404
    assert client.post('/staff/9202/delete', base_url=base).status_code == 404

    import tenancy
    from extensions import db
    from models import Staff
    with boundary.app_context():
        with tenancy.use_tenant(B):
            target = db.session.get(Staff, 9202)
            assert target is not None
            assert target.name == 'B-STAFF'
            assert target.is_active is True
        db.session.remove()


def test_foreign_client_id_cannot_prefill_booking_form(boundary):
    client, base = _authenticated_client(boundary, A)
    response = client.get('/bookings/new?client=9302', base_url=base)
    assert response.status_code == 200
    assert b'B-CLIENT' not in response.data
    assert b'b@example.test' not in response.data


def test_session_cookie_does_not_cross_tenant_hosts(boundary):
    # Authenticate only on A.  The same browser must not become authenticated
    # on B merely because both tenants live below akye.test.
    client, _ = _authenticated_client(boundary, A)
    response = client.get('/', base_url='https://objectb.akye.test',
                          follow_redirects=False)
    assert response.status_code in (301, 302, 303, 307, 308)
    assert '/login' in (response.headers.get('Location') or '')
