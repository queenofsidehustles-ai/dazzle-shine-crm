"""P1 privacy lifecycle: real PostgreSQL closure/retention/purge falsification."""
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

DB_NAME = 'dsm_tenant_data_lifecycle_test'
A = 'erasealpha'
B = 'keepbravo'


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
def lifecycle_db():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('data lifecycle falsification requires PostgreSQL')
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))
    url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    engine = create_engine(url)

    import control_plane
    import tenant_data_lifecycle as lifecycle
    control_plane.ensure_table(engine)
    lifecycle.ensure_columns(engine)
    for slug, name, owner in (
        (A, 'Erase Alpha', 'alpha-owner@example.com'),
        (B, 'Keep Bravo', 'bravo-owner@example.com'),
    ):
        control_plane.create(engine, slug, name, owner)
        schema = f'tenant_{slug}'
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'CREATE TABLE "{schema}".canary (marker text not null)'))
            conn.execute(text(f'INSERT INTO "{schema}".canary VALUES (:m)'),
                         {'m': f'{slug}-private'})
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO public.feedback (org_slug, user_name, body, shot, shot_type) "
            "VALUES (:slug, 'Alpha Owner', 'alpha private feedback', :shot, 'image/jpeg')"),
            {'slug': A, 'shot': b'alpha-private-shot'})
        conn.execute(text(
            "INSERT INTO public.feedback (org_slug, user_name, body) "
            "VALUES (:slug, 'Bravo Owner', 'bravo private feedback')"), {'slug': B})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        admin.dispose()


def _schema_exists(engine, schema):
    with engine.connect() as conn:
        return bool(conn.execute(text(
            'SELECT 1 FROM information_schema.schemata WHERE schema_name=:s'),
            {'s': schema}).first())


def test_close_is_immediate_recoverable_and_timestamp_is_immutable(lifecycle_db):
    import tenant_data_lifecycle as lifecycle
    t0 = datetime(2026, 9, 15, 12, 0, 0)
    first = lifecycle.close_tenant(lifecycle_db, A, now=t0)
    second = lifecycle.close_tenant(lifecycle_db, A, now=t0 + timedelta(days=2))
    assert first['status'] == 'closed'
    assert first['closed_at'] == t0
    assert second['closed_at'] == t0
    assert second['eligible_at'] == t0 + timedelta(days=30)
    assert _schema_exists(lifecycle_db, f'tenant_{A}')
    assert _schema_exists(lifecycle_db, f'tenant_{B}')


def test_purge_refuses_before_30_days_without_touching_either_tenant(lifecycle_db):
    import tenant_data_lifecycle as lifecycle
    state = lifecycle.lifecycle_state(lifecycle_db, A)
    with pytest.raises(lifecycle.RetentionNotExpired):
        lifecycle.purge_tenant(
            lifecycle_db, A, now=state['eligible_at'] - timedelta(seconds=1),
            media_delete=lambda slug: pytest.fail('media deletion ran before eligibility'))
    assert _schema_exists(lifecycle_db, f'tenant_{A}')
    assert _schema_exists(lifecycle_db, f'tenant_{B}')


def test_eligible_purge_is_tenant_bounded_and_removes_control_plane_content(lifecycle_db):
    import tenant_data_lifecycle as lifecycle
    state = lifecycle.lifecycle_state(lifecycle_db, A)
    calls = []
    result = lifecycle.purge_tenant(
        lifecycle_db, A, now=state['eligible_at'],
        media_delete=lambda slug: calls.append(slug) or {'deleted': 3})
    assert calls == [A]
    assert result['purged_at'] == state['eligible_at']
    assert not _schema_exists(lifecycle_db, f'tenant_{A}')
    assert _schema_exists(lifecycle_db, f'tenant_{B}')

    with lifecycle_db.connect() as conn:
        bravo = conn.execute(text(f'SELECT marker FROM "tenant_{B}".canary')).scalar_one()
        alpha_feedback = conn.execute(text(
            'SELECT count(*) FROM public.feedback WHERE org_slug=:s'), {'s': A}).scalar_one()
        bravo_feedback = conn.execute(text(
            'SELECT count(*) FROM public.feedback WHERE org_slug=:s'), {'s': B}).scalar_one()
        tombstone = conn.execute(text(
            'SELECT status, name, owner_email, closed_at, purged_at '
            'FROM public.organizations WHERE slug=:s'), {'s': A}).mappings().one()
    assert bravo == f'{B}-private'
    assert alpha_feedback == 0
    assert bravo_feedback == 1
    assert tombstone['status'] == 'closed'
    assert tombstone['name'] == f'Purged tenant {A}'
    assert tombstone['owner_email'] is None
    assert tombstone['closed_at'] is not None and tombstone['purged_at'] is not None


def test_repeated_purge_is_idempotent_and_does_not_delete_neighbor(lifecycle_db):
    import tenant_data_lifecycle as lifecycle
    calls = []
    result = lifecycle.purge_tenant(
        lifecycle_db, A, now=datetime(2026, 11, 1),
        media_delete=lambda slug: calls.append(slug))
    assert result['already_purged'] is True
    assert calls == []
    assert not _schema_exists(lifecycle_db, f'tenant_{A}')
    assert _schema_exists(lifecycle_db, f'tenant_{B}')


def test_restore_reconciliation_marks_expired_closed_tenant_for_repurge(lifecycle_db):
    import tenant_data_lifecycle as lifecycle
    # Simulate a restore of a backup taken during retention: the schema can come
    # back, but the restored control-plane state remains closed. Recovery must
    # identify it for re-purge before external traffic resumes.
    with lifecycle_db.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "tenant_{A}"'))
        conn.execute(text(f'CREATE TABLE "tenant_{A}".restored_canary (marker text)'))
        conn.execute(text(
            'UPDATE public.organizations SET purged_at=NULL WHERE slug=:s'), {'s': A})
    due = lifecycle.restored_closed_tenants_requiring_repurge(
        lifecycle_db, now=datetime(2026, 11, 1))
    assert [row['slug'] for row in due] == [A]
    org = lifecycle.lifecycle_state(lifecycle_db, A)
    assert org['status'] == 'closed'
    # Clean the simulated restore so the fixture still represents a purged A.
    lifecycle.purge_tenant(
        lifecycle_db, A, now=datetime(2026, 11, 1),
        media_delete=lambda slug: {'deleted': 0})
