"""The product advertises a hostname that actually answers.

BASE_DOMAIN is the bare apex, because company subdomains hang off it. The
product itself is served on www. CRM_BASE was set to the apex on our own deploy
guide's advice, and the marketing site read that for every public URL — so the
sitemap handed search engines /pricing, /terms, /privacy and /subprocessors on a
host that answers 404 to all four, and every canonical tag told them the page
they had just fetched was a duplicate of one they could not fetch.

Two rules here. Without CANONICAL_HOST, a page advertises the host that served
it — which is, by definition, one that works. With it, there is one address for
the site and the other host redirects to it, keeping the path.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/canon.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akyehq.com'
# Exactly the misconfiguration that caused this: the apex, which 404s on paths.
os.environ['CRM_BASE'] = 'https://akyehq.com'
os.environ.pop('CANONICAL_HOST', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
app = create_app()

WWW = 'www.akyehq.com'
APEX = 'akyehq.com'


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
c = app.test_client()

print('\n1. With nothing configured, a page advertises the host that served it')
xml = c.get('/sitemap.xml', base_url=f'https://{WWW}').get_data(as_text=True)
check(f'https://{WWW}/pricing' in xml, 'the sitemap lists the www URL that works')
check(f'https://{APEX}/pricing' not in xml,
      'and not the apex URL that 404s — this is the bug, in one line')

html = c.get('/', base_url=f'https://{WWW}').get_data(as_text=True)
check(f'canonical" href="https://{WWW}' in html,
      'the canonical tag names the working host')

print('\n1b. Each page is canonical for itself, not for the homepage')
# The shell defaulted every page's canonical to "/", so /pricing, /terms,
# /privacy and /subprocessors each declared themselves a duplicate of the
# homepage — an instruction to drop them from the index entirely. A pricing
# page that disowns itself cannot be found.
for path in ('/pricing', '/terms', '/privacy'):
    page = c.get(path, base_url=f'https://{WWW}').get_data(as_text=True)
    want = f'canonical" href="https://{WWW}{path}"'
    check(want in page, f'{path} is canonical for {path}')

print('\n2. CRM_BASE no longer decides what the public site advertises')
check(os.environ['CRM_BASE'] == f'https://{APEX}',
      'CRM_BASE is still the apex, as deployed')
check(f'https://{APEX}/terms' not in xml,
      'and the sitemap ignores it rather than promising a 404')

print('\n3. Robots points a crawler at a sitemap it can fetch')
robots = c.get('/robots.txt', base_url=f'https://{WWW}').get_data(as_text=True)
check(f'Sitemap: https://{WWW}/sitemap.xml' in robots, 'on the serving host')

print('\n4. Nothing redirects while CANONICAL_HOST is unset')
r = c.get('/pricing', base_url=f'https://{APEX}')
check(r.status_code == 200,
      'both hosts serve normally — turning this on is a deliberate act')

print('\n5. With CANONICAL_HOST set, one host wins and the path survives')
os.environ['CANONICAL_HOST'] = APEX
r = c.get('/pricing?ref=card', base_url=f'https://{WWW}')
check(r.status_code == 301, 'the other host redirects permanently')
check(r.headers['Location'] == f'https://{APEX}/pricing?ref=card',
      f'to the same page, query and all ({r.headers["Location"]})')
check(c.get('/pricing', base_url=f'https://{APEX}').status_code == 200,
      'and the canonical host itself serves, rather than looping')

xml = c.get('/sitemap.xml', base_url=f'https://{APEX}').get_data(as_text=True)
check(f'https://{APEX}/pricing' in xml, 'the sitemap follows the choice')

print('\n6. A company subdomain is never redirected to ours')
# Their CRM lives at their own address. Sending it to the marketing site would
# take a cleaning company to a signup page for the product they already pay for.
r = c.get('/login', base_url='https://acme.akyehq.com')
check(r.status_code != 301 or 'akyehq.com/login' not in (r.headers.get('Location') or ''),
      "acme.akyehq.com stays on acme.akyehq.com")

print('\n7. An API call is never redirected')
# Stripe posts webhooks and is not obliged to follow a 301 on a POST. The
# payment would look delivered and never arrive.
r = c.post('/api/stripe-webhook', base_url=f'https://{WWW}', json={})
check(r.status_code != 301, f'the webhook is handled, not bounced ({r.status_code})')

print('\n7b. Infrastructure is never redirected')
# Railway health-checks the container on an internal address. A 301 there reads
# as an unhealthy deploy, and the release rolls itself back — the canonical
# host would take the site down by being correct about hostnames.
for infra in ('localhost', '127.0.0.1', 'web.railway.internal'):
    r = c.get('/version', base_url=f'http://{infra}')
    check(r.status_code == 200, f'{infra} is answered, not bounced')
r = c.get('/static/favicon.svg', base_url='http://localhost')
check(r.status_code != 301, 'and so are static files in development')

print('\n7c. /version answers on any hostname')
# It is how you ask an instance what it is. Redirecting it would mean the one
# endpoint that could tell you the host is wrong refuses to speak on that host.
r = c.get('/version', base_url=f'https://{WWW}')
check(r.status_code == 200, 'including a host that would otherwise redirect')

print('\n8. Turning it off puts everything back')
del os.environ['CANONICAL_HOST']
check(c.get('/pricing', base_url=f'https://{WWW}').status_code == 200,
      'no redirect, and the working host serves again')

print('\n🎉 One host, it answers, and it is the one we tell the world about.')
