"""BrightNest Cleaning Co. -- the fictional company Akye is shown with.

    python3 demo_company.py              build it, or rebuild it fresh
    python3 demo_company.py --dry-run    say what would be built; write nothing
    python3 demo_company.py --verify     check the live demo still adds up
    python3 demo_company.py --reset      same as a plain run, said out loud

Run it inside the app on Railway (see DEMO.md), where DATABASE_URL reaches the
database: `railway ssh`, then `/opt/venv/bin/python demo_company.py`.

## What it is

A cleaning company in Austin that has been running on Akye for about six
months: a team of six, fifty-odd customers, recurring work, a sales pipeline,
payments, payouts, reviews and a few text threads -- and a morning
that makes sense the moment the dashboard opens. Every date is worked out from
the day it is built, so it is always "this morning", however long from now it
is run. See DEMO.md for the story it tells and the paths through it.

## What it can never do

It is a real company in the registry (organizations) with is_demo and is_test
set, which means demo_guard.py stops anything it does from leaving Akye, it is
left out of every product number, and the scheduler never runs its
automations. The seed itself runs under demo_guard.forced() from its first
line, before the company is even registered.

It can only ever build or replace the one company at DEMO_SLUG, and only if
that company is already marked as a demo (or does not exist yet). A real
company that happens to hold the address is refused.

## How a rebuild stays all-or-nothing

The new copy is built in a separate staging schema, checked, and only then
swapped in for the live one in a single transaction. If any stage fails, the
staging schema is dropped and the demo people are already using is untouched.

## Built the way the app builds things

Schemas, tables and starter content come from provisioning (as signup does).
Prices come from pricing.calculate_job, quotes from quoting.quote_lead and
accept_quote, payments from payments.mark_paid / mark_deposit_paid, recurring
visits from recurring.generate_series, invoices from invoicing.issue, and
cleaner pay from Booking.default_crew_pay and contractor_pay.queue_for_booking.
The rest -- crew rows, time entries, ratings, text threads, expenses -- has no
service to go through, and is written with the same fields the app writes,
then checked by verify().
"""
import argparse
import os
import random
import secrets
import sys
from datetime import date, datetime, time, timedelta, timezone

# ── The company ────────────────────────────────────────────────────────────

DEMO_SLUG = os.environ.get('DEMO_SLUG', 'brightnest')
COMPANY = {
    'business_name': 'BrightNest Cleaning Co.',
    'phone': '(512) 555-0100',
    'email': 'hello@brightnest.example',
    'address': '4200 Guadalupe St, Suite 3',
    'city': 'Austin', 'state': 'TX', 'zip_code': '78751',
    'website': 'https://brightnest.example',
    'timezone': 'America/Chicago',
    'brand_tagline': 'Homes that breathe easier.',
    'brand_accent': '#2F7D6D',
    'google_review_link': 'https://brightnest.example/reviews',
    'worker_model': 'contractor',
    'charge_hour': '9',
    'invoice_net_days': '7',
    'pricing_reviewed': '1',
    'terms_reviewed': '1',
    'booking_page_shared': '1',
}
OWNER = ('Sarah Mitchell', 'sarah@brightnest.example', 'owner')
OPS = ('Priya Shah', 'priya@brightnest.example', 'dispatcher')
RNG_SEED = 20260926
BIZ_TZ = COMPANY['timezone']

# name, email, phone digits, level, language, color, months on the team.
# Everybody is paid the way Akye actually pays: the labor rate (pricing.
# get_labor_rate, $43) per person-hour a job is priced at. A per-cleaner
# percentage here would put "48% of job" beside earnings that are not 48%.
TEAM = [
    ('Maria Lopez',     'maria.lopez',     '5125550140', 'senior', 'es', '#2F7D6D', 9),
    ('Jasmine Carter',  'jasmine.carter',  '5125550141', 'senior', 'en', '#3B6FB5', 9),
    ('Alicia Brooks',   'alicia.brooks',   '5125550142', 'senior', 'en', '#B5476B', 7),
    ('Daniel Reyes',    'daniel.reyes',    '5125550143', 'new',    'es', '#D98A2B', 5),
    ('Nicole Grant',    'nicole.grant',    '5125550144', 'new',    'en', '#6B5BD2', 4),
    ('Tasha Williams',  'tasha.williams',  '5125550145', 'new',    'en', '#2F9E6B', 2),
]
MARIA, JASMINE, ALICIA, DANIEL, NICOLE, TASHA = range(6)

FIRST = ['Olivia', 'Marcus', 'Hannah', 'Derek', 'Priscilla', 'Ethan', 'Naomi', 'Grant',
         'Vanessa', 'Owen', 'Leticia', 'Caleb', 'Imani', 'Brandon', 'Rosalind', 'Theo',
         'Megan', 'Andre', 'Lauren', 'Isaac', 'Beatriz', 'Colin', 'Danielle', 'Felix',
         'Gwen', 'Hector', 'Ines', 'Jonah', 'Kiara', 'Lucas', 'Mira', 'Nolan', 'Paige',
         'Quentin', 'Renee', 'Samuel', 'Talia', 'Victor', 'Whitney', 'Xavier', 'Yvonne',
         'Zachary', 'Aubrey', 'Bianca', 'Celeste', 'Dominic', 'Elena', 'Frank', 'Giselle',
         'Harper', 'Ivan', 'Joanna']
LAST = ['Harlow', 'Castillo', 'Whitaker', 'Nguyen', 'Okafor', 'Brennan', 'Delgado',
        'Fairchild', 'Kowalski', 'Pruitt', 'Ashford', 'Lindqvist', 'Moreau', 'Sato',
        'Villanueva', 'Hargrove', 'Ellison', 'Quintero', 'Dunmore', 'Abernathy', 'Solis',
        'Yarbrough', 'Kimura', 'Lockhart', 'Mendez', 'Stroud', 'Tran', 'Holloway',
        'Iverson', 'Galloway', 'Pemberton', 'Rhodes', 'Salazar', 'Thornbury', 'Underwood',
        'Vance', 'Westbrook', 'Yoon', 'Zamora', 'Beckett', 'Carver', 'Duval', 'Esposito',
        'Fenwick', 'Guerrero', 'Haddad', 'Ingram', 'Jennings', 'Kessler', 'Landry',
        'Maddox', 'Novak']
STREETS = ['Bluebonnet Ln', 'Pecan Grove Dr', 'Live Oak St', 'Barton Ridge Rd',
           'Cedar Bend Ct', 'Mesquite Trl', 'Riverbend Dr', 'Juniper Hollow',
           'Limestone Way', 'Cypress Creek Rd', 'Agave Ct', 'Lantana Ln',
           'Wildflower Dr', 'Prairie Dove Ln', 'Sycamore Bend', 'Redbud Trl']
ZIPS = ['78704', '78745', '78731', '78757', '78749', '78703', '78723', '78758',
        '78746', '78741']
SIZES = [(2, 2), (3, 2), (4, 3), (3, 3), (2, 1), (4, 2), (1, 1), (5, 3)]
SLOTS = ['8:00 AM', '9:00 AM', '10:30 AM', '1:00 PM', '2:30 PM']
# Each recurring plan's usual time. Customer 4's moves to 1:00 PM tomorrow.
PLAN_SLOTS = {1: '8:00 AM', 2: '9:00 AM', 3: '9:00 AM', 4: '10:30 AM',
              5: '1:00 PM', 6: '2:30 PM', 7: '10:30 AM', 8: '1:00 PM'}

# Who each customer is, by position in the list above. Kept here, in one
# place, so the story can be read without reading the code that builds it.
JOURNEY = 0                          # lead -> quote -> booking -> paid -> review
WEEKLY = (1, 2)
BIWEEKLY = (3, 4, 5, 6)
MONTHLY = (7, 8)
OCCASIONAL = tuple(range(9, 29))     # a few visits each over the months
ONE_TIME = tuple(range(29, 43))      # came once
NEW_FIRST = (43, 44, 45, 46)         # first clean coming up, deposit paid
DORMANT = (47, 48, 49)               # nothing since the spring
OVERDUE = (50, 51)                   # finished, invoiced, not paid
CANCELLED = 28                       # cancelled their next visit

REVIEWS = [
    (5, 'Came home to a spotless kitchen. Maria even organized the spice rack!'),
    (5, 'Always on time and the house smells amazing.'),
    (5, 'Deep clean was worth every penny. Baseboards look new.'),
    (4, 'Great job overall. Missed the guest bathroom mirror but fixed it next visit.'),
    (5, 'Jasmine is wonderful with our dogs. Highly recommend.'),
    (5, 'Booking online took two minutes. Easy.'),
    (5, 'Best cleaning service we have tried in Austin.'),
    (4, 'Very thorough. Arrived about 15 minutes late.'),
    (5, 'The move-out clean got us our full deposit back.'),
    (5, 'Friendly crew and they text before they arrive.'),
    (3, 'Good clean, but the windows were not included like I thought.'),
    (5, 'Consistent every two weeks. Worth it for a busy family.'),
    (5, 'Alicia and Daniel were fast and careful with our floors.'),
    (4, 'Solid job. Would like an earlier arrival window.'),
    (5, 'They left a little note. Such a nice touch.'),
    (5, 'Fridge and oven look brand new.'),
    (5, 'Reliable, kind, and they actually listen.'),
    (4, 'Nice work on a very dusty house.'),
    (5, 'Easy to reschedule by text when we traveled.'),
    (5, 'Our office has never looked this good.'),
]


def _utcnow():
    """Naive UTC now, the way the models store timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def phone(digits):
    """'5125550101' -> '(512) 555-0101', the way people actually type it in."""
    return f'({digits[:3]}) {digits[3:6]}-{digits[6:]}'


def digits(p):
    return ''.join(ch for ch in (p or '') if ch.isdigit())[-10:]


class SeedError(RuntimeError):
    def __init__(self, stage, cause):
        super().__init__(f'{stage}: {type(cause).__name__}: {cause}')
        self.stage = stage


# ── Dates ──────────────────────────────────────────────────────────────────

def demo_today():
    """The day the demo is 'this morning' on -- the same date the dashboard uses."""
    return date.today()


def _tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(BIZ_TZ)


def at(day, slot):
    """A local wall-clock time in Austin, as the naive UTC the app stores."""
    from zoneinfo import ZoneInfo
    t = datetime.strptime(slot, '%I:%M %p').time()
    local = datetime.combine(day, t).replace(tzinfo=_tz())
    return local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)


# ── The build ──────────────────────────────────────────────────────────────

class Builder:
    """Everything for one build, so each stage can use what earlier ones made."""

    def __init__(self, today=None, say=print):
        self.today = today or demo_today()
        self.rng = random.Random(RNG_SEED)
        self.say = say
        self.team = []
        self.clients = []
        self.bookings = []
        self.busy = {}                  # day -> cleaners already booked that day

    def d(self, n):
        return self.today + timedelta(days=n)

    @staticmethod
    def weekday(day):
        """The same day, or the Monday after if it falls on a weekend."""
        return day + timedelta(days=7 - day.weekday()) if day.weekday() >= 5 else day

    def wd(self, n):
        """n days from today, moved off the weekend."""
        return self.weekday(self.d(n))

    def spread(self, f):
        """A weekday in the last six months: f=0 the oldest, f=1 last week.

        Weighted toward recent months -- the company has been growing -- and
        weekdays only, which is when a cleaning company does most of its work."""
        days = [self.d(n) for n in range(-165, -1) if self.d(n).weekday() < 5]
        return days[min(len(days) - 1, int((min(f, 0.999) ** 0.7) * len(days)))]

    # stage: company ------------------------------------------------------
    def company(self):
        from models import BusinessSetting, User, DiscountCode
        from extensions import db
        import automations
        for k, v in COMPANY.items():
            BusinessSetting.set(k, v)
        for name, email, role in (OWNER, OPS):
            u = User(name=name, username=email, role=role, active=True,
                     created_at=at(self.d(-200 if role == 'owner' else -120), '9:00 AM'))
            u.set_password(secrets.token_urlsafe(24))   # replaced by credentials()
            db.session.add(u)
        db.session.add(DiscountCode(code='NESTNEW', discount_type='percent',
                                    discount_value=15, max_uses=100, times_used=0,
                                    is_active=True, created_at=at(self.d(-150), '9:00 AM')))
        db.session.commit()
        for job, *_ in automations.JOBS:
            automations.set_enabled(job, job not in automations.DEFAULT_OFF)
        automations.set_balance_mode('ask')
        automations.set_cleaner_reminders_enabled(True)
        db.session.commit()

    # stage: team ---------------------------------------------------------
    def team_(self):
        from models import Staff, Availability
        from extensions import db
        import pricing
        rate = pricing.get_labor_rate()
        for i, (name, email, tel, level, lang, color, months) in enumerate(TEAM):
            joined = self.d(-months * 30)
            s = Staff(name=name, email=f'{email}@brightnest.example', phone=phone(tel),
                      color=color, is_active=True, pay_type='hourly', pay_rate=rate,
                      experience_level=level, language=lang, worker_model='contractor',
                      has_transportation=True, has_supplies=i != TASHA,
                      payment_pref='zelle', pay_schedule='weekly',
                      agreement_token=secrets.token_urlsafe(32),
                      agreement_signature=name,
                      agreement_signed_at=at(joined, '10:00 AM'),
                      welcome_forms_at=at(joined, '11:00 AM'),
                      orientation_completed_at=at(joined + timedelta(days=1), '2:30 PM'),
                      roster_start_date=joined.isoformat(),
                      emergency_contact_name='On file', emergency_contact_phone='(512) 555-0199',
                      created_at=at(joined, '9:00 AM'))
            # Every step of onboarding done -- the optional trial shift aside
            # for Tasha, who joined last and went straight to her own jobs.
            import json
            s.onboarding_steps = json.dumps([
                k for k, _ in Staff.ONBOARDING_STEPS
                if k not in Staff.EMPLOYEE_ONLY_STEPS
                and not (i == TASHA and k == 'shadow_job')])
            db.session.add(s)
            self.team.append((s, joined))
        db.session.flush()
        # This week's answers to "which days can you work?"
        off = {TASHA: (5, 6), NICOLE: (6,), DANIEL: (2,)}
        for i, (s, _) in enumerate(self.team):
            for n in range(0, 7):
                day = self.d(n)
                db.session.add(Availability(staff_id=s.id, day=day.isoformat(),
                                            available=day.weekday() not in off.get(i, ()),
                                            note='after 1pm' if (i == JASMINE and n == 2) else None))
        db.session.commit()

    def staff(self, i):
        return self.team[i][0]

    def can_work(self, i, day):
        return self.team[i][1] <= day

    # stage: customers ----------------------------------------------------
    def customers(self):
        from models import Client
        from extensions import db
        assert len(FIRST) == len(LAST) == 52, 'the cast is 52 customers'
        for i in range(52):
            name = f'{FIRST[i]} {LAST[i]}'
            street = STREETS[i % len(STREETS)]
            apt = f' #{200 + i}' if i % 9 == 4 else ''
            c = Client(name=name, email=f'{FIRST[i].lower()}.{LAST[i].lower()}@example.com',
                       phone=phone(f'512555{101 + i:04d}' if i < 39 else f'512555{150 + i - 39:04d}'),
                       address=f'{1100 + i * 37} {street}{apt}', city='Austin',
                       zip_code=ZIPS[i % len(ZIPS)],
                       portal_token=secrets.token_urlsafe(24),
                       notes='Gate code 4821. Two friendly cats.' if i == 1 else
                             'Prefers unscented products.' if i == 9 else None)
            db.session.add(c)
            self.clients.append(c)
        db.session.commit()

    def size(self, i):
        return SIZES[i % len(SIZES)]

    # the one way a job is made -----------------------------------------
    def job(self, i, day, slot, service='standard', extras=(), frequency='one_time',
            status='completed', crew=(), discount_pct=0, source='website', group=None,
            created=None, notes=None):
        import pricing
        from models import Booking, BookingCrew
        from extensions import db
        c = self.clients[i]
        beds, baths = self.size(i)
        calc = pricing.calculate_job(service, beds, baths, extras=list(extras),
                                     frequency=frequency)
        discount = round(calc['client_price'] * discount_pct / 100, 2)
        price = round(calc['client_price'] - discount, 2)
        b = Booking(client_id=c.id, service_type=service, bedrooms=beds, bathrooms=baths,
                    extras=', '.join(extras), frequency=frequency,
                    preferred_date=day.isoformat(), preferred_time=slot,
                    name=c.name, email=c.email, phone=c.phone, address=c.address,
                    city=c.city, zip_code=c.zip_code, price=price, balance_due=price,
                    estimated_hours=calc['hours'],
                    labor_rate_applied=pricing.get_labor_rate(),
                    crew_size=max(1, len(crew)), status=status, source=source,
                    discount_code='NESTNEW' if discount_pct else '',
                    discount_amount=discount, recurring_group=group,
                    recurring_active=bool(group) or None, notes=notes,
                    created_at=created or at(day - timedelta(days=4 + i % 6), '9:00 AM'))
        db.session.add(b)
        db.session.flush()
        self.assign(b, day, crew)
        self.bookings.append(b)
        return b

    def assign(self, b, day, crew):
        """Put cleaners on a job the way bookings.py does: a crew row at the
        default share of the labor budget, the first name on the job, off the
        claim board."""
        from models import BookingCrew
        from extensions import db
        for n, s_i in enumerate(crew):
            s = self.staff(s_i)
            db.session.add(BookingCrew(booking_id=b.id, staff_id=s.id,
                                       pay_amount=b.default_crew_pay(s, size=len(crew)),
                                       created_at=b.created_at))
            if n == 0:
                b.assigned_cleaner = s.name
                b.open_for_claim = False
        if crew and b.status != 'cancelled':
            b.cleaner_notified_at = b.created_at + timedelta(hours=1)
            b.cleaner_response = 'accepted'
            self.busy.setdefault(day, set()).update(crew)

    def pick_crew(self, day, size=1):
        """Cleaners on the team by then and free that day, rotated so the work
        is shared out."""
        free = [i for i in range(6) if self.can_work(i, day)
                and i not in self.busy.get(day, ())]
        pool = free if len(free) >= size else \
            [i for i in range(6) if self.can_work(i, day)]
        start = (day.toordinal() * 7) % len(pool)
        return tuple(pool[(start + k) % len(pool)] for k in range(size))

    # stage: history ------------------------------------------------------
    def history(self):
        from extensions import db
        rng = self.rng
        # Recurring plans: past visits, all done. Future visits come in plans().
        # Today's and tomorrow's plans run on whatever day those are; the rest
        # land on weekdays, when a cleaning company does most of its work.
        self.plans_seed = {}
        anchors = {1: 0, 2: 1, 3: 0, 4: 1}
        for i, n in ((5, 3), (6, 5), (7, 10), (8, 17)):
            anchors[i] = (self.wd(n) - self.today).days
        for i in WEEKLY + BIWEEKLY + MONTHLY:
            freq = 'weekly' if i in WEEKLY else 'biweekly' if i in BIWEEKLY else 'monthly'
            step = 7 if freq == 'weekly' else 14 if freq == 'biweekly' else 30
            visits = {'weekly': 12, 'biweekly': 12 - (i - 3) * 1, 'monthly': 6 - (i - 7)}[freq]
            group = f'bn-plan-{i:02d}'
            slot = PLAN_SLOTS[i]
            regular = (MARIA, TASHA, JASMINE, NICOLE, ALICIA, DANIEL, MARIA, JASMINE)[i - 1]
            for k in range(visits, 0, -1):
                day = self.d(anchors[i] - k * step)
                if freq == 'monthly':
                    day = self.weekday(day)
                free = self.can_work(regular, day) and regular not in self.busy.get(day, ())
                crew = (regular,) if free else self.pick_crew(day)
                self.job(i, day, slot, frequency=freq, crew=crew, group=group,
                         extras=('Inside fridge',) if (i == 7 and k % 3 == 0) else ())
            self.plans_seed[i] = (freq, group, slot, regular, anchors[i])

        # Occasional customers: two or three visits each, spread across the
        # months so no week is empty.
        services = ['standard', 'standard', 'deep', 'standard', 'moveout']
        for i in OCCASIONAL:
            n = 2 + (i % 3 == 0)
            for k in range(n):
                day = self.spread((k + 0.15 + ((i * 7) % 10) / 14) / n)
                svc = services[(i + k) % len(services)]
                if svc == 'moveout' and k:
                    svc = 'deep'
                size = 2 if svc != 'standard' and i % 2 else 1
                extras = (('Inside oven',) if (i + k) % 4 == 0 else ()) + \
                         (('Inside windows',) if (i + k) % 7 == 0 else ())
                self.job(i, day, SLOTS[(i + k) % len(SLOTS)], service=svc, extras=extras,
                         crew=self.pick_crew(day, size))

        # One-time customers. The rest came through a quote (see pipeline()).
        for i in ONE_TIME:
            if i >= 35:
                day = self.spread(((i * 13) % 97) / 97)
                svc = 'moveout' if i % 3 == 0 else 'deep'
                self.job(i, day, SLOTS[i % len(SLOTS)], service=svc,
                         crew=self.pick_crew(day, 2 if svc == 'moveout' else 1),
                         discount_pct=15 if i % 4 == 0 else 0,
                         source='google' if i % 2 else 'website')

        # Dormant: nothing since the spring.
        for i in DORMANT:
            for k in range(2):
                day = self.weekday(self.d(-175 + i + k * 28))
                self.job(i, day, SLOTS[k % len(SLOTS)], crew=self.pick_crew(day))

        # Finished, invoiced, still unpaid.
        for n, i in enumerate(OVERDUE):
            day = self.weekday(self.d(-20 - n * 15))
            self.job(i, day, SLOTS[2 + n], service='deep', crew=self.pick_crew(day))

        # No weekday in the last three weeks without work: a quiet day right
        # before a busy Monday reads as a company that is not really running.
        spare = iter(OCCASIONAL[::3])
        worked = {date.fromisoformat(b.preferred_date) for b in self.bookings}
        for n in range(-21, -1):
            day = self.d(n)
            if day.weekday() < 5 and day not in worked:
                i = next(spare)
                self.job(i, day, SLOTS[(n * 3) % len(SLOTS)], crew=self.pick_crew(day))

        # Yesterday: one paid and reviewed this morning, one invoiced last night
        # and not yet paid -- the payment the dashboard asks about.
        self.reviewed_yesterday = self.job(16, self.d(-1), '9:00 AM', crew=(MARIA,))
        self.attention = self.job(17, self.d(-1), '1:00 PM', service='deep',
                                  crew=(JASMINE,), extras=('Inside windows',))

        # A cancellation or two in the history, as every calendar has.
        for i in (12, 21):
            day = self.weekday(self.d(-40 + i))
            b = self.job(i, day, '1:00 PM', status='cancelled')
            b.internal_notes = 'Customer traveling -- will rebook.'
        db.session.commit()

    # stage: pipeline (leads and quotes, through the app's own quoting) ---
    def pipeline(self):
        import quoting
        from models import Lead
        from extensions import db
        rng = self.rng

        def quote(i, service, extras=(), frequency='one_time', source='website',
                  created=0, discount_pct=0):
            import pricing
            c = self.clients[i]
            beds, baths = self.size(i)
            calc = pricing.calculate_job(service, beds, baths, extras=list(extras),
                                         frequency=frequency)
            price = round(calc['client_price'] * (1 - discount_pct / 100), 2)
            lead = quoting.quote_lead(c.name, c.email, c.phone, service, beds, baths,
                                      extras=', '.join(extras), frequency=frequency,
                                      price=price, address=c.address, city=c.city,
                                      zip_code=c.zip_code)
            lead.source = source
            lead.created_at = at(self.d(created), '9:00 AM')
            lead.quote_sent_at = at(self.d(created), '11:30 AM')   # sent; never actually sent
            if discount_pct:
                lead.discount_code, lead.discount_amount = 'NESTNEW', round(
                    calc['client_price'] - price, 2)
            db.session.commit()
            return lead

        def book_from(lead, i, day, slot, crew=(), status='completed'):
            """The customer accepts the quote -- quoting.accept_quote, as the page does."""
            b = quoting.accept_quote(lead, preferred_date=day.isoformat(),
                                     preferred_time=slot)
            b.created_at = lead.quote_sent_at + timedelta(hours=5)
            beds, baths = self.size(i)
            import pricing
            calc = pricing.calculate_job(b.service_type, beds, baths,
                                         extras=[e for e in (b.extras or '').split(', ') if e])
            b.estimated_hours = calc['hours']
            b.labor_rate_applied = pricing.get_labor_rate()
            b.crew_size = max(1, len(crew))
            db.session.flush()
            self.assign(b, day, crew)
            b.status = status
            self.bookings.append(b)
            db.session.commit()
            return b

        # The canonical journey: a website lead, quoted, accepted, cleaned
        # six days ago, paid, and reviewed. Her second visit is on the books.
        lead = quote(JOURNEY, 'deep', extras=('Inside oven', 'Inside fridge'),
                     source='website', created=-11)
        self.journey = book_from(lead, JOURNEY, self.d(-6), '9:00 AM',
                                 crew=(ALICIA, DANIEL))
        self.journey.notes = 'First visit. Kitchen is the priority.'

        # Earlier one-time customers who came through a quote.
        for i in ONE_TIME:
            if i < 35:
                src = ('google', 'referral', 'facebook', 'website')[i % 4]
                svc = 'moveout' if i % 3 == 0 else 'deep'
                day = self.spread(((i * 29) % 89) / 89)
                created = (day - self.today).days - 6
                lead = quote(i, svc, source=src, created=created,
                             discount_pct=15 if i % 4 == 1 else 0)
                book_from(lead, i, day, SLOTS[i % len(SLOTS)],
                          crew=self.pick_crew(day, 2 if svc == 'moveout' else 1))

        # New customers: quoted, accepted, deposit paid, first clean coming up.
        firsts = {43: (0, '1:00 PM', 'moveout'),
                  44: ((self.wd(3) - self.today).days, '9:00 AM', 'deep'),
                  45: ((self.wd(5) - self.today).days, '10:30 AM', 'standard'),
                  46: ((self.wd(9) - self.today).days, '2:30 PM', 'deep')}
        self.new_first = {}
        for i, (days_out, slot, svc) in firsts.items():
            lead = quote(i, svc, source=('website', 'referral', 'google', 'facebook')[i % 4],
                         created=-8 + i % 4)
            day = self.d(days_out)
            # Maria takes today's after her 8:00; the next two are covered;
            # the last is still waiting for somebody.
            crew = (MARIA,) if i == 43 else () if i == 46 else self.pick_crew(day)
            self.new_first[i] = book_from(lead, i, day, slot, crew=crew,
                                          status='confirmed' if crew else 'pending')

        # The pipeline today: people who have asked and not yet booked.
        open_leads = [
            ('Rebecca Tate', 'deep', 3, 2, 'website', 'new', 0, 'Wants a deep clean before her parents visit.'),
            ('Jordan Ellis', 'standard', 2, 2, 'google', 'new', -1, None),
            ('Sofia Marchetti', 'moveout', 2, 1, 'facebook', 'new', -3, 'Lease ends on the 30th.'),
            ('Aaron Blackwell', 'standard', 4, 3, 'referral', 'contacted', -4, 'Referred by Olivia Harlow.'),
            ('Chloe Park', 'deep', 3, 3, 'website', 'contacted', -5, None),
            ('Martin Obi', 'standard', 3, 2, 'phone', 'contacted', -7, 'Asked about biweekly.'),
            ('Laila Hassan', 'moveout', 4, 2, 'google', 'contacted', -9, None),
            ('Greg Summers', 'deep', 2, 2, 'website', 'contacted', -12, 'Quote sent; follow up Friday.'),
            ('Tina Robles', 'standard', 1, 1, 'facebook', 'lost', -26, 'Went with a friend who cleans.'),
            ('Victor Alvarez', 'moveout', 3, 2, 'google', 'lost', -33, 'Moved the date out a month; out of area.'),
        ]
        import pricing
        for n, (name, svc, beds, baths, src, status, created, notes) in enumerate(open_leads):
            first = name.split()[0].lower()
            calc = pricing.calculate_job(svc, beds, baths)
            l = Lead(name=name, email=f'{first}.{name.split()[1].lower()}@example.com',
                     phone=phone(f'512555{170 + n:04d}'), service_type=svc, bedrooms=beds,
                     bathrooms=baths, frequency='biweekly' if 'biweekly' in (notes or '') else 'one_time',
                     city='Austin', zip_code=ZIPS[n % len(ZIPS)], status=status, source=src,
                     notes=notes, quoted_price=calc['client_price'],
                     created_at=at(self.d(created), '8:15 AM' if created == 0 else '2:00 PM'))
            if status in ('contacted', 'lost'):
                l.quote_token = secrets.token_urlsafe(32)
                l.quote_sent_at = at(self.d(created), '4:00 PM')
            db.session.add(l)
        # A commercial enquiry, priced at a walkthrough rather than the matrix.
        db.session.add(Lead(name='Dana Whitfield', email='dana.whitfield@example.com',
                            phone='(512) 555-0180', service_type='commercial', sqft=3200,
                            city='Austin', zip_code='78701', status='contacted',
                            source='referral', notes='Riverside Dental -- 3,200 sq ft, '
                            'evenings, three times a week.',
                            created_at=at(self.d(-6), '10:00 AM')))
        db.session.commit()
        self.commercial()

    def commercial(self):
        from models import CommercialAccount, CommercialQuote
        from extensions import db
        db.session.add_all([
            CommercialAccount(business_name='Congress Avenue Law Group',
                              contact_name='Helen Park', email='office@congresslaw.example',
                              phone='(512) 555-0190', address='700 Congress Ave, Floor 4',
                              city='Austin', square_footage=5200, drive_minutes=12,
                              category='office', frequency='weekly', billing_type='monthly',
                              billing_amount=1450, status='active', source='referral',
                              first_paid_at=at(self.d(-120), '9:00 AM'),
                              created_at=at(self.d(-128), '9:00 AM')),
            CommercialAccount(business_name='Mueller Pediatric Therapy',
                              contact_name='Andre Coles', email='admin@muellerpt.example',
                              phone='(512) 555-0191', address='1900 Aldrich St, Suite 110',
                              city='Austin', square_footage=2100, drive_minutes=18,
                              category='medical', frequency='biweekly', billing_type='monthly',
                              billing_amount=620, status='active', source='website',
                              first_paid_at=at(self.d(-55), '9:00 AM'),
                              created_at=at(self.d(-63), '9:00 AM')),
        ])
        db.session.add_all([
            CommercialQuote(company='Riverside Dental', contact_name='Dana Whitfield',
                            email='dana.whitfield@example.com', phone='(512) 555-0180',
                            property_type='medical office', property_address='2110 Riverside Dr',
                            sqft=3200, services='Nightly janitorial, restrooms, exam rooms',
                            frequency='3x weekly', contract_term='12 months',
                            price_per_visit=145, monthly_price=1885, status='sent',
                            token=secrets.token_urlsafe(24),
                            created_at=at(self.d(-5), '10:00 AM'),
                            sent_at=at(self.d(-5), '3:00 PM'),
                            viewed_at=at(self.d(-4), '8:40 AM')),
            CommercialQuote(company='Congress Avenue Law Group', contact_name='Helen Park',
                            email='office@congresslaw.example', property_type='office',
                            sqft=5200, services='Weekly office clean, kitchen, restrooms',
                            frequency='weekly', contract_term='12 months',
                            price_per_visit=335, monthly_price=1450, status='accepted',
                            token=secrets.token_urlsafe(24),
                            created_at=at(self.d(-135), '10:00 AM'),
                            sent_at=at(self.d(-134), '9:00 AM'),
                            responded_at=at(self.d(-129), '4:00 PM')),
            CommercialQuote(company='Eastside Coworking', contact_name='Kim Ortega',
                            email='kim.ortega@example.com', property_type='coworking',
                            sqft=4000, services='Daily common areas', frequency='5x weekly',
                            price_per_visit=120, monthly_price=2600, status='draft',
                            token=secrets.token_urlsafe(24),
                            created_at=at(self.d(-1), '4:00 PM')),
        ])
        db.session.commit()

    # stage: today and what is coming ------------------------------------
    def plans(self):
        """Today's jobs, tomorrow's, and the recurring plans carried forward."""
        import recurring
        from extensions import db
        self.today_jobs = []

        # Each plan's next visit is its seed; recurring.generate_series fills
        # three weeks ahead from it, as the app does when a plan is set up.
        seeds = {}
        for i, (freq, group, slot, regular, days_out) in self.plans_seed.items():
            day = self.d(days_out)
            if days_out <= 1:
                crew = (regular,)                  # today's and tomorrow's, as the story says
            elif regular not in self.busy.get(day, ()):
                crew = (regular,)
            else:
                crew = self.pick_crew(day)
            if i == 4:
                slot = '1:00 PM'                   # moved by text yesterday (messages())
            b = self.job(i, day, slot, frequency=freq, status='confirmed', crew=crew,
                         group=group)
            seeds[i] = b
            if days_out == 0:
                self.today_jobs.append(b)
        db.session.commit()
        for i, b in seeds.items():
            recurring.generate_series(b, weeks_ahead=3)
        # A customer on a plan has already said yes to every visit on it.
        from models import Booking
        for b in Booking.query.filter(Booking.recurring_group.isnot(None),
                                      Booking.status == 'pending').all():
            b.status = 'confirmed'
        db.session.commit()

        # Today: five jobs, four cleaners, one still out for anyone to claim.
        deep = self.job(9, self.today, '10:30 AM', service='deep', status='confirmed',
                        crew=(ALICIA, DANIEL), extras=('Inside oven',))
        self.today_jobs.append(deep)
        first = self.new_first[43]                  # 1:00 PM move-out, Maria after her 8:00
        self.today_jobs.append(first)
        claim = self.job(10, self.today, '2:30 PM', status='confirmed')
        claim.open_for_claim = True
        claim.claim_token = secrets.token_urlsafe(24)
        claim.broadcast_at = at(self.today, '7:15 AM')
        self.today_jobs.append(claim)

        # Tomorrow: one waiting on the customer, one nobody is on yet.
        wait = self.job(12, self.d(1), '8:00 AM', status='pending', crew=(JASMINE,))
        wait.confirm_token = secrets.token_urlsafe(24)
        wait.confirm_sent_at = at(self.d(-1), '5:00 PM')
        self.awaiting = wait
        self.unassigned_tomorrow = self.job(11, self.d(1), '10:30 AM', status='confirmed')

        # The rest of the fortnight: a few one-offs, and a cancellation.
        for i, n, slot, svc in ((13, 4, '9:00 AM', 'deep'), (14, 6, '1:00 PM', 'standard')):
            day = self.wd(n)
            self.job(i, day, slot, service=svc, status='confirmed', crew=self.pick_crew(day))
        self.job(15, self.wd(11), '10:30 AM', status='pending')    # just asked; nobody yet
        day = self.wd(8)
        again = (ALICIA,) if ALICIA not in self.busy.get(day, ()) else self.pick_crew(day)
        self.job(JOURNEY, day, '9:00 AM', status='confirmed', crew=again,
                 notes='Second visit -- standard clean.')
        lost = self.job(CANCELLED, self.d(2), '2:30 PM', status='cancelled')
        lost.internal_notes = 'Cancelled by text -- moving out of Austin.'
        db.session.commit()

        # A job started this morning: Maria clocked in at 8:04 at the Castillos'.
        from models import TimeEntry, JobChecklist, ChecklistTemplate
        weekly_today = next(b for b in self.today_jobs if b.client_id == self.clients[1].id)
        db.session.add(TimeEntry(booking_id=weekly_today.id, staff_id=self.staff(MARIA).id,
                                 clock_in_at=at(self.today, '8:04 AM')))
        tpl = ChecklistTemplate.query.first()
        if tpl:
            db.session.add(JobChecklist(
                booking_id=weekly_today.id, token=secrets.token_hex(16),
                template_name=tpl.name, items=tpl.items, completed_items='[]',
                sent_at=at(self.d(-1), '6:00 PM'), on_the_way_at=at(self.today, '7:48 AM'),
                clock_in_at=at(self.today, '8:04 AM')))
        db.session.commit()

    # stage: timesheets --------------------------------------------------
    def timesheets(self):
        """Clock-in and clock-out for every finished job, the way My Day records
        them: a few minutes either side of the start, and roughly the hours the
        job was priced at, because real days are never exactly on estimate."""
        from models import TimeEntry, BookingCrew
        from extensions import db
        for b in self.bookings:
            if b.status != 'completed':
                continue
            day = date.fromisoformat(b.preferred_date)
            crew = BookingCrew.query.filter_by(booking_id=b.id).all()
            each = b.hours_each() or b.estimated_hours or 2
            worked = 0.0
            for n, row in enumerate(crew):
                start = at(day, b.preferred_time) + timedelta(minutes=(b.id * 7 + n * 3) % 12 - 3)
                hours = round(each * (0.9 + ((b.id + n) % 5) * 0.05), 2)
                db.session.add(TimeEntry(booking_id=b.id, staff_id=row.staff_id,
                                         clock_in_at=start,
                                         clock_out_at=start + timedelta(hours=hours),
                                         created_at=start))
                worked += hours
            b.hours_worked = round(worked, 2) if crew else None
        db.session.commit()

    # stage: customer since ----------------------------------------------
    def since(self):
        """A customer is on the books from just before their first job or quote."""
        from models import Booking, Lead
        from extensions import db
        for c in self.clients:
            firsts = [b.created_at for b in Booking.query.filter_by(client_id=c.id).all()]
            lead = Lead.query.filter_by(email=c.email).first()
            if lead:
                firsts.append(lead.created_at)
            c.created_at = min(firsts) - timedelta(hours=1)
        db.session.commit()

    # stage: money --------------------------------------------------------
    def money(self):
        """Payments, invoices and cleaner pay for everything that is finished."""
        from blueprints.payments import mark_paid, mark_deposit_paid
        import invoicing
        import contractor_pay
        from models import Booking, ContractorPayment, BookingCrew
        from extensions import db
        rng = self.rng
        methods = ['card'] * 12 + ['zelle'] * 5 + ['cash'] * 2 + ['check']
        overdue_ids = {self.clients[i].id for i in OVERDUE}

        done = sorted([b for b in self.bookings if b.status == 'completed'],
                      key=lambda b: (b.preferred_date, b.preferred_time, b.id))
        for b in done:
            day = date.fromisoformat(b.preferred_date)
            b.completed_at = at(day, '4:30 PM')
            invoicing.issue(b)
            b.invoice_issued_at = at(day, '5:00 PM')
            b.invoice_due_date = (day + timedelta(days=7)).isoformat()
            # A quote booking took its deposit when it was accepted.
            if b.source == 'quote' and not b.deposit_paid:
                mark_deposit_paid(b, method='card', when=b.created_at, notify=False)
            if b.client_id in overdue_ids or b is self.attention:
                continue                                    # still owed
            if rng.random() < 0.22:
                b.tip_amount = rng.choice([15.0, 20.0, 25.0, 30.0, 40.0])
            method = rng.choice(methods)
            lag = 0 if method == 'card' else rng.choice([0, 1, 2, 3])
            mark_paid(b, method=method, when=at(day + timedelta(days=lag), '6:15 PM'),
                      notify=False)
        db.session.commit()

        # Deposits on the new customers' first cleans.
        for b in self.new_first.values():
            mark_deposit_paid(b, method='card', when=b.created_at + timedelta(minutes=8),
                              notify=False)
        db.session.commit()

        # What the cleaners are owed for each finished job, the way the app
        # queues it; paid every Friday for the week before, so this week's
        # work is still waiting on the payroll screen.
        last_friday = self.today - timedelta(days=(self.today.weekday() - 4) % 7 or 7)
        for b in done:
            contractor_pay.queue_for_booking(b)
        for pay in ContractorPayment.query.all():
            b = db.session.get(Booking, pay.booking_id)
            day = date.fromisoformat(b.preferred_date)
            payday = day + timedelta(days=(4 - day.weekday()) % 7 or 7)
            if payday > last_friday:
                continue                                    # this week's -- not paid yet
            crew = BookingCrew.query.filter_by(booking_id=b.id).all()
            if b.tip_amount:
                pay.tip_amount = round(b.tip_net / max(1, len(crew)), 2)
            pay.status = 'paid'
            pay.method = 'zelle'
            pay.created_at = at(payday, '5:00 PM')
            row = next((c for c in crew if c.staff_id == pay.staff_id), None)
            if row:
                row.paid_at = pay.created_at
                row.payment_id = pay.id
            b.cleaner_paid_at = pay.created_at
        db.session.commit()

    # stage: card fees -----------------------------------------------------
    def card_fees(self):
        """What Stripe kept each month, as stripe_fees.py would have synced it.

        A demo company never talks to Stripe (demo_guard.py), so the monthly
        figure is written here: 2.9% + 30 cents of every card payment, tip
        included, in the month the money landed. Without it the P&L would
        report card payments as free."""
        from zoneinfo import ZoneInfo
        from models import Booking, ProcessingFee
        from extensions import db
        utc, local = ZoneInfo('UTC'), _tz()
        months = {}
        for b in Booking.query.filter(Booking.paid_at.isnot(None),
                                      Booking.paid_method == 'card').all():
            when = b.paid_at.replace(tzinfo=utc).astimezone(local)
            charged = float(b.amount_collected or b.price) + float(b.tip_amount or 0)
            key = (when.year, when.month)
            months[key] = months.get(key, 0) + charged * 0.029 + 0.30
        for (y, m), fee in sorted(months.items()):
            db.session.add(ProcessingFee(year=y, month=m, amount=round(fee, 2),
                                         synced_at=_utcnow()))
        db.session.commit()

    # stage: costs --------------------------------------------------------
    def costs(self):
        from models import Expense, RecurringExpense
        from extensions import db
        db.session.add(RecurringExpense(category='insurance', amount=145.0,
                                        vendor='Next Insurance', method='card',
                                        day_of_month=5, active=True,
                                        created_at=at(self.d(-190), '9:00 AM')))
        for m in range(6, -1, -1):
            month = self.today.replace(day=1)
            for _ in range(m):
                month = (month - timedelta(days=1)).replace(day=1)
            wobble = (m * 37) % 60
            rows = [
                (month + timedelta(days=4), 'insurance', 145.00, 'Next Insurance'),
                (month + timedelta(days=6), 'supplies', 164.20 + wobble, 'Restaurant Depot'),
                (month + timedelta(days=19), 'supplies', 88.45 + wobble / 2, 'Target'),
                (month + timedelta(days=9), 'ads_google', 300.00 if m % 3 else 450.00, 'Google Ads'),
                (month + timedelta(days=14), 'fuel', 92.10 + wobble / 3, 'Mileage reimbursements'),
                (month + timedelta(days=2), 'software', 79.00, 'Akye'),
            ]
            for day, cat, amount, vendor in rows:
                if day <= self.today:
                    db.session.add(Expense(date=day.isoformat(), category=cat,
                                           amount=round(amount, 2), vendor=vendor,
                                           method='card', created_at=at(day, '9:00 AM')))
        db.session.commit()

    # stage: reviews ------------------------------------------------------
    def reviews(self):
        from models import BookingRating
        from extensions import db
        done = sorted([b for b in self.bookings if b.status == 'completed' and b.paid_at],
                      key=lambda b: b.preferred_date, reverse=True)
        # Yesterday's customer reviewed this morning; the journey customer too.
        chosen = [self.reviewed_yesterday, self.journey]
        for b in done:
            if len(chosen) >= len(REVIEWS):
                break
            if b not in chosen and b.id % 3 == 0:
                chosen.append(b)
        for b, (stars, comment) in zip(chosen, REVIEWS):
            day = date.fromisoformat(b.preferred_date)
            when = at(self.today, '7:20 AM') if day == self.d(-1) else \
                at(day + timedelta(days=1), '7:45 PM')
            if b is self.journey:
                stars, comment = 5, ('From the first message to the last corner, '
                                     'BrightNest was easy. The oven looks brand new.')
            db.session.add(BookingRating(booking_id=b.id, token=secrets.token_hex(16),
                                         rating=stars, comment=comment, rated_at=when,
                                         created_at=when))
            b.review_nudge_at = when - timedelta(hours=2)
        db.session.commit()

    # stage: messages -----------------------------------------------------
    def messages(self):
        from models import Message
        from extensions import db
        c4 = self.clients[4]
        c1 = self.clients[1]
        maria = self.staff(MARIA)
        rebecca_phone = '5125550170'      # her lead, first in the pipeline
        threads = [
            (digits(c4.phone), c4.name, None, [
                ('in', -1, '3:42 PM', "Hi! Could we move tomorrow's cleaning to 1 PM instead of 10:30?"),
                ('out', -1, '3:51 PM', "Absolutely — we've moved you to 1:00 PM tomorrow. "
                                       "Nicole will see you then."),
                ('in', -1, '3:53 PM', 'Thank you!!'),
            ]),
            (digits(maria.phone), maria.name, maria.id, [
                ('in', 0, '7:41 AM', "Morning! Running about 10 minutes behind, traffic on MoPac."),
                ('out', 0, '7:43 AM', f"Thanks Maria — I've let {c1.name.split()[0]} know."),
                ('in', 0, '8:05 AM', 'Here now, starting in the kitchen.'),
            ]),
            (rebecca_phone, 'Rebecca Tate', None, [
                ('in', 0, '8:12 AM', "Hi, I just requested a deep clean on your website. "
                                     "Do you bring your own supplies?"),
            ]),
        ]
        for phone, name, staff_id, rows in threads:
            for direction, day_n, slot, body in rows:
                when = at(self.d(day_n), slot)
                unread = direction == 'in' and day_n == 0 and phone == rebecca_phone
                db.session.add(Message(phone=phone, direction=direction, body=body,
                                       contact_name=name, staff_id=staff_id,
                                       created_at=when, read_at=None if unread else when))
        db.session.commit()

    # stage: automation history -------------------------------------------
    def automation_runs(self):
        from models import CronRun
        from extensions import db
        import automations
        for job, _label, _desc, cadence in automations.JOBS:
            if not automations.is_enabled(job):
                continue
            if cadence == 'hourly':
                for h in range(1, 6):
                    db.session.add(CronRun(job=job, ok=True, items=0,
                                           ran_at=_utcnow() - timedelta(hours=h)))
            else:
                for n in range(3, 0, -1):
                    db.session.add(CronRun(job=job, ok=True,
                                           items={'reminders': 7, 'lifecycle-emails': 3,
                                                  'send-drips': 2}.get(job, 0),
                                           ran_at=at(self.d(1 - n), '7:00 AM')))
        db.session.commit()

    def run(self):
        stages = [('company', self.company), ('team', self.team_),
                  ('customers', self.customers), ('history', self.history),
                  ('pipeline', self.pipeline), ('today and upcoming', self.plans),
                  ('timesheets', self.timesheets), ('customer since', self.since),
                  ('money', self.money), ('card fees', self.card_fees),
                  ('costs', self.costs),
                  ('reviews', self.reviews), ('messages', self.messages),
                  ('automations', self.automation_runs)]
        for name, fn in stages:
            try:
                fn()
            except Exception as e:
                from extensions import db
                db.session.rollback()
                raise SeedError(name, e) from e
            self.say(f'  {name:.<22} done')


# ── Checks ─────────────────────────────────────────────────────────────────

def counts():
    """What is in the company schema in use."""
    from models import (Booking, Client, Lead, Staff, User, BookingRating, Message,
                        ContractorPayment, Expense, CommercialAccount, CommercialQuote)
    today = demo_today().isoformat()
    up = Booking.query.filter(Booking.preferred_date > today,
                              Booking.status.in_(('pending', 'confirmed')))
    return {
        'users': User.query.count(),
        'team': Staff.query.count(),
        'customers': Client.query.count(),
        'leads': Lead.query.count(),
        'jobs': Booking.query.count(),
        'completed': Booking.query.filter_by(status='completed').count(),
        'today': Booking.query.filter(Booking.preferred_date == today,
                                      Booking.status != 'cancelled').count(),
        'upcoming': up.count(),
        'next 14 days': up.filter(Booking.preferred_date <= (
            demo_today() + timedelta(days=14)).isoformat()).count(),
        'recurring plans': len({b.recurring_group for b in Booking.query.filter(
            Booking.recurring_group.isnot(None)).all()}),
        'invoices': Booking.query.filter(Booking.invoice_number.isnot(None)).count(),
        'paid jobs': Booking.query.filter(Booking.paid_at.isnot(None)).count(),
        'cleaner payouts': ContractorPayment.query.count(),
        'reviews': BookingRating.query.count(),
        'messages': Message.query.count(),
        'expenses': Expense.query.count(),
        'commercial accounts': CommercialAccount.query.count(),
        'commercial quotes': CommercialQuote.query.count(),
    }


def verify():
    """[(check, ok, detail)] for the company schema in use. Nothing is written."""
    from sqlalchemy import func
    from extensions import db
    from models import (Booking, BookingCrew, Client, Lead, ContractorPayment,
                        BookingRating, Staff, User)
    from blueprints.payments import collected, is_settled
    import finance
    import invoicing
    import onboarding
    today = demo_today()
    out = []

    def check(name, ok, detail=''):
        out.append((name, bool(ok), detail))

    jobs = Booking.query.all()
    clients = {c.id for c in Client.query.all()}
    staff = {s.id for s in Staff.query.all()}

    check('every job belongs to a customer here',
          all(b.client_id in clients for b in jobs))
    valid = set(Booking.STATUS_LABELS)
    check('every job has a real status', all(b.status in valid for b in jobs),
          ', '.join(sorted({b.status for b in jobs} - valid)))
    crews = BookingCrew.query.all()
    check('every crew row points at a job and a cleaner here',
          all(c.staff_id in staff and c.booking_id in {b.id for b in jobs} for c in crews))
    check('nothing finished is in the future',
          all(b.preferred_date <= today.isoformat() for b in jobs if b.status == 'completed'))
    check('nothing still to do is in the past',
          all(b.preferred_date >= today.isoformat()
              for b in jobs if b.status in ('pending', 'confirmed')),
          ', '.join(b.preferred_date for b in jobs
                    if b.status in ('pending', 'confirmed') and b.preferred_date < today.isoformat()))

    # A cleaner is never booked into two jobs that overlap.
    clash = []
    by_day = {}
    for c in crews:
        b = next(x for x in jobs if x.id == c.booking_id)
        if b.status == 'cancelled':
            continue
        start = datetime.strptime(b.preferred_time, '%I:%M %p')
        end = start + timedelta(hours=(b.estimated_hours or 2) / max(1, b.crew_size or 1))
        by_day.setdefault((c.staff_id, b.preferred_date), []).append((start, end, b.id))
    for key, spans in by_day.items():
        spans.sort()
        for a, bb in zip(spans, spans[1:]):
            if bb[0] < a[1]:
                clash.append(f'{key[1]} jobs {a[2]} and {bb[2]}')
    check('no cleaner is in two places at once', not clash, '; '.join(clash[:5]))

    # Money: every figure is what the app's own functions say.
    check('every job has a price', all(float(b.price or 0) > 0 for b in jobs))
    import pricing
    check('recurring visits carry their plan discount', all(
        float(b.price) < pricing.calculate_job(b.service_type, b.bedrooms, b.bathrooms,
                                               extras=[e for e in (b.extras or '').split(', ') if e])['client_price']
        for b in jobs if b.frequency in ('weekly', 'biweekly', 'monthly')))
    settled_bad = [b.id for b in jobs if b.paid_at and not is_settled(b)]
    check('every paid job is settled in full', not settled_bad, str(settled_bad[:5]))
    collected_total = round(sum(collected(b) for b in jobs), 2)
    rev = finance.revenue_between(today - timedelta(days=400), today + timedelta(days=1))
    check('revenue on the reports equals the money collected',
          abs(rev - round(sum(collected(b) for b in jobs if b.paid_at), 2)) < 0.01,
          f'reports ${rev:,.2f}')
    owed = finance.unpaid_outstanding()
    by_hand = round(sum(max(0.0, float(b.price) - collected(b)) for b in jobs
                        if b.status in ('confirmed', 'completed')), 2)
    check('what is owed equals price less money collected', abs(owed - by_hand) < 0.01,
          f'${owed:,.2f}')
    overdue = [b for b in jobs if b.invoice_number and invoicing.status(b) == 'overdue']
    check('the overdue invoices are the ones meant to be', len(overdue) == 2,
          f'{len(overdue)} overdue')
    paid_out = ContractorPayment.query.filter_by(status='paid').all()
    check('cleaner pay matches each job', all(
        abs(p.amount - next(x for x in jobs if x.id == p.booking_id).pay_for(
            db.session.get(Staff, p.staff_id))) < 0.01 for p in ContractorPayment.query.all()))
    check('some cleaner pay is paid and some is waiting',
          paid_out and ContractorPayment.query.filter_by(status='pending').count())

    months = [finance.revenue_between(*finance.month_bounds(
        (today.replace(day=1) - timedelta(days=30 * k)).year,
        (today.replace(day=1) - timedelta(days=30 * k)).month)) for k in range(1, 6)]
    check('five months of revenue, none of them empty', all(m > 0 for m in months),
          ', '.join(f'${m:,.0f}' for m in months))
    check('and not all the same', len({round(m, -1) for m in months}) > 2)

    worked_days = {b.preferred_date for b in jobs if b.status != 'cancelled'}
    empty = [(today + timedelta(days=n)).isoformat() for n in range(-21, -1)
             if (today + timedelta(days=n)).weekday() < 5
             and (today + timedelta(days=n)).isoformat() not in worked_days]
    check('no weekday in the last three weeks without work', not empty, ', '.join(empty))
    waiting = [b for b in jobs if b.status == 'pending' and b.preferred_date >= today.isoformat()]
    check('only a couple of jobs waiting on confirmation', 1 <= len(waiting) <= 3,
          str(len(waiting)))

    ratings = [r.rating for r in BookingRating.query.all()]
    avg = db.session.query(func.avg(BookingRating.rating)).scalar()
    check('reviews average what they say',
          ratings and abs(float(avg) - sum(ratings) / len(ratings)) < 0.001,
          f'{float(avg or 0):.2f} from {len(ratings)}')

    # Today's story.
    today_jobs = [b for b in jobs if b.preferred_date == today.isoformat()
                  and b.status != 'cancelled']
    crew_today = {c.staff_id for c in crews if c.booking_id in {b.id for b in today_jobs}}
    check('five jobs today', len(today_jobs) == 5, str(len(today_jobs)))
    check('four cleaners out today', len(crew_today) == 4, str(len(crew_today)))
    check('one job today out for anyone to claim',
          sum(1 for b in today_jobs if b.open_for_claim and b.needs_cleaner) == 1)
    tomorrow = (today + timedelta(days=1)).isoformat()
    check('one job tomorrow with nobody on it',
          sum(1 for b in jobs if b.preferred_date == tomorrow and b.needs_cleaner
              and b.status in ('pending', 'confirmed')) == 1)
    check('one customer yet to confirm', sum(
        1 for b in jobs if b.confirm_sent_at and not b.confirm_response
        and b.status == 'pending') == 1)
    check('two new leads since yesterday', Lead.query.filter(
        Lead.status == 'new', Lead.created_at >= datetime.combine(
            today - timedelta(days=1), time.min)).count() == 2)
    check('the journey customer went from quote to review', Booking.query.join(
        BookingRating, BookingRating.booking_id == Booking.id).filter(
        Booking.source == 'quote', Booking.paid_at.isnot(None)).count() >= 1)
    check('setup shows as complete', onboarding.progress()['percent'] == 100,
          f"{onboarding.progress()['percent']}%")
    check('an owner and an office login', User.query.filter_by(role='owner').count() == 1
          and User.query.count() == 2)
    return out


# ── Building, swapping, resetting ──────────────────────────────────────────

def _say_counts(say):
    for k, v in counts().items():
        say(f'  {k:.<22} {v}')


def _app():
    os.environ.setdefault('SECRET_KEY', 'demo-company')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import create_app
    return create_app()


def _engine():
    import provisioning
    engine = provisioning._engine()
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('The demo company needs PostgreSQL (one schema per company).')
    return engine


def _preflight(engine):
    """(org or None). Refuses if a real company holds the demo's address."""
    import control_plane
    import tenancy
    if not tenancy.valid_slug(DEMO_SLUG):
        raise RuntimeError(f'{DEMO_SLUG!r} is not a usable company address.')
    control_plane.ensure_table(engine)
    org = control_plane.find(engine, DEMO_SLUG)
    if org and not org.get('is_demo'):
        raise RuntimeError(
            f'A company that is not the demo already uses {DEMO_SLUG!r}. '
            f'Refusing to touch it. Set DEMO_SLUG to another address.')
    return org


class _RebuildLock:
    """One rebuild at a time, across every machine sharing the database.

    Two at once would build into the same staging schema, and the second
    one's DROP would pull the first one's work out from under it. The lock is
    held by a connection of its own, so it lasts the whole rebuild and goes
    away by itself if the process dies."""

    def __init__(self, engine):
        self.engine = engine
        self.key = f'akye:demo-company:{DEMO_SLUG}'

    def __enter__(self):
        from sqlalchemy import text
        self.conn = self.engine.connect()
        got = self.conn.execute(text('SELECT pg_try_advisory_lock(hashtext(:k))'),
                                {'k': self.key}).scalar()
        if not got:
            self.conn.close()
            raise RuntimeError('Another rebuild of the demo company is running. '
                               'Let it finish, then try again.')
        return self

    def __exit__(self, *exc):
        from sqlalchemy import text
        try:
            self.conn.execute(text('SELECT pg_advisory_unlock(hashtext(:k))'), {'k': self.key})
        finally:
            self.conn.close()


def credentials(app, schema):
    """Set the owner's and office login's passwords. Returns {email: (pw, from_env)}."""
    import tenancy
    from models import User
    from extensions import db
    out = {}
    with app.app_context(), tenancy.use_tenant(schema):
        for (name, email, role), env in ((OWNER, 'DEMO_OWNER_PASSWORD'),
                                         (OPS, 'DEMO_OPS_PASSWORD')):
            pw = (os.environ.get(env) or '').strip()
            from_env = bool(pw)
            pw = pw or secrets.token_urlsafe(12)
            u = User.query.filter_by(username=email).first()
            u.set_password(pw)
            out[email] = (pw, from_env)
        db.session.commit()
        db.session.remove()
    return out


def build(say=print):
    """Build a fresh BrightNest and swap it in. Returns the counts."""
    import control_plane
    import provisioning
    import tenancy
    import demo_guard
    from sqlalchemy import text
    from extensions import db

    app = _app()
    with app.app_context(), demo_guard.forced(), _RebuildLock(_engine()):
        engine = _engine()
        org = _preflight(engine)
        live = tenancy.schema_for(DEMO_SLUG)
        staging = live + demo_guard.STAGING_SUFFIX

        # Registered and marked first, so no request ever finds this company
        # unmarked -- even while its schema is still being built.
        if not org:
            control_plane.create(engine, DEMO_SLUG, COMPANY['business_name'], OWNER[1])
            control_plane.mark_provisioned(engine, DEMO_SLUG)
        control_plane.set_demo_company(engine, DEMO_SLUG)
        control_plane.set_billing(engine, DEMO_SLUG, plan='scale',
                                  subscription_status='active', grandfathered=False,
                                  activated_at=_utcnow() - timedelta(days=180))
        control_plane.record_tenant_login(engine, OWNER[1], DEMO_SLUG)
        demo_guard.forget_cache()

        say(f'\n  BrightNest demo seed -- {DEMO_SLUG} ({demo_today():%a %d %b %Y})')
        say('  ' + '-' * 40)
        try:
            provisioning.drop_schema(engine, staging)
            provisioning.create_schema(engine, staging)
            provisioning.migrate_schema(engine, staging)
            from blueprints.signup import _seed_strict
            _seed_strict(app, staging)
            with tenancy.use_tenant(staging):
                db.session.remove()
                Builder(say=say).run()
                results = verify()
                failed = [r for r in results if not r[1]]
                if failed:
                    raise SeedError('verification', RuntimeError(
                        '; '.join(f'{n} ({d})' for n, _, d in failed)))
                result_counts = counts()
                db.session.remove()
        except Exception as e:
            db.session.remove()
            try:
                provisioning.drop_schema(engine, staging)
            except Exception:
                pass
            stage = getattr(e, 'stage', 'setup')
            say(f'\n  ❌ Stopped at "{stage}": {e}')
            say('     The live demo was not touched.')
            e.reported = True
            raise

        # The swap: one transaction, so there is never a moment with no demo.
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{live}" CASCADE'))
            conn.execute(text(f'ALTER SCHEMA "{staging}" RENAME TO "{live}"'))
        demo_guard.forget_cache()
        creds = credentials(app, live)

    for k, v in result_counts.items():
        say(f'  {k:.<22} {v}')
    say('\n  Safety')
    say('  live Stripe ........... BLOCKED   (demo_guard: no keys, no checkout)')
    say('  live texts ............ BLOCKED   (demo_guard: send_sms refuses)')
    say('  live email ............ BLOCKED   (demo_guard: send_email refuses)')
    say('  automations ........... NOT RUN   (scheduler skips demo companies)')
    say('  product numbers ....... EXCLUDED  (is_test)')
    say('\n  Verification .......... PASS (every check -- run --verify to list them)')
    say(f'\n  Sign in at https://{DEMO_SLUG}.<your domain>/login')
    for email, (pw, from_env) in creds.items():
        say(f'    {email:28} ' + ('password from the environment' if from_env
                                   else f'password {pw}   (one-off: set it in the environment to keep it)'))
    say('')
    return result_counts


def verify_live(say=print):
    """Print verify() for the live demo. Returns True if every check passed."""
    import tenancy
    from extensions import db
    app = _app()
    with app.app_context():
        engine = _engine()
        org = _preflight(engine)
        if not org:
            say(f'\n  No demo company at {DEMO_SLUG!r} yet. Run this without --verify to build it.\n')
            return False
        with tenancy.use_tenant(tenancy.schema_for(DEMO_SLUG)):
            db.session.remove()
            results = verify()
            say(f'\n  BrightNest -- {len(results)} checks\n')
            for name, ok, detail in results:
                say(f'  {"PASS" if ok else "FAIL"}  {name}' + (f'  ({detail})' if detail else ''))
            say(f'\n  marked demo ............ {"yes" if org.get("is_demo") else "NO"}')
            say(f'  marked test ............ {"yes" if org.get("is_test") else "NO"}')
            _say_counts(say)
            db.session.remove()
    say('')
    return all(ok for _, ok, _ in results) and bool(org.get('is_demo'))


def dry_run(say=print):
    app = _app()
    with app.app_context():
        engine = _engine()
        org = _preflight(engine)
        say(f'\n  Dry run -- nothing will be written.')
        say(f'  company address ........ {DEMO_SLUG}')
        say(f'  already built .......... {"yes, it would be rebuilt" if org else "no, it would be created"}')
        say(f'  "today" would be ....... {demo_today():%A %d %B %Y}')
        say(f'  team / customers ....... {len(TEAM)} / {len(FIRST)}')
        say('  schemas touched ........ only ' + ', '.join(
            (f'{__import__("tenancy").schema_for(DEMO_SLUG)}',
             f'{__import__("tenancy").schema_for(DEMO_SLUG)}__next')))
        say('')


def main(argv=None):
    p = argparse.ArgumentParser(description='The BrightNest demo company.')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--dry-run', action='store_true', help='say what would happen; write nothing')
    g.add_argument('--verify', action='store_true', help='check the live demo; write nothing')
    g.add_argument('--reset', action='store_true', help='rebuild it fresh (the same as no flag)')
    args = p.parse_args(argv)
    if args.dry_run:
        dry_run()
        return 0
    if args.verify:
        return 0 if verify_live() else 1
    try:
        build()
    except Exception as e:
        if not getattr(e, 'reported', False):
            print(f'\n  ❌ Stopped: {e}\n')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
