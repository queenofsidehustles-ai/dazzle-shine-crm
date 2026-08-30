"""A cleaning company that looks like a real one, for showing the software.

    python3 seed_demo.py            # fill this database with a demo business
    python3 seed_demo.py --wipe     # clear it out again

Never demonstrate an empty dashboard. A prospect looking at zeroes has to
imagine their business inside it, and imagining is work they will not do while
somebody is talking at them. A prospect looking at Sparkle Cleaning Services —
six cleaners, jobs on Thursday, a customer who tips, one job nobody has claimed
yet — is looking at their own business and thinking about their own Thursday.

## What makes it convincing is the mess

A tidy demo is a suspicious demo. Every cleaning company has a job somebody
cancelled, a cleaner who has not confirmed, a customer who owes money and a
Tuesday nobody wants. So this seeds those on purpose. The point of the demo is
not that the software is neat; it is that it holds a real week without falling
over.

## It refuses to run on a real business

Checked before anything is written, because the one unforgivable outcome here
is seeding demo data into somebody's actual CRM.
"""
import argparse
import os, secrets
import random
import sys
from datetime import datetime, timedelta

DEMO_MARK = 'demo_seeded'

FIRST = ['Maria', 'Jennifer', 'Rosa', 'Ashley', 'Yolanda', 'Danielle',
         'Carmen', 'Tiffany']
LAST = ['Alvarez', 'Whitfield', 'Nguyen', 'Okafor', 'Ramos', 'Bennett',
        'Castillo', 'Doyle']

# Neutral towns on purpose. The white-label guard exists to stop one company's
# details being baked into the source, and it was right to catch an earlier
# version of this that used the original business's own city.
#
# DEMO_CITY is worth setting before a demo: a prospect in Dallas looking at
# Dallas addresses is looking at their own round, not somebody else's.
DEMO_CITY = os.environ.get('DEMO_CITY', 'Fairview')

CLIENTS = [
    ('Patricia Halloway', '412 Live Oak Ln', '32789', 4, 3),
    ('Denise Uhle', '77 Sandpiper Ct', '32819', 3, 2),
    ('Marcus Feld', '1904 Bramble Way', '32751', 3, 2),
    ('The Ashbury Rental', '55 Palmetto Dr #2', '32801', 2, 2),
    ('Grace Okonkwo', '8 Heron Bay', '34786', 5, 4),
    ('Tom & Lisa Brandt', '221 Cypress Run', '32703', 4, 3),
    ('Sunrise Daycare', '3300 Colonial Dr', '32803', 5, 4),
    ('Amara Sesay', '19 Willow Bend', '32701', 2, 2),
    ('Rebecca Lindqvist', '640 Beacon Hill', '32792', 3, 3),
    ('Hector Villalobos', '5 Juniper Ct', '34761', 3, 2),
    ('The Kestrel Airbnb', '88 Lakeview Ter', '32806', 2, 2),
    ('Nadia Petrov', '1201 Foxglove St', '32750', 4, 3),
]


def _app():
    os.environ.setdefault('SECRET_KEY', 'seed-demo')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import notifications
    # Nothing here texts or emails anybody. The demo data contains phone
    # numbers, and a seeder that messaged them would be unforgivable.
    notifications.send_sms = lambda *a, **k: (True, 'demo — not sent')
    notifications.send_email = lambda *a, **k: (True, 'demo — not sent')
    from app import create_app
    return create_app()


def looks_real():
    """Is there a business in here already? Returns a reason, or None."""
    from models import Booking, Client, ContractorPayment, BusinessSetting
    if BusinessSetting.get(DEMO_MARK):
        return None                      # our own demo data; safe to touch
    counts = {'bookings': Booking.query.count(), 'clients': Client.query.count(),
              'payouts': ContractorPayment.query.count()}
    if any(counts.values()):
        return (f'this database already has {counts["bookings"]} jobs, '
                f'{counts["clients"]} customers and {counts["payouts"]} payouts')
    return None


def wipe():
    from extensions import db
    from models import (Booking, BookingCrew, Client, Staff, JobChecklist,
                        ContractorPayment, Expense, Message, BusinessSetting,
                        BookingRating)
    if not BusinessSetting.get(DEMO_MARK):
        raise RuntimeError('This database was not seeded by seed_demo. '
                           'Refusing to delete anything.')
    for model in (BookingRating, JobChecklist, BookingCrew, ContractorPayment,
                  Message, Booking, Client, Expense, Staff):
        model.query.delete()
    BusinessSetting.set(DEMO_MARK, '')
    db.session.commit()


def seed(quiet=False):
    from extensions import db
    from models import (Booking, BookingCrew, Client, Staff, JobChecklist,
                        ContractorPayment, Expense, BusinessSetting,
                        ChecklistTemplate, BookingRating)
    say = (lambda m: None) if quiet else print
    rng = random.Random(20260829)        # same demo every time it is shown
    today = datetime.utcnow().date()

    BusinessSetting.set('business_name', 'Sparkle Cleaning Services')
    BusinessSetting.set('phone', '(407) 555-0142')
    BusinessSetting.set('email', 'hello@sparklecleaning.example')
    BusinessSetting.set('pricing_reviewed', '1')
    BusinessSetting.set('terms_reviewed', '1')

    # Six cleaners, on the pay arrangements a real company ends up with rather
    # than one tidy rule.
    cleaners = []
    for i in range(6):
        s = Staff(name=f'{FIRST[i]} {LAST[i]}',
                  phone=f'407555{2100 + i:04d}',
                  email=f'{FIRST[i].lower()}@example.com',
                  # Two of the six are paid by the hour. A real company rarely
                  # pays everybody the same way, and a demo where nobody is
                  # hourly never shows the timesheet at all.
                  is_active=True,
                  pay_type='hourly' if i in (4, 5) else 'percent',
                  pay_rate=(21.0 if i == 4 else 18.5) if i in (4, 5)
                           else (55.0 if i < 2 else 50.0),
                  experience_level='senior' if i < 2 else 'new',
                  language='es' if i in (2, 4) else 'en',
                  worker_model='contractor',
                  # Without this the cleaner's phone view has no address to
                  # open at, and that screen IS the demo -- holding up a real
                  # phone with a real job on it is the moment the sale is made.
                  # In the product this is minted when a job is first assigned;
                  # a seeded company needs it up front.
                  agreement_token=secrets.token_urlsafe(32))
        db.session.add(s)
        cleaners.append(s)
    db.session.commit()
    say(f'  {len(cleaners)} cleaners')

    clients = []
    sizes = {}
    for name, addr, zc, beds, baths in CLIENTS:
        city = DEMO_CITY
        c = Client(name=name, email=f'{name.split()[0].lower()}@example.com',
                   phone=f'407555{rng.randint(1000, 1999)}',
                   address=addr, city=city, zip_code=zc)
        db.session.add(c)
        clients.append(c)
        sizes[name] = (beds, baths)
    db.session.commit()
    say(f'  {len(clients)} customers')

    tpl = ChecklistTemplate.query.first()
    jobs, paid_total = [], 0.0

    def make(client, day, service, price, hours, status, **kw):
        b = Booking(client_id=client.id, name=client.name, email=client.email,
                    phone=client.phone, address=client.address, city=client.city,
                    zip_code=client.zip_code, service_type=service, price=price,
                    balance_due=price, estimated_hours=hours,
                    labor_rate_applied=43.0, status=status,
                    preferred_date=day.isoformat(),
                    # A real week does not start every job at ten o'clock, and
                    # a calendar where every chip reads the same time is the
                    # first thing that makes a demo look staged.
                    preferred_time=kw.pop('preferred_time', None)
                                   or rng.choice(['8:00 AM', '8:30 AM', '9:00 AM',
                                                  '10:00 AM', '11:00 AM', '1:00 PM',
                                                  '2:00 PM', '3:30 PM']),
                    bedrooms=sizes.get(client.name, (None, None))[0],
                    bathrooms=sizes.get(client.name, (None, None))[1],
                    **kw)
        db.session.add(b)
        db.session.commit()
        jobs.append(b)
        return b

    # Four weeks behind: completed, paid, some with checklists and a rating.
    for w in range(4, 0, -1):
        for i, client in enumerate(clients[:6]):
            day = today - timedelta(days=w * 7 - i)
            b = make(client, day, 'standard', 240.0 + i * 20, 3.0, 'completed',
                     balance_collected=True,
                     paid_at=datetime.combine(day, datetime.min.time()),
                     paid_method='card',
                     tip_amount=20.0 if (w + i) % 5 == 0 else 0)
            paid_total += b.price
            cleaner = cleaners[i % len(cleaners)]
            db.session.add(BookingCrew(booking_id=b.id, staff_id=cleaner.id,
                                       pay_amount=round(b.labor_budget or 129.0, 2)))
            db.session.add(ContractorPayment(
                staff_id=cleaner.id, booking_id=b.id,
                amount=round(b.labor_budget or 129.0, 2), status='paid',
                method='zelle',
                created_at=datetime.combine(day, datetime.min.time())))
            if tpl and i % 2 == 0:
                db.session.add(JobChecklist(
                    booking_id=b.id, token=os.urandom(16).hex(),
                    template_name=tpl.name, items=tpl.items,
                    completed_items=tpl.items,
                    completed_at=datetime.combine(day, datetime.min.time()),
                    clock_in_at=datetime.combine(day, datetime.min.time()),
                    clock_out_at=datetime.combine(day, datetime.min.time())))
            if i == 1:
                db.session.add(BookingRating(
                    booking_id=b.id, token=os.urandom(16).hex(), rating=5,
                    comment='Maria was lovely. House smells amazing.',
                    rated_at=datetime.combine(day, datetime.min.time())))
    db.session.commit()

    # This week and next: the mess a real week actually contains.
    #
    # Three of these are TODAY. A demo that opens on "nothing booked today" is
    # a demo of an empty business, and today is the first thing both the
    # dashboard and the cleaner's phone show.
    upcoming = [
        (clients[5], 0, 'standard', 285.0, 3.5, 'confirmed', {}),
        (clients[2], 0, 'deep',     430.0, 5.5, 'confirmed', {}),
        (clients[8], 0, 'standard', 240.0, 3.0, 'confirmed', {}),
        (clients[0], 1, 'deep', 445.0, 6.0, 'confirmed', {}),
        (clients[1], 1, 'standard', 260.0, 3.0, 'confirmed', {}),
        (clients[6], 2, 'commercial', 600.0, 5.0, 'confirmed', {}),
        (clients[3], 2, 'moveout', 494.0, 6.5, 'confirmed', {}),
        (clients[4], 3, 'standard', 320.0, 4.0, 'confirmed', {}),
        (clients[7], 3, 'standard', 225.0, 2.5, 'pending', {}),
        (clients[8], 4, 'standard', 260.0, 3.0, 'confirmed', {}),
        (clients[10], 5, 'standard', 225.0, 2.5, 'confirmed', {}),
        (clients[2], 6, 'deep', 416.0, 5.0, 'cancelled', {}),
        (clients[9], 7, 'standard', 260.0, 3.0, 'confirmed', {}),
        (clients[11], 8, 'standard', 320.0, 4.0, 'confirmed', {}),
    ]
    for client, offset, service, price, hours, status, extra in upcoming:
        b = make(client, today + timedelta(days=offset), service, price, hours,
                 status, **extra)
        # Deliberately NOT all assigned. A demo where every job has a cleaner
        # on it does not look like anybody's Thursday.
        if status == 'confirmed' and offset not in (2, 5):
            crew = [cleaners[offset % 6]]
            if hours >= 5:
                crew.append(cleaners[(offset + 1) % 6])
            for cl in crew:
                db.session.add(BookingCrew(
                    booking_id=b.id, staff_id=cl.id,
                    pay_amount=round((b.labor_budget or 129.0) / len(crew), 2)))
        elif status == 'confirmed':
            # Out with the team, first to claim it. This is the screen worth
            # showing, and it is the one nobody else has.
            b.open_for_claim = True
            b.claim_token = os.urandom(24).hex()
            b.broadcast_at = datetime.utcnow()
    db.session.commit()
    say(f'  {len(jobs)} jobs — {len(upcoming)} coming up, one cancelled, '
        f'two out to the team unclaimed')

    for cat, amount, vendor, days in [('supplies', 184.50, 'Restaurant Depot', 6),
                                      ('ads_google', 300.00, 'Google Ads', 12),
                                      ('fuel', 96.20, 'Wawa', 3),
                                      ('insurance', 145.00, 'Next Insurance', 20)]:
        db.session.add(Expense(date=(today - timedelta(days=days)).isoformat(),
                               category=cat, amount=amount, vendor=vendor))
    db.session.commit()

    BusinessSetting.set(DEMO_MARK, datetime.utcnow().isoformat())
    db.session.commit()
    say(f'  4 expenses, and about ${paid_total:,.0f} of collected revenue behind it')
    return {'cleaners': len(cleaners), 'clients': len(clients), 'jobs': len(jobs)}


def main():
    p = argparse.ArgumentParser(description='A demo cleaning company, for showing the software.')
    p.add_argument('--wipe', action='store_true', help='remove the demo data')
    p.add_argument('--force', action='store_true',
                   help='seed even though this database already has data in it')
    args = p.parse_args()

    app = _app()
    with app.app_context():
        if args.wipe:
            wipe()
            print('\n  Demo data removed.\n')
            return 0

        reason = looks_real()
        if reason and not args.force:
            print(f'\n  ⚠️  Refusing to seed: {reason}.')
            print('     This looks like a real business. Seeding demo customers and')
            print('     jobs into somebody\'s actual CRM is the one unforgivable')
            print('     thing this script could do.')
            print('     Use --force only if you are certain.\n')
            return 1

        print('\n  Seeding Sparkle Cleaning Services…')
        seed()
        print('\n  Ready. Sign in and it looks like a working business.')
        # Step 5 of the demo in GETTING_CUSTOMERS.md is "pick up your phone and
        # open the link the cleaner just got". Print the links so nobody has to
        # go digging in the database for them mid-call.
        try:
            import branding
            from models import Staff
            base = branding.crm_base().rstrip('/')
            links = [(x.name, f'{base}/contractors/my-day/{x.agreement_token}')
                     for x in Staff.query.filter(Staff.agreement_token.isnot(None))
                                         .order_by(Staff.id).limit(3).all()]
            if links:
                print('\n  The cleaner\'s phone view — open one of these on a real phone:')
                for name, link in links:
                    print(f'    {name:22} {link}')
        except Exception:
            pass
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
