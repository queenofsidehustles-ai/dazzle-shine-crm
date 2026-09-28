"""A cleaning company can set its own prices.

It could not. There were two pricing systems and the settings page showed the
wrong one.

Every quote reads a list of prices, one per house size — `std_price_3_2` and
so on. The settings page edited `{service}_base`, `{service}_per_extra_bed`
and `{service}_per_extra_bath`, a formula from an older version that nothing
had read for a long time. So:

  * typing into those boxes changed nothing a customer was ever quoted
  * the list that does drive every quote could not be edited anywhere at all
  * a company in another city was permanently stuck on the prices this
    software was first built with

The owner of a cleaning company looked at that page and said it confused her.
It confused her because it was lying.

The rules this holds:

  * saving on that page changes what a real customer is quoted
  * one question anybody can answer fills in a whole list they can then edit
  * deep and move-out follow the standard price, so there is one list not three
  * a typo in one box does not lose the others
"""
import os, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/pg.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
import pricing

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


def quote(service='standard', beds=3, baths=2):
    with app.app_context():
        return pricing.calculate_price(service_type=service, bedrooms=beds,
                                       bathrooms=baths)


print('\n1. The page asks something a cleaning company can answer')
page = c.get('/settings/pricing').data.decode('utf8', 'replace')
check('What do you charge for a standard clean' in page,
      'it asks what they charge for one specific house')
check('std_price_3_2' in page, 'and shows the list, one row per size')
check('fillgrid' in page, 'with an offer to fill the rest in from that one price')

print('\n2. The boxes that did nothing are gone')
# They saved to settings nothing read. Leaving them would be worse than
# useless: somebody sets a price, believes it, and quotes from it.
check('per_extra_bed' not in page, 'no per-bedroom box')
check('per_extra_bath' not in page, 'no per-bathroom box')


print('\n3. Saving changes what a customer is actually quoted')
# The assertion that matters. Everything else on the page is presentation.
before = quote(beds=3, baths=2)
c.post('/settings/pricing', data={
    'std_price_3_2': '275', 'deep_multiplier': '1.6', 'moveout_multiplier': '1.9',
}, follow_redirects=True)
after = quote(beds=3, baths=2)
check(after == 275.0, f'a 3 bed / 2 bath standard is now $275 (was ${before})')
check(after != before, 'which is not what it was before')


print('\n4. Deep and move-out follow, so there is one list and not three')
check(abs(quote('deep', 3, 2) - 275 * 1.6) < 1,
      f"deep is 1.6x the standard (${quote('deep', 3, 2)})")
check(abs(quote('moveout', 3, 2) - 275 * 1.9) < 1,
      f"move-out is 1.9x (${quote('moveout', 3, 2)})")

c.post('/settings/pricing', data={'deep_multiplier': '2.0'}, follow_redirects=True)
check(abs(quote('deep', 3, 2) - 275 * 2.0) < 1,
      'and changing the multiplier moves every deep clean at once')


print('\n5. Every size can be set, not only the common one')
sizes = pricing.matrix_sizes()
check(len(sizes) >= 8, f'{len(sizes)} house sizes are covered')
c.post('/settings/pricing', data={f'std_price_{b}_{ba}': str(100 + 10 * i)
                                  for i, (b, ba) in enumerate(sizes)},
       follow_redirects=True)
with app.app_context():
    got = [pricing.get_std_price(b, ba) for b, ba in sizes]
check(got == [100 + 10 * i for i in range(len(sizes))],
      'each one saved independently')


print('\n6. One bad box does not lose the others')
# Somebody types "abt" into a price. The rest of their afternoon should not
# be undone by it.
with app.app_context():
    keep = pricing.get_std_price(3, 2)
c.post('/settings/pricing', data={'std_price_3_2': 'not a number',
                                  'std_price_2_2': '199'}, follow_redirects=True)
with app.app_context():
    check(pricing.get_std_price(3, 2) == keep,
          f'the unreadable one is left as it was (${keep})')
    check(pricing.get_std_price(2, 2) == 199.0,
          'and the good one alongside it still saved')


print('\n7. A suggestion is built from the one price they know')
m = pricing.suggest_matrix(180, (2, 2))
check(m[(2, 2)] == 180, 'the anchor comes back exactly as typed')
check(m[(1, 1)] < 180 < m[(5, 4)], 'smaller houses cost less and bigger ones more')
check(all(v % 5 == 0 for v in m.values()),
      'and every suggestion is a round number — nobody quotes $237.42')


print('\n8. Looking at the page counts as reviewing prices')
# The getting-started list asks somebody to check their prices. Saving the
# page is the moment that happened.
import onboarding
with app.app_context():
    step = [s for s in onboarding.journey() if s['key'] == 'pricing'][0]
check(step['done'], 'the getting-started step ticks once prices are saved')


if failures:
    print(f'\n\n❌ {len(failures)} pricing-setup check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ A business can set its own prices, and they take effect.\n')
