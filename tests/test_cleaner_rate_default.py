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

if failures:
    print(f'\n❌ {len(failures)} failed')
    sys.exit(1)
print('\n✅ New companies start at $25; existing cleaners are paid what they were.')
