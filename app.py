import os
try:
    # Load a local .env file if present (safe no-op in production, where
    # Railway injects real env vars). Lets GOOGLE_PLACES_API_KEY etc. work locally.
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
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
from blueprints.scripts import scripts_bp
from blueprints.sops import sops_bp
from blueprints.email_templates import email_templates_bp
from blueprints.interviews import interviews_bp
from blueprints.pricing_public import pricing_public_bp
from blueprints.deposit import deposit_bp
from blueprints.messages import messages_bp
from blueprints.payments import payments_bp
from blueprints.claims import claims_bp
from blueprints.places_finder import places_finder_bp
from blueprints.team_logins import team_logins_bp
from blueprints.commercial import commercial_bp
from blueprints.commissions import commissions_bp
from blueprints.invoices import invoices_bp
from blueprints.portal import portal_bp
from blueprints.money import money_bp
from blueprints.team import team_bp, availability_bp


def create_app():
    app = Flask(__name__)

    # Trust Railway's proxy so url_for(_external=True) builds https:// links
    # (Stripe live mode rejects http return URLs, and email links should be secure).
    try:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    except Exception:
        pass

    # Database
    db_url = os.environ.get('DATABASE_URL', '')
    # Fall back to SQLite if URL is missing or unresolved template
    if not db_url or db_url.startswith('$') or '://' not in db_url:
        db_url = 'sqlite:///crm.db'
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
    app.register_blueprint(scripts_bp)
    app.register_blueprint(sops_bp)
    app.register_blueprint(email_templates_bp)
    app.register_blueprint(interviews_bp)
    app.register_blueprint(pricing_public_bp)
    app.register_blueprint(deposit_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(places_finder_bp)
    app.register_blueprint(team_logins_bp)
    app.register_blueprint(commercial_bp)
    app.register_blueprint(commissions_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(portal_bp)
    from blueprints.confirm import confirm_bp
    app.register_blueprint(confirm_bp)
    app.register_blueprint(money_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(availability_bp)

    # The menu itself — see navigation.py. Built per request because what the
    # sidebar shows depends on whether the owner or a team member is looking.
    @app.context_processor
    def inject_navigation():
        try:
            from flask import session, request
            if not session.get('logged_in'):
                return {}
            import navigation
            role = session.get('role', 'owner')
            tabs, active_tab = navigation.tabs_for(request.endpoint, role)
            return {'NAV': navigation.sidebar(role),
                    'NAV_ACTIVE': navigation.active_item(request.endpoint),
                    'NAV_TABS': tabs,
                    'NAV_ACTIVE_TAB': active_tab}
        except Exception:
            # A broken menu must never take a working page down with it.
            return {'NAV': [], 'NAV_ACTIVE': None, 'NAV_TABS': [], 'NAV_ACTIVE_TAB': None}

    # Unread-message count for the sidebar badge (all admin pages).
    @app.context_processor
    def inject_nav_unread():
        try:
            from flask import session
            if not session.get('logged_in'):
                return {}
            from models import Message
            return {'nav_unread': Message.query.filter_by(direction='in', read_at=None).count()}
        except Exception:
            return {}

    # Who this CRM belongs to. Every template that used to say "Dazzle & Shine
    # Maids" in plain text now reads BIZ, so one deployment can serve one company
    # and a second deployment can serve another without a line of code changing.
    @app.context_processor
    def inject_brand():
        import branding
        try:
            import brands
            return {
                'BIZ': branding.biz_name(),
                'BIZ_COMMERCIAL': brands.get_brand(brands.COMMERCIAL)['name'],
                'BIZ_PHONE': branding.phone(),
                'BIZ_EMAIL': branding.reply_to(),
                'BIZ_WEBSITE': branding.website(),
                'BIZ_CITY': branding.city_line(),
                'BIZ_BOOKING_LINK': branding.booking_link(),
                'CRM_BASE': branding.crm_base(),
                'APP_VERSION': branding.version(),
            }
        except Exception:
            # A template must never 500 because a setting is missing.
            return {'BIZ': 'Your Cleaning Company', 'BIZ_COMMERCIAL': 'Your Cleaning Company',
                    'BIZ_PHONE': '', 'BIZ_EMAIL': '', 'BIZ_WEBSITE': '',
                    'BIZ_CITY': '', 'BIZ_BOOKING_LINK': '', 'CRM_BASE': '',
                    'APP_VERSION': branding.version()}

    # A nudge for a business that hasn't finished setting itself up. Goes quiet
    # for good once the essentials are connected, so an established business
    # never sees it.
    @app.context_processor
    def inject_setup_state():
        try:
            from flask import session
            from models import BusinessSetting
            if not session.get('logged_in') or session.get('role') != 'owner':
                return {'SETUP_PENDING': None}
            if BusinessSetting.get('setup_complete') == '1':
                return {'SETUP_PENDING': None}
            import onboarding
            s = onboarding.summary()
            if s['complete']:
                BusinessSetting.set('setup_complete', '1')
                db.session.commit()
                return {'SETUP_PENDING': None}
            n = len(s['blocking'])
            return {'SETUP_PENDING': f"{n} thing{'s' if n != 1 else ''}"}
        except Exception:
            return {'SETUP_PENDING': None}

    # Timestamps are stored as UTC and read by people in one particular place.
    # These render them in the business's own timezone, labelled, so nobody has
    # to do the arithmetic — least of all somebody reviewing a dispute.
    import scheduling as _sched
    app.jinja_env.filters['stamp'] = _sched.stamp
    app.jinja_env.filters['short_stamp'] = _sched.short_stamp
    app.jinja_env.globals['business_tz_label'] = lambda: _sched.local_now().strftime('%Z')

    with app.app_context():
        db.create_all()
        _migrate_db()
        _seed_checklists()
        _seed_scripts()
        _seed_sales_scripts()
        _seed_sops()
        _seed_email_templates()
        _apply_template_patches()
        _seed_pricing_defaults()
        _seed_message_templates()
        _patch_pay_rate_40_to_50()
        _seed_existing_brand_settings()
        _skip_setup_for_established_business()

    return app


def _skip_setup_for_established_business():
    """Don't show a 'finish setting up' checklist to a business that is plainly
    already running.

    The checklist asks the owner to confirm she has reviewed her prices and her
    customer terms. There is no way to detect that — a business may quite
    reasonably keep a default price. So for an instance with real booking
    history behind it, those are taken as read rather than nagged about.

    Deliberately generic: any deployment with a real history skips it, not just
    the first one."""
    from models import BusinessSetting, Booking
    if BusinessSetting.get('setup_seen'):
        return
    BusinessSetting.set('setup_seen', '1')
    if Booking.query.count() >= 5:
        for key in ('pricing_reviewed', 'terms_reviewed', 'setup_complete'):
            if not BusinessSetting.get(key):
                BusinessSetting.set(key, '1')
        print('  ✅ established business — setup checklist skipped')
    db.session.commit()


def _seed_existing_brand_settings():
    """Restore the original business's identity into Settings — see legacy_brands."""
    import legacy_brands
    if legacy_brands.restore_if_original():
        print('  ✅ original business details restored into Settings')


def _patch_pay_rate_40_to_50():
    """One-time fix: bump percent-based cleaners stuck at the old 40% default
    up to the 50% policy. Skips hourly staff (their 40 means $40/hr). Runs once."""
    from models import Staff, BusinessSetting
    if BusinessSetting.get('patch_payrate_40to50'):
        return
    fixed = 0
    for s in Staff.query.filter(Staff.pay_rate == 40).all():
        if (s.pay_type or 'percent') == 'percent':
            s.pay_rate = 50
            fixed += 1
    BusinessSetting.set('patch_payrate_40to50', 'done')
    db.session.commit()
    if fixed:
        print(f"[patch] Bumped {fixed} contractor(s) from 40% to 50%.")


def _seed_message_templates():
    """Seed the reusable text-message templates once (idempotent by title)."""
    from models import MessageTemplate, BusinessSetting
    if not BusinessSetting.get('owner_name'):
        BusinessSetting.set('owner_name', 'Monica')
        db.session.commit()
    welcome_v1 = (
        "Welcome to the {business} family, {name}! 🎉 We are SO excited to have you on the "
        "team 💛 Your first day is set for {start_date} — just reply “yes” to confirm "
        "that works and we'll get everything ready for you. Here's a little sneak peek of what "
        "your daily assignments will look like, so you'll always know exactly where to go and "
        "what to do: {sample_link} Everything — the address, checklist, directions, and how to "
        "get in — will be right there in one spot. And remember, I'm always here if you need "
        "anything at all. Can't wait to work with you! — {owner}")
    welcome_v2 = (
        "Welcome to the {business} family, {name}! 🎉 We are SO excited to have you on the "
        "team 💛 Let's lock in your first day — just tap here to pick the start date that "
        "works best for you: {start_link} And here's a little sneak peek of what your daily "
        "assignments will look like, so you'll always know exactly where to go and what to do: "
        "{sample_link} Everything — the address, checklist, directions, and how to get in — "
        "will be right there in one spot. I'm always here if you need anything at all. Can't "
        "wait to work with you! — {owner}")
    defaults = [
        ('Personal Welcome',
         "Hi {name} 💛 This is {owner}, the owner of {business}. I just had to reach out "
         "personally to say how genuinely happy I am to have you with us! 🎉 I know starting "
         "somewhere new can feel like a lot, so hear this straight from me: you're never on "
         "your own here. I'm always just a text away — any question, big or small, anytime. "
         "So glad you're here. Welcome to the family! — {owner}"),
        ('Welcome + Start Date + Sample', welcome_v2),
    ]
    for title, body in defaults:
        if not MessageTemplate.query.filter_by(title=title).first():
            db.session.add(MessageTemplate(title=title, body=body))
    # Auto-upgrade the un-customized welcome template to the start-date-link version.
    w = MessageTemplate.query.filter_by(title='Welcome + Start Date + Sample').first()
    if w and w.body.strip() == welcome_v1.strip():
        w.body = welcome_v2
    db.session.commit()


def _apply_template_patches():
    """One-time content patches to LIVE email templates (idempotent via flags),
    so fixes reach existing installs without the owner pasting anything."""
    from models import EmailTemplate, BusinessSetting
    # Patch 1: client anti-poaching / buyout clause in the booking confirmation
    if not BusinessSetting.get('tmpl_patch_buyout_v1'):
        t = EmailTemplate.query.filter_by(trigger='booking_confirmed').first()
        if t and 'buyout' not in (t.body or '').lower():
            clause = ("Our team: The cleaners we send are valued members of the {{business_name}} team. "
                      "To keep things fair for everyone, you agree not to directly hire or pay any "
                      "{{business_name}} cleaner outside the company for 24 months, except with our written "
                      "approval and a $2,000 buyout fee. Thank you for understanding!")
            marker = "We can't wait to make your home sparkle!"
            if marker in t.body:
                t.body = t.body.replace(marker, clause + "\n\n" + marker)
            else:
                t.body = (t.body or '').rstrip() + "\n\n" + clause
        BusinessSetting.set('tmpl_patch_buyout_v1', '1')
        db.session.commit()

    # Patch 2: add the cleaner's "My Day" link to the job-assignment email
    if not BusinessSetting.get('tmpl_patch_myday_v1'):
        t = EmailTemplate.query.filter_by(trigger='cleaner_job_assigned').first()
        if t and 'myday_link' not in (t.body or ''):
            block = ("See all your jobs, navigate, and open your checklists here:\n{{myday_link}}\n\n")
            marker = "Please review"
            if marker in t.body:
                t.body = t.body.replace(marker, block + marker, 1)
            else:
                t.body = (t.body or '').rstrip() + "\n\n" + block
        BusinessSetting.set('tmpl_patch_myday_v1', '1')
        db.session.commit()

    # Patch 3: square-footage pricing disclaimer on quotes + confirmations
    if not BusinessSetting.get('tmpl_patch_sqft_disclaimer_v1'):
        disclaimer = ("💡 Pricing note: Your quote is based on an average-size home for this "
                      "many bedrooms. Larger homes may have a small size adjustment — always "
                      "confirmed with you first. No surprises!")
        for trig in ('lead_quote', 'booking_confirmed'):
            t = EmailTemplate.query.filter_by(trigger=trig).first()
            if t and 'average-size home' not in (t.body or ''):
                t.body = (t.body or '').rstrip() + "\n\n" + disclaimer
        BusinessSetting.set('tmpl_patch_sqft_disclaimer_v1', '1')
        db.session.commit()


def _migrate_db():
    """Add any missing columns to existing tables safely (idempotent)."""
    from sqlalchemy import text
    new_cols = [
        # Booking columns added after initial deploy
        ('booking', 'frequency',                "VARCHAR(20) DEFAULT 'one_time'"),
        ('booking', 'monthly_mode',             'VARCHAR(10)'),
        ('booking', 'tip_payment_intent',       'VARCHAR(100)'),
        ('booking', 'confirm_token',            'VARCHAR(64)'),
        ('booking', 'confirm_sent_at',          'TIMESTAMP'),
        ('booking', 'confirm_note',             'TEXT'),
        ('booking', 'confirm_response',         'VARCHAR(10)'),
        ('booking', 'confirm_alt',              'TEXT'),
        ('booking', 'onsite_people',            'TEXT'),
        ('booking', 'terms_accepted_at',        'TIMESTAMP'),
        ('booking', 'terms_accepted_text',      'TEXT'),
        ('booking', 'terms_accepted_ip',        'VARCHAR(64)'),
        ('booking', 'confirm_responded_at',     'TIMESTAMP'),
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
        ('booking', 'lead_fee',                 'FLOAT DEFAULT 0'),
        ('booking', 'pay_token',                'VARCHAR(64)'),
        ('booking', 'paid_at',                  'TIMESTAMP'),
        ('booking', 'paid_method',              'VARCHAR(20)'),
        ('booking', 'invoice_sent_at',          'TIMESTAMP'),
        ('message', 'body_translated',          'TEXT'),
        ('booking', 'sqft',                     'INTEGER'),
        ('booking', 'open_for_claim',           'BOOLEAN DEFAULT FALSE'),
        ('booking', 'claim_token',              'VARCHAR(64)'),
        ('booking', 'broadcast_at',             'TIMESTAMP'),
        ('staff',   'language',                 "VARCHAR(5) DEFAULT 'en'"),
        ('contractor_application', 'language',   "VARCHAR(5) DEFAULT 'en'"),
        ('staff',   'pay_type',                 "VARCHAR(20) DEFAULT 'percent'"),
        ('staff',   'pay_rate',                 'FLOAT DEFAULT 50'),
        ('staff',   'experience_level',         "VARCHAR(20) DEFAULT 'new'"),
        ('staff',   'emergency_contact_name',   'VARCHAR(100)'),
        ('staff',   'emergency_contact_phone',  'VARCHAR(20)'),
        ('staff',   'has_transportation',       'BOOLEAN DEFAULT TRUE'),
        ('staff',   'has_supplies',             'BOOLEAN DEFAULT FALSE'),
        ('staff',   'onboarding_steps',         "TEXT DEFAULT '[]'"),
        ('staff',   'agreement_token',          'VARCHAR(64)'),
        ('staff',   'agreement_signature',      'VARCHAR(100)'),
        ('staff',   'agreement_signed_at',      'TIMESTAMP'),
        ('staff',   'shirt_size',               'VARCHAR(10)'),
        ('staff',   'payment_pref',             'VARCHAR(50)'),
        ('staff',   'payment_notes',            'VARCHAR(200)'),
        ('staff',   'welcome_forms_at',         'TIMESTAMP'),
        ('staff',   'orientation_token',        'VARCHAR(64)'),
        ('staff',   'orientation_completed_at', 'TIMESTAMP'),
        ('staff',   'notes',                    'TEXT'),
        # Staff table
        ('staff',   'color',                    "VARCHAR(7) DEFAULT '#7c3aed'"),
        # CommercialQuote — full column set in case table was created early
        ('commercial_quote', 'token',            'VARCHAR(64)'),
        ('commercial_quote', 'phone',            'VARCHAR(20)'),
        ('commercial_quote', 'property_type',    'VARCHAR(100)'),
        ('commercial_quote', 'property_address', 'VARCHAR(200)'),
        ('commercial_quote', 'units',            'VARCHAR(20)'),
        ('commercial_quote', 'sqft',             'VARCHAR(20)'),
        ('commercial_quote', 'services',         'TEXT'),
        ('commercial_quote', 'frequency',        'VARCHAR(50)'),
        ('commercial_quote', 'contract_term',    'VARCHAR(50)'),
        ('commercial_quote', 'price_per_visit',  'FLOAT'),
        ('commercial_quote', 'monthly_price',    'FLOAT'),
        ('commercial_quote', 'scope_notes',      'TEXT'),
        ('commercial_quote', 'status',           "VARCHAR(20) DEFAULT 'draft'"),
        ('commercial_quote', 'sent_at',          'TIMESTAMP'),
        ('commercial_quote', 'viewed_at',        'TIMESTAMP'),
        ('commercial_quote', 'responded_at',     'TIMESTAMP'),
        ('commercial_quote', 'brand',            "VARCHAR(10) DEFAULT 'lm'"),
        ('commercial_quote', 'drip_step',        'INTEGER DEFAULT 0'),
        ('commercial_quote', 'last_drip_at',     'TIMESTAMP'),
        # Booking cleaner tracking
        ('booking', 'cleaner_notified_at', 'TIMESTAMP'),
        ('booking', 'cleaner_response',    'VARCHAR(20)'),
        # Per-booking review-request opt-out
        ('booking', 'skip_review',         'BOOLEAN DEFAULT FALSE'),
        # Staff worker model
        ('staff', 'worker_model', "VARCHAR(20) DEFAULT 'contractor'"),
        # Contractor application hiring pipeline
        ('contractor_application', 'source',                       "VARCHAR(50) DEFAULT 'Website'"),
        ('contractor_application', 'experience_years',             'VARCHAR(20)'),
        ('contractor_application', 'availability',                 'VARCHAR(50)'),
        ('contractor_application', 'phone_interview_completed',    'BOOLEAN DEFAULT FALSE'),
        ('contractor_application', 'phone_interview_at',           'TIMESTAMP'),
        ('contractor_application', 'phone_interview_notes',        'TEXT'),
        ('contractor_application', 'background_check_status',      "VARCHAR(20) DEFAULT 'not_started'"),
        ('contractor_application', 'background_check_notes',       'TEXT'),
        ('contractor_application', 'background_check_at',          'TIMESTAMP'),
        ('contractor_application', 'bgcheck_existing_link',         'VARCHAR(500)'),
        ('contractor_application', 'bgcheck_request_sent_at',      'TIMESTAMP'),
        ('contractor_application', 'bgcheck_results_received',     'BOOLEAN DEFAULT FALSE'),
        ('contractor_application', 'ref1_name',                    'VARCHAR(100)'),
        ('contractor_application', 'ref1_phone',                   'VARCHAR(20)'),
        ('contractor_application', 'ref1_notes',                   'TEXT'),
        ('contractor_application', 'ref1_called',                  'BOOLEAN DEFAULT FALSE'),
        ('contractor_application', 'ref2_name',                    'VARCHAR(100)'),
        ('contractor_application', 'ref2_phone',                   'VARCHAR(20)'),
        ('contractor_application', 'ref2_notes',                   'TEXT'),
        ('contractor_application', 'ref2_called',                  'BOOLEAN DEFAULT FALSE'),
        ('contractor_application', 'interview_invite_sent_at',     'TIMESTAMP'),
        ('contractor_application', 'rejection_sent_at',            'TIMESTAMP'),
        # Video interview
        ('contractor_application', 'interview_token',              'VARCHAR(64)'),
        ('contractor_application', 'interview_status',             "VARCHAR(20) DEFAULT 'not_sent'"),
        ('contractor_application', 'interview_sent_at',            'TIMESTAMP'),
        ('contractor_application', 'interview_completed_at',       'TIMESTAMP'),
        ('contractor_application', 'interview_nudge_count',        'INTEGER DEFAULT 0'),
        ('contractor_application', 'interview_last_sent_at',       'TIMESTAMP'),
        ('contractor_application', 'offer_sent_at',                'TIMESTAMP'),
        ('contractor_application', 'offer_sent_count',             'INTEGER DEFAULT 0'),
        ('contractor_application', 'offer_token',                  'VARCHAR(64)'),
        ('contractor_application', 'offer_accepted_at',            'TIMESTAMP'),
        ('booking', 'access_notes',    'TEXT'),
        # Booking lifecycle email tracking
        ('booking', 'completed_at',    'TIMESTAMP'),
        ('booking', 'morning_note_at', 'TIMESTAMP'),
        ('booking', 'review_nudge_at', 'TIMESTAMP'),
        ('booking', 'upsell_sent_at',  'TIMESTAMP'),
        ('booking', 'upsell_nudge_at', 'TIMESTAMP'),
        ('booking', 'winback_sent_at', 'TIMESTAMP'),
        # Staff Stripe Connect (payouts)
        ('staff', 'stripe_account_id',        'VARCHAR(64)'),
        ('staff', 'stripe_payouts_enabled',   'BOOLEAN DEFAULT FALSE'),
        ('staff', 'stripe_details_submitted', 'BOOLEAN DEFAULT FALSE'),
        ('staff', 'stripe_disabled_reason',   'VARCHAR(120)'),
        ('staff', 'pay_schedule',             "VARCHAR(10) DEFAULT 'daily'"),
        ('staff', 'insurance_reminder_sent_at', 'TIMESTAMP'),
        ('staff', 'roster_start_date',        'VARCHAR(20)'),
        ('staff', 'onboarding_reminder_at',   'TIMESTAMP'),
        ('staff', 'onboarding_reminder_count', 'INTEGER DEFAULT 0'),
        ('staff', 'schedule_reminder_date',   'VARCHAR(20)'),
        # Interview response transcripts
        ('interview_response', 'transcript',       'TEXT'),
        ('interview_response', 'transcript_lang',  'VARCHAR(10)'),
        # Tentative booking deposit link
        ('booking', 'deposit_token', 'VARCHAR(64)'),
        # Job completion before/after photos
        ('job_checklist', 'before_photos',       "TEXT DEFAULT '[]'"),
        ('job_checklist', 'after_photos',        "TEXT DEFAULT '[]'"),
        ('job_checklist', 'photos_submitted_at', 'TIMESTAMP'),
        # Guided job workflow — step timestamps + client sign-off
        ('job_checklist', 'on_the_way_at',    'TIMESTAMP'),
        ('job_checklist', 'clock_in_at',      'TIMESTAMP'),
        ('job_checklist', 'clock_out_at',     'TIMESTAMP'),
        ('job_checklist', 'client_signature', 'TEXT'),
        ('job_checklist', 'client_signed_at', 'TIMESTAMP'),
        ('job_checklist', 'client_rating',    'INTEGER'),
        ('job_checklist', 'client_review',    'TEXT'),
        # Background check candidate upload
        ('contractor_application', 'bgcheck_upload_token',  'VARCHAR(64)'),
        ('contractor_application', 'bgcheck_uploaded_url',  'VARCHAR(500)'),
        ('contractor_application', 'bgcheck_uploaded_link', 'VARCHAR(500)'),
        ('contractor_application', 'bgcheck_uploaded_at',   'TIMESTAMP'),
        # VA commission attribution
        ('booking', 'source',               "VARCHAR(50) DEFAULT 'website'"),
        ('booking', 'agent',                'VARCHAR(100)'),
        ('lead', 'agent',                   'VARCHAR(100)'),
        ('prospect', 'agent',               'VARCHAR(100)'),
        ('commercial_account', 'agent',         'VARCHAR(100)'),
        ('commercial_account', 'first_paid_at', 'TIMESTAMP'),
        # Proactive recurring scheduling
        ('booking', 'recurring_group',  'VARCHAR(32)'),
        ('booking', 'recurring_active', 'BOOLEAN DEFAULT TRUE'),
        # Real invoicing
        ('booking', 'invoice_number',    'VARCHAR(20)'),
        ('booking', 'invoice_issued_at', 'TIMESTAMP'),
        ('booking', 'invoice_due_date',  'VARCHAR(10)'),
        # Customer portal + card on file (auto-pay)
        ('client',  'portal_token',             'VARCHAR(64)'),
        ('client',  'stripe_customer_id',       'VARCHAR(100)'),
        ('client',  'stripe_payment_method_id', 'VARCHAR(100)'),
        ('client',  'card_brand',               'VARCHAR(20)'),
        ('client',  'card_last4',               'VARCHAR(4)'),
        ('client',  'autopay',                  'BOOLEAN DEFAULT FALSE'),
        # Link a Team member back to the application they came from
        ('staff',   'application_id',           'INTEGER'),
        # Cleaner payout tracking (one-click pay per job) — prevents double-paying
        ('booking', 'cleaner_paid_at',      'TIMESTAMP'),
        ('booking', 'cleaner_payment_id',   'INTEGER'),
        ('contractor_payment', 'booking_id', 'INTEGER'),
        # Crew jobs — 2+ cleaners on one big house (booking_crew table is created
        # by create_all; this is just the size flag on the booking itself)
        ('booking', 'crew_size',            'INTEGER DEFAULT 1'),
        # Pay set by hand, per cleaner. NULL means "work it out from the hours",
        # which is what every existing job keeps doing.
        ('booking', 'crew_pay_each',        'FLOAT'),
        # Bookkeeping (expense, recurring_expense, commission_payment and
        # processing_fee tables are created by create_all)
        ('expense', 'miles',                'FLOAT'),
        ('expense', 'rate_per_mile',        'FLOAT'),
        ('expense', 'receipt_url',          'VARCHAR(400)'),
        # Labor-based pay: person-hours of work in a job, which sets what the
        # cleaner(s) are paid. Null on every existing booking, which is what
        # keeps them on the old percentage until they're re-estimated.
        ('booking', 'estimated_hours',      'FLOAT'),
        ('booking', 'labor_rate_applied',   'FLOAT'),
        ('booking', 'below_floor_reason',   'VARCHAR(200)'),
        # Tips — the customer's, passed straight to the cleaner. Kept separate
        # from price and from labor so they never distort revenue or margin.
        ('booking', 'tip_amount',           'FLOAT DEFAULT 0'),
        ('contractor_payment', 'tip_amount', 'FLOAT DEFAULT 0'),
        ('booking', 'owner_hours',          'FLOAT DEFAULT 0'),
        ('expense', 'booking_id',           'INTEGER'),
        # Prospecting funnel — where a prospect is, and what happens next.
        # stage and attempts are deliberately left NULL rather than defaulted:
        # a DEFAULT would stamp every business already on the call list as a
        # never-touched New with zero attempts, wiping the work done so far.
        # NULL means "predates the funnel", which prospecting.backfill() reads
        # and fills in from the call history that is already there.
        ('prospect', 'stage',               'VARCHAR(20)'),
        ('prospect', 'next_action',         'VARCHAR(120)'),
        ('prospect', 'next_action_date',    'VARCHAR(10)'),
        ('prospect', 'attempts',            'INTEGER'),
        ('prospect', 'contact_name',        'VARCHAR(120)'),
        ('prospect', 'email',               'VARCHAR(200)'),
        ('prospect', 'renewal_note',        'VARCHAR(120)'),
        ('prospect', 'last_emailed_at',     'TIMESTAMP'),
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


def _seed_sales_scripts():
    """Add the deep, psychology-backed cold-call scripts for both brands.
    Idempotent (guarded by a BusinessSetting flag). Lines starting with 💡 render
    as tap-to-open 'Why this works' notes so the VA reads clean during a call."""
    from models import Script, BusinessSetting

    scripts = [
        ('outbound', '🏢 Cold Call Opening + Discovery — Commercial (offices · daycares · medical)', 0, """[When they answer]
"Hi, this is {owner} with {biz} here in {city} — did I catch you at an okay time?"
💡 Asking "is now okay?" hands them control and lowers their guard. People relax the moment they feel free to say no.

[If they say go ahead]
"Thanks — I'll be quick and real with you. You weren't expecting my call, so I'll get right to the point."
💡 Naming the awkwardness ("you weren't expecting my call") disarms suspicion. Radical honesty builds instant trust.

"We handle commercial cleaning for a handful of offices and daycares around {city}, and I'm reaching out to a few local spots to see if we're a fit. Quick question — who handles your cleaning right now, in-house or an outside company?"
💡 "A handful of local spots" is social proof + quiet scarcity (we're selective). The open question gets THEM talking instead of you pitching.

[Listen. Then diagnose — don't sell yet.]
"Got it. And how's that been working out for you?"
💡 A calibrated question. Their answer reveals the pain — no-shows, inconsistency — that you can solve. Diagnose before you prescribe.

[If they hint at any frustration, label it:]
"It sounds like reliability has been a bit of a headache."
💡 Labeling their feeling makes them feel understood, and they open up more. This is tactical empathy, not flattery.

"That's exactly what we hear most. Here's all I'd suggest, no pressure: let me do a quick 10-minute walkthrough of your space and put together a clear quote. If it's a fit, great — if not, no hard feelings. Would it be unreasonable to grab 10 minutes this week?"
💡 "Would it be unreasonable to…?" is a no-oriented question — it's easy to say "no, that's fine," which really means yes. And a 10-minute walkthrough is a tiny commitment, not a contract (foot-in-the-door)."""),

        ('outbound', '🏘️ Cold Call Opening + Discovery — [Your Company] (apartments · property managers)', 1, """[When they answer]
"Hi, this is [Your Name] with [Your Company] — did I catch you at a bad time?"
💡 "Bad time?" invites a safe "no" and disarms. It beats "How are you today?", which instantly signals a sales pitch.

"Thanks for a sec. I'll be straight with you — I'm reaching out to property managers around {city} because turnovers and move-outs are usually where cleaning falls apart. Who's handling your unit turnover cleans right now?"
💡 Leading with THEIR known pain (turnovers) proves you understand their world. Specific beats generic every time.

[Listen]
"And when a unit turns and your cleaner cancels last minute — how big a problem is that for you?"
💡 A calibrated question that surfaces loss aversion: a vacant unit that isn't rent-ready costs real money. You're helping them feel the cost of staying put.

"Right — that's the exact gap we fill: reliable turnover cleans so your units are rent-ready on time. Would it be ridiculous to set up a quick walkthrough of one property so I can show you what we'd charge per unit?"
💡 "Would it be ridiculous to…?" is the safe-no close again. "Per unit" framing matches how property managers actually think about cost."""),

        ('outbound', '🔑 Cold Call Opening + Discovery — Realtors (listing & closing cleans) — [Your Company]', 2, """[When they answer]
"Hi, is this [Name]? This is [Your Name] with [Your Company] — did I catch you between showings?"
💡 "Between showings?" shows you get a realtor's crazy schedule and gives a respectful out. Rapport in one line.

"I'll be quick — I work with a few {city} agents on move-in and move-out cleans, the kind that make a listing photograph beautifully and close smoothly. Do you have a go-to cleaner for your listings right now?"
💡 Tie cleaning to what a realtor actually cares about: photos, showings, on-time closings. Sell their outcome, not your service.

[Listen]
"And when a closing's tight and the house has to be spotless fast — who do you call?"
💡 A calibrated question that surfaces the panic moment (the last-minute clean) where you become the hero. Loss aversion: a delayed close costs them.

"That's exactly what we're great at — fast, reliable turn cleans on your timeline. Would it be crazy to be your on-call cleaner, so your next tight closing is already handled?"
💡 "Would it be crazy to…?" safe-no close. "On-call" is a tiny yes, not a commitment — and frames you as their safety net."""),

        ('outbound', '🛏️ Cold Call Opening + Discovery — Airbnb / STR Hosts (turnovers) — [Your Company]', 3, """[When they answer]
"Hi [Name], this is [Your Name] with [Your Company] — did I catch you at an okay time?"
💡 A permission opener — hands control over and lowers the guard.

"I'll keep it short. I help short-term rental hosts around {city} with guest turnovers — the fast, spotless resets between check-out and check-in. How are you handling your turnovers right now?"
💡 Speak their language: "turnovers," "check-out/check-in," "5-star clean." Insider words prove you truly get their business.

[Listen]
"And on a same-day turnaround, when a cleaner flakes and a guest is checking in at 4 — how stressful is that?"
💡 Name their nightmare. The pain of a bad review over a dirty unit is powerful loss aversion.

"Right — that's the exact gap we fill: dependable same-day turnovers so you never scramble and your reviews stay 5-star. Would it be unreasonable to set up one property so you can see how we do?"
💡 "Would it be unreasonable to…?" safe-no close, and "one property" shrinks it to a low-risk trial."""),

        ('general', '🔑 Gatekeeper — Getting to the Decision-Maker', 0, """[Front desk / receptionist answers]
"Hi! Maybe you can help me out — who would I talk to about the cleaning or janitorial services for the building?"
💡 "Maybe you can help me" turns the gatekeeper into an ally instead of an obstacle. People genuinely like to help.

[If they ask what it's about]
"Of course — I'm [Your Name] with [Brand]. We do commercial cleaning locally, and I just wanted to see if they're happy with their current setup. Are they around?"
💡 Honest and low-stakes ("just seeing if they're happy") gives them nothing to block. You're not selling — you're checking in.

[If the decision-maker isn't available]
"No worries. What's the best way to reach them — and is there a better time of day I'd catch them?"
💡 Asking for the best TIME (not just "can I leave a message") earns you a real callback window instead of the voicemail graveyard.

[Always get the name]
"Great — and who should I ask for when I call back?"
💡 A name turns your next call from cold into warm. Tiny ask, huge payoff."""),

        ('general', '📵 Voicemail Scripts That Actually Get Callbacks', 1, """[Keep it under 20 seconds. Curiosity + an easy reason to call back.]
"Hi [Name], it's {owner} with {biz} here in {city}. I had a quick question about how you're handling the cleaning at [Business/Property] — I think we might save you a headache. Call me back at [number]; again that's [number]. Thanks!"
💡 "A quick question" + "save you a headache" opens a curiosity loop their brain wants to close. Saying the number twice makes calling back effortless.

[Second voicemail, a few days later — reference the first, stay light]
"Hi [Name], [Your Name] with [Brand] again. Still happy to take the cleaning off your plate whenever the timing's right — no rush at all. [number]."
💡 "No rush" removes pressure, which paradoxically makes people MORE likely to call back. Persistence without pushiness."""),

        ('objection', '🛡️ Objection Handling — The Top 6 (both brands)', 0, """❝ "We already have a cleaner." ❞
"That's great — honestly, most of our best clients did when we first met. Can I ask… on their worst day, what's the one thing you wish they did better?"
💡 Agree first (zero resistance), then a calibrated question that opens a crack. Nobody is 100% happy with their vendor.
"All I'd ask is to be your backup — so the day they cancel, you've already got someone. Costs you nothing to have us on file."
💡 "Backup" is a zero-risk foot-in-the-door, and it plants loss aversion around the cancellation that WILL eventually happen.

❝ "Just email me some info." ❞
"Happy to! So I send something actually useful and not generic — what matters most to you: price, reliability, or flexibility?"
💡 "Email me" is usually a polite brush-off. This flips it into quick discovery AND earns you a real reason to follow up.
"Perfect — I'll send that. And so it doesn't get buried, mind if I give you a quick call Thursday?"
💡 Locking the next step kills the email black hole. You control the follow-up instead of hoping.

❝ "What's your price?" ❞
"Fair question — it depends on your space, so I won't guess and be wrong. That's exactly why the 10-minute walkthrough helps. Most spots your size land around [range] — want me to get you an exact number?"
💡 Drop a range so they're not shocked later (anchoring), then pivot back to the walkthrough. Never quote blind over the phone.

❝ "It's too expensive." ❞
"I hear you. Can I ask — expensive compared to what?"
💡 A calibrated question that makes THEM define the comparison. Usually it's a cheaper, less reliable option — which opens the value conversation.
"When a cheap cleaner no-shows, it costs way more than the few dollars saved. We're not the cheapest — we're the ones who actually show up."
💡 Reframe price as risk. The cost of unreliability dwarfs the price gap (loss aversion).

❝ "I'm not interested." ❞
"Totally fair, and thanks for being straight with me. Mind if I ask — is it the timing, or just not a priority right now?"
💡 Accept the no gracefully (that builds trust), then one soft calibrated question. Their answer tells you whether to nurture or move on.
"No problem at all — I'll check back in a few months, since things change. Have a great one!"
💡 Leaving warm keeps the door open. Today's "no" is often next quarter's "yes."

❝ "I'll think about it." ❞
"Absolutely. What's the one thing you'd need to see to feel good about moving forward?"
💡 Surfaces the REAL hesitation so you can handle it now, instead of losing them to silence."""),

        ('closing', '✅ The Close — Booking the Walkthrough / Quote', 0, """[Assume the yes. Offer a choice of WHEN, not WHETHER.]
"Perfect — does Tuesday morning or Thursday afternoon work better for a quick walkthrough?"
💡 The alternative close: both options are a yes. Choosing between two times is far easier than deciding whether to meet at all.

[Lock it in and shrink the commitment]
"Great, Thursday at 2. It only takes me about 10 minutes, and you'll have a clear quote the same day. What's the best number to text you a reminder?"
💡 Restating how short it is (10 min) melts resistance. Getting their number confirms it AND gives you a follow-up channel.

[Confirm and create a tiny obligation]
"You're down for Thursday at 2 — I'll be the one from [Brand], and I'll text when I'm 10 minutes out. Sound good?"
💡 "Sound good?" earns a final verbal yes. A confirmed micro-commitment sharply cuts no-shows (the consistency principle).

[If they're close but hesitating]
"Just so I'm not overstepping — is there any reason a quick, no-obligation walkthrough wouldn't make sense?"
💡 Inviting the objection surfaces it so you can handle it. "No reason" means you're booked."""),

        ('followup', '🔁 Follow-Up — Call + Text + Email Templates', 0, """[FOLLOW-UP CALL — they got a quote and went quiet]
"Hi [Name], [Your Name] with [Brand]. No pressure at all — I just wanted to make sure the quote made sense and see if any questions came up?"
💡 "No pressure" + a genuinely helpful reason positions you as a consultant, not a chaser. Openness invites honesty.
[If they hesitate, label it:]
"It sounds like now might not be the perfect time — is that fair?"
💡 A label plus a safe-no question. If they reply "actually, it's just the price," you've found the real objection.

[TEXT — short, friendly, ONE ask]
"Hi [Name], it's [Your Name] with [Brand] 😊 Just checking you got the cleaning quote — happy to tweak anything. Want me to pencil you in for a start date?"
💡 One clear ask ("a start date") is easier to answer than "let me know your thoughts." The emoji keeps it human, not corporate.

[EMAIL — subject: "Quick question about your cleaning quote"]
"Hi [Name], following up on the proposal for [Business]. I'd love to earn your business — is there anything holding you back that I can help with? Even a quick 'not yet' helps me know where you stand. — [Your Name], [Brand]"
💡 "Even a quick not-yet helps" gives them a low-effort way to reply, which beats silence and often restarts the whole conversation."""),
    ]

    for cat, title, order, content in scripts:
        if not Script.query.filter_by(title=title).first():
            db.session.add(Script(category=cat, title=title, content=content, sort_order=order))
    BusinessSetting.set('seeded_sales_scripts_v1', '1')
    db.session.commit()


def _seed_scripts():
    """Seed placeholder VA scripts if none exist yet."""
    from models import Script
    if Script.query.count() > 0:
        return

    seeds = [
        # ── Inbound ──────────────────────────────────────────────
        ('inbound', 'Inbound — New Client Inquiry', 0, """Thank you for calling [Business Name], this is [Your Name]. How can I help you today?

[Listen to their need]

Great! We'd love to help with that. Can I get a few quick details?
- Your name?
- Your address and zip code?
- What type of cleaning are you looking for? (Standard, Deep Clean, Move-Out, etc.)
- How many bedrooms and bathrooms?
- Any pets or special instructions?

Based on that, I can give you a quote right now / I'll have our team follow up within [X hours].

Do you have a preferred date and time in mind?

[Book or pencil in]

Perfect! You'll receive a confirmation email shortly. Is there anything else I can help you with?

Thank you for choosing [Business Name] — we look forward to making your home sparkle!"""),

        ('inbound', 'Inbound — Existing Client Reschedule', 1, """Thank you for calling [Business Name], this is [Your Name].

May I get your name and address to pull up your account?

[Look up booking]

Of course! I see your appointment is scheduled for [Date/Time]. Let's find a new time that works for you.

[Offer 2–3 available slots]

I've updated your appointment to [New Date/Time]. You'll receive a confirmation email. Is there anything else I can help with?"""),

        # ── Outbound ─────────────────────────────────────────────
        ('outbound', 'Outbound — New Lead Follow-Up Call', 0, """Hi, may I speak with [Client Name]?

Hi [Client Name]! This is [Your Name] calling from [Business Name]. You recently submitted a request for a cleaning quote on our website — I just wanted to follow up and answer any questions!

[If interested] Wonderful! Let me get a few details to finalize your quote…
[If not a good time] No problem at all! When would be a better time for me to call back?

[Get: service type, beds/baths, preferred dates]

Based on that, your estimate is $[Price]. We have openings on [Date 1] and [Date 2] — which works best for you?

[Book it]

Perfect! You'll receive a confirmation email at [Email]. We're excited to take cleaning off your plate!"""),

        ('outbound', 'Outbound — Inactive Client Win-Back', 1, """Hi, may I speak with [Client Name]?

Hi [Client Name]! This is [Your Name] from [Business Name]. We noticed it's been a while since your last cleaning and we wanted to check in!

We're currently offering [Discount/Promo] for returning clients. Would you be interested in scheduling a fresh clean?

[If yes] Wonderful! Let's get you back on the schedule…
[If not now] Totally understand! Can I send you a reminder in [X weeks]?

Either way, we're so grateful for your past support and hope to serve you again soon!"""),

        # ── Follow-Up ─────────────────────────────────────────────
        ('followup', 'Follow-Up — After Quote (No Response)', 0, """Hi [Client Name], this is [Your Name] from [Business Name].

I'm following up on the cleaning quote we sent over on [Date]. I wanted to make sure you received it and answer any questions you might have!

[Pause — let them respond]

[If questions] Happy to go over that with you right now…
[If not ready] No worries at all! When would be a good time to circle back?
[If ready] Fantastic! Let's get you on the calendar. We have [Date 1] and [Date 2] available…

We'd love to earn your business. Is there anything that would make you feel more comfortable moving forward?"""),

        ('followup', 'Follow-Up — After Completed Job', 1, """Hi [Client Name]! This is [Your Name] from [Business Name].

I'm calling to follow up after your cleaning on [Date]. How did everything go? Were you happy with the results?

[If happy] Wonderful! We'd love to keep the momentum going. Would you like to schedule your next cleaning? We also have a recurring discount if you'd like to set up a regular schedule…
[If issue] I'm so sorry to hear that. Can you tell me more about what happened? We want to make this right for you…

Thank you so much for your feedback — it truly helps us improve. Have a great day!"""),

        # ── Objection Handling ────────────────────────────────────
        ('objection', 'Objection — "It\'s Too Expensive"', 0, """I completely understand — budget is always important!

A few things I'd love to share:
- Our prices include [list what's included: supplies, insurance, background-checked cleaners, etc.]
- We offer a recurring discount of [X%] when you schedule regularly — that brings it down to $[Lower Price] per visit.
- We also have a one-time Deep Clean option to get started, and many clients find it's worth every penny.

Would it help if I customized a package to better fit your budget?"""),

        ('objection', 'Objection — "I Need to Think About It"', 1, """Absolutely, take all the time you need!

Can I ask — is there a specific concern I can help address right now? Sometimes I can clear things up quickly.

[Listen]

That makes total sense. How about I follow up with you on [Specific Date]? And in the meantime, I'll send over some reviews from clients in your area so you can see what others are saying.

Does that sound good?"""),

        ('objection', 'Objection — "I Already Have a Cleaner"', 2, """That\'s great — it sounds like you\'re already taking care of your home!

May I ask — are you fully happy with your current service, or is there anything you wish was different?

[Listen]

I understand. Many of our best clients switched after a one-time trial with us. We\'re not asking you to cancel anyone — just give us one chance to show you the difference.

Would you be open to booking a single Deep Clean so you can compare?"""),

        # ── Closing ───────────────────────────────────────────────
        ('closing', 'Closing — "Pencil You In" Script', 0, """I totally get it if you\'re not 100% ready to commit yet — and that\'s perfectly okay!

What I can do is pencil you in for [Date/Time] so the spot is held for you. There\'s no obligation and no charge until we confirm.

If something changes, just give us a call by [Deadline] and we\'ll adjust. Does that work for you?

[If yes] Perfect! I\'ve got you down for [Date/Time]. I\'ll send a soft hold confirmation to [Email]. We\'ll follow up to confirm closer to the date!"""),

        # ── General Outreach ──────────────────────────────────────
        ('general', 'General — Nextdoor / Facebook DM Outreach', 0, """Hi [Name]! I saw your post looking for a cleaning recommendation and I\'d love to help!

I work with [Business Name] — we\'re a local cleaning company serving [City/Area]. We\'re fully insured, background-checked, and our clients love us!

We\'d love to offer you a free quote. You can book online at [Website] or I can get your info here and have someone reach out.

Would that work for you?"""),
    ]

    for cat, title, order, content in seeds:
        s = Script(category=cat, title=title, sort_order=order, content=content.strip())
        db.session.add(s)
    db.session.commit()


def _seed_email_templates():
    """Add any automated email templates that don't exist yet (idempotent —
    never overwrites templates the owner has customized)."""
    from models import EmailTemplate

    templates = [
        # ── Client Emails ─────────────────────────────────────────
        ('booking_confirmed', 'client', 'Booking Confirmation',
         'Sent immediately when a client books and pays deposit',
         'Your booking is confirmed — {{business_name}}',
         """Hi {{first_name}},

Your ${{deposit}} deposit has been received and your cleaning is confirmed. Here are your booking details:

Service: {{service_type}}
Date: {{booking_date}}
Time: {{booking_time}}
Address: {{address}}

Total price: ${{price}}
Deposit paid: ${{deposit}}
Balance charged the morning of your cleaning: ${{balance}}

The balance is automatically charged to your card the morning of your cleaning. No need to do anything!

Need to reschedule? Call or text us at {{phone}} as soon as possible. Deposits are non-refundable but you may reschedule at any time.

Our team: The cleaners we send are valued members of the {{business_name}} team. To keep things fair for everyone, you agree not to directly hire or pay any {{business_name}} cleaner outside the company for 24 months, except with our written approval and a $2,000 buyout fee. Thank you for understanding!

We can't wait to make your home sparkle!"""),

        ('booking_reminder_24h', 'client', '24-Hour Reminder',
         'Sent automatically the day before every scheduled cleaning',
         "Your cleaning is tomorrow — {{business_name}}",
         """Hi {{first_name}},

Just a friendly reminder that your cleaning is scheduled for tomorrow!

Service: {{service_type}}
Date: {{booking_date}} at {{booking_time}}
Address: {{address}}
Balance charged the morning of your cleaning: ${{balance}}

Please make sure your home is accessible at your scheduled time. If you need to reschedule, please call us at {{phone}} as soon as possible.

See you tomorrow!"""),

        ('balance_collected', 'client', 'Balance Payment Received',
         'Sent after the balance is successfully charged post-cleaning',
         'Payment received — thank you! — {{business_name}}',
         """Hi {{first_name}},

Your balance of ${{balance}} has been successfully collected. Thank you!

We hope your home is looking and feeling amazing. If you have any questions about your payment, please don't hesitate to reach out at {{phone}}.

We'd love to keep your home this clean — ask us about our recurring cleaning discounts!"""),

        # ── Lead Emails ───────────────────────────────────────────
        ('lead_quote', 'lead', 'Instant Quote Email',
         'Sent immediately when a lead submits the quick quote form',
         'Your free cleaning quote — {{business_name}}',
         """Hi {{first_name}},

Thank you for reaching out! Here's your personalized cleaning quote:

Service: {{service_type}}
Bedrooms: {{beds}} | Bathrooms: {{baths}}
Estimated Total: ${{quote_amount}}

Ready to book? All we need is a $50 deposit to hold your spot — the remaining balance is charged to your card the morning of your appointment.

You can book online at {{booking_link}} or call us at {{phone}} and we'll get you scheduled in minutes.

Questions? Just reply to this email — we're happy to help!"""),

        ('lead_drip_day2', 'lead', 'Day 2 Follow-Up',
         'Sent 2 days after the quote if the lead has not booked',
         "Still thinking about it? — {{business_name}}",
         """Hi {{first_name}},

Just following up on your cleaning quote of ${{quote_amount}}!

We'd love to help you reclaim your time. Here's what you get when you book with {{business_name}}:

- Background-checked, insured cleaners
- Satisfaction guaranteed — if something's missed we'll come back
- Only a $50 deposit to hold your spot
- The balance is charged the morning of your cleaning — nothing more due today

Booking takes less than 2 minutes: {{booking_link}}

Or call us at {{phone}} and we'll handle everything for you.

Hope to hear from you soon!"""),

        ('lead_drip_lastchance', 'lead', 'Last Chance Offer',
         'Sent ~5 days after quote — final follow-up with a discount',
         '10% off your first cleaning — {{business_name}}',
         """Hi {{first_name}},

We'd really love to earn your business, so here's a special offer just for you:

10% off your first cleaning!

Your original quote: ${{quote_amount}}
Your discounted price: ${{discounted_price}}

Just mention this email when you book and we'll honor the discount. This offer expires in 48 hours.

Book now: {{booking_link}}
Or call us at {{phone}}.

This is a one-time offer for new clients only. We hope to see you soon!"""),

        # ── Cleaner Emails ────────────────────────────────────────
        ('cleaner_orientation', 'cleaner', 'Orientation & Training Email',
         'Auto-fires when a cleaner signs their work agreement — sends training resources',
         'Next step: complete your orientation — {{business_name}}',
         """Hi {{first_name}},

Your agreement is signed — congratulations, you are officially part of the {{business_name}} team!

Here are your next two steps:

STEP 1 — COMPLETE YOUR ONBOARDING FORMS
Fill in your shirt size, payment preference, and emergency contact:
{{forms_link}}

STEP 2 — COMPLETE YOUR ORIENTATION
Review all of our training materials, quality standards, and cleaning checklists. Once you've finished, click the link below to confirm and let us know you're ready:
{{orientation_link}}

What to review during orientation:
- Our standard cleaning checklist (available in the CRM when you're assigned jobs)
- Quality expectations and client communication guidelines
- Our scheduling and punctuality policy
- Supply usage and safety guidelines

Once you've completed both steps above, you'll be ready for your first assignment!

Questions? Call us at {{phone}} — we're here to help.

Welcome to the family!"""),

        ('cleaner_welcome', 'cleaner', 'Cleaner Welcome Email',
         'Sent when a contractor application is approved and they are hired',
         'Welcome to the {{business_name}} team, {{first_name}}!',
         """Hi {{first_name}},

We are so excited to have you on the {{business_name}} team! Welcome aboard!

Here's what happens next:

1. Sign your work agreement — use the link we emailed you
2. Complete your onboarding forms — payment info, shirt size, emergency contact
3. Complete orientation — review our training materials and quality checklists
4. Your first job — bring your own supplies; we'll stay in close contact and review your photos to make sure everything's perfect. When an experienced team member is available, you may be paired to shadow them first.

Once all steps are complete, you'll be ready for your first solo job!

Questions? Reply to this email or call us at {{phone}}.

We're excited to build something great together."""),

        ('cleaner_job_assigned', 'cleaner', 'Job Assignment Notification',
         'Sent when a cleaner is assigned to a booking',
         'New job assigned — {{booking_date}} — {{business_name}}',
         """Hi {{first_name}},

You have a new job assignment! Here are the details:

Date: {{job_date}}
Service: {{service_type}}
Address: {{job_address}}
Your estimated earnings: ${{earnings}}

See all your jobs, navigate, and open your checklists here:
{{myday_link}}

Please review your work order checklist before arriving. Arrive on time and complete all checklist items before leaving.

Have questions about this job? Call us at {{phone}}.

Thank you — let's make it a great one!"""),

        # ── Owner Alerts ──────────────────────────────────────────
        ('owner_new_booking', 'owner', 'New Booking Alert',
         'Sent to the owner when a new booking and deposit are received',
         'New booking: {{client_name}} — {{business_name}}',
         """New booking received!

Client: {{client_name}}
Amount: ${{amount}}

Log in to the CRM to view full details and assign a cleaner."""),

        ('owner_new_application', 'owner', 'New Cleaner Application',
         'Sent to the owner when someone submits the contractor application form',
         'New cleaner application: {{applicant_name}} — {{business_name}}',
         """A new contractor application has been submitted.

Applicant: {{applicant_name}}

Log in to the CRM → Applications to review and take action."""),

        ('owner_payment_failed', 'owner', 'Payment Failed Alert',
         'Sent to the owner when a balance charge fails',
         'PAYMENT FAILED: {{client_name}} — ${{amount}}',
         """A balance payment failed and requires your attention.

Client: {{client_name}}
Amount: ${{amount}}
Error: {{error}}

Log in to the CRM to resolve this manually."""),

        # ── Lifecycle Automation (new) ────────────────────────────
        ('lead_drip_final', 'lead', 'Final Lead Follow-Up',
         'Last touch ~10 days after the quote if the lead never booked',
         "One last note about your quote — {{business_name}}",
         """Hi {{first_name}},

We don't want to crowd your inbox, so this is our last note about your ${{quote_amount}} cleaning quote.

If now isn't the right time, no worries at all — your quote stays good and we're here whenever you're ready. Booking only takes 2 minutes:

{{booking_link}}

Or just reply with any questions. Thank you for considering {{business_name}}!"""),

        ('booking_morning_of', 'client', 'Morning-Of Reminder',
         'Sent the morning of a scheduled cleaning',
         "See you today, {{first_name}}! — {{business_name}}",
         """Hi {{first_name}},

Just a friendly heads-up that your cleaning is scheduled for today!

Your remaining balance will be charged automatically this morning — nothing you need to do.

Please make sure we can access your home at your scheduled time. Questions? Call or text us at {{phone}}.

See you soon!"""),

        ('review_nudge', 'client', 'Review Reminder',
         'Sent ~3 days after a cleaning if the customer has not rated yet',
         "How was your cleaning, {{first_name}}?",
         """Hi {{first_name}},

We'd still love to hear how your recent cleaning went — it only takes 5 seconds:

{{rate_link}}

Your feedback helps us improve and helps other families find us. Thank you!"""),

        ('recurring_upsell', 'client', 'Recurring Upsell',
         'Sent ~2 days after a one-time cleaning — invites them to go recurring',
         "Loved your clean? Keep it that way & save — {{business_name}}",
         """Hi {{first_name}},

We hope your home is still sparkling!

Most of our happy customers switch to regular cleanings so they never have to think about it again — and they save on every single visit:

- Monthly — ${{monthly_price}} (save 5%)
- Bi-Weekly — ${{biweekly_price}} (save 10%)
- Weekly — ${{weekly_price}} (save 15%)

Lock in your spot and your discount here:

{{booking_link}}

Questions? Just reply or call {{phone}}. We'd love to keep your home fresh year-round!"""),

        ('recurring_upsell_nudge', 'client', 'Recurring Upsell Reminder',
         'Second nudge ~9 days later if they have not rebooked',
         "Still time to save on regular cleanings, {{first_name}}",
         """Hi {{first_name}},

Just circling back — your recurring cleaning discount is still available:

- Monthly ${{monthly_price}} · Bi-Weekly ${{biweekly_price}} · Weekly ${{weekly_price}}

Set it and forget it: a consistently clean home with no big deep-clean surprises.

{{booking_link}}

Reply anytime with questions!"""),

        ('winback', 'client', 'Win-Back — We Miss You',
         'Sent to a past customer who has not booked in ~50 days',
         "We miss you, {{first_name}}! Here's 10% off — {{business_name}}",
         """Hi {{first_name}},

It's been a little while since your last cleaning with {{business_name}}, and we'd love to welcome you back!

As a thank-you for being a valued customer, here's 10% off your next cleaning — just use code {{discount_code}} at checkout:

{{booking_link}}

We'd love to make your home shine again. See you soon!"""),

        ('owner_low_rating', 'owner', 'Low Rating Alert',
         'Alerts the owner when a customer rates below 4 stars',
         "Low rating: {{client_name}} — {{stars}} stars",
         """{{client_name}} just left a {{stars}}-star rating for their cleaning.

Comment: {{comment}}

Please reach out to make it right as soon as possible. Log in to the CRM for details."""),

        ('cleaner_schedule_reminder', 'cleaner', 'Day-Before Schedule Reminder',
         'Texts/emails a cleaner the day before, reminding them of their jobs tomorrow',
         "Reminder: you have {{job_count}} job(s) tomorrow — {{business_name}}",
         """Hi {{first_name}},

Quick reminder — you have {{job_count}} job(s) scheduled for tomorrow ({{tomorrow_date}}).

See your full schedule, addresses, navigation, and checklists here:
{{myday_link}}

Please arrive on time and bring your supplies. Questions? Reply or call {{phone}}.

Thanks — let's make it a great day!"""),

        ('contractor_onboarding_reminder', 'cleaner', 'Onboarding Reminder',
         'Nudges a new hire every ~2 days until they finish onboarding (up to 3 times)',
         "Finish setting up your {{business_name}} account, {{first_name}}",
         """Hi {{first_name}},

Welcome again to the team! We noticed you haven't finished setting up your account yet — it only takes a few minutes, and it's the last step before you can start getting jobs.

Tap here to finish:
{{onboarding_link}}

You'll sign your work agreement, set up how you get paid, pick your start date, and review your training guide. Any questions, just reply to this email — we're happy to help!

We're excited to have you on the team!"""),

        ('contractor_insurance_reminder', 'cleaner', 'Insurance Reminder',
         'Friendly nudge to a contractor to get their own insurance, after a few completed cleanings',
         "A quick tip to protect yourself, {{first_name}}",
         """Hi {{first_name}},

You've completed a few cleanings with {{business_name}} now — congratulations, and thank you for your great work!

Now that you're earning, this is a great time to protect yourself with your own general liability insurance. As an independent contractor, it covers you if anything ever comes up on a job — and it's usually very affordable (often around $30–$50 per month).

A couple of popular options for cleaners:
- Next Insurance (nextinsurance.com)
- Thimble (thimble.com)

It only takes a few minutes to get a quote. Any questions, just reply to this email — we're happy to point you in the right direction!

Thanks again for being part of the team."""),
    ]

    added = 0
    for trigger, cat, name, desc, subject, body in templates:
        if EmailTemplate.query.filter_by(trigger=trigger).first():
            continue  # already exists — keep the owner's version
        db.session.add(EmailTemplate(trigger=trigger, category=cat, name=name,
                       description=desc, subject=subject, body=body.strip()))
        added += 1
    if added:
        db.session.commit()


def _seed_sops():
    """Add any missing SOPs (idempotent — never overwrites the owner's edits)."""
    from models import SOP

    seeds = [
        # ── Cleaning Procedures ───────────────────────────────────
        ('cleaning', 'Standard Cleaning — Room-by-Room SOP', 0, """STANDARD CLEANING PROCEDURE

BEFORE YOU START
1. Review the client's booking notes and any special instructions in the work order.
2. Do a quick walk-through of the home before touching anything. Note any damage or unusual mess — photo it.
3. Set up your supplies at the front door. Never leave products in a client's home.

KITCHEN
1. Clear and wipe all countertops (remove items, clean under them, replace).
2. Clean stovetop — remove grates, scrub burners, wipe down surface.
3. Wipe exterior of all appliances (microwave, fridge, dishwasher, oven).
4. Clean interior of microwave.
5. Scrub sink — disinfect, shine faucet.
6. Wipe cabinet fronts.
7. Clean inside of trash can if needed.
8. Sweep and mop floor last.

BATHROOMS (do all bathrooms before moving on)
1. Apply toilet bowl cleaner — let sit while you clean the rest.
2. Wipe mirror and glass surfaces.
3. Clean and disinfect sink and faucet.
4. Wipe vanity, countertop, soap dish.
5. Scrub tub/shower — walls, door/curtain, fixtures.
6. Scrub and disinfect toilet (bowl, under rim, seat, lid, base, behind base).
7. Wipe baseboards and door.
8. Sweep and mop floor.

BEDROOMS
1. Make bed with hotel-style tuck.
2. Dust all surfaces — nightstands, dressers, shelves (move items, dust under).
3. Wipe light switches and door handles.
4. Vacuum floors including under bed and in closet doorway.

LIVING AREAS
1. Dust all surfaces, shelves, entertainment units.
2. Wipe light switches, remotes staging, door handles.
3. Vacuum sofa cushions and under cushions.
4. Vacuum carpet or sweep/mop hardwood.

FINISH
1. Do a final walk-through using your checklist.
2. Replace everything exactly as it was.
3. Take before/after photos if required.
4. Lock up per client's instructions.
5. Mark job complete in the CRM."""),

        ('cleaning', 'Deep Clean — Additional Steps SOP', 1, """DEEP CLEAN — ADDITIONAL STEPS
(Perform all Standard Cleaning steps PLUS the following)

KITCHEN DEEP EXTRAS
1. Clean inside of oven (use oven cleaner, allow to soak per instructions).
2. Clean inside of refrigerator — remove all items, wipe all shelves and drawers.
3. Clean range hood filter — soak in degreaser if needed.
4. Degrease backsplash thoroughly.
5. Wipe interior cabinet shelves (if client requested).

BATHROOM DEEP EXTRAS
1. Scrub grout lines with grout brush.
2. Remove and clean soap scum from glass doors with razor blade scraper if needed.
3. Disinfect all handles, knobs, and light switches with hospital-grade disinfectant.

WHOLE HOME DEEP EXTRAS
1. Wipe all baseboards throughout the home.
2. Wipe all door frames and light switch plates.
3. Clean all window sills and tracks.
4. Dust ceiling fans and light fixtures.
5. Vacuum upholstery and under cushions on all furniture.
6. Wipe all interior door surfaces.

CHECKLIST SIGN-OFF
Complete and photograph the deep clean checklist before leaving."""),

        ('cleaning', 'Post-Construction Cleaning SOP', 2, """POST-CONSTRUCTION CLEANING PROCEDURE

WARNING: Post-construction jobs require extra time and supplies. Always confirm scope and pricing before starting.

SUPPLIES NEEDED
- Heavy-duty vacuum (NOT a standard residential vacuum — debris will damage it)
- Microfiber cloths (many — replace frequently, do not re-use on different surfaces)
- Painter's tape scraper / razor blade
- Construction-grade all-purpose cleaner
- Glass cleaner
- Grout brush
- Floor mop and bucket (dedicated for construction jobs)

PHASE 1 — ROUGH CLEAN
1. Remove all large debris: wood scraps, plastic wrap, cardboard, tape.
2. Vacuum all surfaces — walls, windowsills, cabinets (inside and out), counters.
3. Sweep all floors to remove construction dust and debris.
4. Remove paint drips and adhesive from hard surfaces using scraper (gentle, test first).

PHASE 2 — DETAIL CLEAN
1. Wipe all surfaces with damp microfiber — walls, cabinets, shelves, doors.
2. Clean all windows inside (construction dust on glass): spray, wipe, buff streak-free.
3. Clean all window tracks and sills — use brush to remove packed-in dust.
4. Clean all light fixtures and ceiling fans.
5. Clean all outlets and switch plates.
6. Scrub bathrooms completely — grout, fixtures, tubs, sinks.
7. Clean kitchen — cabinets, counters, appliances.

PHASE 3 — FLOOR FINISH
1. Vacuum all floors a second time.
2. Mop hard floors with appropriate cleaner.
3. Spot-clean carpet if applicable (note: full carpet cleaning may require a specialist).

FINAL CHECK
1. Walk room by room with your checklist.
2. Look up — check ceilings and ceiling fans.
3. Look down — check baseboards and floor edges.
4. Photograph completed areas.
5. Mark complete in CRM and note any items outside scope."""),

        ('cleaning', 'Move-Out / Move-In Cleaning SOP', 3, """MOVE-OUT / MOVE-IN CLEANING PROCEDURE

NOTE: These jobs require the home to be fully empty of furniture. If items remain, note it and check with client before proceeding.

PRIORITY ORDER (top to bottom, back to front of home)
1. Start in the furthest room and work toward the exit.
2. Always clean top-to-bottom within each room (ceilings/fans → walls → counters → floors).

EVERY ROOM
1. Wipe all ceiling fans and light fixtures.
2. Wipe all walls — spot-clean scuffs and marks.
3. Clean all windows (inside) and window sills/tracks.
4. Wipe all baseboards.
5. Wipe all door frames, doors, and handles.
6. Vacuum then mop all floors.

KITCHEN (same as deep clean extras)
- Inside of oven, fridge, all cabinets and drawers (inside and out).
- Degrease hood, backsplash, all surfaces.

BATHROOMS
- Scrub everything — grout, fixtures, tub, toilet, vanity.
- Check under the sink for residue or staining.

CLOSETS
- Wipe shelves and rods.
- Vacuum or sweep floor.
- Check for leftover items.

FINAL
1. Complete move-out checklist.
2. Photograph every room.
3. Note any pre-existing damage in writing."""),

        # ── Commercial ────────────────────────────────────────────
        ('commercial', 'Commercial Walkthrough SOP', 0, """COMMERCIAL PROPERTY WALKTHROUGH SOP

PURPOSE: Use this before quoting OR before starting a new commercial account to document the property and set client expectations.

BEFORE THE WALKTHROUGH
1. Confirm appointment with decision-maker (property manager or business owner).
2. Bring: measuring tape, notepad, phone (camera), quote form.
3. Review any notes from the initial inquiry.

DURING THE WALKTHROUGH
DOCUMENT THE FOLLOWING:
- Total square footage (ask or estimate room by room)
- Number of restrooms and their condition
- Flooring types throughout (carpet, tile, hardwood, etc.)
- Break room / kitchen details
- Number of offices, conference rooms, common areas
- Special areas: server rooms, medical areas, high-traffic zones
- Current cleaning frequency and pain points ("what's not getting done?")
- Access information: key, code, after-hours or before-hours schedule
- Any special cleaning products required (e.g., no fragrance, hospital-grade disinfectant)

PHOTOS TO TAKE
- Entrance / lobby
- Each restroom
- Kitchen/break room
- Any problem areas the client points out

AFTER THE WALKTHROUGH
1. Note scope of work and any extra services needed.
2. Build the commercial quote in the CRM within 24 hours.
3. Send quote for review using the commercial quote link.
4. Follow up within 3 business days if no response."""),

        ('commercial', 'Commercial Restroom Cleaning SOP', 1, """COMMERCIAL RESTROOM CLEANING SOP

FREQUENCY: Perform at every scheduled cleaning visit.
TIME ESTIMATE: 10–15 min per restroom depending on size.

SUPPLIES
- Commercial-grade disinfectant (EPA-registered)
- Toilet brush
- Microfiber cloths (color-coded: red = toilet only, blue = everything else)
- Mop and bucket (dedicated to restrooms)
- Paper products for restocking

PROCEDURE
1. Restock paper products first (toilet paper, paper towels, soap) — note shortages.
2. Apply toilet bowl cleaner — let sit.
3. Spray and wipe all dispensers, door handles, light switches.
4. Clean mirrors — spray, wipe, buff.
5. Clean and disinfect sinks and faucets.
6. Wipe vanity surfaces and soap dispensers.
7. Clean and disinfect toilet — bowl (scrub under rim), seat both sides, lid, tank, base.
8. Wipe partition walls and door handles (inside stalls).
9. Empty trash, replace liner.
10. Sweep then mop floor using disinfectant solution.

FINAL CHECK
- No streaks on mirrors.
- Toilet paper installed correctly (over the top).
- Floor dry before leaving or wet floor sign in place."""),

        # ── Lead & Phone Handling ─────────────────────────────────
        ('leads', 'Lead Phone Call SOP', 0, """LEAD PHONE CALL — STANDARD OPERATING PROCEDURE

PURPOSE: Respond to every new lead within 2 hours of submission. Speed = conversion. The first company to call usually gets the job.

STEP 1 — BEFORE YOU CALL
1. Open the lead in the CRM. Read all submitted details.
2. Note their service type, beds/baths, and any notes.
3. Have the pricing guide open so you can quote on the spot.
4. Call from the business number (not a personal cell).

STEP 2 — THE CALL
- Use the VA Inbound or Outbound Call Script from the Scripts Library.
- Goal: give a quote AND secure a booking date in one call.
- If no answer: leave a voicemail (see voicemail script), send a follow-up text.

STEP 3 — VOICEMAIL (if no answer)
"Hi, this message is for [Name]. This is [Your Name] calling from [Business Name]. You recently requested a cleaning quote and I'd love to help! I'll try you again shortly, or feel free to call us back at [Phone]. We look forward to hearing from you!"

STEP 4 — TEXT FOLLOW-UP (immediately after voicemail)
"Hi [Name]! This is [Business Name] following up on your cleaning quote request. We'd love to help! Reply here or call [Phone] to get scheduled. 😊"

STEP 5 — AFTER THE CALL
1. Update the lead status in the CRM (Contacted / Converted / Lost).
2. Add a note with call summary: answered/voicemail, quoted price, next step.
3. If booked: create the booking in CRM immediately.
4. If not booked: schedule a follow-up reminder for 24–48 hours.

FOLLOW-UP CADENCE (if no response)
- Day 0: Call + voicemail + text
- Day 1: Call again (different time of day)
- Day 3: Final follow-up call or email
- Day 7: Mark as Lost if still no response"""),

        ('leads', 'New Inquiry Email Response SOP', 1, """NEW INQUIRY EMAIL RESPONSE SOP

PURPOSE: Respond to email inquiries within 1 hour during business hours.

STEP 1 — READ THE INQUIRY
Note: service type, urgency, location, any questions asked.

STEP 2 — SEND A RESPONSE WITHIN 1 HOUR
Use this template as a starting point:

---
Subject: Re: Your Cleaning Quote Request — [Business Name]

Hi [Name],

Thank you for reaching out to [Business Name]! We'd love to help keep your home spotless.

Based on what you shared, here's a quick estimate:
[Service Type] — [Beds/Baths] — $[Price Range]

To confirm your exact quote, I have a couple of quick questions:
1. [Any clarifying question]
2. Do you have any preferred dates in mind?

You can also book directly at [Website] or reply here and I'll get everything set up for you!

Looking forward to hearing from you.

[Your Name]
[Business Name] | [Phone] | [Website]
---

STEP 3 — LOG IN CRM
Update the lead status to "Contacted" and add a note.

STEP 4 — FOLLOW UP
If no reply within 24 hours, call the phone number on the inquiry."""),

        # ── Quality Control ───────────────────────────────────────
        ('quality', 'Post-Job Quality Check SOP', 0, """POST-JOB QUALITY CHECK SOP

PURPOSE: Ensure every job meets [Business Name] standards before the cleaner leaves.

WHO DOES THIS: The cleaner performs a self-check before leaving. A supervisor spot-checks remotely using photos.

STEP 1 — CLEANER SELF-CHECK (before leaving the property)
Go room by room and verify:
□ All surfaces dusted and wiped
□ Mirrors streak-free
□ Floors vacuumed and mopped (no footprints on mopped floors)
□ Beds made hotel-style
□ Toilets clean inside, outside, and behind
□ Sinks and faucets shining
□ No products or cloths left behind
□ Client's items returned to original positions
□ Trash emptied and new liner in place
□ Home locked up per instructions

STEP 2 — PHOTO DOCUMENTATION
Take photos of:
- Each bathroom (toilet, sink, mirror)
- Kitchen (counters, sink, stovetop)
- Each bedroom (made bed)
- Living area (vacuumed floors/carpet)
Upload to the work order in the CRM.

STEP 3 — MARK COMPLETE
Mark the job complete in the CRM work order checklist.

STEP 4 — CLIENT RATING
The CRM will automatically send a rating request to the client. If the client rates below 4 stars, flag it for manager review immediately."""),

        ('quality', 'Client Complaint Resolution SOP', 1, """CLIENT COMPLAINT RESOLUTION SOP

PURPOSE: Handle complaints quickly and professionally to protect our reputation and retain the client.

RULE: Never argue. Never make excuses. Always apologize first.

STEP 1 — RECEIVE THE COMPLAINT
- If by phone: listen fully before responding. Do not interrupt.
- If by email/text: respond within 1 hour.
- Log the complaint in the CRM under the client's booking.

STEP 2 — ACKNOWLEDGE AND APOLOGIZE
Script: "I'm so sorry to hear that, [Name]. That is absolutely not the experience we want for you. I want to make this right."

STEP 3 — ASSESS THE SITUATION
Ask: "Can you tell me specifically what was missed or what happened?"
Take notes. Do not dismiss or minimize.

STEP 4 — OFFER A SOLUTION
Options (use judgment based on severity):
- Minor issue: "I'd love to send someone back to touch up that area at no charge."
- Major issue: "I want to offer you a complimentary re-clean on [Date]."
- Extreme issue: Escalate to owner immediately.

STEP 5 — FOLLOW THROUGH
1. Schedule the re-clean or callback immediately — don't promise without confirming.
2. Assign the same cleaner if possible (they know the home) OR a senior cleaner.
3. After the resolution, follow up with the client to confirm they're satisfied.
4. Log resolution in CRM notes.

STEP 6 — INTERNAL REVIEW
1. Debrief with the cleaner privately — what happened?
2. Identify if it's a training issue, supplies issue, or one-off.
3. Update training or SOPs if needed."""),

        # ── Operations ────────────────────────────────────────────
        ('operations', 'New Client Setup SOP', 0, """NEW CLIENT SETUP SOP

PURPOSE: Ensure every new client is properly set up in the system before their first cleaning.

STEP 1 — AFTER BOOKING IS CONFIRMED
1. Verify all booking details are complete in the CRM: name, address, service type, date, time, price.
2. Confirm deposit has been collected (Stripe).
3. Assign a cleaner based on availability and the client's area.

STEP 2 — SEND CONFIRMATION EMAIL
The CRM sends this automatically. Verify it went out. If not, send manually.

STEP 3 — ADD CLIENT NOTES
In the client's profile, note:
- Gate codes, alarm codes, parking instructions
- Pets (type, name, location during cleaning)
- Areas to avoid
- Any allergies to cleaning products
- Preferred products or methods
- Key pickup/lockbox instructions

STEP 4 — 24-HOUR REMINDER
The CRM sends this automatically the day before. Verify it's scheduled.

STEP 5 — DAY-OF PREP
1. Confirm the assigned cleaner has the work order.
2. Text the cleaner the client's address and any special notes.
3. Text the client: "We're looking forward to your cleaning tomorrow! Your cleaner [Name] will arrive between [Time Window]."

STEP 6 — AFTER THE CLEANING
1. Mark complete in CRM.
2. CRM auto-charges the balance and sends a rating request.
3. If the client is on recurring service, confirm the next appointment is scheduled."""),

        # ── Cleaning Procedures (added layer) ─────────────────────
        ('cleaning', 'Products & Surfaces — What to Use Where', 4, """PRODUCTS & SURFACES — WHAT TO USE WHERE

Using the wrong product can damage a client's home and cost us the account. When in doubt, use the gentlest option and test a hidden spot first.

GENERAL RULE
- Start with the mildest cleaner that works. Escalate only if needed.
- Never mix products (especially bleach + ammonia — it creates toxic fumes).
- Always read the client's surface before spraying.

BY SURFACE
- Granite / marble / natural stone: pH-neutral stone cleaner ONLY. Never vinegar, lemon, or acidic/abrasive cleaners — they etch and dull stone.
- Quartz / laminate counters: all-purpose cleaner, soft cloth.
- Stainless steel: stainless cleaner or a little dish soap + water; wipe WITH the grain; dry to avoid streaks.
- Wood (floors, cabinets, furniture): wood-safe cleaner, barely-damp cloth. Never soak wood.
- Glass / mirrors: glass cleaner + flat-weave microfiber; buff dry for no streaks.
- Tubs / tile / grout: non-scratch bathroom cleaner; soft scrub for grout. No steel wool.
- Toilets: toilet bowl cleaner inside; disinfectant outside.
- Electronics / TVs: dry or slightly damp microfiber only — never spray directly.

IF YOU'RE UNSURE
Text the office a photo before using anything you're not sure about. Protecting the client's home always comes first."""),

        ('cleaning', 'Color-Coded Cloths & Cross-Contamination', 5, """COLOR-CODED CLOTHS — PREVENT CROSS-CONTAMINATION

Using the same cloth in the bathroom and then the kitchen spreads germs. We keep colors separated so every home is truly sanitary.

THE SYSTEM (suggested)
- BLUE — glass, mirrors, windows
- GREEN — kitchen surfaces & counters
- YELLOW — general dusting, living areas, bedrooms
- RED — bathrooms & toilets ONLY

RULES
1. A red (bathroom) cloth NEVER touches a kitchen or living surface. Ever.
2. Use a fresh cloth per home — never carry a used cloth from one client to the next.
3. When a cloth is visibly dirty, swap it for a clean one.
4. Wash cloths after every day: hot water, no fabric softener (it ruins microfiber).
5. Keep a "dirty cloth" bag separate from your clean stack in your caddy.

Same idea for sponges and scrubbers — bathroom tools stay in the bathroom."""),

        ('cleaning', 'Arrival & In-Home Etiquette', 6, """ARRIVAL & IN-HOME ETIQUETTE

You represent the company the moment you pull up. First impressions win reviews and repeat clients.

ARRIVAL
1. Arrive on time (aim 5 minutes early). If you're running late, message the office immediately.
2. Park considerately — never block driveways or neighbors.
3. Knock/ring; announce yourself warmly: "Hi, I'm ___ with [Your Company]!"
4. If entering with a code/key, follow the exact instructions in the work order.

INSIDE THE HOME
1. Wear clean, professional attire. Shoe covers or remove shoes if requested.
2. Do a quick walkthrough with the client (if home) to confirm priorities.
3. Note and photo any pre-existing damage before you start.
4. Keep your phone on silent. No personal calls in a client's home.
5. Respect privacy — never open drawers, closets, or personal items unless the job requires it.
6. If you find cash, jewelry, or valuables out, do not touch — clean around them and note it.

PETS & PEOPLE
- Be friendly but keep doors closed so pets don't escape.
- If a client is working from home, keep noise down and stay out of their space."""),

        ('cleaning', 'Kitchen — Detailed Deep Clean', 7, """KITCHEN — DETAILED DEEP CLEAN

Work top to bottom so crumbs and dust fall to the floor you clean last.

TOP DOWN
1. Dust the top of cabinets, hood, and any high shelves.
2. Wipe cabinet fronts and handles (grease loves handles).
3. Backsplash — degrease and wipe.

APPLIANCES
4. Microwave: steam a bowl of water 2 min, then wipe inside; clean door and handle.
5. Stovetop: remove grates/knobs, degrease, scrub, dry, replace.
6. Oven (if included): apply oven cleaner per instructions; wipe thoroughly.
7. Fridge exterior + handles; interior only if booked.
8. Dishwasher front, small appliances (toaster, coffee maker) wiped.

COUNTERS & SINK
9. Clear counters, clean surface (right product for the material), replace items neatly.
10. Sink: scrub basin, disinfect, clean drain area, SHINE the faucet — a gleaming faucet says "clean."

FINISH
11. Empty trash, wipe can, fresh liner.
12. Sweep, then mop the floor last (get edges and under the toe-kick)."""),

        ('cleaning', 'Bathroom — Detailed Deep Clean', 8, """BATHROOM — DETAILED DEEP CLEAN

Bathrooms make or break a review. Be thorough and disinfect.

START
1. Apply toilet bowl cleaner and let it sit while you work elsewhere.
2. Spray tub/shower and let the cleaner dwell (dwell time = less scrubbing).

TOP DOWN
3. Dust vents, light fixtures, and top of mirror/cabinets.
4. Mirror and glass — buff streak-free.
5. Counter, sink, faucet — clean and disinfect; shine the faucet.
6. Wipe cabinet fronts and handles.

TUB / SHOWER
7. Scrub walls, door/track or curtain rod, and floor of the tub.
8. Remove soap scum and hard-water spots; rinse; squeegee glass.
9. Polish fixtures.

TOILET (use RED tools only)
10. Scrub bowl (including under the rim), then flush.
11. Disinfect seat (both sides), lid, tank, handle, base, and behind the base — the spot everyone forgets.

FINISH
12. Wipe baseboards and door.
13. Empty trash, fresh liner.
14. Fold/replace towels neatly. Sweep and mop last."""),

        ('cleaning', 'Floors — Vacuuming & Mopping by Type', 9, """FLOORS — VACUUM & MOP BY TYPE

Floors are the last thing you clean in every room.

VACUUMING
- Carpet: slow, overlapping passes; go both directions in high-traffic areas. Get edges and under furniture you can reach.
- Hard floors: vacuum or sweep first to remove grit that scratches.
- Stairs: top to bottom; don't skip the edges.

MOPPING (match the floor)
- Hardwood / laminate: barely-damp microfiber mop + wood-safe cleaner. NEVER soak — standing water warps wood.
- Tile: standard mop + all-purpose or tile cleaner; get grout lines.
- Luxury vinyl (LVP): damp mop, pH-neutral cleaner.
- Natural stone: stone-safe, pH-neutral cleaner only.

TECHNIQUE
1. Work from the far corner toward the exit so you don't walk on wet floor.
2. Change mop water when it's dirty — dirty water = streaky floors.
3. Dry high-traffic/entry spots so no one slips."""),

        ('cleaning', 'Homes with Pets', 10, """HOMES WITH PETS

Many of our clients have pets. Handle them safely and leave the home fur-free.

SAFETY FIRST
1. Confirm in the work order if pets are present and any instructions.
2. Keep exterior doors closed at all times so pets can't slip out.
3. Never let a pet out of a room the owner has closed.
4. If a pet seems aggressive or anxious, don't force it — message the office.

CLEANING FOR PET HOMES
5. Pet hair: rubber broom, vacuum with pet attachment, or a slightly damp rubber glove to lift hair off upholstery.
6. Lint-roll or vacuum furniture where pets rest.
7. Watch for accidents — clean and disinfect, and note it for the office.
8. Empty vacuum more often (pet hair fills bags/bins fast).
9. Avoid strong chemical smells where pets eat/sleep when possible.

Leave no trace of fur — that "wow, no more dog hair!" moment earns 5-star reviews."""),

        # ── Quality Control (added layer) ─────────────────────────
        ('quality', 'Before & After Photos', 2, """BEFORE & AFTER PHOTOS — HOW & WHY

Photos protect you, prove your great work, and win us reviews. Take them every job.

WHY IT MATTERS
- Protects YOU: proof of the home's condition before you started (pre-existing damage).
- Proves quality: shows the transformation.
- Marketing: great afters (with permission) become social posts that bring in clients.

HOW TO DO IT
1. BEFORE you touch a room, take a quick photo of each main area (kitchen, each bathroom, living room).
2. AFTER you finish, take the same angle so the difference is clear.
3. Good light, steady shot, no people or personal info (no mail, photos, documents) in frame.
4. Upload/attach them where the office asks, or text them in.

PRIVACY
- Never post a client's home publicly without the office's OK.
- Never photograph valuables, safes, or anything personal."""),

        ('quality', 'The Final Walkthrough', 3, """THE FINAL WALKTHROUGH

Before you leave, do this every single time. It's the difference between "clean" and "WOW."

STAND IN EACH DOORWAY AND ASK: "Would I say WOW?"

CHECK
1. Kitchen: counters clear and shining, sink and faucet gleaming, floor clean to the edges, trash emptied.
2. Bathrooms: no streaks on mirror/glass, toilet spotless (including base), fresh towels, floor mopped.
3. Bedrooms/living: beds made, surfaces dusted, pillows straight, floors done, nothing out of place.
4. Whole home: baseboards, switches, and handles wiped; no missed corners.
5. Smell: the home should smell fresh and clean, not chemical-heavy.

BEFORE LOCKING UP
6. Turn off lights you turned on; return thermostat/blinds as found.
7. Collect ALL your supplies and trash — leave nothing behind.
8. Lock up exactly per the work order and confirm the door is secured.
9. Take your AFTER photos.
10. Mark the job complete in your checklist."""),

        # ── Commercial (added layer) ──────────────────────────────
        ('commercial', 'Airbnb / Vacation Rental Turnover', 2, """AIRBNB / VACATION RENTAL TURNOVER SOP

Turnovers are time-sensitive — the next guest may check in the same day. Speed AND hotel-level detail both matter.

BEFORE YOU START
1. Confirm checkout is complete and note the checkout/check-in times in the work order.
2. Report any damage, missing items, or items left behind immediately with photos.

RESET THE SPACE (hotel standard)
3. Strip and remake all beds with fresh linens; hospital corners, crisp presentation.
4. Fresh towels folded/staged neatly (fan or roll per the host's style).
5. Restock supplies the host provides: toilet paper, paper towels, soap, coffee, etc.
6. Empty ALL trash; fresh liners.

CLEAN
7. Kitchen: wash/put away or load dishes, wipe all surfaces and appliances, check the fridge for leftovers, sink shining.
8. Bathrooms: full clean + disinfect, streak-free mirrors, restock.
9. Living/bedrooms: dust, straighten, vacuum/mop.
10. Check under beds and couches for guest items.

FINISH
11. Stage the space to look photo-ready (like the listing photos).
12. Take after photos for the host.
13. Lock up per instructions and confirm secured."""),
    ]

    added = 0
    for cat, title, order, content in seeds:
        if SOP.query.filter_by(category=cat, title=title).first():
            continue  # already exists — keep the owner's version
        db.session.add(SOP(category=cat, title=title, sort_order=order, content=content.strip()))
        added += 1
    if added:
        db.session.commit()


def _seed_pricing_defaults():
    """
    Write pricing matrix into PricingSetting DB.
    Uses a version key so price updates in code push through to the live DB
    exactly once — after that, admin edits persist across restarts.
    Bump PRICING_VERSION whenever the default matrix changes.
    """
    PRICING_VERSION = 3  # increment this when defaults change (v3: raised matrix, 3/2 std $225→$260)

    try:
        from models import PricingSetting
        from pricing import (
            PRICE_MATRIX_DEFAULTS, HOURS_MATRIX_DEFAULTS,
            SERVICE_MULTIPLIERS_DEFAULTS, EXTRAS,
            DEPOSIT_AMOUNT, CONTRACTOR_SPLIT_PCT, SQFT_SURCHARGE_RATE,
        )

        current_version = int(PricingSetting.get('pricing_version') or 0)
        if current_version >= PRICING_VERSION:
            return  # already at this version — respect any admin overrides

        seeds = {}
        for (beds, baths), price in PRICE_MATRIX_DEFAULTS.items():
            seeds[f'std_price_{beds}_{baths}'] = price
        for (beds, baths), hours in HOURS_MATRIX_DEFAULTS.items():
            seeds[f'std_hours_{beds}_{baths}'] = hours
        for svc, mult in SERVICE_MULTIPLIERS_DEFAULTS.items():
            seeds[f'{svc}_multiplier'] = mult
        for name, price in EXTRAS.items():
            key = f"extra_{name.lower().replace(' ', '_')}"
            seeds[key] = price
        seeds['deposit_amount']   = DEPOSIT_AMOUNT
        seeds['contractor_split'] = CONTRACTOR_SPLIT_PCT
        seeds['sqft_surcharge']   = SQFT_SURCHARGE_RATE

        for key, value in seeds.items():
            PricingSetting.set(key, str(value))
        PricingSetting.set('pricing_version', str(PRICING_VERSION))
        db.session.commit()
    except Exception:
        pass


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8001)), debug=True)

# Redeploy trigger: ensure clean boot runs _migrate_db (adds access_notes + recent columns to prod)
