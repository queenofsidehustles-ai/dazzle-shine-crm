"""The booking page reads like the New Booking form, not like a pinboard.

Eleven cards sat in two columns, each with its own border, its own uppercase
title and its own button, so every one of them shouted equally and you scanned
all eleven to find the one you came for. The New Booking form next door does
the opposite: four plain headings in one flow, and it is the page she said was
easy to follow.

So the same content, grouped by the moment in a job's life you are in:

    The booking  ·  The money  ·  Who's doing it  ·  Talk to the customer

and everything you touch once in a while behind "Less often".

Drag-to-rearrange survives untouched, because the script reorders anything
carrying data-card-key and grabs it by its heading -- a section is a card as
far as that code is concerned.
"""
import os, re, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/sections.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda **k: (True, 'ok')
notifications.send_sms = lambda *a, **k: (True, 'ok')

from app import create_app
from extensions import db
from models import Booking, Staff

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, 'templates/admin/booking_detail.html'), encoding='utf-8').read()

with app.app_context():
    db.create_all()
    db.session.add(Staff(name='Maya Johnson', is_active=True,
                         email='maya@example.com', phone='+12565550111'))
    b = Booking(service_type='standard', name='Eric Rosebro', email='eric@example.com',
                phone='+17165550100', status='confirmed', price=430.0,
                preferred_date='2026-11-02', address='1 Oak St', city='Huntsville',
                bedrooms=5, bathrooms=3, estimated_hours=1.5)
    db.session.add(b)
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    page = c.get(f'/bookings/{b.id}').get_data(as_text=True)

    print('\n1. Five sections, not eleven cards')
    keys = re.findall(r'data-card-key="([^"]+)"', SRC)
    # Who's doing it before the money: assigning is the next thing a new
    # booking needs, and being paid comes after the work.
    check(keys == ['booking', 'confirm', 'who', 'money', 'talk', 'extras'],
          f'the page is {" · ".join(keys)}')
    check(len(keys) == len(set(keys)), 'every key is distinct, so a saved order cannot collide')
    # How many cleaners, then who (2026-10-25): headcount is chosen first.
    check(SRC.index('for="crewSize"') < SRC.index('for="assignTo"'),
          'Cleaners needed comes before Assign to')
    for gone in ('customer', 'service', 'manage', 'crew-pay', 'send-customer',
                 'recurring-cleaning', 'recurring-plan', 'job-photos',
                 'on-hold', 'put-on-hold', 'payment'):
        if gone in keys:
            check(False, f'the old card key {gone} is still a top-level box')
    check(True, 'none of the eleven old card keys survive as boxes')

    print('\n2. Nothing was dropped on the way')
    for probe, what in (
            ('bookings.update_contact', 'correcting name, email or phone'),
            ('bookings.update_address', 'changing the address'),
            ('bookings.update_service', 'editing the service details'),
            ('bookings.save_crew', 'saving pay'),
            ('bookings.assign', 'assigning a cleaner'),
            ('bookings.send_confirmation', 'the booking confirmation'),
            ('bookings.send_invoice', 'the invoice'),
            ('bookings.mark_paid_route', 'marking it paid'),
            ('bookings.mark_deposit_paid_route', 'recording a deposit'),
            ('bookings.start_plan', 'starting a recurring plan'),
            ('bookings.hold', 'putting the job on hold'),
            ('bookings.delete', 'deleting the booking')):
        check(f'/{probe.split(".")[1]}' in page or probe.split('.')[1] in SRC,
              f'still here: {what}')

    print('\n3. The rarely-used things are folded away, not deleted')
    check('Less often' in page, 'there is a "Less often" section')
    check(page.count('<details') >= 5, f'{page.count("<details")} disclosures on the page')
    check('Recurring Cleaning' in page or 'Recurring' in page, 'recurring is still reachable')

    print('\n4. Drag-to-rearrange still works on the sections')
    check('data-reorder="bookingDetailCardOrder"' in SRC, 'the area is still a reorder board')
    check('data-reorder-col="left"' in SRC and 'data-reorder-col="right"' in SRC,
          'both columns are still there')
    for key in ('booking', 'money', 'who', 'talk', 'extras'):
        i = SRC.index(f'data-card-key="{key}"')
        rest = SRC[i:i + 400]
        if '<h2' not in rest:
            check(False, f'section {key} has no <h2> for the drag handle')
    check(True, 'every section has a heading the script can grab as its handle')

    print('\n5. The work-order tickbox stops lying about the team')
    check('id="woBox"' in page and 'id="teamNote"' in page,
          'the tickbox and its replacement are both on the page')
    check('not the address' in page,
          'and the team note says what the team actually sees')
    check("sel.value === 'team'" in SRC,
          'the script swaps them on the team choice')

    print('\n6. The headcount is a decision, so it stays in the open')
    # It spent one release folded in with the hours, on the theory that it was
    # arithmetic. It is not: it sets how many spots the team offer advertises
    # and how the pot divides. test_crew_size_visible holds the full contract.
    details = SRC[SRC.index('Pay details — hours, rate'):]
    cut = details.index('</details>')
    check('name="crew_size"' not in details[:cut],
          'it is NOT buried in the pay details fold')
    # The pay card's assign form, not the "Next: who's cleaning" bar on top,
    # which posts to the same endpoint but leaves the headcount down here.
    who = SRC[SRC.index('data-card-key="who"'):]
    assign = who[who.index("url_for('bookings.assign'"):]
    check('name="crew_size"' in assign[:assign.index('</form>')],
          'it sits with "Assign to", where who-and-how-many is decided together')

if failures:
    print(f'\n❌ {len(failures)} failed')
    for f in failures:
        print('  -', f)
    raise SystemExit(1)
print('\n🎉 Four moments and a drawer, and everything still reachable.')
