from extensions import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import json


class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))
    city = db.Column(db.String(50))
    zip_code = db.Column(db.String(10))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Customer portal + card on file (auto-pay for recurring clients)
    portal_token = db.Column(db.String(64), index=True)   # link to their self-serve portal
    stripe_customer_id = db.Column(db.String(100))        # Stripe vault customer
    stripe_payment_method_id = db.Column(db.String(100))  # saved card for off-session charges
    card_brand = db.Column(db.String(20))                 # Visa, Mastercard… (display only)
    card_last4 = db.Column(db.String(4))                  # last 4 digits (display only)
    autopay = db.Column(db.Boolean, default=False)        # charge the saved card morning-of

    bookings = db.relationship('Booking', backref='client', lazy=True)

    @property
    def total_bookings(self):
        return len(self.bookings)

    @property
    def last_service(self):
        completed = [b for b in self.bookings if b.status == 'completed']
        if not completed:
            return None
        return max(completed, key=lambda b: b.created_at)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=True)

    # Service details
    service_type = db.Column(db.String(50), nullable=False)
    bedrooms = db.Column(db.String(10))
    bathrooms = db.Column(db.String(10))
    sqft = db.Column(db.Integer)        # optional home size — drives the sqft surcharge
    extras = db.Column(db.String(200))  # comma-separated: oven, fridge, laundry

    # Frequency
    frequency = db.Column(db.String(20), default='one_time')  # one_time, weekly, biweekly, monthly

    # Scheduling
    preferred_date = db.Column(db.String(50))
    preferred_time = db.Column(db.String(50))

    # Contact info (copied from client or entered directly)
    name = db.Column(db.String(100))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))
    city = db.Column(db.String(50))
    zip_code = db.Column(db.String(10))

    # Payment
    stripe_payment_intent = db.Column(db.String(100))
    stripe_customer_id = db.Column(db.String(100))
    stripe_payment_method_id = db.Column(db.String(100))
    deposit_paid = db.Column(db.Boolean, default=False)
    deposit_token = db.Column(db.String(64))   # unique link for paying deposit after a tentative booking
    tip_amount = db.Column(db.Float, default=0)  # customer's tip — belongs to the cleaner, never revenue
    tip_payment_intent = db.Column(db.String(100))  # the Stripe charge, when tipped after the job
    balance_due = db.Column(db.Float)
    balance_collected = db.Column(db.Boolean, default=False)
    pay_token = db.Column(db.String(64))       # unique link for paying the full amount (invoice / on-site)
    paid_at = db.Column(db.DateTime)           # when paid in full (card or manual)
    paid_method = db.Column(db.String(20))     # card, cash, zelle, venmo, other
    invoice_sent_at = db.Column(db.DateTime)   # morning-of invoice sent (one per day guard)
    invoice_number = db.Column(db.String(20))       # e.g. INV-1042 (real invoice)
    invoice_issued_at = db.Column(db.DateTime)      # when the invoice was issued/sent
    invoice_due_date = db.Column(db.String(10))     # YYYY-MM-DD net terms

    # Lead fee — advertising cost baked into the customer price but EXCLUDED
    # from the contractor's commission (invisible to the customer).
    lead_fee = db.Column(db.Float, default=0)

    # Discount
    discount_code = db.Column(db.String(50))
    discount_amount = db.Column(db.Float, default=0)
    # Payroll
    estimated_hours = db.Column(db.Float)   # total person-hours of WORK in this job
    owner_hours = db.Column(db.Float, default=0)  # hours the owner works herself — unpaid, but shares the tip
    labor_rate_applied = db.Column(db.Float)  # $/hr locked in when quoted, so raising the rate never restates old jobs
    below_floor_reason = db.Column(db.String(200))  # why this was taken under the floor price
    hours_worked = db.Column(db.Float)
    cleaner_paid_at = db.Column(db.DateTime)             # when the cleaner was paid out for THIS job
    cleaner_payment_id = db.Column(db.Integer)           # the ContractorPayment.id that paid it

    # Sales attribution (VA commission)
    source = db.Column(db.String(50), default='website')  # carried from the Lead's source
    agent = db.Column(db.String(100))                     # team member (VA) credited for this lead

    # Recurring plan (proactive scheduling)
    recurring_group = db.Column(db.String(32), index=True)  # links visits in one recurring series
    recurring_active = db.Column(db.Boolean, default=True)  # keep generating future visits
    monthly_mode = db.Column(db.String(10))   # 'date' (the 9th) or 'weekday' (2nd Wednesday)
    # Asking a customer to confirm a proposed date and price
    confirm_token = db.Column(db.String(64), index=True)
    confirm_sent_at = db.Column(db.DateTime)
    confirm_note = db.Column(db.Text)               # the owner's own words, added to the ask
    confirm_response = db.Column(db.String(10))     # 'yes', 'no', or 'other' (wants a different time)
    confirm_alt = db.Column(db.Text)                # the day/time they'd prefer instead
    # Who was actually on site. A plain record for invoices and disputes — it is
    # deliberately NOT the crew, because the crew drives pay and rewriting that
    # after the fact would change what a past job paid out.
    onsite_people = db.Column(db.Text)
    # Proof the customer agreed to the terms, captured at the moment they paid.
    # The wording is snapshotted, not referenced — terms get edited, and a record
    # pointing at whatever they say today proves nothing about what was agreed.
    terms_accepted_at = db.Column(db.DateTime)
    terms_accepted_text = db.Column(db.Text)
    terms_accepted_ip = db.Column(db.String(64))
    confirm_responded_at = db.Column(db.DateTime)

    # Admin fields
    notes = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    access_notes = db.Column(db.Text)   # entry info for the cleaner: gate code, key, parking, alarm, pets
    assigned_cleaner = db.Column(db.String(100))        # solo job: the cleaner. Crew job: the lead.
    crew_size = db.Column(db.Integer, default=1)        # 2+ = big house needing a crew (see BookingCrew)
    cleaner_notified_at = db.Column(db.DateTime)        # when job notification was last sent
    cleaner_response = db.Column(db.String(20))         # accepted, declined, None
    open_for_claim = db.Column(db.Boolean, default=False)  # broadcast to team, first to claim wins
    claim_token = db.Column(db.String(64))              # link token for the claim page
    broadcast_at = db.Column(db.DateTime)               # when it was last offered to the team
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, in_progress, completed, cancelled
    price = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)               # when marked completed (drives lifecycle emails)
    # Lifecycle email tracking (one send each, never repeats)
    morning_note_at = db.Column(db.DateTime)            # morning-of note
    review_nudge_at = db.Column(db.DateTime)            # review reminder
    skip_review = db.Column(db.Boolean, default=False)  # owner opted this customer out of review/rating requests
    upsell_sent_at = db.Column(db.DateTime)             # one-time → recurring upsell
    upsell_nudge_at = db.Column(db.DateTime)            # upsell 2nd nudge
    winback_sent_at = db.Column(db.DateTime)            # "we miss you" win-back

    SERVICE_LABELS = {
        'standard': 'Standard House Cleaning',
        'deep': 'Deep Cleaning',
        'moveout': 'Move-Out / Move-In Cleaning',
        'airbnb': 'Airbnb / Vacation Rental',
        'apartment': 'Apartment & Condo Cleaning',
        'luxury': 'Luxury Home Cleaning',
    }

    STATUS_COLORS = {
        'pending': '#f59e0b',
        'confirmed': '#3b82f6',
        'completed': '#10b981',
        'cancelled': '#ef4444',
    }

    @property
    def commissionable_price(self):
        """LEGACY. Base for the old percentage model — total minus the lead fee.
        Only still used by jobs that have no estimated_hours (see labor_budget)."""
        return round((self.price or 0) - (self.lead_fee or 0), 2)

    # ── Labor budget: what the WORK is worth, not what the customer paid ─────
    @property
    def rate_applied(self):
        """The $/hour this job was quoted at. Locked at quote time, so changing
        the company rate tomorrow can never restate what a job from last month
        was worth."""
        if self.labor_rate_applied:
            return self.labor_rate_applied
        from pricing import get_labor_rate
        return get_labor_rate()

    @property
    def payable_hours(self):
        """Hours somebody gets PAID for — the job's work minus whatever the owner
        does herself. She doesn't pay herself, so her hours leave the pot."""
        if not self.estimated_hours:
            return None
        return max(0.0, round(self.estimated_hours - (self.owner_hours or 0), 2))

    @property
    def labor_budget(self):
        """The pot of money the cleaners on this job share.

        payable person-hours × the hourly rate this job was quoted at.
        Deliberately has nothing to do with the price — discount a job and this
        doesn't move, so a discount comes out of the owner's margin instead of
        the cleaner's pay.

        Returns None when the job has no estimated hours, which is how every
        booking made before this existed behaves. Callers fall back to the old
        percentage in that case, so nothing already on the books changes."""
        if not self.estimated_hours:
            return None
        return round((self.payable_hours or 0) * self.rate_applied, 2)

    @property
    def rate_is_stale(self):
        """True when the company rate has moved since this job was quoted and
        the job hasn't been paid — the only case where re-rating is safe."""
        from pricing import get_labor_rate
        if not self.labor_rate_applied or self.cleaner_paid_at:
            return False
        if any(c.paid_at for c in self.crew):
            return False
        return abs(self.labor_rate_applied - get_labor_rate()) > 0.001

    @property
    def committed_labor(self):
        """What this job will actually cost in cleaner pay.

        Once people are assigned with amounts against their names, that IS the
        cost — not the theoretical value of the hours. Measuring the budget
        instead flagged jobs as underwater when the owner was working them
        herself and paying out a fraction of it."""
        if self.crew:
            return self.crew_allocated
        return self.labor_budget

    @property
    def labor_percent(self):
        """Labor as a share of what the customer pays — the margin warning light."""
        labor = self.committed_labor
        if labor is None or not self.price:
            return None
        return round(labor / self.price * 100, 1)

    @property
    def floor_price(self):
        """The least this job can be sold for and still be worth doing.

        Worked back from what it actually costs to get cleaned: if labor must
        stay under, say, 60% of the price, the price can't drop below that cost
        ÷ 0.60. The lead fee rides on top, because that money is recovering ad
        spend rather than paying for cleaning."""
        labor = self.committed_labor
        if labor is None:
            return None
        from pricing import get_max_labor_percent
        cap = (get_max_labor_percent() or 60) / 100.0
        return round(labor / cap + (self.lead_fee or 0), 2)

    @property
    def below_floor_by(self):
        """Dollars this job is under its floor, or None when it's fine."""
        floor = self.floor_price
        if floor is None or not self.price or self.price >= floor:
            return None
        return round(floor - self.price, 2)

    @property
    def service_label(self):
        return self.SERVICE_LABELS.get(self.service_type, self.service_type.title())

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, '#9ca3af')

    # ── Crew jobs (2+ cleaners on one house) ────────────────────────────────
    @property
    def is_crew_job(self):
        return (self.crew_size or 1) > 1

    @property
    def spots_filled(self):
        return len(self.crew)

    @property
    def spots_left(self):
        return max(0, (self.crew_size or 1) - len(self.crew))

    @property
    def crew_names(self):
        return [c.staff.name for c in self.crew if c.staff]

    @property
    def crew_label(self):
        """'Maria + Ana' for a crew job, the single name for a solo job."""
        names = self.crew_names
        return ' + '.join(names) if names else (self.assigned_cleaner or '')

    @property
    def crew_allocated(self):
        """Total already handed out to the crew — compare against the pot."""
        return round(sum(c.pay_amount or 0 for c in self.crew), 2)

    def default_crew_pay(self, staff, size=None):
        """Suggested pay for one cleaner on this job — an even slice of the
        labor budget. One cleaner takes the whole pot; two split it in half and
        each finish in half the time, so the hourly rate is the same either way.

        Still only a suggestion: the owner can type over any figure.

        Jobs with no estimated hours fall back to the old percentage split, so
        anything booked before this existed keeps paying what it always did."""
        size = max(1, size or self.crew_size or 1)
        budget = self.labor_budget
        if budget is None:
            share = self.commissionable_price / size
            return staff.calc_pay(job_price=share, hours_worked=self.hours_worked or 0)
        return round(budget / size, 2)

    def hours_each(self, size=None):
        """Paid hours each cleaner works, for showing alongside their pay."""
        if not self.estimated_hours:
            return None
        return round((self.payable_hours or 0) / max(1, size or self.crew_size or 1), 2)

    @property
    def tip_fee(self):
        """What the card processor took out of the tip. Shown so she can see the
        real figure that landed — the CRM doesn't act on it."""
        gross = round(self.tip_amount or 0, 2)
        if gross <= 0:
            return 0.0
        from pricing import get_tip_fee_percent
        return round(gross * (get_tip_fee_percent() or 0) / 100.0, 2)

    @property
    def tip_net(self):
        """What actually reached the bank out of the customer's tip.

        Deliberately NOT split or allocated to anybody. Monica divides tips
        herself — between her, the cleaner, and sometimes her daughter, who
        isn't in the CRM at all — so no rule here could get it right. She types
        each person's share when she pays them."""
        return round(max(0.0, (self.tip_amount or 0) - self.tip_fee), 2)

    def pay_for(self, staff):
        """What this one cleaner earns on this job — the single answer every
        screen should use, so the offer, My Day, payroll and the payout can
        never disagree with each other.

        Order: a pay amount already agreed on their crew row wins; otherwise a
        solo cleaner takes the whole labor budget; otherwise the old percentage."""
        if self.crew:
            row = self.crew_row_for(staff)
            return round(row.pay_amount or 0, 2) if row else 0.0
        budget = self.labor_budget
        if budget is not None:
            return budget
        return staff.calc_pay(job_price=self.commissionable_price,
                              hours_worked=self.hours_worked or 0)

    def crew_row_for(self, staff):
        sid = getattr(staff, 'id', staff)
        return next((c for c in self.crew if c.staff_id == sid), None)


class BookingCrew(db.Model):
    """One cleaner's spot on a multi-cleaner job — a 2-cleaner job has 2 rows.

    Pay is set per person by the owner, so the crew can split the job's
    commissionable amount any way she likes. On a crew job THIS is the source of
    truth for payroll and payouts; solo jobs have no rows here and still run off
    Booking.assigned_cleaner."""
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    pay_amount = db.Column(db.Float)        # what THIS cleaner earns for the job
    claimed_at = db.Column(db.DateTime)     # set if they grabbed the spot off the board
    paid_at = db.Column(db.DateTime)        # when this person's share was paid out
    payment_id = db.Column(db.Integer)      # the ContractorPayment.id that paid it
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # One spot per person per job — stops a double-claim outright.
    __table_args__ = (db.UniqueConstraint('booking_id', 'staff_id', name='uq_crew_booking_staff'),)

    booking = db.relationship('Booking', backref=db.backref(
        'crew', lazy=True, cascade='all, delete-orphan', order_by='BookingCrew.id'))
    staff = db.relationship('Staff')


class PricingSetting(db.Model):
    """Stores pricing overrides set via the CRM admin UI."""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        row = PricingSetting.query.filter_by(key=key).first()
        if row:
            try:
                return float(row.value)
            except ValueError:
                return row.value
        return default

    @staticmethod
    def set(key, value):
        row = PricingSetting.query.filter_by(key=key).first()
        if row:
            row.value = str(value)
        else:
            row = PricingSetting(key=key, value=str(value))
            db.session.add(row)


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    service_type = db.Column(db.String(50))
    bedrooms = db.Column(db.String(10))
    bathrooms = db.Column(db.String(10))
    extras = db.Column(db.String(200))
    frequency = db.Column(db.String(20), default='one_time')
    address = db.Column(db.String(200))
    city = db.Column(db.String(50))
    zip_code = db.Column(db.String(10))
    quoted_price = db.Column(db.Float)
    status = db.Column(db.String(20), default='new')  # new, contacted, converted, lost
    source = db.Column(db.String(50), default='website')
    agent = db.Column(db.String(100))                 # team member (VA) credited for commission
    notes = db.Column(db.Text)
    drip_step = db.Column(db.Integer, default=1)
    last_drip_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    SERVICE_LABELS = {
        'standard': 'Standard House Cleaning', 'deep': 'Deep Cleaning',
        'moveout': 'Move-Out / Move-In Cleaning', 'airbnb': 'Airbnb / Vacation Rental',
        'apartment': 'Apartment & Condo Cleaning', 'luxury': 'Luxury Home Cleaning',
        'commercial': 'Commercial / Janitorial',
        'apartment_turnover': 'Apartment Turnover / Make-Ready',
    }

    # Leads priced at a walkthrough, not from the residential matrix
    COMMERCIAL_TYPES = ('commercial', 'apartment_turnover')

    @property
    def is_commercial(self):
        return (self.service_type or '') in self.COMMERCIAL_TYPES

    @property
    def service_label(self):
        return self.SERVICE_LABELS.get(self.service_type or '', self.service_type or '—')


class ChecklistTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    service_type = db.Column(db.String(50))
    items = db.Column(db.Text, default='[]')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_items(self):
        try:
            return json.loads(self.items or '[]')
        except Exception:
            return []


class JobChecklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    template_name = db.Column(db.String(100))
    items = db.Column(db.Text, default='[]')
    completed_items = db.Column(db.Text, default='[]')
    token = db.Column(db.String(64), unique=True, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    before_photos = db.Column(db.Text, default='[]')   # JSON list of Cloudinary URLs
    after_photos = db.Column(db.Text, default='[]')    # JSON list of Cloudinary URLs
    photos_submitted_at = db.Column(db.DateTime)       # when cleaner closed out the job
    # Guided job workflow — one timestamp per step (drives the stepper + resume)
    on_the_way_at = db.Column(db.DateTime)             # cleaner tapped "On My Way"
    clock_in_at = db.Column(db.DateTime)               # cleaner arrived & started
    clock_out_at = db.Column(db.DateTime)              # cleaner finished (auto-fills hours)
    client_signature = db.Column(db.Text)              # signature image data URL (client sign-off)
    client_signed_at = db.Column(db.DateTime)
    client_rating = db.Column(db.Integer)              # 1-5 stars collected on-site
    client_review = db.Column(db.Text)                 # optional review comment
    booking = db.relationship('Booking', backref='job_checklists')

    @property
    def hours_on_site(self):
        """Elapsed time between clock-in and clock-out, rounded to 2 decimals."""
        if self.clock_in_at and self.clock_out_at:
            return round((self.clock_out_at - self.clock_in_at).total_seconds() / 3600, 2)
        return None

    def get_items(self):
        try:
            return json.loads(self.items or '[]')
        except Exception:
            return []

    def get_completed(self):
        try:
            return set(json.loads(self.completed_items or '[]'))
        except Exception:
            return set()

    def get_before_photos(self):
        try:
            return json.loads(self.before_photos or '[]')
        except Exception:
            return []

    def get_after_photos(self):
        try:
            return json.loads(self.after_photos or '[]')
        except Exception:
            return []

    @property
    def completion_percent(self):
        items = self.get_items()
        if not items:
            return 0
        return int(len(self.get_completed()) / len(items) * 100)


class ContentPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_type = db.Column(db.String(50))
    platform = db.Column(db.String(50))
    caption = db.Column(db.Text)
    context = db.Column(db.Text)
    scheduled_date = db.Column(db.String(20))
    status = db.Column(db.String(20), default='draft')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BookingRating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    rating = db.Column(db.Integer)  # 1-5, None until submitted
    comment = db.Column(db.Text)
    rated_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    booking = db.relationship('Booking', backref='rating_requests')


class DiscountCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(20), default='percent')  # percent, fixed
    discount_value = db.Column(db.Float, nullable=False)
    max_uses = db.Column(db.Integer)  # None = unlimited
    times_used = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def check_valid(self):
        if not self.is_active:
            return False, 'This code is inactive.'
        if self.max_uses and self.times_used >= self.max_uses:
            return False, 'This code has reached its usage limit.'
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False, 'This code has expired.'
        return True, 'Valid'

    def apply(self, price):
        if self.discount_type == 'percent':
            return round(price * (1 - self.discount_value / 100), 2)
        return max(0, round(price - self.discount_value, 2))

    def discount_label(self):
        if self.discount_type == 'percent':
            return f'{self.discount_value:.0f}% off'
        return f'${self.discount_value:.2f} off'


class ContractorApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    years_experience = db.Column(db.String(20))
    services = db.Column(db.Text)           # comma-separated
    availability = db.Column(db.Text)       # comma-separated days
    has_transportation = db.Column(db.Boolean, default=True)
    has_supplies = db.Column(db.Boolean, default=False)
    has_references = db.Column(db.Boolean, default=False)
    background_check_consent = db.Column(db.Boolean, default=False)
    agrees_to_ic_terms = db.Column(db.Boolean, default=False)
    why_interested = db.Column(db.Text)
    source = db.Column(db.String(50), default='Website')  # Indeed, Facebook, Website, etc.
    language = db.Column(db.String(5), default='en')      # preferred language: 'en' or 'es'
    status = db.Column(db.String(20), default='new')  # new, reviewing, phone_screen, bg_check, hired, rejected
    admin_notes = db.Column(db.Text)
    # Hiring pipeline tracking
    phone_interview_completed = db.Column(db.Boolean, default=False)
    phone_interview_at = db.Column(db.DateTime)
    phone_interview_notes = db.Column(db.Text)
    background_check_status = db.Column(db.String(20), default='not_started')  # not_started, requested, received, cleared, failed
    background_check_notes = db.Column(db.Text)
    background_check_at = db.Column(db.DateTime)
    bgcheck_existing_link = db.Column(db.String(500))   # link applicant provides on application
    bgcheck_request_sent_at = db.Column(db.DateTime)
    bgcheck_results_received = db.Column(db.Boolean, default=False)
    bgcheck_upload_token = db.Column(db.String(64))      # unique link candidate uses to submit results
    bgcheck_uploaded_url = db.Column(db.String(500))     # Cloudinary URL of uploaded PDF/image
    bgcheck_uploaded_link = db.Column(db.String(500))    # OR a verification link they pasted
    bgcheck_uploaded_at = db.Column(db.DateTime)
    # Reference tracking
    ref1_name = db.Column(db.String(100))
    ref1_phone = db.Column(db.String(20))
    ref1_notes = db.Column(db.Text)
    ref1_called = db.Column(db.Boolean, default=False)
    ref2_name = db.Column(db.String(100))
    ref2_phone = db.Column(db.String(20))
    ref2_notes = db.Column(db.Text)
    ref2_called = db.Column(db.Boolean, default=False)
    # Email action tracking
    interview_invite_sent_at = db.Column(db.DateTime)
    rejection_sent_at = db.Column(db.DateTime)
    # Video interview
    interview_token = db.Column(db.String(64), unique=True)
    interview_status = db.Column(db.String(20), default='not_sent')  # not_sent, sent, in_progress, completed
    interview_sent_at = db.Column(db.DateTime)
    interview_completed_at = db.Column(db.DateTime)
    interview_nudge_count = db.Column(db.Integer, default=0)   # auto follow-up nudges sent (0, 1, 2)
    interview_last_sent_at = db.Column(db.DateTime)            # last time the link went out (original or nudge)
    # Conditional offer email tracking
    offer_sent_at = db.Column(db.DateTime)                     # last time the conditional offer email went out
    offer_sent_count = db.Column(db.Integer, default=0)        # how many times it's been sent
    offer_token = db.Column(db.String(64), unique=True)        # link the candidate clicks to accept
    offer_accepted_at = db.Column(db.DateTime)                 # when they accepted the offer
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    responses = db.relationship('InterviewResponse', backref='application', lazy=True,
                                order_by='InterviewResponse.question_index')


class InterviewResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('contractor_application.id'), nullable=False)
    question_index = db.Column(db.Integer, nullable=False)  # 0–4
    question_en = db.Column(db.Text)
    cloudinary_public_id = db.Column(db.String(200))
    cloudinary_url = db.Column(db.String(500))
    transcript = db.Column(db.Text)       # auto-captured via Web Speech API
    transcript_lang = db.Column(db.String(10))  # 'en' or 'es'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CommercialQuote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(150), nullable=False)
    contact_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    property_type = db.Column(db.String(100))
    property_address = db.Column(db.String(200))
    units = db.Column(db.String(20))
    sqft = db.Column(db.String(20))
    services = db.Column(db.Text)
    frequency = db.Column(db.String(50))
    contract_term = db.Column(db.String(50))
    price_per_visit = db.Column(db.Float)
    monthly_price = db.Column(db.Float)
    scope_notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='draft')  # draft, sent, accepted, declined
    token = db.Column(db.String(64), unique=True, nullable=False)
    brand = db.Column(db.String(10), default='lm')      # 'lm' (L & M) or 'dazzle'
    drip_step = db.Column(db.Integer, default=0)        # nurture follow-ups already sent
    last_drip_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime)
    viewed_at = db.Column(db.DateTime)      # first time the contact opened the proposal
    responded_at = db.Column(db.DateTime)


class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    color = db.Column(db.String(7), default='#7c3aed')
    is_active = db.Column(db.Boolean, default=True)
    application_id = db.Column(db.Integer, db.ForeignKey('contractor_application.id'))  # back-link to the application they came from
    # Pay settings
    pay_type = db.Column(db.String(20), default='percent')  # percent, hourly
    pay_rate = db.Column(db.Float, default=50.0)            # % of job or $/hr
    experience_level = db.Column(db.String(20), default='new')  # new, experienced, senior
    # Profile
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(20))
    has_transportation = db.Column(db.Boolean, default=True)
    has_supplies = db.Column(db.Boolean, default=False)
    worker_model = db.Column(db.String(20), default='contractor')  # contractor, employee
    onboarding_steps = db.Column(db.Text, default='[]')  # JSON list of completed step keys
    agreement_token = db.Column(db.String(64), unique=True)
    agreement_signature = db.Column(db.String(100))
    agreement_signed_at = db.Column(db.DateTime)
    shirt_size = db.Column(db.String(10))
    payment_pref = db.Column(db.String(50))   # Zelle, Direct Deposit, Check
    payment_notes = db.Column(db.String(200)) # Zelle email/phone or notes
    welcome_forms_at = db.Column(db.DateTime)
    orientation_token = db.Column(db.String(64), unique=True)
    orientation_completed_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    # Stripe Connect (payouts)
    stripe_account_id = db.Column(db.String(64))               # acct_... connected account
    stripe_payouts_enabled = db.Column(db.Boolean, default=False)  # Stripe verified & ready to receive money
    stripe_details_submitted = db.Column(db.Boolean, default=False)  # finished the onboarding form
    stripe_disabled_reason = db.Column(db.String(120))        # set if Stripe blocks the account (e.g. can't verify)
    pay_schedule = db.Column(db.String(10), default='daily')  # daily (per job) or weekly
    insurance_reminder_sent_at = db.Column(db.DateTime)       # friendly "get insurance" nudge after a few jobs
    roster_start_date = db.Column(db.String(20))              # date they're ready to start receiving jobs (YYYY-MM-DD)
    language = db.Column(db.String(5), default='en')          # preferred language: 'en' or 'es' (drives message translation)
    onboarding_reminder_at = db.Column(db.DateTime)           # last "finish your onboarding" nudge
    onboarding_reminder_count = db.Column(db.Integer, default=0)
    schedule_reminder_date = db.Column(db.String(20))         # last date we sent a day-before schedule reminder
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def can_verify_on_stripe(self):
        """False only when Stripe has clearly rejected/blocked the account —
        that's when the manual Venmo/Zelle fallback should appear."""
        bad = ('rejected', 'disabled', 'failed', 'unverified')
        r = (self.stripe_disabled_reason or '').lower()
        return not any(b in r for b in bad)

    ONBOARDING_STEPS = [
        ('phone_interview',   'Phone interview completed'),
        ('background_check',  'Background check cleared'),
        ('welcome_email',     'Welcome email sent'),
        ('ic_agreement',      'Work agreement signed'),
        ('welcome_forms',     'Onboarding forms completed'),
        ('payment_info',      'Payment / direct deposit info collected'),
        ('uniform_size',      'Shirt size & uniform issued'),
        ('orientation',       'Orientation / training completed'),
        ('supply_kit',        'Supply kit issued'),
        ('shadow_job',        'Shadow / trial shift (optional)'),
        ('first_solo_job',    'First solo job assigned'),
    ]
    # Steps that only apply to employees (not independent contractors)
    EMPLOYEE_ONLY_STEPS = {'uniform_size', 'supply_kit'}

    def get_onboarding(self):
        try:
            return json.loads(self.onboarding_steps or '[]')
        except Exception:
            return []

    def get_applicable_steps(self):
        """Return steps relevant to this worker's model (contractor vs employee)."""
        model = self.worker_model or 'contractor'
        if model == 'employee':
            return self.ONBOARDING_STEPS
        return [(k, v) for k, v in self.ONBOARDING_STEPS if k not in self.EMPLOYEE_ONLY_STEPS]

    def pay_label(self):
        if self.pay_type == 'hourly':
            return f'${self.pay_rate:.2f}/hr'
        return f'{self.pay_rate:.0f}% of job'

    def calc_pay(self, job_price=0, hours_worked=0):
        if self.pay_type == 'hourly':
            return round((hours_worked or 0) * (self.pay_rate or 0), 2)
        return round((job_price or 0) * ((self.pay_rate or 0) / 100), 2)


class Availability(db.Model):
    """One cleaner's answer for one day: can they work it or not.

    Collected by texting each of them a personal link once a week, so the
    answers arrive as data the schedule can be built from rather than as a pile
    of replies to read and remember."""
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False, index=True)
    day = db.Column(db.String(10), nullable=False, index=True)   # YYYY-MM-DD
    available = db.Column(db.Boolean, default=False)
    note = db.Column(db.String(200))          # "after 2pm", "half day" …
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('staff_id', 'day', name='uq_availability_staff_day'),)

    staff = db.relationship('Staff', backref=db.backref('availability', lazy=True))


class ContractorPayment(db.Model):
    """A record of paying a contractor — via Stripe (automatic) or manually (Venmo/Zelle/etc.)."""
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'))  # the job this pays for (per-job payout)
    amount = db.Column(db.Float, nullable=False)          # labor only — what the P&L counts as a cost
    tip_amount = db.Column(db.Float, default=0)           # customer's tip passed through, NOT a business cost
    method = db.Column(db.String(20), default='stripe')   # stripe, venmo, zelle, cash, check
    status = db.Column(db.String(20), default='paid')     # paid, pending, failed
    stripe_transfer_id = db.Column(db.String(64))         # tr_... when paid via Stripe
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    staff = db.relationship('Staff', backref=db.backref('payments', lazy=True,
                            order_by='ContractorPayment.created_at.desc()'))


# ── Bookkeeping: what goes out, so profit is a real number ──────────────────
# Categories are grouped for the P&L and tagged with the Schedule C line they
# belong on, so the year-end export drops straight onto the tax form.
EXPENSE_CATEGORIES = [
    # (key,          label,                                  group,         schedule C)
    ('ads_google',   'Advertising — Google leads',            'Advertising', 'Line 8 — Advertising'),
    ('ads_promo',    'Advertising — Promotional items',       'Advertising', 'Line 8 — Advertising'),
    ('ads_other',    'Advertising — Thumbtack, Yelp, other',  'Advertising', 'Line 8 — Advertising'),
    ('supplies',     'Cleaning supplies',                     'Operations',  'Line 22 — Supplies'),
    ('equipment',    'Equipment (vacuums, machines)',         'Operations',  'Line 13 — Depreciation / Sec 179'),
    ('mileage',      'Vehicle mileage',                       'Vehicle',     'Line 9 — Car & truck'),
    ('vehicle',      'Vehicle — gas, repairs, parking',       'Vehicle',     'Line 9 — Car & truck'),
    ('insurance',    'Insurance',                             'Overhead',    'Line 15 — Insurance'),
    ('software',     'Software & subscriptions',              'Overhead',    'Line 18 — Office expense'),
    ('phone',        'Phone & internet',                      'Overhead',    'Line 25 — Utilities'),
    ('office',       'Office supplies',                       'Overhead',    'Line 18 — Office expense'),
    ('licenses',     'Licenses & permits',                    'Overhead',    'Line 23 — Taxes & licenses'),
    ('uniforms',     'Uniforms',                              'Operations',  'Line 27a — Other'),
    ('training',     'Training & education',                  'Overhead',    'Line 27a — Other'),
    ('meals',        'Meals (50% deductible)',                'Overhead',    'Line 24b — Meals'),
    ('bank',         'Bank fees',                             'Overhead',    'Line 27a — Other'),
    ('other',        'Other',                                 'Overhead',    'Line 27a — Other'),
]

# These are never typed by hand — they're totalled from records the CRM already
# keeps (payroll, Stripe, VA commissions). Letting them be entered manually is
# how a books gets silently double-counted.
AUTO_CATEGORIES = {
    'contractor_pay':  'Cleaner pay',
    'processing_fees': 'Card processing fees',
    'va_commission':   'VA commissions',
}

CATEGORY_LABELS = {k: label for k, label, _g, _s in EXPENSE_CATEGORIES}
CATEGORY_LABELS.update(AUTO_CATEGORIES)
CATEGORY_GROUP = {k: g for k, _l, g, _s in EXPENSE_CATEGORIES}
CATEGORY_SCHEDULE_C = {k: s for k, _l, _g, s in EXPENSE_CATEGORIES}
ADVERTISING_CATEGORIES = {k for k, _l, g, _s in EXPENSE_CATEGORIES if g == 'Advertising'}

IRS_MILEAGE_RATE = 0.70   # cents-per-mile deduction; editable per entry


class Expense(db.Model):
    """One cost out of the business — the ledger the P&L is built from.

    Only money the owner spends directly. Cleaner pay, card fees, and VA
    commissions are deliberately NOT stored here; they're totalled from their
    own records so a payout can never be counted twice."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), index=True)     # YYYY-MM-DD — when the money went out
    category = db.Column(db.String(40), index=True)
    amount = db.Column(db.Float, nullable=False)
    vendor = db.Column(db.String(120))
    note = db.Column(db.String(300))
    method = db.Column(db.String(20))               # card, cash, zelle, check, bank
    receipt_url = db.Column(db.String(400))         # photo of the receipt (Cloudinary)
    # Mileage entries log the trip; the amount is miles × rate.
    miles = db.Column(db.Float)
    rate_per_mile = db.Column(db.Float)
    recurring_id = db.Column(db.Integer, db.ForeignKey('recurring_expense.id'))
    # Ad spend can point at the job it bought, so the lead fee on a booking and
    # the money actually paid for that lead are entered once, not twice.
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def category_label(self):
        return CATEGORY_LABELS.get(self.category, (self.category or 'Other').title())

    @property
    def group(self):
        return CATEGORY_GROUP.get(self.category, 'Overhead')

    @property
    def schedule_c(self):
        return CATEGORY_SCHEDULE_C.get(self.category, 'Line 27a — Other')

    @property
    def is_mileage(self):
        return self.category == 'mileage' and (self.miles or 0) > 0


class RecurringExpense(db.Model):
    """A cost that repeats every month — insurance, software, phone. Posts itself
    so the deduction never gets forgotten."""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    vendor = db.Column(db.String(120))
    note = db.Column(db.String(300))
    method = db.Column(db.String(20))
    day_of_month = db.Column(db.Integer, default=1)     # clamped to short months
    active = db.Column(db.Boolean, default=True)
    last_posted = db.Column(db.String(7))               # 'YYYY-MM' guard — one post per month
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    expenses = db.relationship('Expense', backref='recurring', lazy=True)

    @property
    def category_label(self):
        return CATEGORY_LABELS.get(self.category, (self.category or 'Other').title())


class CommissionPayment(db.Model):
    """Records that a VA was actually PAID their commission for a month. The
    commission calculator says what's owed; this says what left the account."""
    id = db.Column(db.Integer, primary_key=True)
    agent = db.Column(db.String(100), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(20), default='zelle')
    note = db.Column(db.String(200))
    paid_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (db.UniqueConstraint('agent', 'year', 'month', name='uq_commission_agent_month'),)


class ProcessingFee(db.Model):
    """What Stripe actually kept in a given month, pulled from their balance
    transactions. One authoritative number per month beats guessing 2.9% + 30¢,
    and it picks up refund and payout fees too."""
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, default=0)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('year', 'month', name='uq_processing_fee_month'),)


class EmailTemplate(db.Model):
    """Editable email templates — each trigger key maps to one automated email."""
    id = db.Column(db.Integer, primary_key=True)
    trigger = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)         # human label
    description = db.Column(db.String(200))                  # when does this fire?
    category = db.Column(db.String(40), default='client')    # client, lead, cleaner, owner
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)                 # plain text with {{variables}}
    is_active = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    CATEGORIES = [
        ('client',  'Client Emails'),
        ('lead',    'Lead Emails'),
        ('cleaner', 'Cleaner Emails'),
        ('owner',   'Owner Alerts'),
    ]

    VARIABLES = {
        'client':  ['{{first_name}}', '{{full_name}}', '{{business_name}}', '{{booking_date}}',
                    '{{booking_time}}', '{{service_type}}', '{{address}}', '{{price}}',
                    '{{deposit}}', '{{balance}}', '{{cleaner_name}}', '{{phone}}'],
        'lead':    ['{{first_name}}', '{{full_name}}', '{{business_name}}', '{{service_type}}',
                    '{{quote_amount}}', '{{phone}}', '{{booking_link}}', '{{discount_code}}'],
        'cleaner': ['{{first_name}}', '{{full_name}}', '{{business_name}}', '{{job_date}}',
                    '{{job_address}}', '{{service_type}}', '{{earnings}}', '{{sign_link}}'],
        'owner':   ['{{applicant_name}}', '{{client_name}}', '{{business_name}}',
                    '{{amount}}', '{{error}}'],
    }


class SOP(db.Model):
    """Standard Operating Procedures — step-by-step how-to guides for cleaners and staff."""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    CATEGORIES = [
        ('cleaning',    'Cleaning Procedures'),
        ('commercial',  'Commercial Services'),
        ('leads',       'Lead & Phone Handling'),
        ('quality',     'Quality Control'),
        ('operations',  'Operations & Admin'),
    ]


class Script(db.Model):
    """VA scripts library — organized by call/situation type."""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)   # inbound, outbound, followup, objection, closing, general
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    CATEGORIES = [
        ('inbound',   'Inbound Calls'),
        ('outbound',  'Outbound Calls'),
        ('call_property_manager', 'Call: Property Managers'),
        ('call_medical',          'Call: Medical & Dental'),
        ('call_construction',     'Call: General Contractors'),
        ('call_office',           'Call: Offices & Retail'),
        ('email_outreach', 'Email: Property Managers & Realtors'),
        ('voicemail', 'Voicemail'),
        ('followup',  'Follow-Up'),
        ('objection', 'Objection Handling'),
        ('closing',   'Closing Scripts'),
        ('general',   'General Outreach'),
    ]

    # Which opening script the Find Leads call drawer shows for a given
    # prospect. Anything unmapped falls back to the generic office opener.
    PROSPECT_CATEGORY_MAP = {
        'property_manager':   'call_property_manager',
        'apartment':          'call_property_manager',
        'realtor':            'call_property_manager',
        'airbnb':             'call_property_manager',
        'medical_office':     'call_medical',
        'general_contractor': 'call_construction',
        'office':             'call_office',
        'daycare':            'call_office',
        'other':              'call_office',
    }

    # Shown in the drawer under the opener regardless of who is being called.
    ALWAYS_SHOW = ['outbound', 'closing', 'objection', 'voicemail', 'followup']

    @staticmethod
    def script_category_for(prospect_category):
        return Script.PROSPECT_CATEGORY_MAP.get(prospect_category, 'call_office')


class BusinessSetting(db.Model):
    """General business config — name, phone, address, etc."""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=''):
        row = BusinessSetting.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = BusinessSetting.query.filter_by(key=key).first()
        if row:
            row.value = str(value)
        else:
            row = BusinessSetting(key=key, value=str(value))
            db.session.add(row)


class EmailOptOut(db.Model):
    """Emails that have unsubscribed from marketing messages (global, by email)."""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MessageTemplate(db.Model):
    """Reusable text-message templates with {placeholders} for the inbox."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Message(db.Model):
    """One text message in a two-way conversation with a cleaner or applicant.
    Threads are grouped by `phone` (last-10 digits). direction 'in' = they
    texted us, 'out' = we texted them."""
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), index=True)         # last-10 digits — the thread key
    direction = db.Column(db.String(3))                  # 'in' or 'out'
    body = db.Column(db.Text)                            # original language as typed/received
    body_translated = db.Column(db.Text)                 # translation shown/sent (if thread is bilingual)
    contact_name = db.Column(db.String(120))             # cached display name
    staff_id = db.Column(db.Integer)                     # optional link to Staff
    application_id = db.Column(db.Integer)               # optional link to ContractorApplication
    twilio_sid = db.Column(db.String(64))
    read_at = db.Column(db.DateTime)                     # inbound: when the owner viewed it
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class OutboundLog(db.Model):
    """A record of every outbound SMS/email the system sends, from anywhere in
    the app — pay updates, work orders, confirmations, reminders, payment links,
    custom customer emails, etc. Gives the owner a single 'Sent' history."""
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String(10))       # 'sms' or 'email'
    to_address = db.Column(db.String(200))   # phone number or email address
    to_name = db.Column(db.String(120))      # recipient name if known
    subject = db.Column(db.String(300))      # email subject (blank for SMS)
    body = db.Column(db.Text)                # message content (HTML for emails)
    status = db.Column(db.String(10))        # 'sent' or 'failed'
    detail = db.Column(db.String(400))       # provider detail or error reason
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class Prospect(db.Model):
    """A cold-outreach business to CALL — the 'Big Fish Finder' call list.
    Kept separate from Lead (inbound quote requests) on purpose: prospects are
    businesses we go hunt (property managers, realtors, Airbnb hosts) and must
    NOT be swept into the customer email drip. When a prospect says yes, the VA
    converts them into a real Lead/Booking."""
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(40), default='property_manager')  # property_manager / realtor / airbnb / apartment / other
    phone = db.Column(db.String(40))
    website = db.Column(db.String(300))
    address = db.Column(db.String(300))
    city = db.Column(db.String(100))
    rating = db.Column(db.Float)                 # Google star rating (helps prioritise calls)
    place_id = db.Column(db.String(220), index=True)  # Google Place id — used to de-duplicate imports
    status = db.Column(db.String(30), default='new')  # last OUTCOME: new / called / no_answer / callback / interested / not_interested / won
    notes = db.Column(db.Text)
    source = db.Column(db.String(50), default='google_places')
    agent = db.Column(db.String(100))                 # team member (VA) credited for commission
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    called_at = db.Column(db.DateTime)

    # Where they are in the funnel, as opposed to what happened on the last
    # call. "No answer" is one call; "Working" is a position. Keeping them in
    # one column meant a list of outcomes that could not be counted.
    stage = db.Column(db.String(20), default='new', index=True)

    # The two fields that stop things being dropped: what happens next and the
    # day it is due. A status of "Call Back" without a date is a note to
    # nobody — the list had no way to surface anything at the right time.
    next_action = db.Column(db.String(120))
    next_action_date = db.Column(db.String(10), index=True)   # YYYY-MM-DD

    attempts = db.Column(db.Integer, default=0)        # calls placed, not conversations had
    contact_name = db.Column(db.String(120))           # the human, not the business
    email = db.Column(db.String(200))                  # asked for on the call; Places never has it
    renewal_note = db.Column(db.String(120))           # "March 2027" — why a no is worth keeping
    last_emailed_at = db.Column(db.DateTime)

    CATEGORY_LABELS = {
        'property_manager': '🏢 Property Manager',
        'realtor': '🔑 Realtor',
        'airbnb': '🛏️ Airbnb / STR Host',
        'apartment': '🏘️ Apartment Complex',
        'daycare': '🧸 Daycare / Childcare',
        'medical_office': '🩺 Doctor / Medical Office',
        'general_contractor': '🏗️ General Contractor',
        'office': '💼 Office Space',
        'other': '📇 Other',
    }

    STATUS_LABELS = {
        'new': 'New',
        'called': 'Called',
        'no_answer': 'No Answer',
        'callback': 'Call Back',
        'interested': 'Interested',
        'not_interested': 'Not Interested',
        'won': 'Won 🎉',
    }

    # Ordered — this is the funnel, drawn left to right on the pipeline board.
    STAGE_LABELS = [
        ('new',        'New'),
        ('working',    'Working'),
        ('interested', 'Interested'),
        ('proposal',   'Proposal'),
        ('won',        'Won 🎉'),
        ('nurture',    'Nurture'),
        ('lost',       'Lost'),
    ]
    LIVE_STAGES = ('new', 'working', 'interested', 'proposal')

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category or 'Other')

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status or 'New')

    @property
    def stage_label(self):
        return dict(self.STAGE_LABELS).get(self.stage or 'new', 'New')

    @property
    def is_open(self):
        return (self.stage or 'new') in self.LIVE_STAGES

    def due_state(self, today=None):
        """'overdue' / 'today' / 'later' / None — what the Today list sorts on."""
        if not self.next_action_date:
            return None
        from datetime import date as _date
        today = today or _date.today().isoformat()
        if self.next_action_date < today:
            return 'overdue'
        if self.next_action_date == today:
            return 'today'
        return 'later'


class User(db.Model):
    """A person who can log into the CRM.
    role 'owner'  → sees everything, money included (that's Monica).
    role 'team'   → VAs / future hires: everything EXCEPT money pages
                    (payroll, contractor pay, reports, settings).
    Monica's original env-based login still works and is always an owner."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='team')   # 'owner' or 'team'
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    def set_password(self, pw):
        # pbkdf2:sha256 is supported on every Python build; werkzeug's newer
        # default (scrypt) needs OpenSSL scrypt support that some builds lack.
        self.password_hash = generate_password_hash(pw, method='pbkdf2:sha256')

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def role_label(self):
        return '👑 Owner' if self.role == 'owner' else '👤 Team'


class CommercialAccount(db.Model):
    """A commercial cleaning client — an ongoing ACCOUNT, not a one-off booking.
    Think 'Sunrise Daycare — cleaned every Friday, $600/month'. Created when the
    VA closes a business from Find Leads (the Won → Customer hand-off), or added
    by hand. Kept separate from residential Bookings, which think in bedrooms."""
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(200), nullable=False)
    contact_name = db.Column(db.String(120))          # the person we deal with
    email = db.Column(db.String(200))
    phone = db.Column(db.String(40))
    address = db.Column(db.String(300))
    city = db.Column(db.String(100))
    square_footage = db.Column(db.Integer)                     # drives the cost-based quote
    category = db.Column(db.String(40), default='office')      # reuses Prospect categories
    frequency = db.Column(db.String(30), default='weekly')     # nightly/weekly/biweekly/monthly/custom
    billing_type = db.Column(db.String(20), default='monthly') # 'monthly' or 'per_visit'
    billing_amount = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='active')        # active/paused/lead
    notes = db.Column(db.Text)
    source = db.Column(db.String(50), default='find_leads')
    agent = db.Column(db.String(100))                          # team member (VA) credited for commission
    first_paid_at = db.Column(db.DateTime)                     # first invoice paid → triggers landing bonus + residuals
    prospect_id = db.Column(db.Integer)                        # origin prospect, if converted
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    FREQ_LABELS = {
        'nightly': 'Nightly', 'weekly': 'Weekly', 'biweekly': 'Every 2 weeks',
        'monthly': 'Monthly', 'custom': 'Custom',
    }
    STATUS_LABELS = {'active': 'Active', 'paused': 'Paused', 'lead': 'Lead'}
    # roughly how many billing periods land in a month, to estimate monthly value
    _PER_MONTH = {'nightly': 22, 'weekly': 4.3, 'biweekly': 2.15, 'monthly': 1, 'custom': 1}

    @property
    def category_label(self):
        return Prospect.CATEGORY_LABELS.get(self.category, self.category or 'Other')

    @property
    def frequency_label(self):
        return self.FREQ_LABELS.get(self.frequency, self.frequency or 'Weekly')

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status or 'Active')

    @property
    def monthly_value(self):
        """Estimated monthly revenue — used for the pipeline total."""
        amt = self.billing_amount or 0
        if self.billing_type == 'monthly':
            return round(amt, 2)
        return round(amt * self._PER_MONTH.get(self.frequency, 4.3), 2)
