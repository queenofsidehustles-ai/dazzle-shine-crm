"""The booking page explains itself, and its checklist step tells the truth.

Two faults, and the second one is why the first went unnoticed.

**The step ticked itself.** "Share your booking page" was marked done the
first time anybody opened `/book` — and `/book` was where that step's own
button went. So clicking "See your page" completed the step, and the list then
showed a line through "Share your booking page" for a business that had shared
nothing. The owner saw it crossed out, knew she had never made a booking page,
and could not tell what it was claiming she had done.

A checklist item that completes itself when you look at it is worse than no
checklist item: it is a list that lies about you.

**And it explained nothing.** The step sent people to the customer-facing page,
which has no text on it saying what it is or what to do with it. The first
person outside the company to try the product had to have it explained in a
conversation — and anything explained in a conversation is a screen that has
not been written.

So the step now points at a screen that answers the questions people actually
ask: what is it, do I have to build it (no), where do I put the link, and what
is the widget for (a website you already have, and most people never need it).
And it is ticked by copying the link or saying so — something a person does on
purpose.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/bp.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import onboarding

app = create_app()
c = app.test_client()
with c.session_transaction() as sess:
    sess['logged_in'] = True
    sess['role'] = 'owner'

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def words(html):
    """The prose, with line wrapping taken out.

    Asserting on raw HTML means asserting on where somebody's editor happened
    to wrap a sentence — so a reflow that changes nothing a reader sees turns
    the suite red. Collapse the whitespace and ask about the words.
    """
    import re
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


def step_done():
    with app.app_context():
        return bool([s for s in onboarding.journey()
                     if s['key'] == 'booking_page'][0]['done'])


print('\n1. Looking at something is not doing it')
check(not step_done(), 'the step starts undone')
check(c.get('/book').status_code == 200, 'the public booking page opens')
check(not step_done(),
      'and opening it does NOT tick the step — this was the bug')
check(c.get('/settings/booking-page').status_code == 200, 'the explainer opens')
check(not step_done(), 'nor does reading about it')


print('\n2. Copying the link is doing it')
c.post('/settings/booking-page/shared')
check(step_done(), 'saying you have shared it ticks the step')
c.post('/settings/booking-page/shared', data={'undo': '1'})
check(not step_done(),
      'and it can be unticked — a wrong tick must not be permanent')
c.post('/settings/booking-page/shared')


print('\n3. The step sends people somewhere that explains it')
with app.app_context():
    s = [x for x in onboarding.journey() if x['key'] == 'booking_page'][0]
check(s['link'] == '/settings/booking-page',
      f"it points at the explainer, not the raw page ({s['link']})")
check('/book' != s['link'], 'and no longer at the customer-facing page')
check('already have one' in s['why'].lower() or 'you already' in s['why'].lower(),
      'and says they already have one rather than implying they must build it')


print('\n4. The page answers what it is')
raw = c.get('/settings/booking-page').data.decode('utf8', 'replace')
page = words(raw)
check('What it is' in page, 'it opens by saying what it is')
check('book you themselves' in page or 'book themselves' in page,
      'in terms of what a customer does')
check('do not have to build it' in page,
      'and says plainly they do not have to build it — the question that was asked')
check('already exists' in page, 'because it already exists')


print('\n5. It says where to put the link')
for place in ('Facebook', 'Google Business', 'email signature'):
    check(place in page, f'{place} is named as a place to put it')
check('bookurl' in raw and '/book' in page, 'the link itself is on the page')
check('Copy link' in page, 'with a button to copy it')
check('Preview' in page, 'and a way to look at it first')


print('\n6. The widget is explained, and de-mystified')
# The other half of what had to be explained by hand. Most people do not need
# it, and saying so is more useful than another paragraph about how it works.
check('do not need this' in page.lower() or 'You do not need this' in page,
      'it says outright that most people do not need the widget')
check('already have a website' in page,
      'and who it is actually for')
for host in ('Wix', 'Squarespace', 'WordPress', 'GoDaddy'):
    check(host in page, f'{host} is named, so the instruction is followable')
check('Embed' in page and 'Custom HTML' in page,
      'naming the block to look for, which is the bit people get stuck on')
check('send them that one line' in page,
      'and what to hand a website person')


print('\n7. Nothing is explained in two places')
# The embed instructions used to live at the bottom of Business Settings,
# where they went unread. Two copies would drift.
biz = c.get('/settings/business').data.decode('utf8', 'replace')  # raw: ids and urls
check('embed.js' not in biz,
      'business settings no longer carries its own copy of the snippet')
check('/settings/booking-page' in biz, 'it points at the one screen instead')
check('embedsnippet' not in biz,
      'and no wiring is left behind looking for an element that moved')


print('\n8. A free plan is told the truth about the widget')
import entitlements
with app.app_context():
    real = entitlements.can
    entitlements.can = lambda f: False
    try:
        free = words(c.get('/settings/booking-page').data.decode('utf8', 'replace'))
    finally:
        entitlements.can = real
check('Pro' in free, 'the widget is marked as a paid feature')
check('carries our name' in free,
      'and what the free page does instead is stated, not hidden')
check('/book' in free,
      'while the link itself still works — that is not what is gated')


if failures:
    print(f'\n\n❌ {len(failures)} booking-page check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ The booking page explains itself, and the tick means something.\n')
