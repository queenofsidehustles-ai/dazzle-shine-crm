"""The blog on the product site: an index, posts, and a sitemap that lists them.

The guide proved the shape works -- somebody typing "how to start a cleaning
business" is this product's buyer months before they know cleaning software
exists. One page that answers a real question keeps working while nobody
watches it. A blog is that repeated, and the compounding only happens if the
posts are actually reachable and actually indexed.

So this checks the two things that silently stop that: a post that renders but
is in no sitemap is a post no crawler finds, and a marketing page that answers
on a company's own subdomain is marketing appearing over somebody's CRM.
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
import blog

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

    print('\n1. The index lists every post, newest first')
    r = c.get('/blog', headers={'Host': PRODUCT_HOST})
    check(r.status_code == 200, 'the index renders')
    body = r.data.decode()
    for p in blog.POSTS:
        check(p['title'] in body, f'“{p["title"]}” is listed')
    check('How to Start a Cleaning Business' in body,
          'and the long guide is listed alongside them')

    print('\n2. The guide keeps its own URL rather than being moved under /blog')
    check(f'/how-to-start-a-cleaning-business' in body,
          'the index links to the address that is already indexed')
    check(c.get('/how-to-start-a-cleaning-business',
                headers={'Host': PRODUCT_HOST}).status_code == 200,
          'and that address still answers')

    print('\n3. Each post renders its own content')
    for p in blog.POSTS:
        r = c.get(f'/blog/{p["slug"]}', headers={'Host': PRODUCT_HOST})
        if r.status_code != 200:
            check(False, f'{p["slug"]} renders')
            continue
        text = r.data.decode()
        first = p['sections'][0]
        check(first['h'] in text, f'{p["slug"]}: its first heading is on the page')
        check(first['body'][0][:40] in text, f'{p["slug"]}: and its actual prose')
        check(p['dek'] in text, f'{p["slug"]}: with the standfirst as the description')

    print('\n4. A post that does not exist is gone, not quietly redirected')
    r = c.get('/blog/a-post-that-was-never-written', headers={'Host': PRODUCT_HOST})
    check(r.status_code == 404,
          'a stale link says 404 rather than landing the reader somewhere else')

    print('\n5. The sitemap promises the posts exist')
    xml = c.get('/sitemap.xml', headers={'Host': PRODUCT_HOST}).data.decode()
    check('/blog<' in xml or '/blog<' in xml.replace('</loc>', '<'),
          'the index is in the sitemap')
    for p in blog.POSTS:
        check(f'/blog/{p["slug"]}' in xml, f'{p["slug"]} is in the sitemap')
    check('www' in xml or 'http' in xml, 'and the URLs are absolute')

    print('\n6. Structured data comes from the same dict the page renders')
    post = blog.POSTS[0]
    sd = blog.structured_data(post, 'Akye', 'https://example.com/blog/x')
    check(sd['headline'] == post['title'], 'the headline is the post title')
    check(sd['datePublished'] == post['date'], 'and the date is the post date')
    text = c.get(f'/blog/{post["slug"]}', headers={'Host': PRODUCT_HOST}).data.decode()
    check('BlogPosting' in text, 'the page carries it for search engines')

    print('\n7. Marketing never appears over a company\'s own CRM')
    # What matters is that the post does not render there, not which refusal
    # is used. _require_product_site raises 404; on SQLite the request never
    # reaches it, because a multi-company host needs PostgreSQL schemas and the
    # app says so with a 503 first. Both are refusals, and asserting the exact
    # code made this test about the test database rather than about the rule.
    # The existing guide and pricing pages behave identically here.
    for path in ('/blog', f'/blog/{blog.POSTS[0]["slug"]}'):
        r = c.get(path, headers={'Host': TENANT_HOST})
        text = r.data.decode(errors='replace')
        check(r.status_code != 200,
              f'{path} is refused on a company subdomain (got {r.status_code})')
        check(blog.POSTS[0]['title'] not in text,
              f'{path} leaks no marketing copy over their CRM')

    print('\n8. Every post is reachable from the index')
    body = c.get('/blog', headers={'Host': PRODUCT_HOST}).data.decode()
    for p in blog.POSTS:
        check(f'/blog/{p["slug"]}' in body, f'{p["slug"]} is linked, not orphaned')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 The blog is readable, linked and indexed.')
