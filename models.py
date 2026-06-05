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
    deposit_paid = db.Column(db.Boolean, default=False)
    balance_due = db.Column(db.Float)
    balance_collected = db.Column(db.Boolean, default=False)

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
