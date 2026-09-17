"""Cohort-30 tenant isolation falsification on real PostgreSQL.

Two-tenant tests prove the mechanism; this test proves the launch cohort shape.
It provisions thirty independent schemas, writes colliding object IDs into every
schema, then verifies each tenant can see only its own rows.  Colliding IDs are
intentional: an accidental public/default-schema query cannot pass by luck.
"""
import os

import pytest
from sqlalchemy import create_engine, text

DB_NAME = "dsm_cohort30_isolation_test"
COHORT_SIZE = 30


def _postgres_admin_url():
    for candidate in (
        os.environ.get("TEST_POSTGRES_URL"),
        f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres',
    ):
        if not candidate:
            continue
        try:
            engine = create_engine(candidate)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return candidate
        except Exception:
            continue
    return None


@pytest.fixture(scope="module")
def cohort_app():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip("30-tenant isolation requires PostgreSQL")

    original = dict(os.environ)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {DB_NAME}"))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    os.environ.update({
        "DATABASE_URL": test_url,
        "SECRET_KEY": "cohort-30-isolation-secret",
        "BASE_DOMAIN": "akye.test",
        "SIGNUPS_OPEN": "0",
    })

    import notifications
    notifications.send_sms = lambda *a, **k: (True, "stub")
    notifications.send_email = lambda *a, **k: (True, "stub")

    import provisioning
    slugs = [f"cohort{i:02d}" for i in range(1, COHORT_SIZE + 1)]
    for slug in slugs:
        provisioning.provision(slug, f"Cohort Business {slug[-2:]}", quiet=True)

    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)

    import tenancy
    from extensions import db
    from models import Booking, Staff

    # Every tenant gets the same primary keys. Schema selection, not globally
    # unique IDs, must be what prevents disclosure.
    with app.app_context():
        for i, slug in enumerate(slugs, 1):
            marker = f"TENANT-{i:02d}-ONLY"
            with tenancy.use_tenant(slug):
                db.session.add_all([
                    Staff(id=7001, name=f"{marker}-STAFF"),
                    Booking(id=8001, service_type="standard",
                            name=f"{marker}-BOOKING", price=float(100 + i)),
                ])
                db.session.commit()
                db.session.remove()

    try:
        yield app, slugs
    finally:
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        except Exception:
            pass
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))
        admin.dispose()
        os.environ.clear()
        os.environ.update(original)


def test_all_30_tenants_resolve_colliding_ids_only_inside_their_schema(cohort_app):
    app, slugs = cohort_app
    import tenancy
    from extensions import db
    from models import Booking, Staff

    with app.app_context():
        for i, slug in enumerate(slugs, 1):
            own = f"TENANT-{i:02d}-ONLY"
            with tenancy.use_tenant(slug):
                staff = db.session.get(Staff, 7001)
                booking = db.session.get(Booking, 8001)
                assert staff is not None and staff.name == f"{own}-STAFF"
                assert booking is not None and booking.name == f"{own}-BOOKING"
                assert booking.price == float(100 + i)
                db.session.remove()


def test_cohort_has_exactly_30_distinct_tenant_schemas(cohort_app):
    app, slugs = cohort_app
    from extensions import db
    import tenancy

    expected = {tenancy.schema_for(slug) for slug in slugs}
    assert len(expected) == COHORT_SIZE
    with app.app_context(), db.engine.connect() as conn:
        actual = set(conn.execute(text(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name LIKE 'tenant_cohort%'"
        )).scalars())
    assert actual == expected
