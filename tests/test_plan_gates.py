"""The plans actually restrict something now.

Until this, the limits engine existed and nothing consulted it: the menu drew
padlocks and every URL behind them still worked. Charging $99 for a tier that
restricts nothing is charging for nothing.

Two directions to get wrong, and the second is the expensive one:

  * A free account reaching a paid feature — that is revenue quietly leaking.
  * A PAYING account being refused something it paid for — that is a customer
    who cancels, and tells people why.

So this checks both, and checks the server rather than the page: hiding a menu
item is decoration, and the person most likely to type the URL is the one who
just hit the wall.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/gates.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications

SMS_SENT = []
_real_sms_guard = None
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import BusinessSetting, Staff, User
import entitlements
import navigation

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def set_plan(plan):
    with app.app_context():
        BusinessSetting.set('plan', plan)
        BusinessSetting.set('plan_status', 'active')
        BusinessSetting.set('trial_ends_at', '')
        db.session.commit()
    entitlements._clear_cache()


def owner_client():
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'
        s['user_name'] = 'Owner'
    return c


with app.app_context():
    db.create_all()

print('\n1. Every page named as gated is actually gated on the server')
# Driven by the same map the menu draws from, so the two can never disagree
# about what is locked -- which is how a padlock ends up on a page that works.
set_plan('solo')
c = owner_client()
leaked = []
with app.app_context():
    endpoints = {r.endpoint: r for r in app.url_map.iter_rules()}
for endpoint, feature in sorted(navigation.MIN_PLAN.items()):
    if entitlements.can(feature):
        continue                       # free plan includes it; nothing to check
    rule = endpoints.get(endpoint)
    if rule is None or 'GET' not in rule.methods:
        continue
    r = c.get(str(rule), follow_redirects=False)
    if r.status_code == 200:
        leaked.append(f'{endpoint} ({feature})')
check(not leaked, f'no locked page returns content on the free plan ({leaked})')

print('\n2. A paying account is refused nothing it paid for')
# The expensive direction. A customer locked out of what they bought cancels.
set_plan('scale')
c = owner_client()
blocked = []
for endpoint, feature in sorted(navigation.MIN_PLAN.items()):
    rule = endpoints.get(endpoint)
    if rule is None or 'GET' not in rule.methods:
        continue
    r = c.get(str(rule), follow_redirects=False)
    if r.status_code in (302, 303) and '/upgrade' in (r.headers.get('Location') or ''):
        blocked.append(f'{endpoint} ({feature})')
check(not blocked, f'the top plan is sent to the upgrade page for nothing ({blocked})')

print('\n3. Pro gets Pro things and not Scale things')
set_plan('pro')
c = owner_client()
check(c.get('/contractors/applications').status_code == 200,
      'Pro can open the hiring pipeline')
check(c.get('/contractors/payroll').status_code == 200, 'and payroll')
r = c.get('/commercial/', follow_redirects=False)
check(r.status_code in (302, 303), 'but commercial accounts send it to upgrade')

print('\n4. The core loop is never gated — the whole freemium bet')
set_plan('solo')
c = owner_client()
for path, what in [('/bookings/', 'the jobs list'), ('/bookings/calendar', 'the calendar'),
                   ('/bookings/clients', 'the customer list'),
                   ('/workorders/templates', 'checklists'),
                   ('/messages/', 'the message inbox')]:
    r = c.get(path, follow_redirects=False)
    check(r.status_code == 200, f'a free account can still reach {what}')

print('\n5. The cleaner limit is enforced where a cleaner is created')
# Counted on ACTIVE cleaners. Somebody who left should not cost their old
# employer a plan tier for ever.
set_plan('solo')
with app.app_context():
    Staff.query.delete()
    db.session.commit()
c = owner_client()
# is_active matters: the limit counts cleaners who are actually on the roster,
# not everybody who ever was. Somebody who left should not cost their old
# employer a plan tier.
for i in range(2):
    c.post('/staff/new', data={'name': f'Cleaner {i}', 'pay_rate': '50',
                               'is_active': 'on'}, follow_redirects=True)
with app.app_context():
    check(Staff.query.filter_by(is_active=True).count() == 2,
          'two active cleaners are allowed on the free plan')

r = c.post('/staff/new', data={'name': 'One Too Many', 'pay_rate': '50',
                               'is_active': 'on'}, follow_redirects=False)
with app.app_context():
    check(Staff.query.filter_by(name='One Too Many').count() == 0,
          'the third is refused')
check(r.status_code in (302, 303) and '/upgrade' in (r.headers.get('Location') or ''),
      'and the person is sent somewhere that explains why')

print('\n6. Upgrading lets the third one through, with the first two untouched')
set_plan('pro')
c = owner_client()
c.post('/staff/new', data={'name': 'Third Cleaner', 'pay_rate': '50',
                           'is_active': 'on'}, follow_redirects=True)
with app.app_context():
    check(Staff.query.filter_by(is_active=True).count() == 3,
          'Pro allows the third cleaner')
    names = {s.name for s in Staff.query.all()}
    check('Cleaner 0' in names and 'Cleaner 1' in names,
          'and the two from before are still there')

print('\n7. Dropping back does not delete anybody')
# A limit must block the next thing, never eat what is already there.
set_plan('solo')
with app.app_context():
    check(Staff.query.filter_by(is_active=True).count() == 3,
          'three cleaners survive a downgrade to a 2-cleaner plan')
with app.app_context():
    # Inside a context on purpose: usage() deliberately returns 0 when it
    # cannot count, so that a database hiccup lets an owner carry on working
    # rather than blocking her. Asking outside a context therefore answers
    # "no limit" -- correct behaviour, wrong question.
    check(entitlements.at_limit('field_workers'), 'a fourth is blocked')
    check(entitlements.remaining('field_workers') == 0,
          'and remaining bottoms out at zero')

print('\n8. The free plan sends no texts, and says so')
set_plan('solo')
with app.app_context():
    ok, detail = notifications.send_sms('4075551212', 'hello')
check(ok is False, 'a text on the free plan is not sent')
check('Pro plan' in detail, f'and the reason is plain: {detail!r}')

print('\n9. Texting works again on Pro')
set_plan('pro')
with app.app_context():
    ok, detail = notifications.send_sms('4075551212', 'hello')
# Twilio is not configured in a test, so it fails for that reason instead --
# which is the point: it got past the plan check.
check('Pro plan' not in detail,
      f'Pro is not refused by the plan (stopped later, at Twilio: {detail[:48]!r})')

print('\n10. Every wall somebody hits is written down')
with app.app_context():
    from models import EntitlementDenial
    kinds = {d.feature for d in EntitlementDenial.query.all()}
check('sms' in kinds, 'the SMS refusal was recorded')
check(any(k.startswith('limit:') or k in entitlements.FEATURE_LABELS for k in kinds),
      f'along with the others hit during this run ({sorted(kinds)})')

print('\n\n✅ All plan-gate tests passed.\n')
