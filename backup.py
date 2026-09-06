"""Take a copy of the whole database, and prove it can be read back.

The business is in this database. Not a copy of the business — the business.
The client list, every job ever run, who cleaned it, what they were paid, the
access notes that say where the key is. Railway keeps it on one Postgres
instance, and until this file existed there was nothing anywhere else.

## What this makes

A single gzipped JSON file per run: every table, every row, in an order that can
be inserted back without tripping a foreign key. Not a `pg_dump` — deliberately.

`pg_dump` produces a better backup and needs the Postgres client tools installed
at the same major version as the server. That is one more thing to have working
on the day it matters, and the day it matters is the day everything else is on
fire. This needs nothing but Python, restores into Postgres or SQLite, and does
not care which version either of them is.

The schema is not in the backup. It comes from `models.py` via `create_all()`,
which means a backup taken in March restores into today's code and picks up
every column added since. A schema-carrying dump would fight that.

## Using it

    python3 backup.py                    # take one
    python3 backup.py --verify           # take one, then restore it and check
    python3 backup.py --list             # what we have
    python3 backup.py --restore FILE --into postgresql://...   # put it back

`--verify` is the one that matters. A backup nobody has restored is a file, not
a backup, and the difference only becomes apparent at the worst possible moment.
"""
import argparse
import base64
import datetime
import decimal
import glob
import gzip
import json
import os
import sys
import tempfile

# Format 2 carries a schema name on every row, so one file can hold the public
# schema and every tenant's. Format 1 files have no schema on their rows and
# restore into public, which is exactly where they came from.
FORMAT_VERSION = 2
DEFAULT_DIR = os.environ.get('BACKUP_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'backups')
DEFAULT_KEEP_DAYS = int(os.environ.get('BACKUP_KEEP_DAYS') or 30)

# The schema a single-business install lives in, and the one Akye keeps its
# company registry in.
PUBLIC = 'public'

# Akye gives every company its own PostgreSQL schema, named for its slug behind
# this prefix. Read out of the database rather than imported from tenancy.py so
# this file works unchanged on a branch that has no tenancy at all.
TENANT_PREFIX = 'tenant_'

# Tables whose loss would end the business, as opposed to being annoying. A
# backup that restores with any of these empty is treated as a failed backup,
# because an empty file is the classic silent failure: the run "succeeds",
# nobody looks, and the discovery happens during the restore.
CRITICAL_TABLES = ('client', 'booking', 'staff')

# Not business data, and actively wrong to carry across a restore.
#
# alembic_version records which schema revision a database is at. A backup's
# schema comes from models.py at restore time, not from the file, so restored
# data always lands on today's schema — copying last night's revision number in
# would tell the migration tool the database is behind when it is exactly up to
# date, and the next boot would try to "catch it up" over a schema that already
# matches. The restore stamps at head instead.
SKIP_TABLES = ('alembic_version',)


class _Encoder(json.JSONEncoder):
    """Types SQLAlchemy hands back that JSON has no opinion about."""

    def default(self, o):
        if isinstance(o, (datetime.datetime, datetime.date, datetime.time)):
            return {'__t__': 'dt', 'v': o.isoformat()}
        if isinstance(o, datetime.timedelta):
            return {'__t__': 'td', 'v': o.total_seconds()}
        if isinstance(o, decimal.Decimal):
            return {'__t__': 'dec', 'v': str(o)}
        if isinstance(o, (bytes, bytearray)):
            return {'__t__': 'b64', 'v': base64.b64encode(bytes(o)).decode()}
        return super().default(o)


def _revive(value):
    if isinstance(value, dict) and '__t__' in value:
        kind, v = value['__t__'], value['v']
        if kind == 'dt':
            for parse in (datetime.datetime.fromisoformat,
                          datetime.date.fromisoformat,
                          datetime.time.fromisoformat):
                try:
                    return parse(v)
                except (ValueError, AttributeError):
                    continue
            return v
        if kind == 'td':
            return datetime.timedelta(seconds=v)
        if kind == 'dec':
            return decimal.Decimal(v)
        if kind == 'b64':
            return base64.b64decode(v)
    return value


def _revive_row(row):
    return {k: _revive(v) for k, v in row.items()}


# ---------------------------------------------------------------------------

def normalise(url):
    """The same URL rewriting create_app() does, so both reach one database."""
    if not url or url.startswith('$') or '://' not in url:
        url = 'sqlite:///crm.db'
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    if url.startswith('postgresql://') and '+psycopg2' not in url:
        url = url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    return url


def _read_engine(database_url=None):
    """A plain connection to the source database. Reads, and only reads.

    Emphatically NOT create_app(). Booting the application runs create_all(),
    then _migrate_db(), then a dozen seed functions — so using it here would
    mean the act of backing up a database altered the database being backed up,
    and the first thing to touch a damaged production database during an
    incident would be a migration nobody asked for.

    A backup must be able to read a database it is not allowed to change, and a
    database whose schema is older or newer than this checkout.
    """
    from sqlalchemy import create_engine
    url = normalise(database_url or os.environ.get('DATABASE_URL', ''))
    return create_engine(url)


def _app(database_url=None):
    """Boot the application — used only for RESTORE, which needs the schema
    built from models.py."""
    if database_url:
        os.environ['DATABASE_URL'] = database_url
    os.environ.setdefault('SECRET_KEY', 'backup-tool')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # Nothing here should send a text message or an email because a restore ran.
    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'backup-stub')
    notifications.send_email = lambda *a, **k: (True, 'backup-stub')
    from app import create_app
    return create_app()


def _safe_url(url):
    """A connection string with the password removed, for printing."""
    if not url or '@' not in url:
        return url or '(unset)'
    head, tail = url.rsplit('@', 1)
    if ':' in head:
        scheme_user = head.rsplit(':', 1)[0]
        return f'{scheme_user}:***@{tail}'
    return f'{head}@{tail}'


def tenant_schemas(engine):
    """Every company schema in this database, in a stable order.

    Empty for a single-business install and for SQLite, which has no schemas —
    so everything downstream behaves exactly as it did before Akye existed.

    This is asked of the database rather than of a company registry table on
    purpose. A schema holding a company's data is a thing to back up whether or
    not a row somewhere still lists it; the registry is what we would lose.
    """
    from sqlalchemy import inspect
    try:
        names = inspect(engine).get_schema_names()
    except Exception:
        return []                       # SQLite, or a server that will not say
    return sorted(n for n in names if n.startswith(TENANT_PREFIX))


def _reflect(engine, schema):
    """The tables in one schema, parents before children."""
    from sqlalchemy import MetaData
    md = MetaData()
    md.reflect(bind=engine, schema=None if schema == PUBLIC else schema)
    return [t for t in md.sorted_tables if t.name not in SKIP_TABLES]


def create(out_dir=DEFAULT_DIR, database_url=None, quiet=False):
    """Dump every table. Returns (path, manifest).

    Reads the schema out of the database itself rather than out of models.py.
    The two drift — a column added last week is in the models and not yet in an
    instance that has not redeployed, and a column dropped last year may still
    be sitting in somebody's table. Selecting the model's idea of the columns
    fails outright on the first mismatch, which is a poor reason to have no
    backup. Whatever is actually in there is what gets copied.
    """
    engine = _read_engine(database_url)
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%SZ')
    path = os.path.join(out_dir, f'backup-{stamp}.json.gz')
    # The name is only accurate to the second, so a manual run started moments
    # after the scheduled one would land on the same filename and quietly
    # replace it. Losing a backup to a naming collision is a silly way to lose
    # a backup.
    n = 1
    while os.path.exists(path):
        path = os.path.join(out_dir, f'backup-{stamp}-{n}.json.gz')
        n += 1

    counts = {}
    tenant_counts = {}
    url = str(engine.url)
    if not quiet:
        print(f'  reading  {_safe_url(url)}')

    # sorted_tables is already in foreign-key order — parents before the rows
    # that point at them. Restoring in this order needs no deferred constraints
    # and no disabling of anything.
    #
    # public first, then a company at a time. Every company gets the same table
    # set, so this used to look like one schema's worth of work; reading only
    # the first one is precisely the bug this loop exists to prevent.
    schemas = [PUBLIC] + tenant_schemas(engine)
    by_schema = {s: _reflect(engine, s) for s in schemas}

    if not any(by_schema.values()):
        raise BackupFailed(f'no tables found in {_safe_url(url)} — '
                           'is the connection string pointing at the right database?')

    with gzip.open(path, 'wt', encoding='utf-8') as fh:
        fh.write(json.dumps({
            'format': FORMAT_VERSION,
            'taken_at': datetime.datetime.utcnow().isoformat(),
            'schemas': schemas,
            'tables': [t.name for t in by_schema[PUBLIC]],
            'tenant_tables': {s: [t.name for t in by_schema[s]]
                              for s in schemas if s != PUBLIC},
            'source': _safe_url(url),
            'release': _release(),
        }) + '\n')
        with engine.connect() as conn:
            for schema in schemas:
                if schema != PUBLIC:
                    tenant_counts[schema] = {}
                    if not quiet:
                        print(f'    {schema}')
                for table in by_schema[schema]:
                    n = 0
                    for row in conn.execute(table.select()).mappings():
                        fh.write(json.dumps(
                            {'__schema__': schema, '__table__': table.name,
                             'row': dict(row)},
                            cls=_Encoder) + '\n')
                        n += 1
                    if schema == PUBLIC:
                        counts[table.name] = n
                    else:
                        tenant_counts[schema][table.name] = n
                    if n and not quiet:
                        pad = '      ' if schema != PUBLIC else '    '
                        print(f'{pad}{table.name:<28} {n:>7}')

    size = os.path.getsize(path)
    tenant_rows = sum(sum(t.values()) for t in tenant_counts.values())
    manifest = {'path': path, 'bytes': size, 'counts': counts,
                'tenants': sorted(tenant_counts),
                'tenant_counts': tenant_counts,
                'tenant_rows': tenant_rows,
                'total_rows': sum(counts.values()) + tenant_rows,
                'taken_at': datetime.datetime.utcnow().isoformat()}

    previous = _previous_manifest(out_dir)
    problems = _sanity_check(manifest, previous)

    # Written even when the checks fail, so the next run can see what happened
    # and so --list does not have to decompress every file to say anything.
    with open(path.replace('.json.gz', '.manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=2)

    if problems:
        # Leave the file. A suspicious backup is still evidence, and deleting
        # it would remove the only thing that shows what went wrong.
        raise BackupFailed('; '.join(problems) + f' (kept at {path})')

    if not quiet:
        print(f'  ✅ {os.path.basename(path)} — '
              f'{manifest["total_rows"]:,} rows, {size / 1024:.0f} KB')
    return path, manifest


class BackupFailed(Exception):
    pass


def _previous_manifest(out_dir):
    """The manifest from the last successful run, or None on the first ever."""
    files = sorted(glob.glob(os.path.join(out_dir, 'backup-*.manifest.json')))
    if not files:
        return None
    try:
        with open(files[-1]) as fh:
            return json.load(fh)
    except Exception:
        return None


# How much of the database may disappear between two runs before this is
# treated as a broken backup rather than a quiet week. A cleaning company does
# not delete a third of its history by accident, so anything at this scale is
# either a bad connection string, a truncated read, or something that needs a
# human before it silently overwrites the good copy behind it.
MAX_SHRINK = 0.34


def _sanity_check(manifest, previous=None):
    """Reasons to distrust a backup that otherwise looks like it worked.

    The failure this is really guarding against is not an exception — those are
    loud. It is a run that completes happily against an empty or wrong database
    and writes a perfectly valid backup of nothing, night after night, until
    somebody needs it.

    A single backup cannot tell the difference between "no clients yet" and
    "the clients are gone", so the test is always against the previous run. A
    brand-new instance with nothing in it passes; an instance that had four
    hundred clients yesterday and none today does not.
    """
    out = []
    if manifest['bytes'] < 200:
        out.append(f'file is only {manifest["bytes"]} bytes')

    # Where the business tables live depends on the product: a single-business
    # install keeps them in public, and Akye keeps a set per company. Either
    # way they have to be SOMEWHERE, and the check has to be able to run on the
    # very first backup — comparing against last night cannot notice a table
    # that has never once been read, which is how a backup of the wrong schema
    # stays green forever instead of failing the night it is set up.
    tenants = manifest.get('tenants') or []
    if tenants:
        for schema in tenants:
            have = set(manifest.get('tenant_counts', {}).get(schema, {}))
            missing = [t for t in CRITICAL_TABLES if t not in have]
            if missing:
                out.append(f'{schema} has no {", ".join(missing)} table — '
                           'is this backup reading the whole schema?')
    else:
        have = set(manifest.get('counts', {}))
        missing = [t for t in CRITICAL_TABLES if t not in have]
        if missing and have:
            out.append(f'no {", ".join(missing)} table in this database — '
                       'if it is a multi-company database, no company schema '
                       'was found, and the businesses in it are NOT backed up')

    if not previous:
        return out                      # first run — nothing to compare against

    # A company that existed last night and has no schema tonight is either a
    # cancellation somebody did on purpose or a database that is quietly losing
    # companies. Worth a human either way.
    gone = set(previous.get('tenants') or []) - set(tenants)
    if gone:
        out.append(f'{len(gone)} company schema(s) present last time and gone '
                   f'now: {", ".join(sorted(gone))}')

    before, now = previous.get('total_rows', 0), manifest['total_rows']
    if before > 0 and now == 0:
        out.append(f'every row vanished — {before:,} rows last time, none now')
    elif before > 20 and now < before * (1 - MAX_SHRINK):
        out.append(f'row count fell from {before:,} to {now:,} '
                   f'({100 * (1 - now / before):.0f}% of the database)')

    for table in CRITICAL_TABLES:
        was = previous.get('counts', {}).get(table, 0)
        has = manifest['counts'].get(table, 0)
        if was > 0 and has == 0:
            out.append(f'{table} had {was:,} rows last time and none now')
    return out


def _release():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'RELEASE')) as fh:
            return fh.readline().strip()
    except Exception:
        return ''


# ---------------------------------------------------------------------------

def read_manifest(path):
    with gzip.open(path, 'rt', encoding='utf-8') as fh:
        return json.loads(fh.readline())


def restore(path, into_url, quiet=False):
    """Load a backup into a database. Returns per-table row counts.

    The target's tables are created from the current models and emptied first,
    so restoring into a database that already holds data replaces it. That is
    destructive on purpose and guarded by the caller, not here.
    """
    from extensions import db
    app = _app(into_url)
    counts = {}
    header = read_manifest(path)
    with app.app_context():
        url = str(db.engine.url)
        if not quiet:
            print(f'  writing  {_safe_url(url)}')
        db.create_all()

        # One table set per schema in the file. A company's schema is rebuilt
        # from today's models exactly as public is, so a company restores onto
        # the current schema rather than the one it was dumped from.
        known = {PUBLIC: {t.name: t for t in db.metadata.sorted_tables}}
        order = {PUBLIC: list(db.metadata.sorted_tables)}
        for schema in header.get('schemas') or [PUBLIC]:
            if schema == PUBLIC:
                continue
            tables = _build_schema(db, schema, url, quiet=quiet)
            if tables is None:
                continue
            known[schema] = {t.name: t for t in tables}
            order[schema] = tables

        dropped_tables, dropped_columns = set(), {}
        with db.engine.begin() as conn:
            # Children first, so nothing is left pointing at a deleted parent.
            for schema in order:
                for table in reversed(order[schema]):
                    conn.execute(table.delete())
            batch, current, current_schema = [], None, PUBLIC

            def flush():
                if batch and current is not None:
                    conn.execute(known[current_schema][current].insert(), batch)

            with gzip.open(path, 'rt', encoding='utf-8') as fh:
                fh.readline()   # manifest
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    name = rec['__table__']
                    # Format 1 files have no schema on their rows. They came
                    # out of public and that is where they go back.
                    schema = rec.get('__schema__', PUBLIC)
                    if schema not in known or name not in known[schema]:
                        # A table that existed when the backup was taken and
                        # does not exist now. Skipped rather than fatal: the
                        # point of a restore is to get the business back, not
                        # to be right about a table nobody uses any more.
                        dropped_tables.add(name if schema == PUBLIC
                                           else f'{schema}.{name}')
                        continue
                    if name != current or schema != current_schema:
                        flush()
                        batch, current, current_schema = [], name, schema
                    # Same argument one level down. A backup from before a
                    # column was removed still carries it, and a restore that
                    # refused the whole file over one dead column would be a
                    # restore that did not happen.
                    cols = set(known[schema][name].columns.keys())
                    row = _revive_row(rec['row'])
                    extra = set(row) - cols
                    if extra:
                        dropped_columns.setdefault(name, set()).update(extra)
                        row = {k: v for k, v in row.items() if k in cols}
                    batch.append(row)
                    key = name if schema == PUBLIC else f'{schema}.{name}'
                    counts[key] = counts.get(key, 0) + 1
                    if len(batch) >= 500:
                        conn.execute(known[schema][name].insert(), batch)
                        batch = []
            flush()
        for schema, tables in order.items():
            _fix_sequences(db, conn_url=url, tables=tables, schema=schema)
        _stamp_schema()
    if not quiet:
        print(f'  ✅ restored {sum(counts.values()):,} rows'
              + (f' across {len(order)} schemas' if len(order) > 1 else ''))
        # Said out loud rather than swallowed. Skipping these is the right
        # call, but it is still data in the backup that is not in the restore,
        # and the person running it should hear that from the tool and not
        # discover it later.
        for name in sorted(dropped_tables):
            print(f'  ⚠️  table "{name}" is in the backup but not in this '
                  f'version of the app — skipped')
        for name, cols in sorted(dropped_columns.items()):
            print(f'  ⚠️  {name}: dropped column(s) {", ".join(sorted(cols))} '
                  f'— not in this version of the app')
    return counts



def _build_schema(db, schema, url, quiet=False):
    """Recreate one company's schema from today's models. Tables, in FK order.

    Returns None when the target cannot hold schemas at all — restoring an Akye
    backup into SQLite gets the registry and says so, rather than failing.
    """
    if not url.startswith('postgres'):
        if not quiet:
            print(f'  ⚠️  {schema}: target is not PostgreSQL and has no '
                  f'schemas — this company was NOT restored')
        return None
    from sqlalchemy import MetaData, text
    md = MetaData()
    for table in db.metadata.sorted_tables:
        table.to_metadata(md, schema=schema)
    with db.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    md.create_all(bind=db.engine)
    return list(md.sorted_tables)


def _stamp_schema():
    """Record the restored database as being on today's schema.

    The tables were just built from models.py, so that is where this data now
    lives regardless of which revision the backup was taken under. Without this
    a restored database has no version row at all and the next boot would treat
    it as a pre-migrations database — which is harmless, but leaves it looking
    unadopted when it is not."""
    try:
        import migrate
        migrate.stamp(migrate.ScriptDirectory.from_config(
            migrate._config()).get_current_head())
    except Exception:
        pass          # a restore that worked must not fail over bookkeeping


def _fix_sequences(db, conn_url='', tables=None, schema=PUBLIC):
    """Postgres remembers the next id per table in a sequence, and inserting
    explicit ids does not move it. Without this the restore looks perfect and
    then the first new booking collides with an id that already exists.

    Every company schema has its own sequences, so this runs once per schema —
    fixing only public would leave every company on Akye handing out ids that
    already exist, which is the same bug multiplied by the customer list."""
    if not conn_url.startswith('postgres'):
        return
    from sqlalchemy import text
    qualified = f'"{schema}".' if schema != PUBLIC else ''
    with db.engine.begin() as conn:
        for table in (db.metadata.sorted_tables if tables is None else tables):
            for col in table.primary_key.columns:
                if not (col.autoincrement and str(col.type).upper().startswith('INT')):
                    continue
                # Quote both identifiers. "user" is a reserved word in
                # Postgres, so SELECT MAX(id) FROM user is a syntax error and
                # the whole restore stops there -- on the one table holding the
                # logins, and only ever on Postgres. The drill that proved this
                # tool works restored into SQLite, where "user" is ordinary, so
                # the disaster-recovery path had never actually been run
                # against the kind of database it exists to recover.
                conn.execute(text(
                    'SELECT setval(pg_get_serial_sequence(:t, :c), '
                    'COALESCE((SELECT MAX("%s") FROM %s"%s"), 1), true)'
                    % (col.name, qualified, table.name)
                ), {'t': f'{schema}.{table.name}', 'c': col.name})


def verify(path, quiet=False, scratch_url=None):
    """Restore into a throwaway database and check it came back whole.

    This is the whole point of the file. Everything above it produces a
    plausible-looking artefact; this is the only part that finds out whether
    the artefact is any good, and it runs on every scheduled backup so the
    answer is never more than a day old.
    """
    manifest = read_manifest(path)
    tenants = [s for s in (manifest.get('schemas') or []) if s != PUBLIC]

    # SQLite is a fine scratch database for a single business and cannot hold a
    # multi-company one at all — it has no schemas. Verifying an Akye backup
    # against it would drop every company and call the difference a failure, so
    # a real PostgreSQL scratch database is required and its absence is an
    # error rather than a reason to check less.
    scratch_url = scratch_url or os.environ.get('BACKUP_VERIFY_URL') or ''
    if tenants and not scratch_url.startswith('postgres'):
        raise BackupFailed(
            f'this backup holds {len(tenants)} company schema(s) and can only '
            'be verified against PostgreSQL. Set BACKUP_VERIFY_URL to a '
            'throwaway Postgres database.')
    if not scratch_url:
        scratch_url = 'sqlite:///' + os.path.join(tempfile.mkdtemp(), 'verify.db')

    counts = restore(path, scratch_url, quiet=True)

    expected = {}
    with gzip.open(path, 'rt', encoding='utf-8') as fh:
        fh.readline()
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                schema = rec.get('__schema__', PUBLIC)
                name = rec['__table__']
                key = name if schema == PUBLIC else f'{schema}.{name}'
                expected[key] = expected.get(key, 0) + 1

    problems = []
    for name, n in expected.items():
        got = counts.get(name, 0)
        if got != n:
            problems.append(f'{name}: backed up {n}, restored {got}')
    # Checked per company, not just in public. On Akye the critical tables are
    # never in public at all, so a check that only looked there would pass by
    # looking at nothing.
    for schema in [PUBLIC] + tenants:
        for name in CRITICAL_TABLES:
            key = name if schema == PUBLIC else f'{schema}.{name}'
            if expected.get(key, 0) and not counts.get(key, 0):
                problems.append(f'{key} did not restore at all')

    if problems:
        raise BackupFailed('restore did not match the backup: ' + '; '.join(problems))
    if not quiet:
        total = sum(expected.values())
        print(f'  ✅ verified — {total:,} rows restored and counted back, '
              f'across {len(expected)} tables')
    return True, manifest


# ---------------------------------------------------------------------------

def prune(out_dir=DEFAULT_DIR, keep_days=DEFAULT_KEEP_DAYS, quiet=False):
    """Delete backups older than the retention window — but never the last one.

    A retention rule that can empty the directory is a retention rule that will,
    the first time backups quietly stop running and the clock keeps going."""
    files = sorted(glob.glob(os.path.join(out_dir, 'backup-*.json.gz')))
    if len(files) <= 1:
        return []
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=keep_days)
    removed = []
    for path in files[:-1]:
        try:
            taken = datetime.datetime.fromisoformat(read_manifest(path)['taken_at'])
        except Exception:
            taken = datetime.datetime.utcfromtimestamp(os.path.getmtime(path))
        if taken < cutoff:
            os.remove(path)
            sidecar = path.replace('.json.gz', '.manifest.json')
            if os.path.exists(sidecar):
                os.remove(sidecar)
            removed.append(os.path.basename(path))
    if removed and not quiet:
        print(f'  pruned {len(removed)} backup(s) older than {keep_days} days')
    return removed


def listing(out_dir=DEFAULT_DIR):
    files = sorted(glob.glob(os.path.join(out_dir, 'backup-*.json.gz')))
    if not files:
        print(f'No backups in {out_dir}.')
        return
    print(f'{len(files)} backup(s) in {out_dir}:\n')
    for path in files:
        rows = ''
        try:
            with open(path.replace('.json.gz', '.manifest.json')) as fh:
                m = json.load(fh)
            rows = f'{m.get("total_rows", 0):>9,} rows'
        except Exception:
            m = {}
        try:
            taken = (m.get('taken_at') or read_manifest(path).get('taken_at', '?'))
            taken = taken[:19].replace('T', ' ')
        except Exception:
            taken = '(unreadable)'
        kb = os.path.getsize(path) / 1024
        print(f'  {os.path.basename(path):<40} {taken}  {rows}  {kb:>8.0f} KB')


# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description='Back the database up, and check it restores.')
    p.add_argument('--verify', action='store_true',
                   help='after backing up, restore it into a scratch database and check')
    p.add_argument('--verify-only', metavar='FILE', help='check an existing backup')
    p.add_argument('--list', action='store_true', help='list backups')
    p.add_argument('--restore', metavar='FILE', help='restore this backup')
    p.add_argument('--into', metavar='URL',
                   help='database to restore into — REQUIRED with --restore')
    p.add_argument('--yes', action='store_true', help='skip the restore confirmation')
    p.add_argument('--dir', default=DEFAULT_DIR, help=f'where backups live (default {DEFAULT_DIR})')
    p.add_argument('--database-url', help='database to read (default: DATABASE_URL)')
    p.add_argument('--keep-days', type=int, default=DEFAULT_KEEP_DAYS)
    args = p.parse_args()

    if args.list:
        listing(args.dir)
        return 0

    if args.verify_only:
        print(f'\nVerifying {os.path.basename(args.verify_only)}')
        try:
            verify(args.verify_only)
            return 0
        except BackupFailed as e:
            print(f'  ❌ {e}')
            return 1

    if args.restore:
        if not args.into:
            print('--restore needs --into. Refusing to guess which database to overwrite.')
            return 2
        print(f'\nThis DELETES everything in {_safe_url(args.into)} and replaces it')
        print(f'with {os.path.basename(args.restore)}.')
        if not args.yes:
            if input('Type RESTORE to continue: ').strip() != 'RESTORE':
                print('Nothing was changed.')
                return 1
        restore(args.restore, args.into)
        print('\n  Check the app before telling anyone it is back.\n')
        return 0

    print(f'\nBacking up  →  {args.dir}')
    try:
        path, manifest = create(args.dir, args.database_url)
    except BackupFailed as e:
        print(f'  ❌ backup failed sanity checks: {e}')
        return 1
    except Exception as e:
        print(f'  ❌ backup failed: {type(e).__name__}: {e}')
        return 1

    if args.verify:
        try:
            verify(path)
        except BackupFailed as e:
            print(f'  ❌ {e}')
            return 1

    prune(args.dir, args.keep_days)
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
