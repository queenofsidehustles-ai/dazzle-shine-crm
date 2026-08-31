"""The trial reaches the person who is not looking at it.

The banner counts down honestly and only ever speaks to somebody who logs in.
The owner the 30-day cap was written for is precisely the one who signed up,
got busy, and has not been back — so without these emails the cap is not a
deadline, it is an ambush.

Four emails in a month, each saying something different. What this file is
really guarding is everything they must never do:

  * a paying customer must never be told their trial is ending
  * a suspended company must never be emailed at all
  * the same nudge must never go twice, however often the cron runs
  * a trial that lapsed months ago must never produce "your trial has just
    finished" — which is what the first run against a real database would do
    without a staleness window, to every customer at once, in one batch

That last one is the reason this file exists in the shape it does. It is a
mistake you get to make once.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/tn.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akyehq.com'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications

SENT = []
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to_email, to_name, subject, html, **k: (
    SENT.append({'to': to_email, 'name': to_name, 'subject': subject,
                 'html': html, 'from_name': k.get('from_name'),
                 'from_email': k.get('from_email')}), (True, 'stub'))[1]

import billing
import trial_nudges as tn

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


NOW = datetime.utcnow()


def org(days_old=0, **kw):
    """A company, described rather than built."""
    created = NOW - timedelta(days=days_old)
    base = {'slug': 'brightside', 'name': 'Brightside Cleaning',
            'owner_email': 'dana@brightside.example', 'status': 'active',
            'created_at': created, 'plan': 'scale',
            'subscription_status': 'trialing',
            'trial_ends_at': created + timedelta(days=billing.START_WITHIN_DAYS),
            'activated_at': None, 'nudges_sent': None}
    base.update(kw)
    return base


def running(days_in, **kw):
    """A company that started its 14 days `days_in` days ago."""
    began = NOW - timedelta(days=days_in)
    return org(days_old=days_in + 2, activated_at=began,
               trial_ends_at=began + timedelta(days=billing.TRIAL_DAYS), **kw)


print('\n1. The person who signed up and never came back')
# The banner cannot reach them. This is the entire point.
check(tn.due(org(days_old=1)) is None, 'day 1 — nothing, they are still setting up')
check(tn.due(org(days_old=6)) is None, 'day 6 — still nothing')
check(tn.due(org(days_old=7)) == 'start_7', 'day 7 — the first nudge')
check(tn.due(org(days_old=14, nudges_sent='start_7')) is None,
      'day 14 — quiet again, one email is not a campaign')
check(tn.due(org(days_old=21, nudges_sent='start_7')) == 'start_21',
      'day 21 — the last useful reminder before the door shuts')


print('\n2. A missed day does not lose the nudge')
# A cron can miss a day: the machine reboots, a deploy runs long, the schedule
# is paused. Keyed to `== 7` the email would simply never be sent.
check(tn.due(org(days_old=9)) == 'start_7',
      'a run two days late still sends the day-7 note')
check(tn.due(org(days_old=26, nudges_sent='start_7')) == 'start_21',
      'and the day-21 one')
check(tn.due(org(days_old=40)) is None,
      'but a window that has long closed does not reopen')


print('\n3. Never the same email twice')
# `nudges_sent` is written down rather than worked out from dates precisely
# for this. The second copy of "9 days left" is what gets a domain marked spam.
for kind, o in (('start_7', org(days_old=8, nudges_sent='start_7')),
                ('start_21', org(days_old=22, nudges_sent='start_7,start_21')),
                ('ending', running(12, nudges_sent='ending')),
                ('ended', org(days_old=31,
                              trial_ends_at=NOW - timedelta(days=1),
                              nudges_sent='ended'))):
    check(tn.due(o) is None, f'{kind} is not sent a second time')


print('\n4. Somebody who is actually using it')
check(tn.due(running(1)) is None, 'day 1 of 14 — leave them alone')
check(tn.due(running(9)) is None, 'day 9 — still nothing')
check(tn.due(running(11)) == 'ending', 'with 3 days left, the one about money')
check(tn.due(running(13)) == 'ending', 'and on the last day if it was missed')
# They engaged, so they never get the "you have not started" emails.
check(tn.due(running(11))not in ('start_7', 'start_21'),
      'and never the ones about not having begun')


print('\n5. When it lapses')
just = org(days_old=31, trial_ends_at=NOW - timedelta(hours=6))
check(tn.due(just) == 'ended', 'the day it ends, one note saying what changed')


print('\n6. The one that could go badly wrong, once')
# First run against a real database. Every trial that ever ended is sitting
# in that table. Without the staleness window this sends "your trial has just
# finished" to all of them, in one batch, months late.
for days_ago in (4, 30, 200, 900):
    old = org(days_old=days_ago + 30,
              trial_ends_at=NOW - timedelta(days=days_ago))
    check(tn.due(old) is None,
          f'a trial that ended {days_ago} days ago is left alone')

# And the whole-batch version of the same thing, which is what would actually
# have happened.
ancient = [org(slug=f'c{i}', days_old=400,
               trial_ends_at=NOW - timedelta(days=370 - i)) for i in range(50)]
check(sum(1 for o in ancient if tn.due(o)) == 0,
      '50 long-dead trials produce 0 emails')


print('\n7. Never a paying customer')
# The worst email a paying customer can get is one saying their trial is
# ending. `trial_state` returns None for them and that is the whole check.
for status in ('active', 'past_due', 'canceled', 'incomplete'):
    check(tn.due(org(days_old=8, subscription_status=status)) is None,
          f'nothing to a {status!r} subscription')
check(tn.due(org(days_old=8, status='suspended')) is None,
      'and nothing at all to a suspended company')


print('\n8. The words')
o = org(days_old=7)
for kind in tn.ALL:
    subj, html = tn.compose(o, kind)
    check(bool(subj) and 'Brightside' in subj, f'{kind}: the subject names them')
    check('brightside.akyehq.com' in html,
          f'{kind}: the link goes to their address, not the product\'s')
    check('akyehq.com/book' not in html and
          'href="https://akyehq.com' not in html,
          f'{kind}: and never to a login page where they do not exist')

# The promise the banner makes, kept in writing. Somebody whose trial has just
# ended is frightened about their data before they are anything else.
_, ended = tn.compose(o, 'ended')
check('nothing has been deleted' in ended.lower(), 'the lapse email says nothing was deleted')
check('free plan' in ended.lower(), 'and names the plan they are on')
_, ending = tn.compose(running(11), 'ending')
check('Nothing is deleted' in ending or 'nothing is deleted' in ending.lower(),
      'so does the one before it')
_, s7 = tn.compose(o, 'start_7')
check('assign' in s7.lower() or 'assigned' in s7.lower(),
      'the day-7 email says the one thing that starts the clock')


print('\n9. It is Akye writing, not the cleaning company')
# Left to default, `from_name` comes from `branding` — which describes
# whichever business the process last looked at. The email would arrive
# signed by somebody else's company.
SENT.clear()
ok, _ = tn._send(org(days_old=7), 'start_7')
check(ok, 'it sends')
check(len(SENT) == 1, 'once')
if SENT:
    m = SENT[0]
    check(m['to'] == 'dana@brightside.example', 'to the owner')
    check(m['from_name'] == 'Akye', f"from Akye ({m['from_name']})")
    check('akyehq.com' in (m['from_email'] or ''),
          f"on the product's own domain ({m['from_email']})")
    check('Brightside' not in (m['from_name'] or ''),
          'and never signed as the customer\'s own business')

check(tn._send(org(days_old=7, owner_email=None), 'start_7')[0] is False,
      'an account with no owner email is skipped, not crashed on')


print('\n10. A single-business install is not affected by any of this')
# No control plane, no organizations table, no trial, no emails. It must not
# raise either — this runs from a cron on every deployment, including the ones
# that are one cleaning company and nothing else.
class Dead:
    def connect(self, *a, **k):
        raise RuntimeError('no control plane here')

    def begin(self, *a, **k):
        raise RuntimeError('no control plane here')


out = tn.run(Dead())
check(sum(out.get(k, 0) for k in tn.ALL) == 0,
      'nothing is sent where there is no control plane')
check(out['considered'] == 0, 'and nothing is even considered')


# ── The rest needs a real control plane, which is a Postgres schema ──────────
# Everything above is the decision, and the decision is where the mistakes
# live. What follows is the plumbing: that a dry run really sends nothing,
# that a send is written down, and that a failure is retried.

def postgres_url():
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres'):
        if not candidate:
            continue
        try:
            from sqlalchemy import create_engine, text
            e = create_engine(candidate)
            with e.connect() as c:
                c.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n' + '=' * 70)
    print('  ⚠️  SKIPPED: sections 11-13 need PostgreSQL and found no server.')
    print('     The rules above — who gets what, and who never does — all ran.')
    print('=' * 70)
    if failures:
        print(f'\n❌ {len(failures)} nudge check(s) failed.\n')
        sys.exit(1)
    print('\n✅ The trial reaches the person who is not looking at it.\n')
    sys.exit(0)

from sqlalchemy import create_engine, text as _t

DB = 'dsm_nudge_test'
TEST_URL = f'{PG.rsplit("/", 1)[0]}/{DB}'
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as c:
    c.execute(_t(f'DROP DATABASE IF EXISTS {DB}'))
    c.execute(_t(f'CREATE DATABASE {DB}'))

import control_plane

engine = create_engine(TEST_URL)
control_plane.ensure_table(engine)
control_plane.create(engine, 'nudgetest', 'Nudge Test Co', 'owner@nudge.example')


def age_to(days, clear=True):
    """Put the test company `days` days past signup."""
    with engine.begin() as conn:
        sql = 'UPDATE organizations SET created_at = :c'
        if clear:
            sql += ', nudges_sent = NULL'
        conn.execute(_t(sql + ' WHERE slug = :s'),
                     {'c': NOW - timedelta(days=days), 's': 'nudgetest'})


print('\n11. A dry run sends nothing')
# She has to be able to see what a real run would do before it does it — and
# the first real run goes to actual customers.
age_to(8)
SENT.clear()
dry = tn.run(engine, dry_run=True)
check(len(SENT) == 0, 'a dry run sends no email at all')
check(dry['start_7'] == 1, 'but reports what it would have sent')
check(any(p[0] == 'nudgetest' for p in dry['plan']), 'and names who would get it')
check(not (control_plane.find(engine, 'nudgetest').get('nudges_sent') or ''),
      'and records nothing, so the real run still sends it')


print('\n12. A real run sends once and then stops')
SENT.clear()
first = tn.run(engine)
check(len(SENT) == 1, f'the first run sends it ({len(SENT)})')
check(first['start_7'] == 1, 'and counts it')
check('start_7' in (control_plane.find(engine, 'nudgetest').get('nudges_sent') or ''),
      'the send is written down')

SENT.clear()
tn.run(engine)
tn.run(engine)
check(len(SENT) == 0, 'running it twice more sends nothing')


print('\n13. A failed send is retried, not silently dropped')
# The nudge is recorded as sent only when it actually went. A mail outage on
# Tuesday must not cost somebody their day-7 email altogether.
age_to(8)
notifications.send_email = lambda *a, **k: (False, 'mail is down')
out = tn.run(engine)
check(out['failed'] == 1, 'the failure is counted')
check(out['start_7'] == 0, 'and not counted as sent')
check(not (control_plane.find(engine, 'nudgetest').get('nudges_sent') or ''),
      'nothing is recorded, so tomorrow tries again')

notifications.send_email = lambda to_email, to_name, subject, html, **k: (
    SENT.append({'to': to_email, 'subject': subject}), (True, 'stub'))[1]
SENT.clear()
check(tn.run(engine)['start_7'] == 1, 'and tomorrow it goes')

# A company with nobody to write to is skipped, not crashed on.
age_to(8)
with engine.begin() as conn:
    conn.execute(_t("UPDATE organizations SET owner_email = NULL WHERE slug = :s"),
                 {'s': 'nudgetest'})
out = tn.run(engine)
check(out['skipped_no_email'] == 1, 'an account with no owner email is skipped')
check(out['failed'] == 0, 'and not reported as a failure')

engine.dispose()
with admin.connect() as c:
    c.execute(_t(f'DROP DATABASE IF EXISTS {DB}'))


if failures:
    print(f'\n\n❌ {len(failures)} nudge check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ The trial reaches the person who is not looking at it.\n')
