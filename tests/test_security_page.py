"""The security page, and remembering which company you sign in to.

Two things are being protected here.

The first is that a public security page is a promise. Every claim on it has to
be something a person could check in this repository, and it must never drift
into the language that means nothing -- "bank-level", "military-grade", a
certification nobody has been audited for. A page that overstates costs you the
trust of exactly the customer who bothered to check.

The second is that the sign-in page must not become a way to ask "does this
company exist?". It normalises what was typed and redirects. It looks nothing
up, and remembering the last address must not change that: what comes back is
the visitor's own answer, handed to the browser that gave it.
"""
import os, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/sec.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app

app = create_app()
PRODUCT = {'Host': 'akye.test'}
TENANT = {'Host': 'acme.akye.test'}

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def body(path, headers=PRODUCT, client=None):
    c = client or app.test_client()
    return c.get(path, headers=headers).data.decode('utf8', 'replace')


print('\n1. The page is there, on the product site only')
c = app.test_client()
r = c.get('/security', headers=PRODUCT)
check(r.status_code == 200, '/security is served on the product site')
check(c.get('/security', headers=TENANT).status_code == 404,
      "and 404s on a company's own CRM — it is not their page to show")

page = r.data.decode('utf8', 'replace')
check('How your data is protected' in page, 'it says what it is')
# Its own date, not the legal pages'. This page changes when the software's
# protections change, which is a different event from a wording change.
check('6 September 2026' in page,
      'dated when the protections were last described, not when the terms were')
check('29 August 2026' in body('/terms'), 'while /terms keeps its own date')


print('\n2. Every claim is one this repository can back up')
for phrase, why in [
        ('pbkdf2', 'names the actual password hashing, not "encrypted passwords"'),
        ('own private area of the database', 'describes the per-company separation'),
        ('W-9', 'names the documents that are encrypted rather than implying all are'),
        ('Stripe', 'says where card details actually go'),
        ('restored and counted back', 'claims the backup is verified, which it is'),
        ('HTTPS', 'covers connections')]:
    check(phrase in page, why)


print('\n3. It does not say the things that mean nothing')
for empty in ('bank-level', 'bank level', 'military-grade', 'military grade',
              'SOC 2', 'SOC2', 'HIPAA', 'ISO 27001', 'unhackable',
              'completely secure', '100% secure', 'fully compliant'):
    check(empty.lower() not in page.lower(), f'does not claim {empty!r}')

check('no software is perfect' in page.lower() or 'not a finished state' in page.lower(),
      'and says plainly that security is not a finished state')


print('\n4. It is reachable without going looking for it')
for path in ('/', '/pricing', '/terms'):
    check('/security' in body(path), f'{path} links to it in the footer')
check('/security' in body('/sitemap.xml'), 'and it is in the sitemap')


print('\n5. It is not dressed as a legal undertaking')
# The terms and privacy pages carry a "not reviewed by a lawyer" banner. This
# page describes what the software does rather than promising anything, so it
# uses a different shell -- and if it ever inherits that banner, the claim and
# the disclaimer would be fighting each other on the same page.
check('not yet been reviewed by a lawyer' not in page,
      'no draft banner: this is a description, not an undertaking')
check('not yet been reviewed by a lawyer' in body('/terms'),
      'while /terms still carries its banner, unchanged')


print('\n6. Sign-in still refuses to say whether a company exists')
c = app.test_client()
r = c.post('/workspace', headers=PRODUCT, data={'workspace': 'no-such-company-at-all'})
check(r.status_code in (301, 302), 'an unknown address redirects rather than erroring')
check('no-such-company-at-all.akye.test' in (r.headers.get('Location') or ''),
      'straight to that host, which tells the visitor nothing new')


print('\n7. The address is remembered, so the second visit is one click')
c = app.test_client()
first = c.get('/workspace', headers=PRODUCT).data.decode('utf8', 'replace')
check('name="workspace"' in first, 'a new browser is asked which company')

c.post('/workspace', headers=PRODUCT, data={'workspace': 'acme'})
second = c.get('/workspace', headers=PRODUCT).data.decode('utf8', 'replace')
check('acme.akye.test/login' in second,
      'having been once, the next visit offers to continue there')
check('name="workspace"' not in second, 'and does not ask again')
check('forget=1' in second, 'with a way to sign in to a different company')

after = c.get('/workspace?forget=1', headers=PRODUCT, follow_redirects=True)
check('name="workspace"' in after.data.decode('utf8', 'replace'),
      'and forgetting puts the question back')


print('\n8. What is remembered is only an address')
c = app.test_client()
r = c.post('/workspace', headers=PRODUCT, data={'workspace': 'ACME Cleaning!!'})
cookie = r.headers.get('Set-Cookie', '')
check('akye_workspace=acmecleaning' in cookie,
      'the cookie holds a normalised address and nothing else')
check('HttpOnly' in cookie, 'not readable by scripts')
check('Lax' in cookie, 'and not sent when another site tries to use it')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ The security page says only what is true, and sign-in still tells nobody anything.')
