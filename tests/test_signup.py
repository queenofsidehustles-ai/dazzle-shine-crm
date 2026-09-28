"""A cleaning company giving itself an account, start to finish.

The happy path matters here more than usual: this is a stranger's first sixty
seconds with the product, unaccompanied, and if it half-works they leave and do
not come back. So this walks the whole thing on a real PostgreSQL — form,
schema, tables, owner account, redirect, session — and then goes looking for the
ways it could go wrong.

The two that would hurt most:

  * A signup that fails half-way and leaves the address unusable, so the person
    retries, is told it is taken, and gives up.
  * A welcome link that could be used twice, or by somebody else.
"""
import os, sys, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


import tenancy
from blueprints.signup import suggest_slug

print('\n1. A business name becomes a sensible web address')
for name, want in [
    ('Sparkle Cleaning Services', 'sparkle-cleaning-services'),
    ('Dazzle & Shine Maids', 'dazzle-shine-maids'),
    ("O'Brien Cleaning", 'o-brien-cleaning'),
    ('   Spaces   Everywhere   ', 'spaces-everywhere'),
    ('A1 Cleaners!!!', 'a1-cleaners'),
]:
    check(suggest_slug(name) == want, f'{name!r} → {suggest_slug(name)!r}')
check(suggest_slug('!!!') == '', 'a name with nothing usable in it suggests nothing')
check(suggest_slug('www') == '', 'and a reserved word is not suggested')


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
    print('  ⚠️  SKIPPED: signup needs PostgreSQL schemas and found no server.')
    print('     Install with: brew install postgresql@16')
    print('=' * 70 + '\n')
    sys.exit(0)

DB = 'dsm_signup_test'
TEST_URL = f'{PG.rsplit("/", 1)[0]}/{DB}'

from sqlalchemy import create_engine, text
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as c:
    c.execute(text(f'DROP DATABASE IF EXISTS {DB}'))
    c.execute(text(f'CREATE DATABASE {DB}'))

env = dict(os.environ, DATABASE_URL=TEST_URL, SECRET_KEY='test',
           BASE_DOMAIN='rollcall.test', SIGNUPS_OPEN='1')
env.pop('ADMIN_USER', None)
env.pop('ADMIN_PASS', None)


def run(code, label, extra_env=None):
    e = dict(env, **(extra_env or {}))
    r = subprocess.run([sys.executable, '-c', code], capture_output=True,
                       text=True, cwd=ROOT, env=e)
    if 'OK' not in r.stdout:
        raise AssertionError(f'{label}:\n{r.stdout}\n{r.stderr}')
    return r.stdout


STUB = '''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
'''

print('\n2. A stranger signs up and lands in their own CRM, signed in')
out = run(STUB + '''
from app import create_app
app = create_app()
c = app.test_client()
r = c.post("/signup", data={
    "business": "Sparkle Cleaning Services", "slug": "sparkle",
    "name": "Dana Reed", "email": "dana@sparkle.test",
    "password": "a-perfectly-fine-password",
}, headers={"Host": "rollcall.test"})
print("REDIRECT:", r.status_code, r.headers.get("Location"))
print("OK")
''', 'signup post')
check('REDIRECT: 302' in out, 'the form redirects rather than rendering an error')
check('//sparkle.rollcall.test/welcome/' in out,
      'and sends them to their own address with a one-time link')
token = out.split('/welcome/')[1].split()[0].strip()

out = run(STUB + f'''
from app import create_app
app = create_app()
c = app.test_client()
H = {{"Host": "sparkle.rollcall.test"}}
r = c.get("/welcome/{token}", headers=H)
print("WELCOME:", r.status_code, r.headers.get("Location"))
# Checked by loading a page that requires a session, not by reading the cookie
# jar: the cookie is scoped to sparkle.rollcall.test on purpose, so looking for
# it under any other host finds nothing. That scoping is the isolation working.
r2 = c.get("/", headers=H, follow_redirects=True)
print("SIGNED IN:", b'name="password"' not in r2.data)
print("DASHBOARD:", r2.status_code, b"Sparkle Cleaning Services" in r2.data)
print("OK")
''', 'welcome')
check('WELCOME: 302' in out, 'the welcome link redirects them onward')
check('SIGNED IN: True' in out,
      'they arrive signed in — a page needing a session renders instead of bouncing')
check('DASHBOARD: 200 True' in out,
      'and the CRM greets them by their business name, not a placeholder')

print('\n3. Their company got a real, complete database of its own')
out = run(STUB + '''
import tenancy, provisioning, extensions, models
from sqlalchemy import inspect as si, text
eng = provisioning._engine()
with eng.connect() as c:
    tables = set(si(c).get_table_names(schema="tenant_sparkle"))
    ver = c.execute(text("SELECT version_num FROM tenant_sparkle.alembic_version")).scalar()
missing = set(extensions.db.metadata.tables) - tables
print("MISSING:", sorted(missing))
print("VERSION:", ver)
from app import create_app
app = create_app()
with app.app_context():
    with tenancy.use_tenant("sparkle"):
        from models import User, ChecklistTemplate, EmailTemplate, Booking
        print("USERS:", User.query.count())
        print("SEEDED CHECKLISTS:", ChecklistTemplate.query.count() > 0)
        print("SEEDED EMAILS:", EmailTemplate.query.count() > 0)
        print("BOOKINGS:", Booking.query.count())
print("OK")
''', 'provisioned schema')
check('MISSING: []' in out, 'every table the models declare exists in their schema')
import migrate as _mig
_head = _mig.ScriptDirectory.from_config(_mig._config()).get_current_head()
check(f'VERSION: {_head}' in out, f'recorded at the current migration ({_head})')
check('USERS: 1' in out, 'exactly one account — theirs')
check('SEEDED CHECKLISTS: True' in out, 'with the starter checklists already in it')
check('SEEDED EMAILS: True' in out, 'and the customer email templates')
check('BOOKINGS: 0' in out, 'and no jobs, because it is their first day')

print('\n4. A welcome link works once')
out = run(STUB + f'''
from app import create_app
app = create_app()
c = app.test_client()
r = c.get("/welcome/{token}", headers={{"Host": "sparkle.rollcall.test"}})
print("SECOND USE:", r.status_code, b"has been used" in r.data)
r2 = c.get("/", headers={{"Host": "sparkle.rollcall.test"}}, follow_redirects=True)
print("STILL SIGNED OUT:", b'name="password"' in r2.data)
print("OK")
''', 'token reuse')
check('SECOND USE: 200 True' in out, 'using it again says so plainly')
check('STILL SIGNED OUT: True' in out, 'and does not sign anybody in')

print('\n5. A second company cannot take the same address')
out = run(STUB + '''
from app import create_app
app = create_app()
c = app.test_client()
r = c.post("/signup", data={
    "business": "Someone Else Entirely", "slug": "sparkle",
    "name": "Imposter", "email": "nope@x.test", "password": "another-password",
}, headers={"Host": "rollcall.test"})
print("STATUS:", r.status_code)
print("SAYS TAKEN:", b"already taken" in r.data)
print("OK")
''', 'duplicate slug')
check('STATUS: 200' in out, 'the form comes back rather than redirecting')
check('SAYS TAKEN: True' in out, 'and says the address is taken')

print('\n6. Bad input is refused, and says which bit')
cases = [
    ({'business': '', 'slug': 'ok-one', 'name': 'A', 'email': 'a@b.test',
      'password': 'a-good-password'}, b'business called'),
    ({'business': 'B', 'slug': 'ok-two', 'name': '', 'email': 'a@b.test',
      'password': 'a-good-password'}, b'your name'),
    ({'business': 'B', 'slug': 'ok-three', 'name': 'A', 'email': 'not-an-email',
      'password': 'a-good-password'}, b'does not look right'),
    ({'business': 'B', 'slug': 'ok-four', 'name': 'A', 'email': 'a@b.test',
      'password': 'short'}, b'at least 8'),
    ({'business': 'B', 'slug': 'www', 'name': 'A', 'email': 'a@b.test',
      'password': 'a-good-password'}, b'reserved word'),
    ({'business': 'B', 'slug': 'NO CAPS', 'name': 'A', 'email': 'a@b.test',
      'password': 'a-good-password'}, b'lower-case'),
]
for data, expect in cases:
    out = run(STUB + f'''
from app import create_app
app = create_app()
c = app.test_client()
r = c.post("/signup", data={data!r}, headers={{"Host": "rollcall.test"}})
print("MATCH:", {expect!r} in r.data, "STATUS:", r.status_code)
print("OK")
''', f'validation {data.get("slug")}')
    check('MATCH: True' in out, f'{expect.decode()!r} — refused with a useful message')

print('\n7. Nothing half-built is left behind by a failed signup')
out = run(STUB + '''
import provisioning, control_plane
from sqlalchemy import inspect as si
eng = provisioning._engine()
with eng.connect() as c:
    schemas = sorted(s for s in si(c).get_schema_names() if s.startswith("tenant_"))
orgs = sorted(o["slug"] for o in control_plane.all_orgs(eng))
print("SCHEMAS:", schemas)
print("ORGS:", orgs)
print("OK")
''', 'no orphans')
check("SCHEMAS: ['tenant_sparkle']" in out,
      'the six refused attempts left no schemas behind')
check("ORGS: ['sparkle']" in out, 'and no half-recorded companies')

print('\n8. The address check answers as somebody types')
out = run(STUB + '''
from app import create_app
app = create_app()
c = app.test_client()
for slug in ("sparkle", "brand-new-one", "www", "ab", "Bad Caps"):
    r = c.get("/signup/check?slug=" + slug, headers={"Host": "rollcall.test"})
    print(slug, "->", r.get_json())
print("OK")
''', 'slug check')
check("'ok': False" in out.split('sparkle ->')[1].split('\n')[0], 'a taken address says so')
check("'ok': True" in out.split('brand-new-one ->')[1].split('\n')[0], 'a free one says so')
check('reserved' in out.split('www ->')[1].split('\n')[0], 'a reserved one explains why')

print('\n9. With no domain configured, signup does not exist')
# The single-business instance running today. There is no product domain, so
# there are no subdomains, so there is nothing to sign up to.
out = run(STUB + '''
from app import create_app
app = create_app()
c = app.test_client()
for path in ("/signup", "/signup/check?slug=x"):
    print(path, "->", c.get(path).status_code)
print("OK")
''', 'signup off', extra_env={'BASE_DOMAIN': ''})
check('/signup -> 404' in out, 'the signup page is not there')
check('/signup/check?slug=x -> 404' in out, 'nor is the address checker')

print('\n10. The door can be shut while tenancy stays on')
out = run(STUB + '''
from app import create_app
app = create_app()
c = app.test_client()
print("/signup ->", c.get("/signup", headers={"Host": "rollcall.test"}).status_code)
import tenancy
print("STILL RESOLVES:", tenancy.slug_from_host("sparkle.rollcall.test", "rollcall.test"))
print("OK")
''', 'signups closed', extra_env={'SIGNUPS_OPEN': '0'})
check('/signup -> 404' in out, 'SIGNUPS_OPEN=0 closes the door')
check('STILL RESOLVES: sparkle' in out,
      'while existing companies carry on working — the state for onboarding by hand')

with admin.connect() as c:
    c.execute(text(f'DROP DATABASE IF EXISTS {DB}'))

print('\n\n✅ All signup tests passed.\n')
