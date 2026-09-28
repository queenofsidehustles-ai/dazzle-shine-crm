"""The Week 1 playbook: its own document, in the owner's own terms.

Seeded by seed_growth_playbook.py like the other playbooks, so running the
seed again on production adds this one title and leaves the four that are
already there alone (tests/test_console_playbooks.py covers that skip).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import seed_growth_playbook as seed

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


TITLE = 'Week 1 — Prep & Warm Activation'
titles = [t for t, _ in seed.DOCS]
docs = dict(seed.DOCS)

print('\n1. A separate playbook, next to the 90-day plan')
check(TITLE in titles, 'the Week 1 playbook is in the seed')
check(titles.index(TITLE) == titles.index('90-Day Day-by-Day Plan') + 1,
      'right after the 90-Day Day-by-Day Plan')
check(len(titles) == len(set(titles)), 'no duplicate titles')
week1 = docs[TITLE]

print("\n2. In the owner's terms")
check('## Day 1 — Mon: 1. Lock founding-cohort offer terms 2. UTM tracking links; '
      '3. Send warm texts/DMs to top 20 contacts.' in week1,
      "Day 1 is the owner's own wording")
check('FOUNDING500' not in week1 and '$79 off' not in week1 and 'Day 21' not in week1,
      'no offer terms are decided for the owner')
check('one free month of Scale' in week1, 'the referral reward the owner kept')
check('**100 signups by Day 7**' in week1, "the 90-day plan's week-1 target")
check('Food Club' not in week1, 'about akyehq.com only')

print('\n3. It points at what the product actually has')
check('Console → Funnel' in week1 and 'Where signups came from' in week1,
      'the Funnel pages that exist')
check('utm_source=sms' in week1 and '/r/' in week1, 'the tracking and referral links that exist')
check('assigns its first job' in week1, "activation as the console measures it")

print('\n4. Every table renders as a table')
for block in re.findall(r'((?:^\|.*\|\n)+)', week1 + '\n', re.M):
    rows = [r for r in block.strip().split('\n')]
    widths = {r.count('|') for r in rows}
    check(len(widths) == 1 and re.match(r'^\|( --- \|)+$', rows[1]),
          f'{rows[0][:50]}… has a divider row and {len(rows) - 2} rows of equal width')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Week 1 is its own playbook, in the owner\'s terms.')
