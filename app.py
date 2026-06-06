import os
from flask import Flask
from extensions import db
from blueprints.admin import admin_bp
from blueprints.bookings import bookings_bp
from blueprints.api import api_bp
from blueprints.settings import settings_bp
from blueprints.staff import staff_bp
from blueprints.leads import leads_bp
from blueprints.workorders import workorders_bp
from blueprints.content import content_bp
from blueprints.quotes import quotes_bp
from blueprints.ratings import ratings_bp
from blueprints.discounts import discounts_bp
from blueprints.contractors import contractors_bp


def create_app():
    app = Flask(__name__)

    # Database
    db_url = os.environ.get('DATABASE_URL', '')
    # Fall back to SQLite if URL is missing or unresolved template
    if not db_url or db_url.startswith('$') or '://' not in db_url:
        db_url = 'sqlite:///dazzle.db'
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    if db_url.startswith('postgresql://') and '+psycopg2' not in db_url:
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

    db.init_app(app)

    app.register_blueprint(admin_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(leads_bp)
    app.register_blueprint(workorders_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(ratings_bp)
    app.register_blueprint(discounts_bp)
    app.register_blueprint(contractors_bp)

    with app.app_context():
        db.create_all()
        _migrate_db()

    return app


def _migrate_db():
    """Add any missing columns to existing tables safely (idempotent)."""
    from sqlalchemy import text
    new_cols = [
        # Booking columns added after initial deploy
        ('booking', 'frequency',                "VARCHAR(20) DEFAULT 'one_time'"),
        ('booking', 'internal_notes',           'TEXT'),
        ('booking', 'assigned_cleaner',         'VARCHAR(100)'),
        ('booking', 'stripe_payment_intent',    'VARCHAR(100)'),
        ('booking', 'deposit_paid',             'BOOLEAN DEFAULT FALSE'),
        ('booking', 'balance_due',              'FLOAT'),
        ('booking', 'balance_collected',        'BOOLEAN DEFAULT FALSE'),
        ('booking', 'stripe_customer_id',       'VARCHAR(100)'),
        ('booking', 'stripe_payment_method_id', 'VARCHAR(100)'),
        ('booking', 'discount_code',            'VARCHAR(50)'),
        ('booking', 'discount_amount',          'FLOAT DEFAULT 0'),
        ('booking', 'hours_worked',             'FLOAT'),
        ('staff',   'pay_type',                 "VARCHAR(20) DEFAULT 'percent'"),
        ('staff',   'pay_rate',                 'FLOAT DEFAULT 40'),
        ('staff',   'experience_level',         "VARCHAR(20) DEFAULT 'new'"),
        ('staff',   'emergency_contact_name',   'VARCHAR(100)'),
        ('staff',   'emergency_contact_phone',  'VARCHAR(20)'),
        ('staff',   'has_transportation',       'BOOLEAN DEFAULT TRUE'),
        ('staff',   'has_supplies',             'BOOLEAN DEFAULT FALSE'),
        ('staff',   'onboarding_steps',         "TEXT DEFAULT '[]'"),
        ('staff',   'notes',                    'TEXT'),
        # Staff table
        ('staff',   'color',                    "VARCHAR(7) DEFAULT '#7c3aed'"),
        # Pricing & business settings tables (created fresh by create_all if missing)
    ]
    for table, col, col_type in new_cols:
        try:
            with db.engine.begin() as conn:  # each gets its own transaction
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col} {col_type}'))
        except Exception:
            pass  # column already exists — safe to ignore


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8001)), debug=True)
