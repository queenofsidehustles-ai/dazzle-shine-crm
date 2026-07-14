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
    balance_due = db.Column(db.Float)
    balance_collected = db.Column(db.Boolean, default=False)
    pay_token = db.Column(db.String(64))       # unique link for paying the full amount (invoice / on-site)
    paid_at = db.Column(db.DateTime)           # when paid in full (card or manual)
    paid_method = db.Column(db.String(20))     # card, cash, zelle, venmo, other
    invoice_sent_at = db.Column(db.DateTime)   # morning-of invoice sent (one per day guard)

    # Lead fee — advertising cost baked into the customer price but EXCLUDED
    # from the contractor's commission (invisible to the customer).
    lead_fee = db.Column(db.Float, default=0)

    # Discount
    discount_code = db.Column(db.String(50))
    discount_amount = db.Column(db.Float, default=0)
    # Payroll
    hours_worked = db.Column(db.Float)

    # Admin fields
    notes = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    access_notes = db.Column(db.Text)   # entry info for the cleaner: gate code, key, parking, alarm, pets
    assigned_cleaner = db.Column(db.String(100))
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
        """Amount the contractor's cut is based on — total minus the lead fee."""
        return round((self.price or 0) - (self.lead_fee or 0), 2)

    @property
    def service_label(self):
        return self.SERVICE_LABELS.get(self.service_type, self.service_type.title())

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, '#9ca3af')


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
    notes = db.Column(db.Text)
    drip_step = db.Column(db.Integer, default=1)
    last_drip_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    SERVICE_LABELS = {
        'standard': 'Standard House Cleaning', 'deep': 'Deep Cleaning',
        'moveout': 'Move-Out / Move-In Cleaning', 'airbnb': 'Airbnb / Vacation Rental',
        'apartment': 'Apartment & Condo Cleaning', 'luxury': 'Luxury Home Cleaning',
    }

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


class ContractorPayment(db.Model):
    """A record of paying a contractor — via Stripe (automatic) or manually (Venmo/Zelle/etc.)."""
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(20), default='stripe')   # stripe, venmo, zelle, cash, check
    status = db.Column(db.String(20), default='paid')     # paid, pending, failed
    stripe_transfer_id = db.Column(db.String(64))         # tr_... when paid via Stripe
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    staff = db.relationship('Staff', backref=db.backref('payments', lazy=True,
                            order_by='ContractorPayment.created_at.desc()'))


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
        ('followup',  'Follow-Up'),
        ('objection', 'Objection Handling'),
        ('closing',   'Closing Scripts'),
        ('general',   'General Outreach'),
    ]


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
    status = db.Column(db.String(30), default='new')  # new / called / no_answer / callback / interested / not_interested / won
    notes = db.Column(db.Text)
    source = db.Column(db.String(50), default='google_places')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    called_at = db.Column(db.DateTime)

    CATEGORY_LABELS = {
        'property_manager': '🏢 Property Manager',
        'realtor': '🔑 Realtor',
        'airbnb': '🛏️ Airbnb / STR Host',
        'apartment': '🏘️ Apartment Complex',
        'daycare': '🧸 Daycare / Childcare',
        'medical_office': '🩺 Doctor / Medical Office',
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

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category or 'Other')

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status or 'New')


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
