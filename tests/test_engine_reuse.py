"""provisioning._engine() is one pool per process, not one per call.

It is called all over -- the console, signup, billing, the nightly jobs -- often
once per company in a loop. A new engine per call was a new pool per call, each
holding its connection until the garbage collector got round to it: a hundred
calls left seventeen connections open, and with a few dozen companies a console
page could exhaust Postgres ("sorry, too many clients already").

Sharing one pool has its own risk, which is what most of this checks: a
connection must not go back to the pool carrying one caller's search_path or
advisory lock to the next.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fresh_postgres  # noqa: E402  (tests/ is on the path when run directly)

URL = fresh_postgres.url('dsm_test_engine_reuse')
os.environ['DATABASE_URL'] = URL
os.environ['PGAPPNAME'] = 'engine-reuse-test'

from sqlalchemy import create_engine, text  # noqa: E402
import provisioning  # noqa: E402

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


print('\n1. One engine per process and database')
first = provisioning._engine()
check(provisioning._engine() is first, 'the same engine comes back on every call')
os.environ['DATABASE_URL'] = URL.rsplit('/', 1)[0] + '/postgres'
check(provisioning._engine() is not first, 'a different DATABASE_URL gets its own')
os.environ['DATABASE_URL'] = URL
real_getpid = os.getpid
os.getpid = lambda: real_getpid() + 1
try:
    check(provisioning._engine() is not first,
          'and so does a forked worker: no pooled connection crosses a fork')
finally:
    os.getpid = real_getpid
check(provisioning._engine() is first, 'back in this process, the first one again')

print('\n2. A hundred calls hold a pool, not a hundred connections')
db = URL.rsplit('/', 1)[1]
for _ in range(100):
    with provisioning._engine().connect() as conn:
        conn.execute(text('SELECT 1'))
probe = create_engine(URL)
with probe.connect() as conn:
    held = conn.execute(text(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = :d "
        "AND application_name = 'engine-reuse-test' AND pid <> pg_backend_pid()"),
        {'d': db}).scalar()
check(held <= 5, f'{held} connection(s) open after 100 calls (was 17 with an engine per call)')

print('\n3. A connection goes back to the pool clean')
with provisioning._engine().connect() as conn:
    default_path = conn.execute(text('SHOW search_path')).scalar()
with provisioning._engine().connect() as conn:
    conn.execute(text('SET search_path TO pg_catalog'))
    conn.execute(text('SELECT pg_advisory_lock(424242)'))
    conn.commit()                       # a committed SET outlives the transaction
with provisioning._engine().connect() as conn:
    path = conn.execute(text('SHOW search_path')).scalar()
check(path == default_path,
      f'a search_path one caller set is not handed to the next ({path!r})')
with probe.connect() as conn:
    locks = conn.execute(text(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = 424242")).scalar()
check(locks == 0, 'nor is an advisory lock it never released')

print('\n4. A connection the server dropped is replaced, not handed out')
with probe.connect() as conn:
    conn.execute(text(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d "
        "AND application_name = 'engine-reuse-test' AND pid <> pg_backend_pid()"), {'d': db})
    conn.commit()
try:
    with provisioning._engine().connect() as conn:
        ok = conn.execute(text('SELECT 1')).scalar() == 1
except Exception as e:
    ok = False
    print(f'     {type(e).__name__}: {e}')
check(ok, 'after the pooled connection was killed (a restart), the next call still works')

probe.dispose()
provisioning._engine().dispose()

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for m in failures:
        print(f'   - {m}')
    sys.exit(1)
print('\n✅ One pool per process, and every connection goes back clean.')
