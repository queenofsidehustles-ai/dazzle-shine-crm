"""Can one company see another company's business? It must never be able to.

This suite exists for one failure. Everything else in this repository can be
wrong and recovered from; a cleaning company opening its CRM and reading a
competitor's client list, home addresses and payroll is the one that ends the
product and possibly the business.

So these are written adversarially. They do not check that the happy path
works. They try to get at data they should not have, by the routes a real
failure would take: a pooled connection carrying the previous company's schema,
a request that forgot to resolve, a background job with no tenant in context, a
subdomain crafted to escape.

Needs a real PostgreSQL — schemas do not exist in SQLite, so none of this can be
tested there. Skips cleanly if there is none, and says so rather than passing
quietly, because a test that silently does not run is worse than no test.
"""
import os, sys, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


# ---------------------------------------------------------------------------
# Hostname parsing needs no database at all
# ---------------------------------------------------------------------------
import tenancy

print('\n1. Which company a web address belongs to')
for host, base, want in [
    ('acme.rollcall.com', 'rollcall.com', 'acme'),
    ('sparkle-pros.rollcall.com', 'rollcall.com', 'sparkle-pros'),
    ('rollcall.com', 'rollcall.com', None),
    ('www.rollcall.com', 'rollcall.com', None),
    ('ACME.RollCall.COM', 'rollcall.com', 'acme'),
    ('acme.rollcall.com:443', 'rollcall.com', 'acme'),
    # Someone else's domain that merely ends in similar text must not resolve.
    ('acme.notrollcall.com', 'rollcall.com', None),
    ('evil.com', 'rollcall.com', None),
    # The instance running today, and local development.
    ('dazzle-shine-crm-production.up.railway.app', None, None),
    ('localhost', None, None),
    ('localhost:5000', None, None),
    ('127.0.0.1', None, None),
    ('', None, None),
    (None, None, None),
]:
    got = tenancy.slug_from_host(host, base)
    check(got == want, f'{host!r} → {got!r}')

print('\n2. Reserved and malformed addresses are refused')
for bad in ('www', 'api', 'admin', 'public', 'billing', 'login', 'a', 'ab',
            '-acme', 'acme-', 'ACME', 'ac me', 'acme.evil', 'acme;drop',
            "acme'--", 'a' * 45, ''):
    check(not tenancy.valid_slug(bad), f'{bad!r} is not a usable address')
for good in ('acme', 'sparkle-pros', 'a1b2', 'dazzle-and-shine'):
    check(tenancy.valid_slug(good), f'{good!r} is usable')

print('\n3. A slug can never become part of a SQL identifier it should not')
# The schema name is derived only from a slug that passed valid_slug, so this
# is belt and braces -- but it is the one place a name reaches raw SQL.
import re
for good in ('acme', 'sparkle-pros', 'a1b2'):
    schema = tenancy.schema_for(good)
    check(bool(re.match(r'^tenant_[a-z0-9_]+$', schema)),
          f'{good!r} → {schema!r}, which is a safe identifier')

print('\n4. With no company in context, everything is public — as it always was')
check(tenancy.current_schema() == 'public', 'the default is public')
check(tenancy.is_tenant() is False, 'and that is not a tenant request')
with tenancy.use_tenant('acme'):
    check(tenancy.current_schema() == 'tenant_acme', 'inside a block it is the company')
    check(tenancy.is_tenant() is True, 'and that is a tenant request')
check(tenancy.current_schema() == 'public', 'and it goes back afterwards')

print('\n5. Nesting and exceptions cannot strand a thread on the wrong company')
with tenancy.use_tenant('acme'):
    with tenancy.use_tenant('baker'):
        check(tenancy.current_schema() == 'tenant_baker', 'the inner one wins')
    check(tenancy.current_schema() == 'tenant_acme', 'and unwinds to the outer')
check(tenancy.current_schema() == 'public', 'and back to public')

try:
    with tenancy.use_tenant('acme'):
        raise RuntimeError('something went wrong mid-request')
except RuntimeError:
    pass
check(tenancy.current_schema() == 'public',
      'an exception inside a company block still restores public')


# ---------------------------------------------------------------------------
# The rest needs PostgreSQL
# ---------------------------------------------------------------------------
def postgres_url():
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres'):
        if not candidate:
            continue
        try:
            from sqlalchemy import create_engine, text
            e = create_engine(candidate)
            with e.connect() as c:
                c.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n' + '=' * 70)
    print('  ⚠️  SKIPPED: the isolation tests need PostgreSQL and found none.')
    print('     Schemas do not exist in SQLite, so nothing below can be checked')
    print('     there. Install with: brew install postgresql@16')
    print('=' * 70 + '\n')
    sys.exit(0)

DB = 'dsm_tenancy_test'
base = PG.rsplit('/', 1)[0]
TEST_URL = f'{base}/{DB}'

from sqlalchemy import create_engine, text
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as c:
    c.execute(text(f'DROP DATABASE IF EXISTS {DB}'))
    c.execute(text(f'CREATE DATABASE {DB}'))

env = dict(os.environ, DATABASE_URL=TEST_URL, SECRET_KEY='test',
           ADMIN_USER='a', ADMIN_PASS='b')


def run(code, label):
    r = subprocess.run([sys.executable, '-c', code], capture_output=True,
                       text=True, cwd=ROOT, env=env)
    if 'OK' not in r.stdout:
        raise AssertionError(f'{label}:\n{r.stdout}\n{r.stderr}')
    return r.stdout


print('\n6. Two companies are provisioned, each with its own data')
run('''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
import provisioning, tenancy
from app import create_app
from extensions import db
from models import Client, Booking, Staff

for slug, name in (("acme", "Acme Cleaning"), ("baker", "Baker Maids")):
    provisioning.provision(slug, name, quiet=True)

app = create_app()
with app.app_context():
    with tenancy.use_tenant("acme"):
        db.session.add_all([
            Client(name="ACME CUSTOMER", email="acme@x.com"),
            Staff(name="ACME CLEANER"),
            Booking(service_type="deep", name="ACME JOB", price=999.0),
        ])
        db.session.commit()
    with tenancy.use_tenant("baker"):
        db.session.add_all([
            Client(name="BAKER CUSTOMER", email="baker@x.com"),
            Staff(name="BAKER CLEANER"),
            Booking(service_type="standard", name="BAKER JOB", price=111.0),
        ])
        db.session.commit()
print("OK")
''', 'provisioning')
print('  ✅ two companies provisioned, each given its own customer, cleaner and job')

print('\n7. Neither company can see the other — the test this file exists for')
out = run('''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
import tenancy
from app import create_app
from extensions import db
from models import Client, Booking, Staff
app = create_app()
problems = []
with app.app_context():
    for me, them in (("acme", "BAKER"), ("baker", "ACME")):
        with tenancy.use_tenant(me):
            for model, field in ((Client, "name"), (Staff, "name"), (Booking, "name")):
                rows = [getattr(r, field) for r in model.query.all()]
                if any(them in (v or "") for v in rows):
                    problems.append(f"{me} could see {them}: {rows}")
                if len(rows) != 1:
                    problems.append(f"{me} saw {len(rows)} {model.__name__} rows, expected 1")
            # The blunt instrument: ask for everything, by raw SQL, no filter.
            from sqlalchemy import text
            names = [r[0] for r in db.session.execute(text("SELECT name FROM client")).all()]
            if any(them in (n or "") for n in names):
                problems.append(f"{me} raw SQL reached {them}: {names}")
print("PROBLEMS:", problems)
print("OK" if not problems else "FAILED")
''', 'isolation')
check('PROBLEMS: []' in out, 'neither company can read the other, by ORM or by raw SQL')

print('\n8. A pooled connection cannot carry one company into the next request')
# The single real danger of this design. A connection that served Acme goes back
# to the pool still pointed at Acme; the next request must not inherit it.
out = run('''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
import tenancy
from app import create_app
from extensions import db
from models import Client
app = create_app()
seen = []
with app.app_context():
    for slug in ("acme", "baker", "acme", "baker", "acme"):
        with tenancy.use_tenant(slug):
            names = sorted(c.name for c in Client.query.all())
            seen.append((slug, names))
            db.session.remove()          # hand the connection back to the pool
bad = [s for s in seen
       if (s[0] == "acme" and s[1] != ["ACME CUSTOMER"])
       or (s[0] == "baker" and s[1] != ["BAKER CUSTOMER"])]
print("BAD:", bad)
print("OK" if not bad else "FAILED")
''', 'pool reuse')
check('BAD: []' in out,
      'five alternating requests over a reused pool each saw only their own company')

print('\n9. A request with no company resolves to public and sees no company data')
out = run('''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
import tenancy
from app import create_app
from extensions import db
from models import Client
app = create_app()
with app.app_context():
    with tenancy.use_tenant("acme"):
        Client.query.all()
        db.session.remove()
    # No tenant now -- the state a background job or a missed resolve is in.
    from sqlalchemy import text
    try:
        names = [r[0] for r in db.session.execute(text("SELECT name FROM client")).all()]
        leaked = [n for n in names if "ACME" in (n or "") or "BAKER" in (n or "")]
    except Exception as e:
        names, leaked = f"error: {type(e).__name__}", []
print("PUBLIC SAW:", names, "LEAKED:", leaked)
print("OK" if not leaked else "FAILED")
''', 'public fallback')
check('LEAKED: []' in out,
      'with no company in context, no company data is reachable')

print('\n10. The company list itself is not inside any company')
out = run('''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
import tenancy, provisioning, control_plane
eng = provisioning._engine()
rows = control_plane.all_orgs(eng)
slugs = sorted(r["slug"] for r in rows)
from sqlalchemy import text, inspect as si
with eng.connect() as c:
    acme_tables = si(c).get_table_names(schema="tenant_acme")
print("ORGS:", slugs)
print("ORGS TABLE INSIDE ACME:", "organizations" in acme_tables)
print("OK")
''', 'control plane placement')
check("ORGS: ['acme', 'baker']" in out, 'both companies are recorded in the control plane')
check('ORGS TABLE INSIDE ACME: False' in out,
      'and the list of all companies is NOT copied into any one company')

print('\n11. Every company gets the full schema, and its own migration record')
out = run('''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
import provisioning, extensions, models
from sqlalchemy import inspect as si, text
eng = provisioning._engine()
declared = set(extensions.db.metadata.tables)
with eng.connect() as c:
    a = set(si(c).get_table_names(schema="tenant_acme"))
    b = set(si(c).get_table_names(schema="tenant_baker"))
    ver_a = c.execute(text("SELECT version_num FROM tenant_acme.alembic_version")).scalar()
missing_a = declared - a
missing_b = declared - b
print("MISSING FROM ACME:", sorted(missing_a))
print("MISSING FROM BAKER:", sorted(missing_b))
print("ACME VERSION:", ver_a)
print("OK")
''', 'schema completeness')
check('MISSING FROM ACME: []' in out, 'Acme has every table the models declare')
check('MISSING FROM BAKER: []' in out, 'so does Baker')
check('ACME VERSION: 0003_deposit_amount_paid' in out,
      'and each company records its own migration position')

print('\n12. Removing a company removes only that company')
out = run('''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
import provisioning, control_plane, tenancy
from sqlalchemy import text, inspect as si
eng = provisioning._engine()
provisioning.drop_schema(eng, "tenant_baker")
with eng.begin() as c:
    c.execute(text("DELETE FROM public.organizations WHERE slug = :s"), {"s": "baker"})
with eng.connect() as c:
    left = [s for s in si(c).get_schema_names() if s.startswith("tenant_")]
    acme_clients = c.execute(text("SELECT name FROM tenant_acme.client")).scalars().all()
print("SCHEMAS LEFT:", left)
print("ACME UNTOUCHED:", acme_clients)
print("OK")
''', 'destroy')
check("SCHEMAS LEFT: ['tenant_acme']" in out, 'only the removed company is gone')
check('ACME UNTOUCHED: [\'ACME CUSTOMER\']' in out, 'the other company is untouched')

print('\n13. Refusing to drop anything that is not a company schema')
for dangerous in ('public', 'information_schema', 'tenant', '', 'pg_catalog'):
    try:
        import provisioning
        provisioning.drop_schema(admin, dangerous)
        raise AssertionError(f'dropping {dangerous!r} was allowed')
    except ValueError:
        pass
print('  ✅ public, pg_catalog and anything unprefixed cannot be dropped')

with admin.connect() as c:
    c.execute(text(f'DROP DATABASE IF EXISTS {DB}'))

print('\n\n✅ All tenancy tests passed.\n')
