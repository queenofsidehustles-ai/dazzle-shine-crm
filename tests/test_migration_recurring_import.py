"""The Migration Toolbox's Clients import can now seed a recurring plan too.

A recurring plan is safe to bring in where booking history is not: nothing
about a *future* visit has happened yet, so there is no payment or payroll
record an import could get wrong. This exercises the happy path and every
way a spreadsheet row can be malformed, on the actual /migration/clients
route -- not just the helper function -- so a routing or template change
can't quietly break it.
"""
import io
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/mig.db'
os.environ['SECRET_KEY'] = 'test-secret'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Client, Booking

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def upload(client, csv_text, filename='clients.csv'):
    data = {'csv_file': (io.BytesIO(csv_text.encode()), filename)}
    return client.post('/migration/clients', data=data,
                       content_type='multipart/form-data', follow_redirects=True)


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'

    print('\n1. A row with a frequency and a next date seeds a recurring plan')
    r = upload(c,
        'name,email,phone,address,city,zip,notes,frequency,next_date\n'
        'Alicia Chen,alicia@example.com,555-0201,12 Oak St,Tampa,33602,Has two dogs,biweekly,2026-10-06\n')
    check(r.status_code == 200, 'the import page responds')
    alicia = Client.query.filter_by(email='alicia@example.com').first()
    check(alicia is not None, 'the client is created')
    visits = Booking.query.filter_by(client_id=alicia.id).order_by(Booking.preferred_date).all()
    check(len(visits) > 1, 'more than one visit was generated, not just the seed')
    check(all(v.recurring_group == visits[0].recurring_group for v in visits),
          'every visit shares the same recurring series')
    check(all(v.frequency == 'biweekly' for v in visits), 'every visit carries the frequency')
    check(all(v.status == 'pending' for v in visits),
          'every visit is pending, not confirmed sight-unseen')
    check(all(v.service_type == 'standard' for v in visits),
          'service_type defaults to Standard Cleaning when the row leaves it blank')
    check(all(v.name == 'Alicia Chen' and v.address == '12 Oak St' for v in visits),
          'contact details are carried from the client onto every visit')
    check(visits[0].preferred_date == '2026-10-06', 'the first visit lands on the date given')
    check('📅' in r.get_data(as_text=True), 'the results page shows the plan was seeded')

    print('\n2. A row with no recurring columns at all gets a client and nothing else')
    r = upload(c,
        'name,email,phone,address,city,zip,notes,frequency,next_date\n'
        'Marcus Lee,marcus@example.com,555-0202,88 Palm Ave,Tampa,33603,,,\n')
    marcus = Client.query.filter_by(email='marcus@example.com').first()
    check(marcus is not None, 'the client is still created')
    check(Booking.query.filter_by(client_id=marcus.id).count() == 0,
          'no booking is created for a non-recurring row')

    print('\n3. An unrecognised frequency is refused, not guessed at')
    r = upload(c,
        'name,email,phone,address,city,zip,notes,frequency,next_date\n'
        'Bad Freq,badfreq@example.com,,,,,,fortnightly,2026-10-06\n')
    bf = Client.query.filter_by(email='badfreq@example.com').first()
    check(bf is not None, 'the client is still created')
    check(Booking.query.filter_by(client_id=bf.id).count() == 0,
          'no booking is guessed into existence from an unknown frequency')
    check('fortnightly' in r.get_data(as_text=True) and 'not a repeat frequency' in r.get_data(as_text=True),
          'the row explains why, by name, instead of failing silently')

    print('\n4. A frequency with no next_date is refused, not defaulted to today')
    r = upload(c,
        'name,email,phone,address,city,zip,notes,frequency,next_date\n'
        'No Date,nodate@example.com,,,,,,weekly,\n')
    nd = Client.query.filter_by(email='nodate@example.com').first()
    check(nd is not None, 'the client is still created')
    check(Booking.query.filter_by(client_id=nd.id).count() == 0,
          'no booking is created without a real date to anchor it')

    print('\n5. An unparseable date is refused, not silently dropped')
    r = upload(c,
        'name,email,phone,address,city,zip,notes,frequency,next_date\n'
        'Bad Date,baddate@example.com,,,,,,weekly,10/06/2026\n')
    bd = Client.query.filter_by(email='baddate@example.com').first()
    check(bd is not None, 'the client is still created')
    check(Booking.query.filter_by(client_id=bd.id).count() == 0,
          'no booking is created from a date in the wrong format')
    check('YYYY-MM-DD' in r.get_data(as_text=True), 'the row says what format is expected')

    print('\n6. One-time is not a recurring plan')
    r = upload(c,
        'name,email,phone,address,city,zip,notes,frequency,next_date\n'
        'One Time,onetime@example.com,,,,,,one_time,2026-10-06\n')
    ot = Client.query.filter_by(email='onetime@example.com').first()
    check(ot is not None, 'the client is still created')
    check(Booking.query.filter_by(client_id=ot.id).count() == 0,
          'one_time is refused the same as any other unrecognised frequency — '
          'a recurring plan needs weekly, biweekly or monthly')

    print('\n7. Re-importing the same client is still a no-op, recurring columns or not')
    before = Booking.query.filter_by(client_id=alicia.id).count()
    r = upload(c,
        'name,email,phone,address,city,zip,notes,frequency,next_date\n'
        'Alicia Chen,alicia@example.com,555-0201,12 Oak St,Tampa,33602,Has two dogs,biweekly,2026-11-01\n')
    check(Client.query.filter_by(email='alicia@example.com').count() == 1,
          'the duplicate email is skipped, not turned into a second client')
    check(Booking.query.filter_by(client_id=alicia.id).count() == before,
          'and no second recurring plan is seeded for a row that never made a new client')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n🎉 A spreadsheet can bring a recurring customer in with their plan already on the calendar.')
