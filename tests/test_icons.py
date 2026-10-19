"""The icons browsers ask for on their own: /favicon.ico and Apple's touch icon.

A quote link or a booking page names no icon, so the browser asks for
/favicon.ico anyway, and every first visit left a 404 in the logs beside the
links that were really broken (remediation report AKY-12).
"""
import os
import sys
import tempfile

os.environ['DATABASE_URL'] = f'sqlite:///{tempfile.mkdtemp()}/icons.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

app = create_app()
c = app.test_client()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


print('\n1. Each answers with the app\'s own icon, and the icon is there')
for path, target in (('/favicon.ico', 'icon-192.png'),
                     ('/apple-touch-icon.png', 'icon-180.png'),
                     ('/apple-touch-icon-precomposed.png', 'icon-180.png')):
    r = c.get(path)
    where = r.headers.get('Location', '')
    check(r.status_code == 301 and where.endswith(f'/static/{target}'), f'{path} -> {target}')
    check(c.get(where).status_code == 200, f'and {target} is served')

print('\n\n✅ Icon requests are answered.\n')
