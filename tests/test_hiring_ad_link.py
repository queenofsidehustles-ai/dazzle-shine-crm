"""The link in a job advert has to reach the application form.

A cleaning company posts its own opening on Indeed for free, using the advert
and the link this page hands it. That link was built by hand as "{base}/apply",
and there is no /apply route -- the form is at /contractors/apply. So every
advert the CRM produced pointed at a 404.

The failure is quiet and expensive. The company does not see it: their advert
is live and applications arrive, because Indeed offers its own Apply button and
candidates use that instead. What they get is an email from Indeed and an empty
hiring pipeline in the CRM, with nothing anywhere saying the two were ever
meant to be connected.

So the link is built from the routing table rather than typed, and this checks
the thing that actually matters: that the URL in the advert resolves.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/ads.db'
os.environ['SECRET_KEY'] = 'test'
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


with app.app_context():
    db.create_all()

    print('\n1. The application form is where the routing table says')
    rules = {str(r.rule) for r in app.url_map.iter_rules()}
    check('/contractors/apply' in rules, 'the form is at /contractors/apply')
    check('/apply' not in rules,
          'and there is no bare /apply — which is what adverts used to point at')

    print('\n2. The advert link resolves')
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['logged_in'] = True
        sess['role'] = 'owner'
    # Asked of the routing table rather than guessed, which is the same
    # mistake this test exists to catch.
    from flask import url_for
    with app.test_request_context():
        ads_url = url_for('directory.hiring_ads')
    page = c.get(ads_url)
    check(page.status_code == 200, f'the hiring-ads page opens (got {page.status_code})')
    body = page.get_data(as_text=True)

    import re
    links = set(re.findall(r'https?://[^\s"\'<>]*/(?:contractors/)?apply\b', body))
    check(links, f'it offers an application link ({sorted(links)[:2]})')
    for link in links:
        path = '/' + link.split('/', 3)[3] if link.count('/') >= 3 else '/'
        r = c.get(path)
        check(r.status_code == 200,
              f'{path} answers {r.status_code} — a candidate who clicks it reaches the form')
        check(path != '/apply',
              'and it is not the bare /apply that never existed')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 An advert sends candidates to a form that exists.')
