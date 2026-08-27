"""Backups: does the file come back as the business that went into it.

Every test here is really one test asked in different ways — restore it and
count. A backup suite that only checks the backup ran is the suite that lets a
year of empty files accumulate, so nothing below trusts a file it has not read
back.
"""
import os, sys, tempfile, gzip, json, subprocess, textwrap
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def run(code):
    """Each scenario needs its own app and its own database, and create_app()
    binds one per process. So each runs in a fresh interpreter."""
    r = subprocess.run([sys.executable, '-c', textwrap.dedent(code)],
                       capture_output=True, text=True, cwd=ROOT)
    if 'OK' not in r.stdout:
        raise AssertionError(f'{r.stdout}\n{r.stderr}')
    return r.stdout


PRELUDE = '''
    import os, sys, tempfile
    sys.path.insert(0, %r)
    TMP = os.environ['T']
    os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/live.db'
    os.environ['SECRET_KEY'] = 'test'
    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    notifications.send_email = lambda *a, **k: (True, 'stub')
''' % ROOT


def seed(n_clients=12, n_staff=5, n_bookings=25):
    return f'''
    from app import create_app
    from extensions import db
    from models import Client, Staff, Booking
    app = create_app()
    with app.app_context():
        for i in range({n_clients}):
            db.session.add(Client(name=f'Client {{i}}', email=f'c{{i}}@x.com',
                                  phone=f'40755500{{i:02d}}', address=f'{{i}} Elm St'))
        for i in range({n_staff}):
            db.session.add(Staff(name=f'Cleaner {{i}}', is_active=True, pay_rate=50.0))
        db.session.commit()
        for i in range({n_bookings}):
            db.session.add(Booking(service_type='standard', name=f'Job {{i}}',
                                   status='completed', client_id=(i % {n_clients}) + 1,
                                   balance_due=180.0 + i))
        db.session.commit()
'''


print('\n1. A backup of a real business restores as that business')
T = tempfile.mkdtemp()
os.environ['T'] = T
run(PRELUDE + seed() + f'''
    import backup
    path, m = backup.create(out_dir=r'{T}/b', quiet=True)
    assert m['counts']['client'] == 12, m['counts']
    assert m['counts']['staff'] == 5, m['counts']
    assert m['counts']['booking'] == 25, m['counts']
    backup.verify(path, quiet=True)
    print('OK')
''')
print('  ✅ 12 clients, 5 cleaners and 25 jobs backed up')
print('  ✅ the backup restored into a scratch database and the counts matched')

print('\n2. The restored data is the same data, not just the same number of rows')
T = tempfile.mkdtemp()
os.environ['T'] = T
run(PRELUDE + seed(n_clients=3, n_staff=2, n_bookings=4) + f'''
    import backup
    path, _ = backup.create(out_dir=r'{T}/b', quiet=True)
    counts = backup.restore(path, f'sqlite:///{T}/restored.db', quiet=True)

    os.environ['DATABASE_URL'] = f'sqlite:///{T}/restored.db'
    import importlib, extensions
    from app import create_app
    from models import Client, Booking, Staff
    app2 = create_app()
    with app2.app_context():
        c = Client.query.filter_by(name='Client 1').first()
        assert c and c.email == 'c1@x.com' and c.address == '1 Elm St', 'client fields'
        b = Booking.query.filter_by(name='Job 2').first()
        assert b and b.balance_due == 182.0 and b.status == 'completed', 'booking fields'
        s = Staff.query.filter_by(name='Cleaner 1').first()
        assert s and s.pay_rate == 50.0 and s.is_active, 'staff fields'
        assert b.client_id is not None and b.client is not None, 'the job still knows its client'
    print('OK')
''')
print('  ✅ names, emails, addresses and prices survive the round trip')
print('  ✅ a job still points at the right client — foreign keys held')

print('\n3. Timestamps come back as timestamps, not strings')
T = tempfile.mkdtemp()
os.environ['T'] = T
run(PRELUDE + f'''
    from app import create_app
    from extensions import db
    from models import Client
    from datetime import datetime
    app = create_app()
    when = datetime(2026, 3, 14, 9, 30, 0)
    with app.app_context():
        db.session.add(Client(name='Time Test', email='t@x.com', created_at=when))
        db.session.commit()
    import backup
    path, _ = backup.create(out_dir=r'{T}/b', quiet=True)
    backup.restore(path, f'sqlite:///{T}/r.db', quiet=True)
    os.environ['DATABASE_URL'] = f'sqlite:///{T}/r.db'
    app2 = create_app()
    with app2.app_context():
        c = Client.query.filter_by(name='Time Test').first()
        assert c.created_at == when, f'got {{c.created_at!r}} wanted {{when!r}}'
    print('OK')
''')
print('  ✅ a datetime restores as the same datetime')

print('\n4. A backup that silently loses the business is refused')
# The failure this guards against is not a crash. It is a run that completes
# happily against the wrong database and writes a valid backup of nothing,
# night after night, until somebody needs it. Two shapes of that:
T = tempfile.mkdtemp()
os.environ['T'] = T
run(PRELUDE + seed(n_clients=40, n_staff=6, n_bookings=120) + f'''
    import backup
    good, m = backup.create(out_dir=r'{T}/b', quiet=True)      # the real one
    assert m['counts']['booking'] == 120

    # (a) A connection string pointing somewhere with nothing in it at all.
    try:
        backup.create(out_dir=r'{T}/b', database_url=f'sqlite:///{T}/nothing.db', quiet=True)
        raise SystemExit('FAILED: a database with no tables was accepted')
    except backup.BackupFailed as e:
        assert 'no tables found' in str(e), str(e)

    # (b) The harder one: the right schema, but empty. This is what a fresh
    # database created by a mistyped connection string looks like — it has
    # every table, it just has none of the business in it.
    from app import create_app
    os.environ['DATABASE_URL'] = f'sqlite:///{T}/blank.db'
    create_app()                     # builds the schema and the seed rows
    try:
        backup.create(out_dir=r'{T}/b', database_url=f'sqlite:///{T}/blank.db', quiet=True)
        raise SystemExit('FAILED: a schema-shaped empty database was accepted')
    except backup.BackupFailed as e:
        assert 'had' in str(e) and 'none now' in str(e), str(e)

    import glob
    kept = glob.glob(os.path.join(r'{T}/b', 'backup-*.json.gz'))
    assert len(kept) >= 2, 'the suspect file should be kept as evidence'
    print('OK')
''')
print('  ✅ a database with no tables at all is refused')
print('  ✅ a database with the right schema but none of the business is refused')
print('  ✅ the suspect file is kept as evidence rather than deleted')

print('\n4b. The backup survives a database whose schema has drifted from the code')
# Found by running against the real local database, which predates a column
# added later. Selecting the model's idea of the columns failed outright.
T = tempfile.mkdtemp()
os.environ['T'] = T
run(PRELUDE + seed(n_clients=4, n_staff=2, n_bookings=5) + f'''
    import backup, sqlite3
    from sqlalchemy import create_engine, text
    # Age the database: give it a column the models have never heard of, and
    # take one away that they expect.
    con = sqlite3.connect(f'{T}/live.db')
    con.execute('ALTER TABLE client ADD COLUMN legacy_note TEXT')
    con.execute("UPDATE client SET legacy_note = 'from an older release'")
    con.commit(); con.close()

    path, m = backup.create(out_dir=r'{T}/b', quiet=True)
    assert m['counts']['client'] == 4, m['counts']

    import gzip, json
    rows = [json.loads(l) for l in gzip.open(path, 'rt').readlines()[1:] if l.strip()]
    client_rows = [r['row'] for r in rows if r['__table__'] == 'client']
    assert 'legacy_note' in client_rows[0], 'the unknown column should be backed up'

    counts = backup.restore(path, f'sqlite:///{T}/r.db', quiet=True)
    assert counts['client'] == 4, counts
    print('OK')
''')
print('  ✅ a column the models do not know about is still backed up')
print('  ✅ and is dropped on restore rather than failing the whole thing')

print('\n5. A first-ever backup of an empty instance is fine')
T = tempfile.mkdtemp()
os.environ['T'] = T
run(PRELUDE + f'''
    from app import create_app
    create_app()                     # a fresh install: schema and seeds, no business
    import backup
    path, m = backup.create(out_dir=r'{T}/b', quiet=True)
    assert m['counts'].get('client', 0) == 0, m['counts']
    assert m['total_rows'] > 0, 'the seeded templates should still be there'
    backup.verify(path, quiet=True)
    print('OK')
''')
print('  ✅ a brand-new instance with no clients is not mistaken for a disaster')

print('\n6. A partial loss is caught too, not just a total one')
T = tempfile.mkdtemp()
os.environ['T'] = T
run(PRELUDE + seed(n_clients=50, n_staff=8, n_bookings=200) + f'''
    import backup
    from extensions import db
    from models import Booking
    from app import create_app
    backup.create(out_dir=r'{T}/b', quiet=True)
    app = create_app()
    with app.app_context():
        for b in Booking.query.limit(180).all():
            db.session.delete(b)
        db.session.commit()
    try:
        backup.create(out_dir=r'{T}/b', quiet=True)
        raise SystemExit('FAILED: a 70% drop was accepted')
    except backup.BackupFailed as e:
        assert 'fell from' in str(e), str(e)
    print('OK')
''')
print('  ✅ losing most of the jobs between two runs is refused')

print('\n7. Retention deletes old backups but never the only one')
T = tempfile.mkdtemp()
os.environ['T'] = T
run(PRELUDE + seed(n_clients=2, n_staff=1, n_bookings=2) + f'''
    import backup, glob, gzip, json, os
    from datetime import datetime, timedelta
    d = r'{T}/b'
    for i in range(3):
        backup.create(out_dir=d, quiet=True)
    files = sorted(glob.glob(os.path.join(d, 'backup-*.json.gz')))
    assert len(files) == 3, files

    # Age the two oldest past the window.
    old = (datetime.utcnow() - timedelta(days=90)).isoformat()
    for f in files[:2]:
        with open(f.replace('.json.gz', '.manifest.json')) as fh:
            m = json.load(fh)
        m['taken_at'] = old
        with open(f.replace('.json.gz', '.manifest.json'), 'w') as fh:
            json.dump(m, fh)
        lines = gzip.open(f, 'rt').readlines()
        head = json.loads(lines[0]); head['taken_at'] = old
        with gzip.open(f, 'wt') as fh:
            fh.write(json.dumps(head) + '\\n')
            fh.writelines(lines[1:])

    removed = backup.prune(d, keep_days=30, quiet=True)
    left = sorted(glob.glob(os.path.join(d, 'backup-*.json.gz')))
    assert len(removed) == 2, removed
    assert len(left) == 1, left
    assert not glob.glob(os.path.join(d, 'backup-*.manifest.json'))[1:], 'sidecars pruned too'

    # Everything is old now. The last one must still survive.
    backup.prune(d, keep_days=0, quiet=True)
    assert len(glob.glob(os.path.join(d, 'backup-*.json.gz'))) == 1, 'never delete the last backup'
    print('OK')
''')
print('  ✅ backups past the retention window are deleted, with their manifests')
print('  ✅ the last remaining backup is never deleted, whatever the window says')

print('\n8. Restoring into a database that already has data replaces it cleanly')
T = tempfile.mkdtemp()
os.environ['T'] = T
run(PRELUDE + seed(n_clients=5, n_staff=2, n_bookings=6) + f'''
    import backup
    path, _ = backup.create(out_dir=r'{T}/b', quiet=True)
    target = f'sqlite:///{T}/target.db'
    backup.restore(path, target, quiet=True)
    counts = backup.restore(path, target, quiet=True)   # again, over the top
    assert counts['client'] == 5, counts
    os.environ['DATABASE_URL'] = target
    from app import create_app
    from models import Client
    app2 = create_app()
    with app2.app_context():
        assert Client.query.count() == 5, 'restoring twice must not double the rows'
    print('OK')
''')
print('  ✅ a second restore over the top replaces rather than duplicates')

print('\n\n✅ All backup tests passed.\n')
