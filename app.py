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
        _seed_checklists()

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
        # CommercialQuote columns added after initial deploy
        ('commercial_quote', 'sent_at',         'TIMESTAMP'),
        ('commercial_quote', 'responded_at',    'TIMESTAMP'),
        ('commercial_quote', 'units',           'VARCHAR(20)'),
        ('commercial_quote', 'sqft',            'VARCHAR(20)'),
        ('commercial_quote', 'contract_term',   'VARCHAR(50)'),
        ('commercial_quote', 'monthly_price',   'FLOAT'),
        ('commercial_quote', 'scope_notes',     'TEXT'),
        # Contractor columns
        ('contractor_application', 'experience_years', 'VARCHAR(20)'),
        ('contractor_application', 'availability',     'VARCHAR(50)'),
    ]
    for table, col, col_type in new_cols:
        try:
            with db.engine.begin() as conn:  # each gets its own transaction
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col} {col_type}'))
        except Exception:
            pass  # column already exists — safe to ignore


def _seed_checklists():
    """Create default checklist templates if they don't exist yet."""
    import json as _json
    from models import ChecklistTemplate

    defaults = [
        ('Standard Cleaning', 'standard', [
            'Dust all surfaces (shelves, furniture, baseboards)',
            'Wipe down countertops and kitchen surfaces',
            'Clean stovetop and microwave exterior',
            'Wipe appliance exteriors',
            'Clean sink(s)',
            'Scrub toilets, tubs, and showers',
            'Wipe bathroom mirrors and fixtures',
            'Vacuum all floors and rugs',
            'Mop hard floors',
            'Empty trash cans and replace liners',
            'Make beds / straighten linens',
            'Wipe light switches and door handles',
        ]),
        ('Deep Cleaning', 'deep', [
            'Everything in Standard Cleaning',
            'Scrub baseboards throughout',
            'Wipe door frames and doors',
            'Clean window sills and blinds',
            'Scrub grout in bathroom tiles',
            'Clean behind and under appliances',
            'Wipe cabinet fronts inside and out',
            'Clean ceiling fans and light fixtures',
            'Vacuum furniture and upholstery',
            'Wipe walls for scuff marks',
            'Detail clean shower/tub (remove soap scum buildup)',
            'Clean interior of microwave',
        ]),
        ('Move-Out / Move-In Cleaning', 'moveout', [
            'Everything in Deep Cleaning',
            'Wipe inside all cabinets and drawers',
            'Clean inside oven (full detail)',
            'Clean inside refrigerator',
            'Wipe all walls top to bottom',
            'Clean inside closets',
            'Remove any remaining trash or debris',
            'Clean all windows (interior)',
            'Scrub all bathrooms top to bottom',
            'Vacuum and mop all rooms',
            'Final walkthrough — photo ready',
        ]),
        ('Airbnb / Vacation Rental Turnover', 'airbnb', [
            'Strip and replace all bed linens',
            'Replace towels (bath, hand, kitchen)',
            'Restock toiletries (soap, shampoo, toilet paper)',
            'Restock paper towels and cleaning supplies',
            'Clean all bathrooms',
            'Wipe kitchen surfaces and appliances',
            'Empty and clean trash cans',
            'Run dishwasher / hand wash dishes',
            'Vacuum and mop all floors',
            'Straighten furniture and décor',
            'Check and replace light bulbs if needed',
            'Check for guest left-behind items',
            'Take photos when complete',
        ]),
        ('Apartment / Condo Cleaning', 'apartment', [
            'Dust all surfaces',
            'Wipe kitchen counters and stovetop',
            'Clean microwave interior and exterior',
            'Clean sink and faucets',
            'Scrub toilet, tub, and shower',
            'Wipe bathroom mirror and counter',
            'Vacuum all areas',
            'Mop hard floors',
            'Empty trash',
            'Straighten bedding',
        ]),
        ('Luxury Home Cleaning', 'luxury', [
            'Dust all surfaces with microfiber — no streaks',
            'Wipe all furniture (wood treatment where applicable)',
            'Clean all bathrooms — white-glove detail',
            'Polish fixtures and hardware',
            'Clean kitchen appliances inside and out',
            'Wipe cabinet fronts and handles',
            'Vacuum furniture and upholstery',
            'Vacuum and mop all floors',
            'Clean ceiling fans and chandeliers',
            'Wipe baseboards, door frames, and trim',
            'Clean all mirrors — streak free',
            'Make all beds with hotel-style finish',
            'Arrange décor and artwork straight',
            'Final walkthrough with checklist sign-off',
        ]),
    ]

    for name, svc_type, items in defaults:
        exists = ChecklistTemplate.query.filter_by(name=name).first()
        if not exists:
            t = ChecklistTemplate(name=name, service_type=svc_type, items=_json.dumps(items))
            db.session.add(t)
    db.session.commit()


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8001)), debug=True)
