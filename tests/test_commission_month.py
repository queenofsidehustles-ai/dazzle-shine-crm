"""Commission months are the business's months, the same as the books.

A payment taken at 8pm New York on the 31st is stamped 00:00 UTC on the 1st.
Commission used to bucket by the UTC calendar, so it counted toward next
month, while revenue (finance) and a rep's own page counted it in the month it
was taken. Three answers to one question. They are one answer now.
"""
import os, sys, tempfile
from datetime import date, datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/cm.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


from app import create_app
from extensions import db
from models import Booking, BusinessSetting
import finance
import va_commission

app = create_app()
with app.app_context():
    db.create_all()
    BusinessSetting.set('timezone', 'America/New_York')
    db.session.commit()

    def paid(when_utc, name):
        b = Booking(service_type='standard', name=name, status='completed', price=100.0,
                    balance_due=100.0, balance_collected=True, paid_at=when_utc,
                    agent='Sam', frequency='one_time', source='referral', email=f'{name}@x.test')
        db.session.add(b)
        db.session.commit()
        return b

    def counted(year, month):
        return sorted(l['label'].split('— ')[1] for l in
                      va_commission.commission_for_month('Sam', year, month)['lines']
                      if l['type'] == 'residential_onetime')

    print('1. A payment belongs to the month on the business\'s clock')
    # Winter (EST, UTC-5): midnight in New York is 05:00 UTC.
    paid(datetime(2027, 1, 1, 1, 30), 'dec-evening')       # 8:30pm Dec 31 in New York
    paid(datetime(2027, 1, 1, 4, 59, 59), 'dec-last-second')
    paid(datetime(2027, 1, 1, 5, 0, 0), 'jan-first-second')
    paid(datetime(2026, 12, 1, 4, 59), 'nov-last-minute')   # 11:59pm Nov 30
    paid(datetime(2026, 12, 1, 5, 0), 'dec-first-minute')
    check(counted(2026, 12) == ['dec-evening', 'dec-first-minute', 'dec-last-second'],
          'December: the evening of the 31st is in, the first minute of the 1st is in, 00:00 UTC on Jan 1 is not the month\'s start')
    check(counted(2027, 1) == ['jan-first-second'], 'January starts at midnight New York, 05:00 UTC')
    check(counted(2026, 11) == ['nov-last-minute'], 'and November ends at 11:59pm New York')

    print('\n2. Summer clock (EDT, UTC-4)')
    paid(datetime(2026, 8, 1, 3, 59, 59), 'jul-last-second')
    paid(datetime(2026, 8, 1, 4, 0, 0), 'aug-first-second')
    check('jul-last-second' in counted(2026, 7) and 'aug-first-second' not in counted(2026, 7),
          'the boundary moves with daylight time: July ends at 04:00 UTC')
    check('aug-first-second' in counted(2026, 8), 'and August begins there')

    print('\n3. Commission and the books answer the same question')
    for ym in ((2026, 12), (2027, 1), (2026, 11), (2026, 7), (2026, 8)):
        start, end = finance.month_bounds(*ym)
        books = finance.revenue_between(start, end)
        cm = len(va_commission.commission_for_month('Sam', *ym)['lines'])
        # Every booking above is $100 and one line each.
        check(abs(books - 100.0 * cm) < 0.01, f'{ym[0]}-{ym[1]:02d}: revenue ${books:.0f} for {cm} commissioned payments')

    print('\n4. A line is dated by the business\'s day, not UTC\'s')
    lines = va_commission.commission_for_month('Sam', 2026, 12)['lines']
    when = {l['label'].split('— ')[1]: l['when'] for l in lines}
    check(when['dec-evening'].date() == date(2026, 12, 31),
          'a payment at 01:30 UTC on Jan 1 is shown as Dec 31')

    print('\n5. The commissions page opens on the business\'s month')
    import blueprints.commissions as cb, inspect
    check('local_today' in inspect.getsource(cb.index), 'the default month follows the business\'s day')

print()
if failures:
    print(f'❌ {len(failures)} commission-month check(s) failed.')
    sys.exit(1)
print('🎉 One month, on one clock.')
