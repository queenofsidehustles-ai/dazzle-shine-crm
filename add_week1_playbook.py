"""Put the week-1 step-by-step plan into the "90-Day Day-by-Day Plan" playbook.

Two changes to that one playbook, in place -- same row, same title:

  * The seven W1 rows of the day-by-day table get sharper actions. Each row's
    day, weekday, phase and signup numbers are kept exactly as they are in
    the console (they may have been hand-edited), so the running totals from
    Day 8 on still add up. Only the Action cell changes.
  * A "Week 1 — step by step" section goes in just above the table: the
    tracking links (attribution.py records them at signup), the founding
    code, and each day's steps.

Run once, the same way seed_growth_playbook.py is:

    railway run python3 add_week1_playbook.py            # writes it
    railway run python3 add_week1_playbook.py --dry-run  # shows it, writes nothing

Safe to run again: if the section is already there it does nothing. If the
table does not look the way this expects (hand-edited past recognition), it
touches nothing and says so.
"""
import re
import sys

TITLE = '90-Day Day-by-Day Plan'
MARKER = '### Week 1 — step by step'

ACTIONS = {
    1: 'Create FOUNDING500 in Console → Discounts ($79 off, forever, 500 uses, ends Day 21); '
       'one tagged link per channel; personal texts/DMs to the top 20 contacts '
       '(see Week 1 step by step).',
    2: 'Answer Day 1 replies first; batch 2 (next 30–50 contacts); give every new owner '
       'their referral link (their Billing page); book setup calls.',
    3: 'Announce the founding cohort to the Queen of Side Hustles audience: email + one '
       'post per platform, each on its own tagged link.',
    4: "Join 15–20 Facebook/Reddit groups, note each group's promo rules, post 3–5 "
       'genuinely useful answers a day, no links.',
    5: 'Choose the lifetime-deal tier (no texts or Nana), submit the AppSumo-style '
       'application; line up a Product Hunt hunter for the week-3 launch.',
    6: 'One personal founder post (the Dazzle & Shine story) on the "personal" link; '
       'reply to every comment.',
    7: 'Review in Console → Funnel: signups, activations, where signups came from, '
       'referrals, jobs run; write 3 decisions for week 2.',
}

WEEK1 = r"""### Week 1 — step by step

**Tracking links.** Tags work on any akyehq.com page, and each signup shows up in Console → Funnel → "Where signups came from". Use exactly these tags, so each channel always adds up in one row:

| Channel | Link |
| --- | --- |
| Texts / DMs | `akyehq.com/?utm_source=sms&utm_medium=text&utm_campaign=founding` |
| Newsletter | `akyehq.com/how-to-start-a-cleaning-business?utm_source=newsletter&utm_medium=email&utm_campaign=founding` |
| Facebook | `akyehq.com/?utm_source=facebook&utm_medium=social&utm_campaign=founding` |
| Instagram | `akyehq.com/?utm_source=instagram&utm_medium=social&utm_campaign=founding` |
| Founder's personal posts | `akyehq.com/?utm_source=personal&utm_medium=social&utm_campaign=founding` |
| Referrals | each owner's own `akyehq.com/r/<their address>`, shown on their Billing page |

**The founding code.** The offer is "first 500 free forever on Pro" (normally $79/month), closing at the week-3 deadline. Make it **$79 off, forever** — not 100% off. Console codes are not tied to one plan, so a 100% code would also make Scale ($249) free forever; $79 off makes Pro $0 and Scale $170.
- Checkout asks for a card even when the total is $0. Either say "card needed to claim, never charged" in the copy, or have checkout skip the card at $0 (a small code change) before Day 3's announcement.
- Solo stays free for everyone with no card; the code is only for owners who want Pro.

**Day 1 — Mon**
1. Offer (30 min): Console → Discounts → new code FOUNDING500: $79 off, duration forever, max 500 uses, expires at the end of Day 21. Check it at checkout with a test account, then mark that account Test.
2. Pick the 20 (30 min): cleaning-business owners you know first, then people who know several owners (suppliers, bookkeepers, coaches).
3. Send (1–2 hrs): a personal message each, never a group text, on the Texts/DMs link. "I built software for cleaning companies: scheduling, crew pay and a free booking page. The first 500 companies get the Pro plan free forever (normally $79/month). Would you try it, or do you know an owner who would?"
4. Same day: reply within the hour; offer to set their account up with them on a call.
- Done when: the code works at checkout and all 20 are sent.

**Day 2 — Tue**
1. Answer every Day 1 reply before sending anything new.
2. Batch 2: the next 30–50 contacts, the same message plus "Know another owner? Send them your link."
3. Show every owner who signed up their Billing page → "Refer another cleaning business". Reward: one free month of Scale when someone they referred activates. Check Funnel → Referrals, and create a one-month code in Console → Discounts.
4. Book a setup call with every Day 1 signup: the 14-day trial only starts when they assign their first job, and "your free-forever spot locks in once you finish setup" makes setup part of the offer.
- Done when: every contact is messaged, and every signup has a call booked or a setup email sent.

**Day 3 — Wed**
1. Angle: "Start or run your cleaning business on free software." Free Solo for anyone, with no card; the founding code for owners who want Pro, until Day 21.
2. Email the audience on the Newsletter link.
3. Social: one post per platform, each on its own link.
4. Clear the reply queue by the evening.

**Day 4 — Thu**
1. Pick 15–20 groups where owners actually post: cleaning-business owner Facebook groups, r/CleaningBusinessOwners, r/smallbusiness, local owner groups.
2. Note each group's rules: self-promotion allowed? a promo day? links need admin approval?
3. Post 3–5 genuinely useful answers a day (pricing a job, paying crew, hiring), with no links.
4. Write down repeated questions: they become week 2 posts.
- Expect about 0 signups: this is groundwork for weeks 2–3.

**Day 5 — Fri**
1. Choose the lifetime-deal tier first. A lifetime deal on Pro means paying for its texts (1,000 a month) and Nana's answers forever, out of one payment. Offer it only on a tier without texts and Nana, or cap them.
2. Submit the AppSumo-style application; approval takes weeks.
3. Product Hunt: find a hunter; draft the tagline, gallery and first comment for the week-3 launch.
- Expect about 0 signups.

**Day 6 — Sat**
1. One personal post on why you built Akye (the Dazzle & Shine story), on the personal link.
2. Reply to comments through the day.

**Day 7 — Sun (1 hr)**
1. Console → Funnel, 30-day window: Signed up, Activated, Paying. Mark any test signups as Test first.
2. "Where signups came from": which link brought signups, and more importantly activations.
3. "Referrals": who sent whom, and which rewards are owed.
4. Jobs run through the platform this week, per company: the number that matters.
5. Write 3 decisions for week 2: which channel to double, which message to rewrite, which setup step to fix.
"""

_ROW = re.compile(r'^\|\s*([1-7])\s*\|\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*\|\s*W1\b')
_HEADER = re.compile(r'^\|\s*Day\s*\|\s*Weekday\s*\|')


def apply(content):
    """(new content, message). new content is None when nothing should change."""
    if MARKER in content:
        return None, 'already there — the Week 1 section is in this playbook.'

    lines = content.split('\n')
    rows = {}
    for i, line in enumerate(lines):
        m = _ROW.match(line)
        if m:
            rows.setdefault(int(m.group(1)), []).append(i)
    if sorted(rows) != list(range(1, 8)) or any(len(v) != 1 for v in rows.values()):
        return None, ('the W1 rows (days 1–7) are not all there exactly once — '
                      'not touching it. Edit it by hand in the console instead.')

    for day, (i,) in rows.items():
        cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
        if len(cells) != 6:
            return None, (f'day {day} does not have 6 columns — not touching it. '
                          'Edit it by hand in the console instead.')
        cells[3] = ACTIONS[day]
        lines[i] = '| ' + ' | '.join(cells) + ' |'

    header = next((i for i, line in enumerate(lines) if _HEADER.match(line)), None)
    if header is None or header > min(i for (i,) in rows.values()):
        return None, 'no table header above the W1 rows — not touching it.'
    lines[header:header] = WEEK1.strip().split('\n') + ['']
    return '\n'.join(lines), 'added the Week 1 section and updated the 7 W1 rows.'


def main(argv):
    import control_plane
    import provisioning

    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    docs = [d for d in control_plane.all_console_docs(engine) if d['title'] == TITLE]
    if not docs:
        print(f'  ❌ no playbook titled {TITLE!r} found — nothing to do.')
        return 1
    doc = docs[0]

    new, message = apply(doc['content'])
    if new is None:
        print(('  ⏭  ' if message.startswith('already') else '  ❌ ') + message)
        return 0 if message.startswith('already') else 1
    if '--dry-run' in argv:
        print(new)
        print(f'\n  (dry run) would have {message}')
        return 0
    control_plane.update_console_doc(engine, doc['id'], doc['title'], new)
    print(f'  ✅ {message}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
