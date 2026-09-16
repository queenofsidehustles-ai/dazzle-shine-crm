"""TEN-05: financial CSV exports must remain tenant scoped."""
import os

import pytest
from sqlalchemy import create_engine, text

DB_NAME = 'dsm_tenant_export_test'
A = 'exporta'
B = 'exportb'


def _postgres_admin_url():
    candidates = [os.environ.get('TEST_POSTGRES_URL'), f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres']
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
        pytest.skip('TEN-05 export isolation requires PostgreSQL')
    original_env = dict(os.environ)
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))
    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    os.environ.update({
        'DATABASE_URL': test_url,
        'SECRET_KEY': 'tenant-export-secret-at-least-32-characters',
        'BASE_DOMAIN': 'akye.test',
        'SIGNUPS_OPEN': '0',
        'FLASK_ENV': 'development',
    })
    os.environ.pop('ADMIN_USER', None)
    os.environ.pop('ADMIN_PASS', None)

    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    notifications.send_email = lambda *a, **k: (True, 'stub')

    import provisioning
    import tenancy
    from app import create_app
    from extensions import db
    from models import Expense

    provisioning.provision(A, 'Export A Cleaning', quiet=True)
    provisioning.provision(B, 'Export B Cleaning', quiet=True)
    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        with tenancy.use_tenant(A):
            db.session.add(Expense(id=7701, date='2026-09-14', category='supplies', amount=64.50,
                                   vendor='ALPHA-ONLY-VENDOR', note='ALPHA-EXPORT-CANARY', method='card'))
            db.session.commit(); db.session.remove()
        with tenancy.use_tenant(B):
            db.session.add(Expense(id=7701, date='2026-09-14', category='supplies', amount=64.50,
                                   vendor='BRAVO-ONLY-VENDOR', note='BRAVO-EXPORT-CANARY', method='card'))
            db.session.commit(); db.session.remove()
    try:
        yield app
    finally:
        try:
            with app.app_context():
                db.session.remove(); db.engine.dispose()
        except Exception:
            pass
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        admin.dispose()
        os.environ.clear(); os.environ.update(original_env)


def _owner(app, slug):
    client = app.test_client()
    base = f'https://{slug}.akye.test'
    with client.session_transaction(base_url=base) as sess:
        sess['logged_in'] = True
        sess['role'] = 'owner'
        sess['user_id'] = 1
        sess['user_name'] = 'Export Boundary Tester'
        sess['tenant_slug'] = slug
    return client, base


def test_financial_export_contains_only_active_tenant(boundary):
    owner_a, base_a = _owner(boundary, A)
    a = owner_a.get('/money/pnl/export?period=month&year=2026&month=9', base_url=base_a)
    assert a.status_code == 200
    text_a = a.get_data(as_text=True)
    assert 'ALPHA-ONLY-VENDOR' in text_a and 'ALPHA-EXPORT-CANARY' in text_a
    assert 'BRAVO-ONLY-VENDOR' not in text_a and 'BRAVO-EXPORT-CANARY' not in text_a

    owner_b, base_b = _owner(boundary, B)
    b = owner_b.get('/money/pnl/export?period=month&year=2026&month=9', base_url=base_b)
    assert b.status_code == 200
    text_b = b.get_data(as_text=True)
    assert 'BRAVO-ONLY-VENDOR' in text_b and 'BRAVO-EXPORT-CANARY' in text_b
    assert 'ALPHA-ONLY-VENDOR' not in text_b and 'ALPHA-EXPORT-CANARY' not in text_b
