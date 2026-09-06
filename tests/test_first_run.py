"""What a new owner reads, and whether it agrees with itself.

Three things go wrong quietly and this suite is here to make them loud.

The page title used to default to the literal string "Dashboard", so a template
that forgot to set one claimed to be the dashboard. "Getting started" did
exactly that: its own menu item, highlighted, showing a page headed Dashboard
with the dashboard's contents. The default now comes from the menu word that
got you there, so the worst a forgetful template can do is agree with the link
that was clicked.

There were also two setup checklists. `onboarding.py` holds both, and four of
the eight items in one duplicate four of the six in the other, in different
words -- so the first screen told a brand-new owner "4 things still to do" and
"1 of 6 done" at the same time, and nothing explained the difference. A person
who is not confident with software reads a contradiction as their own mistake.
"""
import os, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/first.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

import navigation
from app import create_app

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


print('\n1. Clicking a menu word lands on a page wearing that word')
# Every sidebar destination, from the one place the menu is defined.
dests = [(ep, label) for _group, items in navigation.SECTIONS
         for ep, _icon, label, _owner, _tabs in items]
check(len(dests) >= 15, f'{len(dests)} destinations to check')

for ep, label in dests:
    check(navigation.title_for(ep) == label,
          f'{label!r} titles its page {label!r}')

print('\n2. A page that sets no title of its own is not "Dashboard"')
# The specific failure: Getting started is its own destination, and inherited a
# title claiming to be somewhere else entirely.
check(navigation.title_for('settings.getting_started') == 'Getting started',
      'Getting started says Getting started, not Dashboard')
check(navigation.title_for('admin.dashboard') == 'Dashboard',
      'and the dashboard still says Dashboard')

print('\n3. The words are the owner\'s, not the office\'s')
labels = {label for _ep, label in dests}
for gone, why in [('SOP Library', 'an owner who never worked in an office does not know "SOP"'),
                  ('Content Studio', 'says nothing about what comes out of it'),
                  ('VA commissions', '"VA" is a word learned inside this business')]:
    check(gone not in labels, f'{gone!r} is gone — {why}')
for kept in ('How-to guides', 'Social posts'):
    check(kept in labels, f'{kept!r} is on the menu')
check(any('Sales commissions' == t[1] for _g, items in navigation.SECTIONS
          for it in items for t in it[4]),
      "'Sales commissions' is the tab under Money")

print('\n4. Section pages no longer contradict the link that reaches them')
import re
TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
for f, gone in [('admin/sops.html', 'SOP Library'),
                ('admin/discounts.html', 'Discount Codes'),
                ('admin/find_leads.html', 'Find Leads'),
                ('admin/applications.html', 'Contractor Applications'),
                ('admin/pnl.html', 'Profit'),
                ('admin/content.html', 'Content Studio'),
                ('admin/email_templates.html', 'Email Templates'),
                ('admin/settings_pricing.html', 'Pricing Settings')]:
    body = open(os.path.join(TPL, f)).read()
    titles = re.findall(r'{%\s*block page_title\s*%}(.*?){%\s*endblock', body, re.S)
    check(not any(gone in t for t in titles),
          f'{f} does not overrule the menu with {gone!r}')

print('\n5. One setup tracker, not two')
base = open(os.path.join(TPL, 'base_admin.html')).read()
check('Finish setting up your CRM' not in base,
      'the second checklist banner is gone from every page')
check("NAV_TITLE" in base, 'and the title follows the menu')

# The full configuration list still exists -- it is reached from the Getting
# started card, which already ends with "the full setup list is there when you
# want it". Removing the banner removed the nagging, not the page.
started = open(os.path.join(TPL, 'admin/getting_started.html')).read()
check('setup' in started.lower(), 'the full setup list is still reachable from the card')

print('\n6. The reminder banner stays where somebody is deciding what to do')
check('ON_START' in base, 'the trial bar is scoped to the start pages')
check("'admin.dashboard', 'settings.getting_started'" in base,
      'namely the dashboard and getting started')

print('\n7. The price bar does not sit on top of the booking form')
# Measured on an iPhone-sized viewport: the bar was 189px of a 664px screen and
# the bathrooms dropdown sat at 497-544, behind it. One row instead of four
# stacked blocks brings the bar to 109px, which clears the field.
#
# The first attempt at this was wrong and is worth recording: hiding the price
# until one existed did nothing, because the form has defaults and prices
# itself on load. Size was the problem, not timing.
book = open(os.path.join(TPL, 'public/book.html')).read()
check('waiting' not in book, 'no hide-until-priced: the form prices itself on load')
check('.quote .money' in book, 'the price and the button share a row')
# Matched on the rule itself. Splitting on ".quote {" found the embed override
# further up the file instead, which is a different rule with a different job.
check('display:flex; align-items:center; gap:var(--s4); flex-wrap:wrap;' in book,
      'laid out as a row rather than a stack')
check('#bookform { padding-bottom' in book,
      'and the form can scroll clear of it')
check('flex:0 0 auto; margin:0;' in book, 'the button no longer takes a line of its own')

print('\n9. Settings is seven tabs, not nine')
settings_tabs = [t for _g, items in navigation.SECTIONS for it in items
                 if it[2] == 'Settings' for t in it[4]]
check(len(settings_tabs) == 7, f'{len(settings_tabs)} tabs across the top of Settings')
names = [t[1] for t in settings_tabs]
check('What is left to do' not in names,
      'the setup list is not a settings tab — it is the Getting started card')
check('Errors' not in names, 'nor is the fault log')
check(names[0] == 'Business', 'and the first tab is the one a new company needs first')

# Removed from the menu, not from the product: the alert email links straight
# to the error log, and the Getting started card links to the setup list.
eps = {r.endpoint for r in app.url_map.iter_rules()}
check('settings.setup' in eps, 'the full setup list is still a page')
check('settings.errors_page' in eps, 'and so is the error log')

print('\n10. Getting started climbs while there is setup left')
unfinished = navigation.sidebar('owner', setup_done=False)
top = unfinished[0]
check(top['heading'] == 'Dashboard', 'the first group is Dashboard')
check(any(i['endpoint'] == 'settings.getting_started' for i in top['items']),
      'and Getting started is in it while setup is unfinished')
check(sum(1 for g in unfinished for i in g['items']
          if i['endpoint'] == 'settings.getting_started') == 1,
      'appearing once, not twice')

finished = navigation.sidebar('owner', setup_done=True)
check(not any(i['endpoint'] == 'settings.getting_started'
              for i in finished[0]['items']),
      'and drops back down once the last step is done')
check(any(i['endpoint'] == 'settings.getting_started'
          for g in finished for i in g['items']),
      'still reachable, under Setup where it lives')

print('\n11. The pricing page does not open with forty fields')
pr = open(os.path.join(TPL, 'admin/settings_pricing.html')).read()
check('<details class="more"' in pr, 'the detail sits behind a fold')
check('{% if not first_time %} open{% endif %}' in pr,
      'closed on a first visit, open for a business that has been here before')
check(pr.index('Fill in the rest') < pr.index('<details class="more"'),
      'and the one question that fills the grid comes before the fold')

print('\n8. The pages still render')
c = app.test_client()
r = c.get('/book', headers={'Host': 'acme.akye.test'})
check(r.status_code in (200, 302, 404), f'/book responds ({r.status_code})')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ The menu, the page and the checklist all say the same thing.')
