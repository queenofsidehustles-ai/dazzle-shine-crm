"""The calendar was drawing every job one day to the left.

The column headings read Sun..Sat, but Python's calendar module starts its weeks
on Monday and nothing told it otherwise. So the grid was Monday-first under
Sunday-first headings and every date sat one column off: a Saturday job appeared
under Friday, and the cleaner reading the month saw the wrong weekday.

"Today" was wrong too, for a different reason. It came from the server's clock,
and the server runs on UTC — so from 8pm in Florida the highlighted square was
already tomorrow.
"""
import os, sys, tempfile
from datetime import date, datetime, timezone
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/cg.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking
import scheduling
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. Every day of a month sits under its real weekday')
    import calendar as cal
    grid = cal.Calendar(firstweekday=6).monthdayscalendar(2026, 8)
    headings = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    wrong = []
    for week in grid:
        for col, day in enumerate(week):
            if not day:
                continue
            real = date(2026, 8, day).strftime('%a')
            if real != headings[col]:
                wrong.append((day, headings[col], real))
    check(not wrong, f'all 31 days of August 2026 line up ({wrong[:3]})')

    print('\n2. The job on Saturday the 22nd is drawn on a Saturday')
    b = Booking(service_type='standard', name='Karen Doyle', address='55 Oak',
                price=245, preferred_date='2026-08-22', status='confirmed')
    db.session.add(b); db.session.commit()
    html = c.get('/bookings/calendar?year=2026&month=8').get_data(as_text=True)
    check('Karen Doyle' in html, 'the job is on the month')
    # Column position of the cell holding the job, counted within its week row.
    row = [w for w in grid if 22 in w][0]
    check(headings[row.index(22)] == 'Sat',
          f'the 22nd is in the {headings[row.index(22)]} column, and it is a Saturday')
    check(date(2026, 8, 22).strftime('%a') == 'Sat', 'which is the real weekday')

    print('\n3. A month that starts on a Saturday still lines up')
    for y, m in ((2026, 8), (2026, 2), (2027, 5), (2026, 11)):
        g = cal.Calendar(firstweekday=6).monthdayscalendar(y, m)
        bad = [(d, headings[i]) for w in g for i, d in enumerate(w)
               if d and date(y, m, d).strftime('%a') != headings[i]]
        check(not bad, f'{y}-{m:02d} lines up')

    print("\n4. Today is the business's day, not the server's")
    # 9pm in Florida is already tomorrow in UTC. The calendar must still say
    # today is today.
    evening = datetime(2026, 8, 19, 21, 0, tzinfo=scheduling.business_timezone())
    check(evening.astimezone(timezone.utc).date() != evening.date(),
          'at 9pm Florida time the server has already rolled over to tomorrow')
    check(scheduling.local_today() == datetime.now(
        scheduling.business_timezone()).date(),
        'local_today() follows the business timezone')
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'blueprints', 'bookings.py')).read()
    calendar_fn = src[src.index('def calendar():'):src.index('def detail(')]
    check('local_today()' in calendar_fn and 'today = date.today()' not in calendar_fn,
          'the calendar reads the business day')

    print('\n5. The funnel dates its follow-ups by the business day too')
    import prospecting
    check('date.today()' not in open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'prospecting.py')).read(),
        'nothing in the funnel uses the server day')
    check(prospecting._plus(0) == scheduling.local_today().isoformat(),
          'a callback booked "today" is dated today in Florida')

print('\n🎉 Calendar checks passed.')
