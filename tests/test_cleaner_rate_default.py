"""A new company starts paying cleaners $25 an hour; nobody else's pay moves.

$25 is what a cleaner costs and $43 read like a price, so the starting rate
(pricing.LABOR_RATE_DEFAULT) came down. A company that never saved its own
rate was paying the default, so migration 0036 writes $43 down for every
company already in use before the default moves under it.

Against a disposable Postgres, migrating real company schemas.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fresh_postgres
os.environ.update(DATABASE_URL=fresh_postgres.url('akye_cleaner_rate_test'),
                  SECRET_KEY='cleaner-rate-test', BASE_DOMAIN='akye.test',
                  FLASK_ENV='development')

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app import create_app
from extensions import db
import pricing
import provisioning
import tenancy

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


app = create_app()
engine = provisioning._engine()


def downgrade_to_0035(slug):
    cfg = Config(os.path.join(ROOT, 'alembic.ini'))
    cfg.set_main_option('script_location', os.path.join(ROOT, 'migrations'))
    cfg.attributes['tenant_schema'] = tenancy.schema_for(slug)
    with tenancy.use_tenant(tenancy.schema_for(slug)):
        command.downgrade(cfg, '0035_commercial_jobs')


def sql(slug, statement, **params):
    with engine.begin() as conn:
        conn.execute(text(f'SET search_path TO "{tenancy.schema_for(slug)}"'))
        return conn.execute(text(statement), params)


def rate(slug):
    with app.app_context(), tenancy.use_tenant(slug):
        try:
            return pricing.get_labor_rate()
        finally:
            db.session.remove()


with app.app_context():
    for slug in ('ratenew', 'rateold', 'ratesaved'):
        provisioning.provision(slug, slug.title(), f'{slug}@rate.test', quiet=True)
    db.session.remove()

print('\n1. A company created now starts at $25')
check(pricing.LABOR_RATE_DEFAULT == 25, 'the starting rate is $25')
check(rate('ratenew') == 25, f'a brand-new company pays ${rate("ratenew"):.0f}/hr')
check(sql('ratenew', "SELECT count(*) FROM pricing_setting WHERE key='labor_rate'").scalar() == 0,
      'nothing is written for it: it reads the default')

print('\n2. A company already in use keeps the $43 it was paying')
for slug in ('rateold', 'ratesaved'):
    sql(slug, 'INSERT INTO "user" (username, password_hash, role, name, active) '
              "VALUES (:u, 'x', 'owner', 'Owner', true)", u=f'{slug}-owner')
sql('ratesaved', "INSERT INTO pricing_setting (key, value) VALUES ('labor_rate', '30')")
for slug in ('rateold', 'ratesaved'):
    downgrade_to_0035(slug)
    provisioning.migrate_schema(engine, tenancy.schema_for(slug))
check(rate('rateold') == 43, f'an existing company that never set a rate stays at ${rate("rateold"):.0f}/hr')
check(rate('ratesaved') == 30, f'one that saved its own rate keeps it (${rate("ratesaved"):.0f}/hr)')
downgrade_to_0035('rateold')
provisioning.migrate_schema(engine, tenancy.schema_for('rateold'))
check(sql('rateold', "SELECT count(*) FROM pricing_setting WHERE key='labor_rate'").scalar() == 1,
      'running it again writes nothing twice')

print('\n3. Restoring a backup applies the same rule')
import gzip
import json
import tempfile
import backup
from sqlalchemy import create_engine

# Brand new since the change, now in use, and never saved a rate: $25.
sql('ratenew', 'INSERT INTO "user" (username, password_hash, role, name, active) '
               "VALUES ('ratenew-owner', 'x', 'owner', 'Owner', true)")
out = tempfile.mkdtemp()
path, manifest = backup.create(out_dir=out, database_url=os.environ['DATABASE_URL'], quiet=True)
header = backup.read_manifest(path)
from alembic.config import Config as _AlembicConfig
from alembic.script import ScriptDirectory as _ScriptDirectory
_head = _ScriptDirectory.from_config(_AlembicConfig('alembic.ini')).get_current_head()
check(header.get('revisions', {}).get(tenancy.schema_for('ratenew')) == _head,
      'a backup records the migration each company was on')
scratch_url = fresh_postgres.url('akye_cleaner_rate_restore')


def restored_rate(slug):
    e = create_engine(scratch_url)
    try:
        with e.connect() as conn:
            conn.execute(text(f'SET search_path TO "{tenancy.schema_for(slug)}"'))
            v = conn.execute(text("SELECT value FROM pricing_setting WHERE key='labor_rate'")).scalar()
    finally:
        e.dispose()
    return float(v) if v is not None else pricing.LABOR_RATE_DEFAULT


backup.restore(path, scratch_url, quiet=True)
check(restored_rate('ratenew') == 25 and restored_rate('rateold') == 43 and restored_rate('ratesaved') == 30,
      'a backup taken since: every company restores at the rate it had ($25, $43, $30)')

# The same backup as one taken before this release: no revisions recorded.
old_path = os.path.join(out, 'before-0036.json.gz')
with gzip.open(path, 'rt', encoding='utf-8') as fh:
    lines = fh.readlines()
first = json.loads(lines[0]); first.pop('revisions', None); lines[0] = json.dumps(first) + '\n'
with gzip.open(old_path, 'wt', encoding='utf-8') as fh:
    fh.writelines(lines)
scratch_url = fresh_postgres.url('akye_cleaner_rate_restore')
backup.restore(old_path, scratch_url, quiet=True)
check(restored_rate('ratenew') == 43,
      'a backup from before it: a company in use with no saved rate restores at the $43 it paid')
check(restored_rate('ratesaved') == 30, 'and a saved rate is still never touched')

if failures:
    print(f'\n❌ {len(failures)} failed')
    sys.exit(1)
print('\n✅ New companies start at $25; existing cleaners are paid what they were.')
