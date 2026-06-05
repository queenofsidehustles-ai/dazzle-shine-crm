from extensions import db
from datetime import datetime


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

    # Admin fields
    notes = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, completed, cancelled
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
