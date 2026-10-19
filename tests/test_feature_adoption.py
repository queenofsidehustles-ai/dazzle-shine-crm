"""Pointing each person at the features they have not found -- and finding out
which help tips work.

What would go wrong without each of these:
  * every menu item dotted at once, so no dot means anything;
  * dots and suggestions on an owner's first day, competing with Getting
    started for the one thing she should be doing;
  * a dot on a feature her plan does not include;
  * "Did you know?" on every page, or on every visit, until it is wallpaper;
  * "Not now" ignored, the same suggestion back next sign-in;
  * one person's discoveries counted as another's;
  * the report counting a tip as working because somebody had already used
    the feature before they read it;
  * recording a visit while a page renders, and so saving whatever that page
    had changed but meant to throw away.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import os
import pathlib
import re
import secrets
import sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_feature_adoption')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from sqlalchemy import func, select, text

from app import create_app
from extensions import db
from models import BusinessSetting, FeatureSeen, User
import adoption
import control_plane
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SLUG = 'nudge' + secrets.token_hex(3)
HOST = f'http://{SLUG}.akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Nudge Cleaning', quiet=True)
    db.session.remove()
provisioning.seed(app, SLUG)
fresh_postgres.set_company_plan(SLUG, 'scale')
ENGINE = provisioning._engine()


def owner():
    """A fresh sign-in as the owner -- a new session, as signing in makes."""
    return fresh_postgres.owner_client(app, SLUG, 'akye.test')


def in_tenant(fn):
    with app.app_context(), tenancy.use_tenant(SLUG):
        try:
            return fn()
        finally:
            db.session.remove()


def u(endpoint):
    from flask import url_for
    with app.test_request_context('/', base_url=HOST):
        return url_for(endpoint)


def page(client, path):
    r = client.get(path, base_url=HOST)
    return r.status_code, r.get_data(as_text=True)


def sidebar(html):
    return html.split('<nav>', 1)[1].split('</nav>', 1)[0] if '<nav>' in html else ''


def dotted(html):
    """The sidebar items carrying a dot, by label."""
    out = []
    for a in re.findall(r'<a [^>]*>(.*?)</a>', sidebar(html), re.S):
        if 'nav-dot' in a:
            out.append(re.sub(r'<[^>]+>', ' ', a).split('—')[0].split()[1] if a else '')
    return out


def suggested(html):
    m = re.search(r'<strong>Did you know\? ([^<]+)</strong>', html)
    return m.group(1).strip() if m else None


def events(tip, event):
    with ENGINE.connect() as conn:
        return conn.execute(select(func.count()).select_from(control_plane.tip_events).where(
            (control_plane.tip_events.c.slug == SLUG) & (control_plane.tip_events.c.tip == tip)
            & (control_plane.tip_events.c.event == event))).scalar()


def row(endpoint, key=None):
    def q():
        r = FeatureSeen.query.filter_by(endpoint=endpoint, **({'user_key': key} if key else {})).first()
        return None if r is None else {c: getattr(r, c) for c in (
            'user_key', 'first_seen_at', 'tip_opened_at', 'suggested_at', 'dismissed_at')}
    return in_tenant(q)


print('\n1. Nothing while the owner is still setting up')
c = owner()
code, html = page(c, '/')
check(code == 200 and 'nav-dot' not in sidebar(html) and suggested(html) is None,
      'no dots and no "Did you know?" -- Getting started is the one thing to look at')
import onboarding as _ob
in_tenant(lambda: (BusinessSetting.set('setup_complete', _ob.SETUP_VERSION),
                   db.session.commit()))


print('\n2. A few dots, on what pays back most, and one suggestion per sign-in')
c = owner()
code, html = page(c, '/')
dots = dotted(html)
check(dots == ['Money', 'Commercial', 'Rentals'],
      f'three dots, never the whole menu: Find leads, Job economics (under Money), Rentals ({dots})')
check('— not opened yet' in html, 'each read out to a screen reader, not just a colour')
check(suggested(html) == 'Find leads' and events('places_finder.dashboard', 'suggested') == 1,
      f'one "Did you know?" for the first of them ({suggested(html)})')
code, html = page(c, '/bookings/')
check(suggested(html) is None, 'and only once in a sign-in, not on every page')

page(c, '/find-leads/')
code, html = page(c, '/')
dots = dotted(html)
check('Commercial' not in dots and dots == ['Money', 'Leads', 'Rentals'],
      f'opening a feature takes its dot away, and the next one takes its place ({dots})')
check(row('places_finder.dashboard')['first_seen_at'] is not None, 'the first visit is remembered, per person')

page(c, u('money.pnl'))
code, html = page(c, '/')
check('Money' in dotted(html), 'a section keeps its dot while the dotted page inside it is unopened')


print('\n3. "Not now" means never; ignoring it means not for a week')
c = owner()
code, html = page(c, '/')
check(suggested(html) == 'Job economics', f'the next sign-in suggests the next unopened feature ({suggested(html)})')
r = c.post('/tips/dismiss', base_url=HOST, json={'key': 'money.job_economics'},
           headers={'Accept': 'application/json', 'Origin': HOST})
check(r.status_code == 204 and row('money.job_economics')['dismissed_at'] is not None
      and events('money.job_economics', 'dismissed') == 1, '"Not now" is recorded')
c = owner()
code, html = page(c, '/')
check(suggested(html) == 'Rentals', f'and the sign-in after skips it ({suggested(html)})')
c = owner()
code, html = page(c, '/')
check(suggested(html) == 'Missed contacts',
      f'a suggestion shown and ignored waits a week before coming back ({suggested(html)})')


def age(endpoint, days):
    def go():
        with db.engine.begin() as conn:
            conn.execute(text("UPDATE feature_seen SET suggested_at = suggested_at - make_interval(days => :d) "
                              "WHERE endpoint = :e"), {'d': days, 'e': endpoint})
    in_tenant(go)


age('rentals.index', 8)
age('money.job_economics', 30)
c = owner()
code, html = page(c, '/')
check(suggested(html) == 'Rentals', f'then it comes back -- unlike one turned down ({suggested(html)})')
r = c.get('/tips/go/rentals.index', base_url=HOST)
check(r.status_code == 302 and r.headers['Location'].endswith(u('rentals.index'))
      and events('rentals.index', 'clicked') == 1, '"Show me" goes to the feature, and counts')
check(c.get('/tips/go/not.a.tip', base_url=HOST).status_code == 404, 'and nowhere else')


print('\n4. Which tips work: read first, then opened')
for _ in range(2):
    r = c.post('/tips/opened', base_url=HOST, json={'key': 'directory.talent_pool'}, headers={'Origin': HOST})
check(r.status_code == 204 and row('directory.talent_pool')['tip_opened_at'] is not None
      and events('directory.talent_pool', 'open') == 1, 'a tip read is counted once per person')
page(c, u('directory.talent_pool'))
check(events('directory.talent_pool', 'used') == 1, 'opening the feature after reading its tip counts for the tip')
c.post('/tips/opened', base_url=HOST, json={'key': 'places_finder.dashboard'}, headers={'Origin': HOST})
page(c, '/find-leads/')
check(events('places_finder.dashboard', 'open') == 1 and events('places_finder.dashboard', 'used') == 0,
      'but not a feature they had already been using before they read it')
c.post('/tips/opened', base_url=HOST, json={'key': 'no.such.tip'}, headers={'Origin': HOST})
check(row('no.such.tip') is None, 'a key that is not a tip is ignored')

# A menu tip read, then its item clicked: the click's page can land first.
page(c, u('team.availability'))
c.post('/tips/opened', base_url=HOST, json={'key': 'team.availability', 'source': 'menu'}, headers={'Origin': HOST})
check(events('team.availability', 'used') == 1,
      'a menu tip read that arrives just after the visit it prompted still counts for the tip')
page(c, u('invoices.index'))
c.post('/tips/opened', base_url=HOST, json={'key': 'invoices.index', 'source': 'page'}, headers={'Origin': HOST})
check(events('invoices.index', 'open') == 1 and events('invoices.index', 'used') == 0,
      "but the ⓘ on a page they are already on does not -- they were there before they read it")


print('\n5. Locked features, and other people')
fresh_postgres.set_company_plan(SLUG, 'pro')
c = owner()
code, html = page(c, '/')
dots = dotted(html)
check('Commercial' not in dots and code == 200, f'a feature the plan does not include is never dotted ({dots})')
c.post('/tips/opened', base_url=HOST, json={'key': 'quotes.index', 'source': 'menu'}, headers={'Origin': HOST})
check(row('quotes.index') is None and events('quotes.index', 'open') == 0,
      'nor is reading its tip counted: they could not open it, so it says nothing about the tip')
fresh_postgres.set_company_plan(SLUG, 'scale')

from auth import _auth_fingerprint
def make_dispatcher():
    u = User(name='Dee Dispatch', username=f'dee@{SLUG}.test', role='dispatcher', active=True)
    u.set_password('a-perfectly-fine-password')
    db.session.add(u)
    db.session.commit()
    return u.id, _auth_fingerprint(u.password_hash)
uid, fp = in_tenant(make_dispatcher)
d = app.test_client()
with d.session_transaction(base_url=HOST) as sess:
    sess.update(logged_in=True, role='dispatcher', user_id=uid, user_name='Dee Dispatch',
                auth_fingerprint=fp, tenant_slug=SLUG)
code, html = page(d, '/bookings/')
check(code == 200 and row('bookings.index', f'u{uid}') is not None and row('rentals.index', f'u{uid}') is None,
      'each person has their own record: what the owner found is not what the dispatcher found')

uid2, fp2 = in_tenant(lambda: (lambda u: (db.session.add(u), u.set_password('a-perfectly-fine-password'),
                                          db.session.commit(), (u.id, _auth_fingerprint(u.password_hash)))[-1])(
    User(name='Sam Sales', username=f'sam@{SLUG}.test', role='sales', active=True)))
s = app.test_client()
with s.session_transaction(base_url=HOST) as sess:
    sess.update(logged_in=True, role='sales', user_id=uid2, user_name='Sam Sales',
                auth_fingerprint=fp2, tenant_slug=SLUG)
r = s.post('/tips/opened', base_url=HOST, json={'key': 'lead.stages'}, headers={'Origin': HOST})
check(r.status_code == 204, 'a Sales login, held to its module, can still count a tip it read')


print('\n6. Recording a visit never saves what the page meant to throw away')
def dirty_render():
    from flask import session
    import navigation
    with app.test_request_context('/', base_url=HOST):
        session.update(logged_in=True, role='owner', user_id=990077)
        BusinessSetting.set('business_name', 'Changed But Not Saved')   # pending, uncommitted
        adoption.note_visit('bookings.index', navigation.sidebar('owner'))
        db.session.rollback()
    return BusinessSetting.get('business_name')
name = in_tenant(dirty_render)
check(name != 'Changed But Not Saved' and row('bookings.index', 'u990077') is not None,
      f'the visit is saved on its own connection; the page\'s unsaved change is not ({name!r})')


print('\n7. The console report')
TAG = secrets.token_hex(4)
EMAIL, PW = f'tips-{TAG}@example.com', 'a-real-console-password-1'
control_plane.add_console_user(ENGINE, EMAIL, 'Tips Tester', PW, role='helper')
k = app.test_client()
k.post('/console/login', data={'email': EMAIL, 'password': PW})
r = k.get('/console/funnel/tips?window=all')
body = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', r.get_data(as_text=True)))
check(r.status_code == 200 and 'Cleaners near you' in body and 'Help tips' in body,
      'lists each tip, from the Funnel tabs')
m = re.search(r'Cleaners near you directory\.talent_pool (\d+) (\d+) \((\d+)%\)', body)
check(m is not None and m.groups() == ('1', '1', '100'),
      f'read by one person, who then opened it: 1, 1 (100%) ({m.groups() if m else body[:0]})')
m = re.search(r'Rentals rentals\.index (\d+) (\d+) (\d+) (\d+) \((\d+)%\) (\d+)', body)
check(m is not None and m.groups() == ('0', '0', '1', '1', '100', '0'),
      f'and each "Did you know?": shown to one person, who followed it ({m.groups() if m else None})')
# A window counts the people who read in it, and what those people did.
now = datetime.utcnow()
with ENGINE.begin() as conn:
    for person, event, days in (('early', 'open', 40), ('early', 'used', 10),
                                ('inside', 'open', 5), ('inside', 'used', 3),
                                ('early', 'suggested', 45), ('early', 'clicked', 20)):
        conn.execute(control_plane.tip_events.insert().values(
            slug=SLUG, person=person, role='owner', tip='faq.index', event=event,
            created_at=now - timedelta(days=days)))
got = control_plane.tip_report(ENGINE, since=now - timedelta(days=30)).get('faq.index', {})
check(got == {'open': 1, 'used': 1},
      f'in the last 30 days: one read, one opened -- not a success from a read before the window ({got})')
got = control_plane.tip_report(ENGINE).get('faq.index', {})
check(got == {'open': 2, 'used': 2, 'suggested': 1, 'clicked': 1}, f'and all time, everyone ({got})')
with ENGINE.begin() as conn:
    conn.execute(text('DELETE FROM public.console_users WHERE email = :e'), {'e': EMAIL})

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ A few features at a time, per person, and the tips that work are the ones you can see working.')
