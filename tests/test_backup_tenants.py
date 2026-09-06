"""A backup of a multi-company database has to contain the companies.

Akye gives every cleaning company its own PostgreSQL schema. `backup.py` read
one schema — public — which on Akye holds the company registry and none of the
businesses. The run printed a ✅, the manifest showed rows, and every client,
job, cleaner and pay record on the platform was absent from it. Nothing in the
suite noticed, because nothing here asked about a second schema.

These tests need a real PostgreSQL server, because a schema is the whole
subject and SQLite does not have them. Set PGURL to a server that can create
databases, or they skip:

    PGURL=postgresql://localhost/postgres python3 tests/test_backup_tenants.py
"""
import os, sys, subprocess, textwrap, json, gzip, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PGURL = os.environ.get('PGURL') or 'postgresql://localhost/postgres'

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


# ---------------------------------------------------------------------------
# A server, or nothing to say.

def _server_available():
    try:
        from sqlalchemy import create_engine, text
        e = create_engine(PGURL.replace('postgresql://', 'postgresql+psycopg2://', 1))
        with e.connect() as c:
            c.execute(text('SELECT 1'))
        return True
    except Exception as exc:
        print(f'\n⏭️  No PostgreSQL at {PGURL} ({type(exc).__name__}) — skipping.')
        print('   These tests cover schema-per-company backups and need a real server.')
        return False


if not _server_available():
    sys.exit(0)

from sqlalchemy import create_engine, text

ADMIN = create_engine(
    PGURL.replace('postgresql://', 'postgresql+psycopg2://', 1),
    isolation_level='AUTOCOMMIT')

TAG = uuid.uuid4().hex[:8]
LIVE = f'akye_bk_live_{TAG}'
SCRATCH = f'akye_bk_scratch_{TAG}'


def make_db(name):
    with ADMIN.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS {name}'))
        c.execute(text(f'CREATE DATABASE {name}'))
    return PGURL.rsplit('/', 1)[0] + '/' + name


def drop_db(name):
    with ADMIN.connect() as c:
        c.execute(text(
            'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
            f"WHERE datname = '{name}' AND pid <> pg_backend_pid()"))
        c.execute(text(f'DROP DATABASE IF EXISTS {name}'))


def run(code, **env):
    """A fresh interpreter per scenario — create_app() binds one database per
    process, and these tests deliberately use several."""
    e = dict(os.environ)
    e.update({k: str(v) for k, v in env.items()})
    r = subprocess.run([sys.executable, '-c', textwrap.dedent(code)],
                       capture_output=True, text=True, cwd=ROOT, env=e)
    if 'OK' not in r.stdout:
        raise AssertionError(f'--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}')
    return r.stdout


LIVE_URL = make_db(LIVE)
SCRATCH_URL = make_db(SCRATCH)
TMP = os.path.join(os.environ.get('TMPDIR', '/tmp'), f'akye_bk_{TAG}')
os.makedirs(TMP, exist_ok=True)

try:
    # -----------------------------------------------------------------------
    print('\n1. A database with companies in it')

    # Build public from the models, then give two companies a schema each with
    # the same tables, and put a different business in each.
    run('''
        import os, sys
        sys.path.insert(0, %r)
        os.environ['DATABASE_URL'] = os.environ['LIVE']
        os.environ['SECRET_KEY'] = 'test'
        import notifications
        notifications.send_sms = lambda *a, **k: (True, 'stub')
        notifications.send_email = lambda *a, **k: (True, 'stub')
        from app import create_app
        from extensions import db
        from sqlalchemy import MetaData, text
        app = create_app()
        with app.app_context():
            db.create_all()
            for slug, client, email, addr in (
                    ('acme',  'Mrs Patel', 'patel@example.com',
                     '12 Oak Ave - key under the mat'),
                    ('baker', 'T Hall',    'hall@example.com',
                     '3 Ash Lane - gate code 4417')):
                schema = 'tenant_' + slug
                md = MetaData()
                for t in db.metadata.sorted_tables:
                    t.to_metadata(md, schema=schema)
                with db.engine.begin() as c:
                    c.execute(text('CREATE SCHEMA IF NOT EXISTS "%%s"' %% schema))
                md.create_all(bind=db.engine)
                with db.engine.begin() as c:
                    c.execute(text(
                        'INSERT INTO "%%s".client (name, email, address) '
                        'VALUES (:n, :e, :a)' %% schema),
                        {'n': client, 'e': email, 'a': addr})
        print('OK')
    ''' % ROOT, LIVE=LIVE_URL)
    check(True, 'two companies, each with its own schema and its own client')

    # -----------------------------------------------------------------------
    print('\n2. The backup contains both companies, not just the registry')

    import backup

    path, manifest = backup.create(out_dir=TMP, database_url=LIVE_URL, quiet=True)

    check(manifest.get('tenants') == ['tenant_acme', 'tenant_baker'],
          f'both company schemas were found: {manifest.get("tenants")}')
    check(manifest.get('tenant_rows', 0) >= 2,
          f'their rows are in the backup ({manifest.get("tenant_rows")} rows)')

    bodies = []
    with gzip.open(path, 'rt', encoding='utf-8') as fh:
        fh.readline()
        for line in fh:
            if line.strip():
                bodies.append(json.loads(line))

    acme = [r for r in bodies if r.get('__schema__') == 'tenant_acme'
            and r['__table__'] == 'client']
    baker = [r for r in bodies if r.get('__schema__') == 'tenant_baker'
             and r['__table__'] == 'client']
    check(any(r['row'].get('name') == 'Mrs Patel' for r in acme),
          "Acme's client is in the file, by name")
    check(any('key under the mat' in (r['row'].get('address') or '') for r in acme),
          'including the access note, which is the part that cannot be re-typed')
    check(any(r['row'].get('name') == 'T Hall' for r in baker),
          "Baker's client is in the file too")

    # -----------------------------------------------------------------------
    print('\n3. It restores as two separate companies, not one merged pile')

    counts = backup.restore(path, SCRATCH_URL, quiet=True)
    check(counts.get('tenant_acme.client') == 1,
          'Acme restored into its own schema')
    check(counts.get('tenant_baker.client') == 1,
          'Baker restored into its own schema')

    out = run('''
        import os, sys
        sys.path.insert(0, %r)
        from sqlalchemy import create_engine, text
        e = create_engine(os.environ['SCRATCH'].replace(
            'postgresql://', 'postgresql+psycopg2://', 1))
        with e.connect() as c:
            a = [r[0] for r in c.execute(text(
                'SELECT name FROM "tenant_acme".client'))]
            b = [r[0] for r in c.execute(text(
                'SELECT name FROM "tenant_baker".client'))]
        print('ACME', a)
        print('BAKER', b)
        assert a == ['Mrs Patel'], a
        assert b == ['T Hall'], b
        print('OK')
    ''' % ROOT, SCRATCH=SCRATCH_URL)
    check("ACME ['Mrs Patel']" in out,
          'and Acme sees only its own client after the restore')
    check("BAKER ['T Hall']" in out,
          'and Baker sees only its own — no leakage across the restore')

    # -----------------------------------------------------------------------
    print('\n4. Verify refuses to pass a company backup it cannot really check')

    try:
        backup.verify(path, quiet=True, scratch_url='')
        check(False, 'verifying a multi-company backup into SQLite is refused')
    except backup.BackupFailed as exc:
        check('PostgreSQL' in str(exc),
              'verifying a multi-company backup into SQLite is refused, loudly')

    drop_db(SCRATCH)
    SCRATCH_URL = make_db(SCRATCH)
    ok, _ = backup.verify(path, quiet=True, scratch_url=SCRATCH_URL)
    check(ok, 'and passes against a real Postgres scratch database')

    # -----------------------------------------------------------------------
    print('\n5. The bug itself: a company database that reads as empty is refused')

    # This is the shape of the failure that started all of this — the backup
    # reads public, finds no business tables there, and calls it a success.
    fake = {'bytes': 5000, 'total_rows': 3,
            'counts': {'company': 3}, 'tenants': [], 'tenant_counts': {}}
    problems = backup._sanity_check(fake, previous=None)
    check(any('NOT backed up' in p for p in problems),
          'a database with a registry and no business tables is refused '
          'on the FIRST run, not after a comparison that never comes')

    # And a company whose schema was read but came back without the tables.
    half = {'bytes': 5000, 'total_rows': 3, 'counts': {},
            'tenants': ['tenant_acme'],
            'tenant_counts': {'tenant_acme': {'setting': 3}}}
    problems = backup._sanity_check(half, previous=None)
    check(any('tenant_acme' in p for p in problems),
          'a company schema missing its business tables is refused too')

    # A company that vanished between two nights is worth a human.
    now = {'bytes': 5000, 'total_rows': 10, 'counts': {},
           'tenants': ['tenant_acme'],
           'tenant_counts': {'tenant_acme': dict.fromkeys(
               backup.CRITICAL_TABLES, 5)}}
    prev = {'bytes': 5000, 'total_rows': 12, 'counts': {},
            'tenants': ['tenant_acme', 'tenant_baker'], 'tenant_counts': {}}
    problems = backup._sanity_check(now, previous=prev)
    check(any('tenant_baker' in p for p in problems),
          'a company present last night and gone tonight is flagged')

    # -----------------------------------------------------------------------
    print('\n6. A single-business database still behaves exactly as before')

    single = make_db(f'akye_bk_single_{TAG}')
    run('''
        import os, sys
        sys.path.insert(0, %r)
        os.environ['DATABASE_URL'] = os.environ['ONE']
        os.environ['SECRET_KEY'] = 'test'
        import notifications
        notifications.send_sms = lambda *a, **k: (True, 'stub')
        notifications.send_email = lambda *a, **k: (True, 'stub')
        from app import create_app
        from extensions import db
        from sqlalchemy import text
        app = create_app()
        with app.app_context():
            db.create_all()
            with db.engine.begin() as c:
                c.execute(text(
                    "INSERT INTO client (name, email, address) VALUES "
                    "('Only Business', 'only@example.com', '1 High St')"))
        print('OK')
    ''' % ROOT, ONE=single)
    # Its own directory: a single-business backup compared against the
    # multi-company manifest above would correctly report that two companies
    # had vanished, which is a different database rather than a lost one.
    solo_dir = TMP + '-solo'
    os.makedirs(solo_dir, exist_ok=True)
    _, m2 = backup.create(out_dir=solo_dir, database_url=single, quiet=True)
    check(m2.get('tenants') == [],
          'no company schemas found, and none invented')
    check(m2['counts'].get('client') == 1,
          'the business is backed up out of public exactly as it always was')
    drop_db(f'akye_bk_single_{TAG}')

finally:
    drop_db(LIVE)
    drop_db(SCRATCH)

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ Every company in the database is in the backup, and comes back separate.')
