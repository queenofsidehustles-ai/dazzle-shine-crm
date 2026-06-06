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

    # Admin fields
    notes = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    assigned_cleaner = db.Column(db.String(100))
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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
