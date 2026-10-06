"""The lead finder costs real money per search, so it has a fuse.

Google bills per search whatever comes back, and the fields this app asks for
-- phone number, website, rating -- put it in Google's dearest tier. A VA
clicking all afternoon on a $79 plan is the one line item here that can outrun
the revenue it sits on.

So the plan includes a number of searches a month. It is deliberately high:
200 searches is up to about 4,000 businesses, which no cleaning company will
exhaust honestly. It is a fuse, not a meter.

What is worth protecting here:

  * the cap counts searches, because that is what Google charges for, while
    the owner is shown businesses, because that is what she came for
  * a company on its own Google key is not rationed and not counted -- their
    account, their bill
  * a demo company never reaches Google at all, so nothing is spent
  * at the cap no call is made, which is the entire point
  * the free plan has no lead finder, and the POST is gated as well as the
    page -- a hidden button is decoration, the URL is still there
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/leadcap.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
import entitlements as E
import places_finder as finder
import integrations

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


def set_plan(name):
    from models import BusinessSetting
    BusinessSetting.set('plan', name)
    BusinessSetting.set('plan_status', 'active')
    db.session.commit()
    E._clear_cache()


def spend(n):
    for _ in range(n):
        E.record_lead_search()


with app.app_context():
    db.create_all()

    print('1. Every plan gets what it pays for')
    for plan, cap in (('solo', 0), ('pro', 200), ('scale', 600)):
        set_plan(plan)
        check(E.limit('lead_searches_per_month') == cap,
              f'{plan} is capped at {cap} searches a month')
    set_plan('pro')
    check(E.remaining('lead_searches_per_month') * 20 == 4000,
          '200 searches is up to about 4,000 businesses — the number she is shown')

    print('\n2. Searches are counted, and the fuse blows exactly once')
    spend(199)
    check(E.at_limit('lead_searches_per_month') is False, '199 of 200 is still under')
    check(E.remaining('lead_searches_per_month') == 1, 'and one is left')
    spend(1)
    check(E.at_limit('lead_searches_per_month') is True, '200 of 200 is at the cap')

    print('\n3. Whose allowance it comes out of')
    real_present, real_stored = finder.api_key_present, integrations._stored

    finder.api_key_present = lambda: False
    check(finder.allowance() == (False, False),
          'a demo company never reaches Google, so nothing is spent or barred')

    finder.api_key_present = lambda: True
    integrations._stored = lambda name: 'AIza-their-own' if name == 'google_places_api_key' else ''
    check(finder.own_key() is True, 'a company that saved its own key is on its own key')
    check(finder.allowance() == (False, False),
          'so it is not capped at the cap, and not counted against us')

    integrations._stored = lambda name: ''
    check(finder.allowance() == (True, True),
          'but on the platform key, at the cap, the search is refused before the call')

    before = E.usage('lead_searches_per_month')
    set_plan('scale')
    check(finder.allowance() == (False, True),
          'and Scale, with 600, may carry on where Pro could not')
    check(E.usage('lead_searches_per_month') == before,
          'asking the question costs nothing — only a real search is counted')

    finder.api_key_present, integrations._stored = real_present, real_stored

    print('\n4. The free plan cannot use it at all')
    set_plan('solo')
    check(E.can('lead_finder') is False, 'Solo has no lead finder')
    check(E.at_limit('lead_searches_per_month') is True,
          'and a cap of nought is reached before the first search')
    src = open('blueprints/places_finder.py', encoding='utf-8').read()
    search_route = src[src.index("@places_finder_bp.route('/search'"):]
    search_route = search_route[:search_route.index('def search(')]
    check("@requires_plan('lead_finder')" in search_route,
          'and the POST is gated too, not only the page it is posted from')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
