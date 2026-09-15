"""Concurrent cohort-scale PostgreSQL falsification.

The existing cohort test exercises repeated sequential pool reuse.  This test
adds the missing shape for a 30-business launch: many tenants checking out
connections concurrently while every read must remain pinned to its own schema.
"""
import os
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy import create_engine, text


COUNT = 30
WORKERS = 16
READS = 600
DB_NAME = 'dsm_cohort_concurrency_test'
SLUGS = [f'load{i:02d}' for i in range(1, COUNT + 1)]


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
def cohort_db():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('cohort concurrency falsification requires PostgreSQL')

    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    engine = create_engine(test_url, pool_size=5, max_overflow=15, pool_pre_ping=True)

    with engine.begin() as conn:
        for index, slug in enumerate(SLUGS, start=1):
            schema = f'tenant_{slug}'
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(
                f'CREATE TABLE "{schema}".cohort_canary '
                '(id integer primary key, marker text not null)'
            ))
            conn.execute(text(
                f'INSERT INTO "{schema}".cohort_canary (id, marker) '
                'VALUES (1, :marker)'
            ), {'marker': f'TENANT-{index:02d}'})

    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        admin.dispose()


def _tenant_read(engine, slug):
    expected = f'TENANT-{SLUGS.index(slug) + 1:02d}'
    schema = f'tenant_{slug}'
    with engine.connect() as conn:
        # SET LOCAL is transaction-scoped.  Returning the connection to the
        # pool must therefore return it without tenant authority attached.
        with conn.begin():
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            marker = conn.execute(text('SELECT marker FROM cohort_canary')).scalar_one()
            visible = conn.execute(text('SELECT current_schema()')).scalar_one()
        clean_path = conn.execute(text('SHOW search_path')).scalar_one()
    assert marker == expected, (slug, marker, expected)
    assert visible == schema, (slug, visible)
    assert schema not in clean_path, (slug, clean_path)
    return slug


def test_30_tenants_survive_concurrent_pool_reuse_without_bleed(cohort_db):
    rng = random.Random(20260915)
    work = [rng.choice(SLUGS) for _ in range(READS)]
    # Guarantee every tenant participates even if the deterministic random
    # sequence is changed later.
    work[:COUNT] = SLUGS
    rng.shuffle(work)

    completed = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(_tenant_read, cohort_db, slug) for slug in work]
        for future in as_completed(futures):
            completed.append(future.result())

    assert len(completed) == READS
    assert set(completed) == set(SLUGS)


def test_pool_connections_are_public_after_concurrent_tenant_work(cohort_db):
    # Repeated post-load check catches a tenant search_path accidentally left
    # on any physical connection returned by the pool.
    for _ in range(40):
        with cohort_db.connect() as conn:
            path = conn.execute(text('SHOW search_path')).scalar_one()
            assert 'tenant_' not in path, path
            with pytest.raises(Exception):
                conn.execute(text('SELECT marker FROM cohort_canary')).all()
