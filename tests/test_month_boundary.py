"""Money lands on the day the business thinks it is.

A card charged at 9pm on the 31st of the month was stamped 01:00 UTC on the
1st, and dropped out of that month's revenue into the next one.

The columns are stamped with `datetime.utcnow()`, which is right — an instant
should be unambiguous. What was wrong was the question asked of them. "Show me
August" produced the naive datetimes `2026-08-01 00:00` to `2026-09-01 00:00`,
which are midnight *in Orlando*, and those were compared straight against UTC
instants. The two clocks disagree for the last four or five hours of every day
in the eastern US.

So every evening payment landed on the wrong day. Most of the time that is
invisible, because the day after is in the same month. At a month end it is
not: the owner sees a month that is short by its last evening, a next month
that is long by the same amount, and nothing on either screen to explain it.
It flows into the quarter, the year, and the Schedule C export.

This test only fails in the evening, which is exactly why it is written the
way it is. It builds the boundary case on purpose instead of waiting for the
clock to produce it — the original was found by the suite going red at 21:27
on the 31st of August, which is luck, and luck does not run in CI.

Fixed by converting the boundary rather than what is stored. Every row already
in the database is UTC; changing what gets written would leave two meanings in
one column with no way to tell them apart.
"""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/mb.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
os.environ['BUSINESS_TZ'] = 'America/New_York'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import Booking
import finance

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def paid_job(name, price, when_utc):
    """A job paid at a specific UTC instant."""
    with app.app_context():
        b = Booking(name=name, email='c@x.com', phone='4075550000',
                    address='1 Test St', service_type='standard',
                    preferred_date='2026-08-15', status='completed',
                    price=price, paid_at=when_utc)
        db.session.add(b)
        db.session.commit()


with app.app_context():
    db.drop_all()
    db.create_all()


print('\n1. The evening of the last day of the month')
# 9pm on 31 August in Orlando. In UTC that is already 01:00 on 1 September,
# which is where this money used to be filed.
paid_job('Late August job', 500.0, datetime(2026, 9, 1, 1, 0))

with app.app_context():
    aug = finance.revenue_between(*finance.month_bounds(2026, 8))
    sep = finance.revenue_between(*finance.month_bounds(2026, 9))

check(aug == 500.0, f'$500 taken at 9pm on 31 Aug counts as August (${aug})')
check(sep == 0.0, f'and not as September (${sep})')


print('\n2. Just after midnight, locally, is genuinely the next month')
# 00:30 on 1 September in Orlando = 04:30 UTC. The boundary has to move, not
# simply be widened — a fix that swept everything into the earlier month would
# pass the test above and be just as wrong.
with app.app_context():
    db.session.query(Booking).delete()
    db.session.commit()
paid_job('Early September job', 700.0, datetime(2026, 9, 1, 4, 30))

with app.app_context():
    aug = finance.revenue_between(*finance.month_bounds(2026, 8))
    sep = finance.revenue_between(*finance.month_bounds(2026, 9))

check(aug == 0.0, f'$700 taken at 00:30 on 1 Sep is not August (${aug})')
check(sep == 700.0, f'it is September (${sep})')


print('\n3. Nothing is counted twice, and nothing falls between')
# The two months must tile: every instant belongs to exactly one of them. A
# boundary that overlapped would double-count the evening of the 31st, which
# is a worse bug than the one being fixed — it inflates revenue.
with app.app_context():
    db.session.query(Booking).delete()
    db.session.commit()
for i, when in enumerate([
        datetime(2026, 9, 1, 0, 30),    # 20:30 on 31 Aug, Orlando
        datetime(2026, 9, 1, 3, 59),    # 23:59 on 31 Aug
        datetime(2026, 9, 1, 4, 0),     # 00:00 on 1 Sep
        datetime(2026, 9, 1, 12, 0)]):  # 08:00 on 1 Sep
    paid_job(f'Job {i}', 100.0, when)

with app.app_context():
    aug = finance.revenue_between(*finance.month_bounds(2026, 8))
    sep = finance.revenue_between(*finance.month_bounds(2026, 9))

check(aug == 200.0, f'two jobs are August (${aug})')
check(sep == 200.0, f'two are September (${sep})')
check(aug + sep == 400.0, 'and all four are counted exactly once')


print('\n4. The same is true of an ordinary day')
# This is not only a month-end problem. Every evening payment was landing on
# tomorrow, all year — invisible on a monthly total and wrong on a daily one.
with app.app_context():
    db.session.query(Booking).delete()
    db.session.commit()
paid_job('Tuesday evening', 250.0, datetime(2026, 6, 17, 1, 0))  # 21:00, 16 Jun

with app.app_context():
    d16 = finance.revenue_between(date(2026, 6, 16), date(2026, 6, 16))
    d17 = finance.revenue_between(date(2026, 6, 17), date(2026, 6, 17))

check(d16 == 250.0, f'a 9pm payment belongs to that evening (${d16})')
check(d17 == 0.0, f'not to the following morning (${d17})')


print('\n5. It follows the timezone, rather than assuming one')
# A cleaning company in Phoenix or London is not on New York time, and the
# boundary is theirs, not ours.
lo_ny, hi_ny = finance._dt_bounds(date(2026, 8, 1), date(2026, 8, 31))
os.environ['BUSINESS_TZ'] = 'UTC'
with app.app_context():
    lo_utc, hi_utc = finance._dt_bounds(date(2026, 8, 1), date(2026, 8, 31))
check(lo_ny != lo_utc, 'a different timezone gives a different boundary')
check(lo_utc == datetime(2026, 8, 1, 0, 0),
      f'and on UTC it is plain midnight ({lo_utc})')
check((lo_ny - lo_utc) == timedelta(hours=4),
      f'New York in August is four hours behind ({lo_ny - lo_utc})')
os.environ['BUSINESS_TZ'] = 'America/New_York'


print('\n6. A broken timezone setting draws the page anyway')
# This runs inside every money screen. A P&L that cannot be drawn is worse
# than one drawn in the wrong timezone.
os.environ['BUSINESS_TZ'] = 'Not/A_Real_Place'
with app.app_context():
    try:
        lo, hi = finance._dt_bounds(date(2026, 8, 1), date(2026, 8, 31))
        check(True, 'a nonsense timezone does not raise')
        check(lo < hi, 'and still produces a usable range')
    except Exception as e:
        check(False, f'it raised: {type(e).__name__}: {e}')
os.environ['BUSINESS_TZ'] = 'America/New_York'


if failures:
    print(f'\n\n❌ {len(failures)} boundary check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Money lands on the day the business thinks it is.\n')
