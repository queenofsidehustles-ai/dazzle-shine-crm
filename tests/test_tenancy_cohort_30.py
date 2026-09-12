"""Cohort-scale PostgreSQL falsification for Akye tenant isolation.

This complements tests/test_tenancy.py rather than replacing it.  The existing
suite proves the two-party isolation invariant in detail.  This file asks a
different question: does the same invariant survive the first cohort's actual
shape -- thirty independently provisioned businesses, repeated pool reuse, and
all tenants at the same migration head?

A tenant query returning exactly its own canary is stronger and cheaper than
870 explicit pair queries: each read is simultaneously asserting that none of
the other 29 tenants' canaries is reachable through that tenant's search_path.
"""
import os
import random

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text


COUNT = 30
DB_NAME = 'dsm_tenancy_cohort_30_test'
SLUGS = [f'cohort{i:02d}' for i in range(1, COUNT + 1)]


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
def cohort(monkeypatch_module):
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('30-tenant isolation requires PostgreSQL')

    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    os.environ['DATABASE_URL'] = test_url
    os.environ['SECRET_KEY'] = 'cohort-30-isolation-test-secret'
    os.environ['BASE_DOMAIN'] = 'akye.test'
    os.environ['SIGNUPS_OPEN'] = '0'
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

    # Build thirty real schemas through the same migration path used by Akye.
    for index, slug in enumerate(SLUGS, start=1):
        provisioning.provision(slug, f'Cohort Company {index:02d}', quiet=True)

    app = create_app()
    with app.app_context():
        for index, slug in enumerate(SLUGS, start=1):
            marker = f'TENANT-{index:02d}'
            with tenancy.use_tenant(slug):
                db.session.add_all([
                    Client(name=f'{marker}-CLIENT', email=f'{slug}@example.test'),
                    Staff(name=f'{marker}-STAFF'),
                    Booking(service_type='standard', name=f'{marker}-BOOKING',
                            price=100 + index),
                ])
                db.session.commit()
                db.session.remove()

    try:
        yield app, test_url
    finally:
        # Dispose app-side pools before dropping the disposable database.
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        except Exception:
            pass
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope='module')
def monkeypatch_module():
    """Module-scoped environment cleanup without pytest's function fixture."""
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


def test_all_30_tenants_see_only_their_own_rows(cohort):
    app, _ = cohort
    import tenancy
    from extensions import db
    from models import Booking, Client, Staff

    with app.app_context():
        for index, slug in enumerate(SLUGS, start=1):
            marker = f'TENANT-{index:02d}'
            with tenancy.use_tenant(slug):
                clients = [row.name for row in Client.query.all()]
                staff = [row.name for row in Staff.query.all()]
                bookings = [row.name for row in Booking.query.all()]
                raw_clients = [row[0] for row in db.session.execute(
                    text('SELECT name FROM client ORDER BY name')).all()]

            assert clients == [f'{marker}-CLIENT']
            assert staff == [f'{marker}-STAFF']
            assert bookings == [f'{marker}-BOOKING']
            assert raw_clients == [f'{marker}-CLIENT']
            db.session.remove()


def test_randomized_pool_reuse_never_bleeds_between_30_tenants(cohort):
    app, _ = cohort
    import tenancy
    from extensions import db
    from models import Client

    rng = random.Random(20260912)
    order = [rng.choice(SLUGS) for _ in range(300)]

    with app.app_context():
        for slug in order:
            index = SLUGS.index(slug) + 1
            with tenancy.use_tenant(slug):
                names = [row.name for row in Client.query.all()]
            assert names == [f'TENANT-{index:02d}-CLIENT'], (slug, names)
            # Force the checked-out connection back into the pool so the next
            # tenant can receive the same physical PostgreSQL connection.
            db.session.remove()


def test_all_30_schemas_are_complete_and_at_migration_head(cohort):
    _, test_url = cohort
    import extensions
    import migrate

    engine = create_engine(test_url)
    declared = set(extensions.db.metadata.tables)
    head = migrate.ScriptDirectory.from_config(migrate._config()).get_current_head()

    with engine.connect() as conn:
        inspector = sa_inspect(conn)
        for slug in SLUGS:
            schema = f'tenant_{slug}'
            tables = set(inspector.get_table_names(schema=schema))
            assert not (declared - tables), (slug, sorted(declared - tables))
            version = conn.execute(text(
                f'SELECT version_num FROM "{schema}".alembic_version LIMIT 1'
            )).scalar()
            assert version == head, (slug, version, head)
            assert 'organizations' not in tables
    engine.dispose()


def test_30_hosts_resolve_exactly_one_tenant_each(cohort):
    import tenancy

    for slug in SLUGS:
        assert tenancy.slug_from_host(f'{slug}.akye.test', 'akye.test') == slug

    assert tenancy.slug_from_host('akye.test', 'akye.test') is None
    assert tenancy.slug_from_host('www.akye.test', 'akye.test') is None
    assert tenancy.slug_from_host('cohort01.evil.test', 'akye.test') is None


def test_public_context_cannot_reach_any_tenant_canary(cohort):
    app, _ = cohort
    import tenancy
    from extensions import db

    with app.app_context():
        tenancy._current.set(tenancy.PUBLIC)
        db.session.remove()
        try:
            rows = [row[0] for row in db.session.execute(
                text('SELECT name FROM client')).all()]
        except Exception:
            rows = []

    assert not any((name or '').startswith('TENANT-') for name in rows)
