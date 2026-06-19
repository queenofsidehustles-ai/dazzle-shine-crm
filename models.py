from extensions import db
from datetime import datetime
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
    balance_due = db.Column(db.Float)
    balance_collected = db.Column(db.Boolean, default=False)

    # Discount
    discount_code = db.Column(db.String(50))
    discount_amount = db.Column(db.Float, default=0)
    # Payroll
    hours_worked = db.Column(db.Float)

    # Admin fields
    notes = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    assigned_cleaner = db.Column(db.String(100))
    cleaner_notified_at = db.Column(db.DateTime)        # when job notification was last sent
    cleaner_response = db.Column(db.String(20))         # accepted, declined, None
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, in_progress, completed, cancelled
    price = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    booking = db.relationship('Booking', backref='job_checklists')

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
    pay_rate = db.Column(db.Float, default=40.0)            # % of job or $/hr
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
        ('shadow_job',        'Shadow job / trial shift completed'),
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
