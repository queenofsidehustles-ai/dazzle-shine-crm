"""The menu: thirty-one sidebar links regrouped into sixteen.

Merging pages into tabs is only safe if nothing became unreachable and no old
address broke, so this walks every admin page rather than trusting the map in
navigation.py to match the app.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/nav.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
import navigation
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    endpoints = {r.endpoint: r for r in app.url_map.iter_rules()}

    print('\n1. Every page named in the menu actually exists')
    named = set()
    for _, items in navigation.SECTIONS:
        for ep, _i, _l, _o, tabs in items:
            named.add(ep)
            named.update(t[0] for t in tabs)
    named |= set(navigation.BELONGS_TO) | set(navigation.BELONGS_TO.values())
    missing = sorted(n for n in named if n not in endpoints)
    check(not missing, f'no menu entry points at a route that does not exist ({missing})')

    print('\n2. The menu is shorter than it was')
    owner_items = sum(len(s['items']) for s in navigation.sidebar('owner'))
    check(owner_items <= 17, f'{owner_items} sidebar links for the owner, down from 31')

    print('\n3. Nothing the sidebar used to reach was dropped')
    # The full set of pages the old sidebar linked to, written out so that
    # deleting one from navigation.py fails here instead of silently.
    OLD_SIDEBAR = [
        'admin.dashboard', 'bookings.index', 'bookings.calendar', 'invoices.index',
        'messages.inbox', 'messages.sent_log', 'bookings.clients', 'leads.index',
        'places_finder.dashboard', 'commercial.index', 'quotes.index', 'discounts.index',
        'contractors.team', 'contractors.applications', 'interviews.admin_interviews',
        'team.availability', 'team.broadcast', 'money.pnl', 'money.job_economics',
        'money.expenses', 'contractors.payroll', 'commissions.index',
        'workorders.templates', 'sops.index', 'content.index', 'email_templates.index',
        'scripts.index', 'admin.reports', 'settings.pricing', 'settings.connections',
        'team_logins.index',
    ]
    check(len(OLD_SIDEBAR) == 31, 'the old sidebar had 31 links')
    for ep in OLD_SIDEBAR:
        check(ep in named, f'{ep} is still in the menu')

    print('\n4. Two pages that were in no menu at all are now reachable')
    for ep in ('messages.templates', 'settings.commercial'):
        check(ep in named, f'{ep} has a home now')

    print('\n5. Every page lights up one sidebar item and knows its tabs')
    for ep in OLD_SIDEBAR + ['messages.templates', 'settings.commercial']:
        check(navigation.active_item(ep) is not None, f'{ep} lights up a sidebar item')

    print('\n6. A detail page keeps its parent lit, not a blank menu')
    check(navigation.active_item('bookings.detail') == 'bookings.index',
          'opening a booking keeps Bookings lit')
    check(navigation.active_item('messages.thread') == 'messages.inbox',
          'opening a conversation keeps Messages lit')
    check(navigation.active_item('contractors.staff_detail') == 'contractors.team',
          'opening a cleaner keeps Team lit')

    print('\n7. A team member never sees the owner-only pages')
    team_named = set()
    for s in navigation.sidebar('team'):
        for i in s['items']:
            team_named.add(i['endpoint'])
            team_named.update(t['endpoint'] for t in i['tabs'])
    for ep in ('money.pnl', 'admin.reports', 'settings.pricing', 'team_logins.index',
               'commissions.index', 'team.broadcast'):
        check(ep not in team_named, f'{ep} is hidden from a team login')
    check('bookings.index' in team_named, 'but they still get the day job — Bookings')

    print('\n8. A single-page section shows no tab bar')
    tabs, _ = navigation.tabs_for('bookings.calendar', 'owner')
    check(tabs == [], 'Calendar has no tabs — one tab is just the title twice')
    tabs, _ = navigation.tabs_for('money.pnl', 'owner')
    check(len(tabs) == 7, f'Money has its seven tabs (got {len(tabs)})')

    print('\n9. Every admin page still renders')
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    broken = []
    for ep in sorted(named):
        rule = endpoints[ep]
        if 'GET' not in rule.methods or rule.arguments:
            continue
        r = c.get(rule.rule)
        if r.status_code >= 500:
            broken.append((ep, r.status_code))
    check(not broken, f'no page 500s on the new layout ({broken})')

    print('\n10. The sidebar and tabs actually render into the page')
    html = c.get('/bookings/').get_data(as_text=True)
    check('section-tabs' in html, 'the tab bar is on a section page')
    check('sidebarScroll' in html, 'and the sidebar remembers where it was scrolled to')

print('\n🎉 Navigation checks passed.')
