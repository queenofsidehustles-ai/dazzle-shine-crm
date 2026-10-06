"""TEN-04: real PostgreSQL pool reuse must never carry tenant state.

These tests exercise the actual SQLAlchemy/psycopg2 pool rather than fakes.
They alternate tenant contexts, release sessions back to the pool, force an
exception path, and verify that every subsequent checkout gets the search_path
for the current tenant (or public).
"""
import os

import pytest
from sqlalchemy import create_engine, text

DB_NAME = 'dsm_tenant_pool_reuse_test'


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
def pool_app():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('tenant pool-reuse isolation requires PostgreSQL')

    original = dict(os.environ)
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    os.environ['DATABASE_URL'] = test_url
    os.environ['SECRET_KEY'] = 'tenant-pool-reuse-secret'
    os.environ['BASE_DOMAIN'] = 'akye.test'
    os.environ['SIGNUPS_OPEN'] = '0'
    os.environ.pop('ADMIN_USER', None)
    os.environ.pop('ADMIN_PASS', None)

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
    from models import Client

    with app.app_context():
        with tenancy.use_tenant('alpha'):
            db.session.add(Client(name='ALPHA POOL CUSTOMER', email='alpha@pool.test'))
            db.session.commit()
            db.session.remove()
        with tenancy.use_tenant('bravo'):
            db.session.add(Client(name='BRAVO POOL CUSTOMER', email='bravo@pool.test'))
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


def _first_search_path(db):
    return db.session.execute(text('SHOW search_path')).scalar()


def test_real_pool_alternation_repoints_every_checkout(pool_app):
    import tenancy
    from extensions import db
    from models import Client

    seen = []
    with pool_app.app_context():
        for slug, expected_name in (
            ('alpha', 'ALPHA POOL CUSTOMER'),
            ('bravo', 'BRAVO POOL CUSTOMER'),
            ('alpha', 'ALPHA POOL CUSTOMER'),
            ('bravo', 'BRAVO POOL CUSTOMER'),
            ('alpha', 'ALPHA POOL CUSTOMER'),
        ):
            with tenancy.use_tenant(slug):
                names = [row.name for row in Client.query.order_by(Client.id).all()]
                path = _first_search_path(db)
                seen.append((slug, names, path))
                assert names == [expected_name]
                assert f'tenant_{slug}' in path
                db.session.remove()  # force the next iteration through pool checkout

    assert len(seen) == 5
    assert tenancy.current_schema() == 'public'


def test_exception_path_restores_public_before_next_checkout(pool_app):
    import tenancy
    from extensions import db
    from models import Client

    with pool_app.app_context():
        with pytest.raises(RuntimeError, match='forced mid-request failure'):
            with tenancy.use_tenant('alpha'):
                assert [c.name for c in Client.query.all()] == ['ALPHA POOL CUSTOMER']
                assert 'tenant_alpha' in _first_search_path(db)
                db.session.remove()
                raise RuntimeError('forced mid-request failure')

        assert tenancy.current_schema() == 'public'

        # Hand the pool straight to Bravo after Alpha failed. If stale connection
        # state survives, this is where Alpha data would be exposed.
        with tenancy.use_tenant('bravo'):
            assert [c.name for c in Client.query.all()] == ['BRAVO POOL CUSTOMER']
            assert 'tenant_bravo' in _first_search_path(db)
            db.session.remove()

        assert tenancy.current_schema() == 'public'

        # Finally prove a raw public checkout is not still pointed at Bravo.
        path = _first_search_path(db)
        assert path.strip() == 'public'
        db.session.remove()
