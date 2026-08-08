"""A second cleaning company must be able to run this CRM without a trace of the
first one showing through — not in a page, not in a link, not in an email."""
import os, sys, tempfile, re
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/wl.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['CRM_BASE'] = 'https://sparkle-pros.up.railway.app'
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_fake'
for stale in ('FROM_EMAIL', 'OWNER_EMAIL', 'NOTIFY_EMAIL', 'BUSINESS_NAME'):
    os.environ.pop(stale, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda *a, **k: (SENT.append((a, k)), (True, 'ok'))[1]

from app import create_app
from extensions import db
from models import Booking, BusinessSetting, Staff
import branding, brands

app = create_app()

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

BRAND_WORDS = ('Dazzle', 'dazzleandshinemaids', 'dazzle-shine-crm-production',
               '999-0194', 'L & M Commercial', 'commercialcleanersorlando')

def clean(text, where):
    hits = [w for w in BRAND_WORDS if w in text]
    check(not hits, f'{where}: no trace of the other company {hits if hits else ""}')

with app.app_context():
    db.create_all()

    print('\n1. A brand-new instance does not inherit anyone else\'s identity')
    check(BusinessSetting.get('brand_settings_migrated') == '',
          'the Dazzle migration did NOT run on a fresh database')
    check(BusinessSetting.get('commercial_name') == '',
          "and L & M's details were not seeded in")
    check(branding.biz_name() == 'Your Cleaning Company',
          f'unset business name reads as a neutral placeholder, not a real business')
    from blueprints.ratings import review_link
    check(review_link() == '',
          'the Google review link is empty — a happy customer cannot be sent to review the wrong company')

    print('\n2. The new owner fills in her own details')
    for k, v in [('business_name', 'Sparkle Pros Cleaning'), ('phone', '(407) 555-0142'),
                 ('email', 'hello@sparklepros.com'), ('city', 'Tampa'), ('state', 'FL'),
                 ('website', 'sparklepros.com')]:
        BusinessSetting.set(k, v)
    db.session.commit()
    check(branding.biz_name() == 'Sparkle Pros Cleaning', 'the CRM now answers to her name')
    check(branding.phone() == '(407) 555-0142', 'her phone number')
    check(branding.owner_email() == 'hello@sparklepros.com', 'her inbox gets the alerts')
    check(branding.city_line() == 'Tampa, FL', 'her city on email footers')
    check(branding.booking_link() == 'https://sparklepros.com', 'and her own booking site')

    print('\n3. Her cleaners get links to HER server, not somebody else\'s')
    check(branding.crm_base() == 'https://sparkle-pros.up.railway.app',
          'the CRM knows its own address from the environment')
    b = Booking(service_type='deep', name='Nadia R', address='9 Palm Ave',
                email='nadia@example.com', phone='4075550188', price=420,
                status='confirmed', preferred_date='2026-08-20')
    db.session.add(b); db.session.commit()
    from blueprints.payments import payment_link_url
    link = payment_link_url(b)
    check(link.startswith('https://sparkle-pros.up.railway.app/pay/'),
          f'the customer payment link points at her instance: {link[:52]}…')
    clean(link, 'payment link')

    print('\n4. Both quote brands answer to her business, not two strangers')
    primary = brands.get_brand('primary')
    commercial = brands.get_brand('commercial')
    check(primary['name'] == 'Sparkle Pros Cleaning', 'the residential brand is hers')
    check(commercial['name'] == 'Sparkle Pros Cleaning',
          'and with no separate commercial name set, that brand falls back to hers too')
    check(brands.normalize('lm') == 'commercial' and brands.normalize('dazzle') == 'primary',
          'old saved quotes with the legacy keys still resolve')
    shell = brands.email_shell('commercial', 'Your Proposal', '<p>Hello</p>')
    clean(shell, 'quote email')
    check('Sparkle Pros Cleaning' in shell, 'and her name is in the quote email header')

    print('\n5. Her customer-facing pages are clean')
    c = app.test_client()
    for path, label in [(f'/pay/{b.pay_token}', 'payment page')]:
        html = c.get(path).get_data(as_text=True)
        clean(html, label)
        check('Sparkle Pros Cleaning' in html, f'{label} shows her name')

    print('\n6. Her admin pages are clean too')
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    for path, label in [('/', 'dashboard'), ('/bookings/', 'bookings list'),
                        (f'/bookings/{b.id}', 'booking detail'), ('/bookings/clients', 'clients'),
                        ('/contractors/team', 'team'), ('/contractors/payroll', 'payroll'),
                        ('/money/pnl', 'P&L'), ('/money/expenses', 'expenses'),
                        ('/settings/business', 'business settings'),
                        ('/settings/commercial', 'commercial settings'),
                        ('/settings/pricing', 'pricing settings'), ('/quotes/', 'quotes'),
                        ('/quotes/new', 'new quote'), ('/bookings/calendar', 'calendar'),
                        ('/invoices/', 'invoices'), ('/team/broadcast', 'team broadcast'),
                        ('/team/availability', 'team availability')]:
        r = c.get(path, follow_redirects=True)
        check(r.status_code == 200, f'{label} loads ({r.status_code})')
        clean(r.get_data(as_text=True), label)

    print('\n7. The contractor welcome guide is hers')
    from blueprints.contractors import default_training_guide
    guide = default_training_guide()
    clean(guide, 'training guide')
    check('WELCOME TO THE SPARKLE PROS CLEANING FAMILY' in guide.upper(),
          'it welcomes people to her company')

    print('\n8. Interview questions name her company')
    from blueprints.interviews import QUESTIONS_EN, QUESTIONS_ES
    qs = QUESTIONS_EN() + QUESTIONS_ES()
    clean(' '.join(qs), 'interview questions')
    check(any('Sparkle Pros Cleaning' in q for q in qs), 'in both languages')

print('\n🎉 A second company can run this CRM with nothing of the first showing through.')
