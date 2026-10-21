"""Help tips: every menu item says what it is for, in a sentence, where it is.

What would go wrong without each of these:
  * a new menu item with no tip, so the feature nobody opens stays unopened;
  * a tip for a page that was renamed, pointing at nothing;
  * a {{ tip('key') }} in a template with no tip behind it -- an empty space
    where help should be;
  * a tip that grows into a help page nobody reads;
  * a locked feature labelled "Included in Pro" when it is a Scale feature;
  * "Ask Nana" offered to a login that cannot open her, or a "Watch how" link
    to a video that has not been recorded;
  * an ⓘ only a mouse can open -- most owners are on a phone.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_help_tips')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
os.environ.pop('AKYE_VIDEO_BOOK_JOB', None)

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import funnel_videos
import help_tips
import navigation
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


print('\n1. Every menu item and tab has a tip, and every tip has a home')
menu = set()
for _h, items in navigation.SECTIONS:
    for ep, _i, _l, _o, tabs in items:
        menu.add(ep)
        menu.update(t[0] for t in tabs)
missing = sorted(ep for ep in menu if ep not in help_tips.TIPS)
check(not missing, f'each of the {len(menu)} menu items and tabs says what it is for (missing: {missing})')
endpoints = {r.endpoint for r in app.url_map.iter_rules()}
stale = sorted(k for k in help_tips.TIPS if '.' in k and k.split('.')[0] in
               {r.split('.')[0] for r in endpoints} and k not in endpoints)
check(not stale, f'no tip is left behind by a renamed page ({stale})')

used = set()
for path in (ROOT / 'templates').rglob('*.html'):
    used.update(re.findall(r"tip\('([^']+)'", path.read_text(errors='replace')))
unknown = sorted(k for k in used if k not in help_tips.TIPS)
check(not unknown, f'every tip a page asks for exists ({unknown})')
terms = {k for k in help_tips.TIPS if k not in endpoints}
unused = sorted(terms - used)
check(not unused, f'and every tip that is not a page is placed on one ({unused})')

long_ = [k for k, (t, text, *_r) in help_tips.TIPS.items() if len(text) > help_tips.MAX_TEXT or len(t) > 30]
check(not long_, f'a tip is a sentence or two, not a help page ({long_})')
bad_video = [k for k, row in help_tips.TIPS.items() if row[2] and row[2] not in funnel_videos.VIDEOS]
check(not bad_video, f'videos named are real videos ({bad_video})')


SLUG = 'tipsy'
HOST = f'http://{SLUG}.akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Tipsy Cleaning', quiet=True)
    db.session.remove()
provisioning.seed(app, SLUG)
c = fresh_postgres.owner_client(app, SLUG, 'akye.test')


def page(client, path):
    r = client.get(path, base_url=HOST)
    return r.status_code, r.get_data(as_text=True)


def menu_tips(html):
    import json
    m = re.search(r'<script type="application/json" id="menuTips">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else {}


print('\n2. The menu explains itself, and names the right plan')
fresh_postgres.set_company_plan(SLUG, 'solo')
code, html = page(c, '/')
tips = menu_tips(html)
check(code == 200 and 'bookings.index' in tips and 'data-tip="bookings.index"' in html,
      'each menu item carries its tip, for hover and keyboard focus')
check('static/tips.js' in html and 'id="menuTip"' in html and 'role="tooltip"' in html,
      'with one shared tooltip, read out as the description of the focused item')
lf = tips.get('places_finder.dashboard', {})
check(lf.get('locked') == 'Part of the Scale plan.' and tips.get('money.pnl', {}).get('locked') == 'Part of the Pro plan.',
      f'a locked feature names the plan that has it ({lf.get("locked")!r}), not "Pro" for everything')
check('Included in Pro' not in html, 'and the blanket "Included in Pro" is gone')
check(not tips.get('bookings.index', {}).get('locked'), 'an open feature says nothing about plans')


print('\n3. The ⓘ beside a page title: a button, with its links only when they work')
code, html = page(c, '/bookings/')
m = re.search(r'<button type="button" class="tip-btn" aria-expanded="false" aria-controls="([^"]+)" aria-label="What is Bookings\?">', html)
check(code == 200 and m is not None, 'a page opened from the menu has an ⓘ that is a real button, tappable on a phone')
check(m is not None and f'id="{m.group(1)}" role="dialog"' in html and 'hidden>' in html,
      'opening a popover it controls, closed until asked for')
check('Watch how' not in html, 'no "Watch how" link while the video has not been recorded')
os.environ['AKYE_VIDEO_BOOK_JOB'] = 'https://www.loom.com/share/0123456789abcdef0123456789abcdef'
code, html = page(c, '/bookings/')
check('▶ Watch how' in html and 'loom.com/share/0123456789abcdef' in html, 'and one once it has')
os.environ.pop('AKYE_VIDEO_BOOK_JOB', None)

fresh_postgres.set_company_plan(SLUG, 'scale')
code, html = page(c, '/find-leads/')
check(code == 200 and 'What is Find leads?' in html and '/ask?q=' in html and 'Ask Nana' in html,
      'the owner can take a question further with Ask Nana')
code, html = page(c, '/find-leads/?view=everyone')
check('What do the stages mean?' in html, 'a term on a page has its own ⓘ')


print('\n4. What a Sales login is offered')
from auth import _auth_fingerprint
from models import User
with app.app_context(), tenancy.use_tenant(SLUG):
    u = User(name='Sam Sales', username=f'sam@{SLUG}.test', role='sales', active=True)
    u.set_password('a-perfectly-fine-password')
    db.session.add(u)
    db.session.commit()
    uid, fp = u.id, _auth_fingerprint(u.password_hash)
    db.session.remove()
sc = app.test_client()
with sc.session_transaction(base_url=HOST) as sess:
    sess.update(logged_in=True, role='sales', user_id=uid, user_name='Sam Sales',
                auth_fingerprint=fp, tenant_slug=SLUG)
code, html = page(sc, '/find-leads/')
tips = menu_tips(html)
check(code == 200 and 'What is Find leads?' in html and 'Ask Nana' not in html,
      'the tip, without an Ask Nana link a Sales login cannot open')
check('money.pnl' not in tips and 'bookings.index' not in tips,
      'and only tips for the menu items they actually have')


print('\n5. A tip renders safely outside a page')
with app.test_request_context('/', base_url=HOST):
    out = str(help_tips.render('lead.stages', 'Say "what"? <b>'))
    none = str(help_tips.render('no.such.tip'))
check('&#34;what&#34;' in out and '<b>' not in out, 'labels are escaped')
check(none == '', 'an unknown tip renders nothing rather than breaking the page')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Every menu item says what it is for, on hover, on focus and on a tap.')
