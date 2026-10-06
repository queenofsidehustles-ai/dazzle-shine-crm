"""The blog moved to getakye.com, and every old address still reaches it.

It was built inside the application first. That put publishing behind four
required checks and a redeploy of the CRM every tenant is working in -- twice a
week, forever, to put an article up. getakye.com is plain HTML on Netlify with
no build step, which is why its own README keeps it separate from the app:
nothing there can break this.

What has to stay true here is the leaving-behind. The addresses that were
published keep working and keep their slug, so a link already shared arrives at
the article rather than at a front page; the sitemap stops advertising pages
this host no longer serves, because a sitemap entry that redirects is a lie to a
crawler; and marketing still never appears over a company's own CRM.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/blog.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


PRODUCT_HOST = 'akyehq.test'
TENANT_HOST = 'somecompany.akyehq.test'

with app.app_context():
    db.create_all()
    c = app.test_client()
    HOST = 'akyehq.test'

    print('\n1. The blog addresses still answer, and go to the blog')
    r = c.get('/blog', headers={'Host': HOST})
    check(r.status_code == 301, f'/blog is a permanent redirect (got {r.status_code})')
    check(r.headers.get('Location') == 'https://getakye.com/blog/',
          'to the blog on getakye.com')

    print('\n2. A post keeps its slug rather than landing on a front page')
    r = c.get('/blog/the-jobs-you-lose-without-noticing', headers={'Host': HOST})
    check(r.status_code == 301, 'a post URL redirects permanently')
    check(r.headers.get('Location') ==
          'https://getakye.com/blog/the-jobs-you-lose-without-noticing/',
          'to the same article, not the index — an old link still arrives somewhere useful')

    print('\n3. The sitemap stops promising pages this host no longer serves')
    xml = c.get('/sitemap.xml', headers={'Host': HOST}).data.decode()
    check('/blog' not in xml,
          'no blog URL is advertised here — a sitemap entry that redirects is a lie')
    check('/how-to-start-a-cleaning-business' in xml,
          'while the guide, which really is on this host, stays listed')

    print('\n4. Marketing still never appears over a company\'s CRM')
    r = c.get('/blog', headers={'Host': 'somecompany.akyehq.test'})
    check(r.status_code != 301 or 'getakye' not in (r.headers.get('Location') or ''),
          f'a company subdomain is not handed the marketing blog (got {r.status_code})')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 One blog, one host, and every old address still arrives at it.')
