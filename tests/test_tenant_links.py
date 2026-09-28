"""Every link a company sends points at that company.

`CRM_BASE` is one environment variable for the whole deployment. On a
single-business install that is exactly right. On the hosted product it is
shared by every company on the box, and it used to win outright — so every
texted link, for everybody, was addressed to the product's own domain:

    https://akyehq.com/contractors/my-day/<token>

which is a host where that cleaner's company does not exist. Job offers, claim
links, My Day, availability, payment pages, and the booking form a company
embeds in its own website are all built from `branding.crm_base()`. This would
have shipped and broken the links for every customer at once.

The half that is easy to get wrong twice: a link sent by a **background job**
has no request to read a hostname from. A nightly reminder must reach the same
address a click does, so outside a request the company's address is rebuilt
from its schema name and the product domain.
"""
import os, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/links.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akyehq.com'
os.environ['CRM_BASE'] = 'https://akyehq.com'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
import branding
import tenancy

app = create_app()

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def as_company(schema):
    tenancy._current.set(schema)


print('\n1. Two companies get two different addresses')
# The whole point of the fix. Both of these run with the same CRM_BASE.
as_company('tenant_acme')
acme = branding.crm_base()
as_company('tenant_brightside')
bright = branding.crm_base()
check(acme == 'https://acme.akyehq.com', f'acme is addressed to itself ({acme})')
check(bright == 'https://brightside.akyehq.com',
      f'brightside is addressed to itself ({bright})')
check(acme != bright, 'and they are not the same address')


print('\n2. Neither of them is the product\'s own domain')
# This is the bug, stated as an assertion. akyehq.com has no company on it.
for name, base in (('acme', acme), ('brightside', bright)):
    check(base.rstrip('/') != 'https://akyehq.com',
          f"{name}'s links do not point at the product domain")


print('\n3. It holds with no request in flight')
# A nightly reminder, a scheduled follow-up, a broadcast fired from a cron:
# no request, no host header, and still the right company.
as_company('tenant_acme')
check(branding.crm_base() == 'https://acme.akyehq.com',
      'a link built by a background job still reaches the company')


print('\n4. Inside a request, the host that was actually used wins')
# If somebody reaches a company on an address we did not predict -- a custom
# domain, a preview host, a port -- the reply must come back to where they
# already are, not to where we think they should be.
with app.test_request_context('/', base_url='https://acme.akyehq.com'):
    as_company('tenant_acme')
    check(branding.crm_base() == 'https://acme.akyehq.com',
          'the request host is used as-is')
with app.test_request_context('/', base_url='http://acme.internal:8080'):
    as_company('tenant_acme')
    check(branding.crm_base() == 'http://acme.internal:8080',
          'including an address we would never have guessed')


print('\n5. A single-business install still obeys CRM_BASE')
# This is what CRM_BASE was written for and it must not have been broken on
# the way past. No company in play means the configured value is the answer.
as_company('public')
check(branding.crm_base() == 'https://akyehq.com',
      'with no company in play, the configured base is used')


print('\n6. The embedded booking form points at the company too')
# Same root cause, and the one that made it visible: a customer pasted the
# snippet into their own website and the frame loaded the product's front
# page instead of their booking form.
c = app.test_client()
js = c.get('/embed.js', headers={'Host': 'acme.akyehq.com'}).data.decode('utf8', 'replace')
check('https://acme.akyehq.com/book?embed=1' in js.replace("'", '"').replace(
      '" + "', '') or 'acme.akyehq.com' in js,
      'the embed script frames that company\'s own booking page')
check('akyehq.com/book' not in js.replace('acme.akyehq.com', 'X'),
      'and never the product domain\'s')

as_company('public')

if failures:
    print(f'\n\n❌ {len(failures)} link check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Every company\'s links point at that company.\n')
