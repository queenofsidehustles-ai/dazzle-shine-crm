"""What to do today — counted from what is true, and quiet when nothing is.

Reporting is not the same as helping. "You made $4,200 last month" is a fact;
"three people asked for a price yesterday and nobody replied" is a morning. This
is the second thing, and every line of it is a count against the database rather
than anything composed — a made-up task is worse than no task, because somebody
loses an hour to it and then stops trusting the list.

The other half is restraint. A list that says "post on Facebook, call ten leads"
every single morning is one nobody reads by Friday. Everything here has a real
number in it and disappears the day it stops being true, so a quiet day is
allowed to look quiet.
"""
import os, sys, tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/plan.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import Booking, Lead, Prospect, CommercialQuote
import daily_plan

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def texts():
    return ' | '.join(t for _u, t, _l in daily_plan.items())


with app.app_context():
    db.create_all()
    import scheduling
    today = scheduling.local_today()

    print('\n1. A quiet day is allowed to look quiet')
    # A genuinely quiet day is not an empty database: a business with nothing
    # booked next week has an empty week, and saying so is the point. So book
    # it first, and then there really is nothing to report.
    def fill_next_week(cleaner='Laura'):
        for i in range(7):
            d = today + timedelta(days=7 + i)
            if d.weekday() < 5:
                db.session.add(Booking(
                    service_type='standard', name=f'Filler {d}', email='f@x.com',
                    phone='4070000000', address='2 Oak', city='Orlando',
                    bedrooms='2', bathrooms='1', price=200.0, status='confirmed',
                    assigned_cleaner=cleaner, paid_at=datetime.utcnow(),
                    amount_collected=200.0, preferred_date=d.isoformat()))
        db.session.commit()

    fill_next_week()
    check(daily_plan.items() == [],
          f'nothing invented when there is nothing to do: {daily_plan.items()}')
    check(daily_plan.summary()['nothing'], 'and it says so')
    check('Nothing needs you today' in daily_plan.as_text(),
          f'out loud too: {daily_plan.as_text()!r}')

    print('\n2. Somebody waiting on a price comes first')
    db.session.add(Lead(name='Dana Ruiz', email='d@x.com', phone='4071112222',
                        service_type='standard', status='new'))
    db.session.commit()
    rows = daily_plan.items()
    check(rows[0][0] == 'now', 'it is marked now, not later')
    check('deciding today' in rows[0][1],
          f'and says why it cannot wait: {rows[0][1]!r}')

    print('\n3. A job nobody is going to turn up to')
    tomorrow = today + timedelta(days=1)
    db.session.add(Booking(service_type='standard', name='Rita', email='r@x.com',
                           phone='4079990000', address='1 Elm', city='Orlando',
                           bedrooms='3', bathrooms='2', price=260.0,
                           status='confirmed',
                           preferred_date=tomorrow.isoformat()))
    db.session.commit()
    check('nobody assigned' in texts(), 'an unassigned job tomorrow is on the list')

    print('\n4. Money already earned sits above money not yet won')
    order = [t for _u, t, _l in daily_plan.items()]
    owed_at = next((i for i, t in enumerate(order) if 'owed' in t), None)
    check(owed_at is not None, f'what is owed is on the list: {order[owed_at]!r}')
    # Chasing an invoice is quicker than replacing the job it came from.
    prospect_at = next((i for i, t in enumerate(order) if 'prospect' in t), 99)
    check(owed_at < prospect_at, 'and above prospecting')

    print('\n5. Commercial follow-ups that have gone quiet')
    db.session.add(Prospect(business_name='Palm Ridge', category='property_manager',
                            next_action_date=(today - timedelta(days=1)).isoformat()))
    # sent_at is a DATETIME, unlike the ISO-string date columns elsewhere.
    from datetime import datetime as _dt, time as _time
    def quote(company, contact, days_ago):
        return CommercialQuote(company=company, contact_name=contact,
                               email=f'{contact.lower()}@x.com',
                               token=f'tok-{company[:4].lower()}', status='sent',
                               sent_at=_dt.combine(today - timedelta(days=days_ago),
                                                   _time(9, 0)))
    db.session.add(quote('Lakeview', 'Ada', 9))
    db.session.add(quote('Fresh One', 'Bo', 0))
    db.session.commit()
    said = texts()
    check('due a call back' in said, 'a prospect past its call-back date')
    check('over four days ago' in said, 'and a quote nobody answered')
    check('1 commercial quote' in said,
          'but not one sent this morning — four days is the point')

    print('\n6. An empty diary next week, while it can still be filled')
    check('nothing booked' not in texts(),
          'a full week is not mentioned at all — no standing orders')
    # Empty it and the line appears, because now it is true.
    for b in Booking.query.filter(Booking.name.like('Filler%')).all():
        db.session.delete(b)
    db.session.commit()
    check('nothing booked' in texts(), 'open weekdays next week are named')

    print('\n7. Everything on it is a real count')
    # The test that matters most: clear the data and the list clears with it.
    Lead.query.delete()
    Prospect.query.delete()
    CommercialQuote.query.delete()
    Booking.query.delete()
    db.session.commit()
    left = [t for _u, t, _l in daily_plan.items()]
    check(not any(w in ' '.join(left) for w in
                  ('enquir', 'nobody assigned', 'owed', 'prospect', 'quote')),
          f'every count-driven line is gone: {left}')
    # The diary line stays, and should: a business with nothing booked next week
    # has an empty week, and saying so is the whole point of the list.
    check(any('nothing booked' in t for t in left),
          'and an empty diary is still an empty diary')

    print('\n8. It never takes the dashboard down with it')
    import blueprints.admin as _admin
    real = daily_plan.summary
    daily_plan.summary = lambda: (_ for _ in ()).throw(RuntimeError('boom'))
    try:
        out = _admin._daily_plan()
        check(out == {'items': [], 'nothing': False, 'say': None},
              'a broken plan returns empty rather than raising')
    finally:
        daily_plan.summary = real

    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'
    check(c.get('/').status_code == 200, 'and the dashboard still loads')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ It says what is worth doing, and nothing when nothing is.')
