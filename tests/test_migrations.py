"""Adopting a live database into migrations without breaking it.

The dangerous case is the middle one. A database that already holds a business
must be told it is up to date, not have the baseline run against it — running
`CREATE TABLE booking` against a database that has bookings in it is how a
deploy takes a company off the air.

So most of what follows is about an established database: that it is recognised
as established, that it is recorded rather than rebuilt, and that every row is
still there afterwards.
"""
import os, sys, tempfile, subprocess, textwrap
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def run(code, db_path):
    """Each case needs its own database and its own app, and create_app() binds
    one per process — so each runs in a fresh interpreter."""
    env = dict(os.environ, DATABASE_URL=f'sqlite:///{db_path}',
               SECRET_KEY='test', ADMIN_USER='a', ADMIN_PASS='b')
    r = subprocess.run([sys.executable, '-c', textwrap.dedent(code)],
                       capture_output=True, text=True, cwd=ROOT, env=env)
    if 'OK' not in r.stdout:
        raise AssertionError(f'{r.stdout}\n{r.stderr}')
    return r.stdout


STUB = '''
    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    notifications.send_email = lambda *a, **k: (True, 'stub')
'''

print('\n1. A brand-new database builds itself and is recorded')
T = tempfile.mkdtemp()
run(STUB + '''
    import migrate
    has_tables, current, head = migrate.inspect_db()
    assert not has_tables, 'should start empty'
    assert current is None, 'and untracked'
    migrate.upgrade()
    has_tables, current, head = migrate.inspect_db()
    assert has_tables, f'tables should exist now'
    assert current == head, f'and be at head, got {current}'
    print('OK')
''', f'{T}/new.db')
print('  ✅ an empty database is built from the baseline')
print('  ✅ and left recorded at the latest revision')

print('\n2. An established database is adopted, not rebuilt')
T = tempfile.mkdtemp()
DB = f'{T}/live.db'
run(STUB + '''
    from app import create_app
    from extensions import db
    from models import Client, Booking, Staff
    from sqlalchemy import text
    app = create_app()
    with app.app_context():
        db.session.add_all([
            Client(name='Mrs Johnson', email='j@x.com'),
            Staff(name='Maria', pay_type='percent', pay_rate=50.0),
            Booking(service_type='deep', name='Deep Clean', status='completed',
                    price=280.0),
        ])
        db.session.commit()
        # Make this look like a database from before migrations existed, which
        # is what every instance running today actually is. create_app() now
        # adopts on boot, so the version row has to be removed to get back to
        # the state a real deploy will meet.
        with db.engine.begin() as conn:
            conn.execute(text('DROP TABLE IF EXISTS alembic_version'))
    print('OK')
''', DB)

# Now meet it with alembic, in a fresh process, exactly as a deploy would.
out = run(STUB + '''
    import migrate
    has_tables, current, head = migrate.inspect_db()
    assert has_tables, 'an established database has tables'
    assert current is None, 'and no version row yet'
    ok = migrate.run_at_boot()
    assert ok, 'boot migration should succeed'
    has_tables, current, head = migrate.inspect_db()
    assert current == head, f'now recorded at head, got {current}'

    from app import create_app
    from models import Client, Booking, Staff
    app = create_app()
    with app.app_context():
        assert Client.query.count() == 1, 'the client survived'
        assert Booking.query.count() == 1, 'the booking survived'
        assert Staff.query.count() == 1, 'the cleaner survived'
        b = Booking.query.first()
        assert b.name == 'Deep Clean' and b.price == 280.0, 'and is unchanged'
    print('OK')
''', DB)
print('  ✅ a database with a business in it is recognised as established')
print('  ✅ recorded at the baseline rather than having it run against it')
print('  ✅ and every row is still there afterwards, unchanged')

print('\n3. Booting twice does not migrate twice')
run(STUB + '''
    import migrate
    from app import create_app
    create_app()
    _, first, head = migrate.inspect_db()
    create_app()
    create_app()
    _, after, _ = migrate.inspect_db()
    assert first == after == head, f'{first} -> {after}, head {head}'
    from models import Booking
    app = create_app()
    with app.app_context():
        assert Booking.query.count() == 1, 'and nothing was duplicated'
    print('OK')
''', DB)
print('  ✅ three more boots leave the revision and the data alone')

print('\n4. The dry run prints SQL and changes nothing')
T = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_URL=f'sqlite:///{T}/preview.db', SECRET_KEY='test')
before = subprocess.run([sys.executable, 'migrate.py', 'sql'],
                        capture_output=True, text=True, cwd=ROOT, env=env)
check('CREATE TABLE' in before.stdout,
      'the SQL for a new database can be read before it is run')
check(not os.path.exists(f'{T}/preview.db') or os.path.getsize(f'{T}/preview.db') == 0,
      'and asking to see it did not create anything')

print('\n5. Status says which of the three situations you are in')
env = dict(os.environ, DATABASE_URL=f'sqlite:///{DB}', SECRET_KEY='test')
r = subprocess.run([sys.executable, 'migrate.py', 'status'],
                   capture_output=True, text=True, cwd=ROOT, env=env)
check('up to date' in r.stdout, 'an adopted database reports up to date')
check('0001_baseline' in r.stdout, 'and names the revision it is on')

print('\n6. A database it cannot reach does not stop the CRM starting')
# A migration that fails is serious. A CRM that will not boot is worse: the
# owner loses every page, including the ones that would tell her what is wrong.
bad = dict(os.environ, DATABASE_URL='postgresql://nobody@127.0.0.1:1/nothing',
           SECRET_KEY='test')
r = subprocess.run([sys.executable, '-c', textwrap.dedent('''
    import migrate
    ok = migrate.run_at_boot()
    print('RETURNED', ok)
''')], capture_output=True, text=True, cwd=ROOT, env=bad, timeout=120)
check('RETURNED False' in r.stdout, 'an unreachable database reports failure')
check('MIGRATION DID NOT RUN' in r.stdout, 'says so loudly')
check(r.returncode == 0, 'and does not crash the process')

print('\n7. The baseline matches the models it was generated from')
T = tempfile.mkdtemp()
run(STUB + '''
    import migrate
    migrate.upgrade()
    from sqlalchemy import inspect as sa_inspect
    import extensions, models
    eng = migrate._engine()
    with eng.connect() as conn:
        built = set(sa_inspect(conn).get_table_names())
    declared = set(extensions.db.metadata.tables) | {'alembic_version'}
    missing = declared - built
    assert not missing, f'baseline did not create: {sorted(missing)}'
    print('OK')
''', f'{T}/full.db')
print('  ✅ every table the models declare is created by the baseline')

print('\n8. A database whose schema has drifted is still adopted safely')
# Production carries at least one column the models have never heard of
# (contractor_application.experience_years, seen in a real backup). Adoption
# only writes a version row -- it does not inspect or reconcile the schema --
# so drift must not stop it, and must not be silently "corrected" either.
T = tempfile.mkdtemp()
DRIFT = f'{T}/drifted.db'
run(STUB + '''
    from app import create_app
    from extensions import db
    from models import Client
    from sqlalchemy import text
    app = create_app()
    with app.app_context():
        db.session.add(Client(name='Old Timer', email='o@x.com'))
        db.session.commit()
        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE client ADD COLUMN legacy_field TEXT'))
            conn.execute(text("UPDATE client SET legacy_field = 'from an older release'"))
            conn.execute(text('DROP TABLE IF EXISTS alembic_version'))
    print('OK')
''', DRIFT)

run(STUB + '''
    import migrate
    ok = migrate.run_at_boot()
    assert ok, 'adoption should succeed despite the extra column'
    _, current, head = migrate.inspect_db()
    assert current == head, f'recorded at head, got {current}'

    from sqlalchemy import text, inspect as sa_inspect
    eng = migrate._engine()
    with eng.connect() as conn:
        cols = {c['name'] for c in sa_inspect(conn).get_columns('client')}
        assert 'legacy_field' in cols, 'the unknown column was not dropped'
        kept = conn.execute(text('SELECT legacy_field FROM client')).scalar()
        assert kept == 'from an older release', 'and its data is intact'
    print('OK')
''', DRIFT)
print('  ✅ an extra column the models do not know about does not block adoption')
print('  ✅ and is left exactly where it was, not quietly dropped')

print('\n\n✅ All migration tests passed.\n')
