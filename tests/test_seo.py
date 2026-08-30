"""The product site can be found, and shared, and understood in three seconds.

None of this existed. No canonical link, no OpenGraph, no structured data, no
robots.txt, no sitemap — and an H1 that never said what the product was. The
practical costs of that, in order of how much they matter:

  * Pasting the address into a Facebook group — which is where cleaning
    company owners actually are — produced a blank grey card with a bare URL.
  * A stranger arriving from a search read "Every other tool puts your jobs on
    a calendar" and had to work out for themselves that this was software, and
    for whom.
  * Google had nothing to build a rich result from.

The rule this file exists to hold: **prices and plan names are read from
entitlements.PLANS, never restated.** A pricing claim in a share card or a
search result that the software then refuses to honour is worse than no share
card at all.
"""
import os, sys, tempfile, json, re

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/seo.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['CRM_BASE'] = 'https://www.akye.test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
import entitlements

app = create_app()
c = app.test_client()
PRODUCT = {'Host': 'akye.test'}
TENANT = {'Host': 'acme.akye.test'}

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


home = c.get('/', headers=PRODUCT).data.decode('utf8', 'replace')
# A sentence wrapped across two lines in the template is the same sentence.
# Searching the raw bytes makes these fail on reformatting, which teaches
# people to loosen the assertion rather than read it.
flat = re.sub(r'\s+', ' ', home)


print('\n1. The page says what it is, above everything clever')
h1 = re.search(r'<h1[^>]*>(.*?)</h1>', home, re.S)
check(h1 is not None, 'there is an h1')
h1_text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', h1.group(1))).strip() if h1 else ''
check('cleaning business software' in h1_text.lower(),
      f'and it names the category: {h1_text[:70]!r}')
check('calendar' not in h1_text.lower(),
      'the contrarian line is not doing the h1\'s job')
check('Scheduling is the easy part' in flat,
      'but it is still said, immediately underneath')

print('\n2. And who else it is for')
# She sells to cleaning companies first, but the same shape fits anybody who
# sends a person to an address and pays them per job.
for trade in ('landscaping', 'pressure washing', 'window cleaning'):
    check(trade in flat.lower(), f'{trade} is named as a fit')


print('\n3. A shared link shows something')
for tag in ('og:title', 'og:description', 'og:image', 'og:url',
            'twitter:card', 'twitter:image'):
    check(tag in home, f'{tag} is set')
og_img = re.search(r'property="og:image" content="([^"]+)"', home)
check(og_img is not None and og_img.group(1).startswith('https://'),
      f'og:image is absolute ({og_img.group(1) if og_img else "missing"})')
check(og_img is not None and 'www.akye.test' in og_img.group(1),
      'and on the host that actually serves the site, not the bare domain')


print('\n4. Canonical, robots and a favicon')
check('rel="canonical"' in home, 'canonical link present')
check('name="robots"' in home, 'robots meta present')
check('favicon.svg' in home, 'a favicon is linked')
check(c.get('/static/favicon.svg').status_code == 200, 'and it exists')


print('\n5. Structured data that parses')
block = re.search(r'<script type="application/ld\+json">(.*?)</script>', home, re.S)
check(block is not None, 'there is a JSON-LD block')
data = None
try:
    data = json.loads(block.group(1))
    check(True, 'and it is valid JSON — a malformed block is ignored entirely')
except Exception as e:
    check(False, f'JSON-LD does not parse: {e}')

if data:
    types = [n.get('@type') for n in data.get('@graph', [])]
    for t in ('SoftwareApplication', 'Organization', 'FAQPage'):
        check(t in types, f'{t} described')

    app_node = next(n for n in data['@graph'] if n['@type'] == 'SoftwareApplication')
    offers = {o['name']: o['price'] for o in app_node['offers']}
    print('\n6. The prices in the structured data are the real ones')
    # This is the assertion that matters most in the file. A search result
    # quoting a price the software will not honour is a promise broken before
    # anybody has even clicked.
    for key, plan in entitlements.PLANS.items():
        check(offers.get(plan['label']) == str(plan['price']),
              f"{plan['label']} is ${plan['price']}, matching the plan table")
    check(len(offers) == len(entitlements.PLANS),
          f'every plan is listed ({len(offers)})')

    faq = next(n for n in data['@graph'] if n['@type'] == 'FAQPage')
    check(len(faq['mainEntity']) >= 5,
          f"{len(faq['mainEntity'])} questions answered for search")
    check(all(q['acceptedAnswer']['text'].strip() for q in faq['mainEntity']),
          'and none of them has an empty answer')


print('\n7. The questions are on the page too, not only in the markup')
# Structured data that describes content the visitor cannot see is the kind of
# thing search engines penalise, and rightly.
check('<details' in home, 'the FAQ renders as real details elements')
check(home.count('<summary') >= 5, f'{home.count("<summary")} questions on the page')
check('ZenMaid' in flat or 'Jobber' in flat,
      'including the comparison somebody is definitely searching for')


print('\n8. robots.txt and sitemap.xml')
r = c.get('/robots.txt', headers=PRODUCT)
check(r.status_code == 200, f'/robots.txt serves ({r.status_code})')
body = r.data.decode()
check('text/plain' in r.headers.get('Content-Type', ''), 'as plain text')
check('Sitemap:' in body, 'and points at the sitemap')
check('Disallow: /login' in body, 'signed-in pages are not offered up')

sm = c.get('/sitemap.xml', headers=PRODUCT)
check(sm.status_code == 200, f'/sitemap.xml serves ({sm.status_code})')
check('xml' in sm.headers.get('Content-Type', ''), 'as xml')
smb = sm.data.decode()
check('https://www.akye.test/' in smb, 'with absolute urls on the serving host')
check('/pricing' in smb, 'and pricing is in it')


print('\n9. None of it appears on a cleaning company\'s CRM')
# A customer's CRM is not ours to index, and its robots rules are not ours to
# write.
for path in ('/robots.txt', '/sitemap.xml'):
    check(c.get(path, headers=TENANT).status_code == 404,
          f'{path} is 404 on a company subdomain')


if failures:
    print(f'\n\n❌ {len(failures)} SEO check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ The site can be found, shared and understood.\n')
