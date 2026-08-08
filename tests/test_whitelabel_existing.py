"""The other half of the promise: making the CRM white-label must not change a
single thing about the business already running on it. Her name, her colours,
her L & M commercial brand and her Google review link all have to survive the
move out of code and into Settings."""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/existing.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['CRM_BASE'] = 'https://dazzle-shine-crm-production.up.railway.app'
for stale in ('FROM_EMAIL', 'OWNER_EMAIL', 'NOTIFY_EMAIL', 'BUSINESS_NAME'):
    os.environ.pop(stale, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda *a, **k: (True, 'ok')

from extensions import db
from models import BusinessSetting

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

# ── Stand up the database the way hers already looks, BEFORE the new migration
#    would get a chance to run: business name set, no brand settings yet.
import app as app_module
boot = app_module.create_app()
with boot.app_context():
    BusinessSetting.set('business_name', 'Dazzle & Shine Maids')
    BusinessSetting.set('phone', '(689) 999-0194')
    BusinessSetting.set('email', 'dazzleandshinemaids@gmail.com')
    BusinessSetting.set('city', 'Orlando')
    BusinessSetting.set('state', 'FL')
    BusinessSetting.set('brand_settings_migrated', '')
    db.session.commit()

print('\n1. Her instance is recognised and migrated once')
live = app_module.create_app()
with live.app_context():
    import branding, brands
    check(BusinessSetting.get('brand_settings_migrated') == '1',
          'the one-time brand migration ran on her instance')

    print('\n2. Her own identity is intact')
    check(branding.biz_name() == 'Dazzle & Shine Maids', 'the business name is unchanged')
    check(branding.phone() == '(689) 999-0194', 'her phone number is unchanged')
    check(branding.city_line() == 'Orlando, FL', 'her city line is unchanged')

    print('\n3. Her residential brand keeps its gold palette')
    primary = brands.get_brand('primary')
    check(primary['name'] == 'Dazzle & Shine Maids', 'residential brand name')
    check(primary['accent'] == '#d3a84f', 'the gold accent survived the move to Settings')
    check(primary['dark'] == '#1f1333', 'and the dark purple header')

    print('\n4. Her commercial brand is still a separate business')
    commercial = brands.get_brand('commercial')
    check(commercial['name'] == 'L & M Commercial Cleaners',
          'L & M did NOT get overwritten by the residential name')
    check(commercial['reply_to'] == 'admin@commercialcleanersorlando.com',
          'its replies still go to its own inbox')
    check(commercial['accent'] == '#2a89c4', 'and it keeps its blue palette')
    check(commercial['domain_verified'] is False,
          'its domain is still marked unverified, so mail goes from the verified default')

    print('\n5. Old quotes still route to the right brand')
    check(brands.get_brand('lm')['name'] == 'L & M Commercial Cleaners',
          "a quote saved with brand='lm' still renders as L & M")
    check(brands.get_brand('dazzle')['name'] == 'Dazzle & Shine Maids',
          "and one saved with brand='dazzle' still renders as Dazzle & Shine")
    check(brands.brand_for_property('Apartment complex') == 'primary',
          'apartments still auto-brand residential')
    check(brands.brand_for_property('Medical office') == 'commercial',
          'medical offices still auto-brand commercial')

    print('\n6. Her Google review link was not lost')
    from blueprints.ratings import review_link
    check(review_link() == 'https://g.page/r/CZLGfXgsWHtVEBM/review',
          'customers still reach her real review page')

    print('\n7. Her quote emails look exactly as they did')
    shell = brands.email_shell('lm', 'Your Cleaning Proposal', '<p>Details</p>')
    check('L & M Commercial Cleaners' in shell, 'L & M name in the header')
    check('#12324a' in shell, 'its dark blue header bar')
    # The accent colour only shows up where there is a heading or a button to
    # paint, so give it one.
    shell2 = brands.email_shell('dazzle', 'Your Quote', '<p>Details</p>')
    check('Dazzle & Shine Maids' in shell2 and '#d3a84f' in shell2,
          'and the residential template is unchanged too')

    print('\n8. Running again does not re-migrate or overwrite edits')
    BusinessSetting.set('commercial_name', 'L & M Commercial Cleaners LLC')
    db.session.commit()
    app_module._seed_existing_brand_settings()
    check(BusinessSetting.get('commercial_name') == 'L & M Commercial Cleaners LLC',
          'a name she edits herself is never clobbered by the migration')

print('\n🎉 Nothing about the existing business changed.')
