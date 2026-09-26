"""add_week1_playbook.py: the week-1 plan goes into the 90-day playbook in place.

Checked against the playbook exactly as seed_growth_playbook.py wrote it, and
as it looks after the owner's own edit of the Day 1 row, because the script
runs against whatever is live in the console, not against the seed.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import add_week1_playbook as w1
import seed_growth_playbook as seed

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SEEDED = dict(seed.DOCS)[w1.TITLE].strip()

print('\n1. On the playbook as seeded')
new, msg = w1.apply(SEEDED)
check(new is not None, f'it applies ({msg})')
check(new.count(w1.MARKER) == 1, 'the Week 1 section is added once')
check(new.index(w1.MARKER) < new.index('| Day | Weekday |'), 'above the table')
check(new.index('How to use this table') < new.index(w1.MARKER),
      'after the "How to use this table" paragraph')
rows = [l for l in new.split('\n') if w1._ROW.match(l)]
check(len(rows) == 7, 'still 7 W1 rows')
check(rows[0].endswith('| 15 | 15 |') and rows[6].endswith('| 14 | 100 |'),
      'signup numbers and running totals kept')
check('FOUNDING500' in rows[0] and 'referral link' in rows[1], 'actions replaced')
check('| 8 | Mon | W2' in new and new.split('| 8 | Mon | W2')[1] == SEEDED.split('| 8 | Mon | W2')[1],
      'everything from Day 8 on is untouched')
check(new.replace(w1.WEEK1.strip() + '\n\n', '').split('| Day | Weekday |')[0]
      == SEEDED.split('| Day | Weekday |')[0], 'nothing above the table is lost')

print('\n2. Run twice, nothing doubles')
again, msg = w1.apply(new)
check(again is None and msg.startswith('already'), 'second run does nothing')

print("\n3. On the owner's hand-edited Day 1 row")
edited = SEEDED.replace(
    '| 1 | Mon | W1 — Prep & warm activation | Lock founding-cohort offer terms + UTM tracking links; send warm texts/DMs to top 20 contacts. | 15 | 15 |',
    '| 1 | Mon | W1 — Prep & warm activation | 1. Lock founding-cohort offer terms  2. UTM tracking links; 3. Send warm texts/DMs to top 20 contacts. | 15 | 15 |')
check(edited != SEEDED, 'the edited version differs from the seed')
new2, msg = w1.apply(edited)
check(new2 is not None and 'FOUNDING500' in new2, f'still applies ({msg})')

print('\n4. A table it does not recognise is left alone')
broken = '\n'.join(l for l in SEEDED.split('\n') if not l.startswith('| 4 | Thu'))
check(w1.apply(broken)[0] is None, 'a missing day: untouched')
check(w1.apply(SEEDED.replace('| 3 | Wed | W1 — Prep & warm activation | Announce',
                              '| 3 | Wed | W1 — Prep & warm activation | A | B | Announce'))[0] is None,
      'a row with the wrong number of columns: untouched')

print('\n5. The section says what the product actually does')
check('$79 off' in w1.WEEK1 and '100% code would also make Scale' in w1.WEEK1,
      'the code is $79 off, and says why not 100%')
check('/r/<their address>' in w1.WEEK1 and 'utm_source=sms' in w1.WEEK1,
      'uses the tracking and referral links that exist')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ The week-1 plan lands in the playbook without disturbing the rest of it.')
