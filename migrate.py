"""Schema changes that can be previewed, recorded, and undone.

## What this replaces, and why

`app._migrate_db()` is two hundred and ninety-one lines that try two hundred and
one `ALTER TABLE ... ADD COLUMN` statements on every single boot, each one
wrapped in `except: pass`.

It works, and it has worked for a year. The problem is not that it is untidy:

* **It cannot tell success from failure.** A column that already exists and a
  column that failed to be added for a real reason both arrive as an exception
  that is swallowed. The one time that distinction matters is the one time
  nobody will find out.
* **It keeps no record.** There is nowhere to look to answer "has this change
  been applied to this database", so the only strategy is to try everything,
  every time, forever.
* **It can only add columns.** Anything else — a type change, a rename, an index
  — sits in a second list of raw statements with the same blind `except: pass`.
* **There is no preview and no undo.** The first time anyone sees what a change
  does to real data is when it has already done it.

Two things are queued behind fixing that. Moving nineteen money columns from
floating point to decimal is a change to live financial data on every one of
those columns. And under one schema per customer, those two hundred and one
statements run against every business at once.

## How an existing database is adopted

The delicate part. A database that already has these tables must be told it is
up to date, not have the baseline run against it.

    no tables at all           -> create them, then stamp
    tables but no version row  -> stamp at baseline WITHOUT running it
    a version row              -> upgrade to head

The middle case is this business's own database, and every customer instance.
Getting it wrong means alembic tries to create thirty-seven tables that already
exist, so the check is deliberately conservative: any of the core tables being
present is taken as proof this is an established database.

## During this release only

`create_all()` and `_migrate_db()` still run first, exactly as before, and then
this stamps the result. Nothing about the schema changes on this deploy — the
only difference is that afterwards there is a row saying where the database is.
Once every instance has that row, the old machinery comes out. Adopting a
migration tool and changing the schema in the same release would mean two
suspects if anything went wrong.

## Using it

    python3 migrate.py status          # where is this database
    python3 migrate.py sql             # print the SQL, change nothing
    python3 migrate.py upgrade         # apply what is pending
    python3 migrate.py stamp           # record without running (adoption)
"""
import argparse
import os
import sys

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

ROOT = os.path.dirname(os.path.abspath(__file__))
BASELINE = '0001_baseline'

# Tables whose presence means this is an established database rather than an
# empty one. Any of them is enough; asking for all of them would misjudge a
# database that predates one of them.
ESTABLISHED_MARKERS = ('booking', 'client', 'staff', 'business_setting')


def _config():
    cfg = Config(os.path.join(ROOT, 'alembic.ini'))
    cfg.set_main_option('script_location', os.path.join(ROOT, 'migrations'))
    return cfg


def _engine():
    from sqlalchemy import create_engine
    import backup
    return create_engine(backup.normalise(os.environ.get('DATABASE_URL', '')))


def inspect_db(engine=None):
    """(has_tables, current_revision, head_revision) for this database."""
    from sqlalchemy import inspect as sa_inspect
    engine = engine or _engine()
    with engine.connect() as conn:
        names = set(sa_inspect(conn).get_table_names())
        has_tables = any(t in names for t in ESTABLISHED_MARKERS)
        current = MigrationContext.configure(conn).get_current_revision()
    head = ScriptDirectory.from_config(_config()).get_current_head()
    return has_tables, current, head


def status(quiet=False):
    has_tables, current, head = inspect_db()
    if not quiet:
        print(f'  tables present : {"yes" if has_tables else "no (empty database)"}')
        print(f'  at revision    : {current or "(not tracked yet)"}')
        print(f'  latest is      : {head}')
        if current == head:
            print('  → up to date')
        elif current is None and has_tables:
            print('  → established database, not yet adopted. Run: migrate.py stamp')
        elif current is None:
            print('  → new database. Run: migrate.py upgrade')
        else:
            print('  → behind. Run: migrate.py upgrade')
    return has_tables, current, head


def show_sql():
    """Print what an upgrade would do, without touching anything.

    The preview that did not exist before. On a change to money columns this is
    the difference between reading the statements first and finding out after.
    """
    has_tables, current, head = inspect_db()
    start = current or (BASELINE if has_tables else None)
    if start == head:
        print('  Nothing pending.')
        return
    command.upgrade(_config(), f'{start}:{head}' if start else head, sql=True)


def stamp(revision=None):
    """Record a database as being at a revision without running it."""
    command.stamp(_config(), revision or BASELINE)


def upgrade():
    """Bring the database to the latest revision, adopting it if needed."""
    command.upgrade(_config(), 'head')


def run_at_boot(app=None):
    """Called once from create_app(). Never raises.

    A database that cannot be migrated is a serious problem, but a CRM that
    refuses to start is a worse one: the owner loses every page, including the
    ones that would tell her what is wrong. So this reports loudly and lets the
    application come up.
    """
    try:
        has_tables, current, head = inspect_db()

        if current is None and has_tables:
            # An established database meeting alembic for the first time. Record
            # where it is; do NOT run the baseline against it.
            stamp(BASELINE)
            print(f'  ✅ database adopted into migrations at {BASELINE}')
            has_tables, current, head = inspect_db()

        if current == head:
            return True

        with _lock():
            upgrade()
        print(f'  ✅ database migrated {current or "(new)"} → {head}')
        return True
    except Exception as e:
        # Loud, and recorded where somebody will see it.
        print(f'  ⚠️  MIGRATION DID NOT RUN: {type(e).__name__}: {e}')
        try:
            import errors
            errors.capture(e, path='<startup migration>', method='BOOT')
        except Exception:
            pass
        return False


class _lock:
    """Stop two workers migrating at once.

    Railway starts several gunicorn workers from one image and they all call
    create_app(). Without this they race on the same ALTER TABLE. Postgres has
    advisory locks for exactly this; SQLite is one process and does not need it.
    """
    KEY = 0x0D2A2115          # arbitrary, but must not change between releases

    def __enter__(self):
        self.conn = None
        try:
            engine = _engine()
            if engine.dialect.name != 'postgresql':
                return self
            from sqlalchemy import text
            self.conn = engine.connect()
            self.conn.execute(text('SELECT pg_advisory_lock(:k)'), {'k': self.KEY})
            self.conn.commit()
        except Exception:
            self.conn = None
        return self

    def __exit__(self, *exc):
        if self.conn is not None:
            try:
                from sqlalchemy import text
                self.conn.execute(text('SELECT pg_advisory_unlock(:k)'), {'k': self.KEY})
                self.conn.commit()
                self.conn.close()
            except Exception:
                pass
        return False


def main():
    p = argparse.ArgumentParser(description='Schema migrations for this CRM.')
    p.add_argument('action', nargs='?', default='status',
                   choices=['status', 'sql', 'upgrade', 'stamp', 'history'])
    p.add_argument('--revision', help='for stamp: which revision to record')
    args = p.parse_args()

    url = os.environ.get('DATABASE_URL', '')
    import backup
    print(f'\nDatabase: {backup._safe_url(backup.normalise(url))}\n')

    if args.action == 'status':
        status()
    elif args.action == 'sql':
        show_sql()
    elif args.action == 'history':
        command.history(_config(), verbose=True)
    elif args.action == 'stamp':
        has_tables, current, _ = inspect_db()
        if current and not args.revision:
            print(f'  Already tracked, at {current}. Nothing to do.')
            return 0
        stamp(args.revision)
        print(f'  ✅ stamped at {args.revision or BASELINE}')
    elif args.action == 'upgrade':
        has_tables, current, head = inspect_db()
        if current is None and has_tables:
            print('  Established database — adopting at baseline first.')
            stamp(BASELINE)
        with _lock():
            upgrade()
        print('  ✅ up to date')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
