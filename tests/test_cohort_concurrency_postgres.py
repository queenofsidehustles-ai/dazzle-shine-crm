"""Concurrent cohort-scale PostgreSQL falsification.

The existing cohort test exercises repeated sequential pool reuse.  This test
adds the missing shape for a 30-business launch: many tenants checking out
connections concurrently while every read must remain pinned to its own schema.
"""
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError


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


def test_no_connection_leak_after_concurrent_cohort_load(cohort_db):
    """Every physical connection the load checked out must come back.

    A leak here is invisible in any single request — the pool just silently
    has one fewer usable slot — and only shows up later as an unrelated
    tenant timing out under normal load with no error pointing at the cause.
    """
    pool = cohort_db.pool
    assert pool.checkedout() == 0, 'pool already has checked-out connections before this test ran'

    rng = random.Random(20260916)
    work = [rng.choice(SLUGS) for _ in range(READS)]

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(_tenant_read, cohort_db, slug) for slug in work]
        for future in as_completed(futures):
            future.result()

    assert pool.checkedout() == 0, (
        f'{pool.checkedout()} connections still checked out after the load finished'
    )


def _tenant_read_that_sometimes_fails(engine, slug, force_fail):
    """Like ``_tenant_read``, but half of all calls raise mid-transaction.

    ``with conn.begin():`` is supposed to roll back and release the connection
    on any exception. That guarantee is worth falsifying directly, not just
    trusted, because a leak on the error path is the one that never shows up
    in a happy-path test run.
    """
    schema = f'tenant_{slug}'
    with engine.connect() as conn:
        try:
            with conn.begin():
                conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                conn.execute(text('SELECT marker FROM cohort_canary')).scalar_one()
                if force_fail:
                    raise RuntimeError('forced mid-tenant-read failure')
        except RuntimeError:
            pass
    return slug


def test_no_connection_leak_when_half_of_concurrent_reads_fail(cohort_db):
    pool = cohort_db.pool
    assert pool.checkedout() == 0, 'pool already has checked-out connections before this test ran'

    work = [(SLUGS[i % COUNT], i % 2 == 0) for i in range(200)]

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [
            executor.submit(_tenant_read_that_sometimes_fails, cohort_db, slug, fail)
            for slug, fail in work
        ]
        for future in as_completed(futures):
            future.result()

    assert pool.checkedout() == 0, (
        f'{pool.checkedout()} connections leaked after forced mid-read failures'
    )


def _hold_tenant_connection(engine, slug, hold_seconds, barrier):
    """Simulate one tenant's slow query occupying a pool slot for a while."""
    schema = f'tenant_{slug}'
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            barrier.wait(timeout=5)
            time.sleep(hold_seconds)
            conn.execute(text('SELECT marker FROM cohort_canary')).scalar_one()


def test_noisy_neighbor_queues_without_cross_tenant_bleed(cohort_db):
    """A tenant that exhausts the whole pool must make its neighbor wait, not
    make it wrong.

    Production runs on the unconfigured SQLAlchemy default pool (5 + 10
    overflow) shared by every company on the platform, so one company's slow
    request routinely means another company's request queues for a
    connection. Shrunk here to 2 total connections (pool_size=1 +
    max_overflow=1) so exhaustion is guaranteed and reproducible in a single
    test run. A neighbor that waits long enough must still see only its own
    tenant's row when it finally gets a connection — queueing on
    ``pool_timeout`` must never mean queueing on ``search_path``.
    """
    url = cohort_db.url.render_as_string(hide_password=False)
    engine = create_engine(url, pool_size=1, max_overflow=1, pool_timeout=3)
    try:
        noisy_slug = SLUGS[0]
        waiting_slug = SLUGS[1]
        barrier = threading.Barrier(2)
        noisy_threads = [
            threading.Thread(
                target=_hold_tenant_connection, args=(engine, noisy_slug, 1.5, barrier)
            )
            for _ in range(2)  # exactly the pool's total capacity
        ]
        for t in noisy_threads:
            t.start()

        # Let the noisy tenant actually own both slots before anyone else
        # tries, so the contention below is deterministic rather than a race.
        time.sleep(0.4)

        result = _tenant_read(engine, waiting_slug)
        assert result == waiting_slug

        for t in noisy_threads:
            t.join(timeout=5)
            assert not t.is_alive(), 'noisy tenant thread never finished'

        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_noisy_neighbor_pool_exhaustion_fails_loudly_not_with_stale_tenant_data(cohort_db):
    """A neighbor that cannot wait long enough must get a clear timeout, never
    a connection still pointed at someone else's schema.

    The failure mode this falsifies is silent cross-tenant exposure under
    load: a request that could not get its own connection in time must never
    be handed one carrying a prior tenant's ``search_path`` as a substitute.
    """
    url = cohort_db.url.render_as_string(hide_password=False)
    engine = create_engine(url, pool_size=1, max_overflow=1, pool_timeout=0.3)
    try:
        noisy_slug = SLUGS[2]
        timeout_slug = SLUGS[3]
        barrier = threading.Barrier(2)
        noisy_threads = [
            threading.Thread(
                target=_hold_tenant_connection, args=(engine, noisy_slug, 1.5, barrier)
            )
            for _ in range(2)
        ]
        for t in noisy_threads:
            t.start()

        time.sleep(0.4)

        with pytest.raises(PoolTimeoutError):
            _tenant_read(engine, timeout_slug)

        for t in noisy_threads:
            t.join(timeout=5)
            assert not t.is_alive(), 'noisy tenant thread never finished'

        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()
