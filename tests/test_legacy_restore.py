"""The original business's name was never stored — it lived as a fallback in the
code. Removing those fallbacks to make the CRM white-label left it with no name
at all, showing customers a placeholder.

This is the repair, tested against the database as it actually was: business_name
empty, real quotes on file. The earlier test seeded the name first and so proved
nothing about the situation that actually occurred.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/legacy.db'
os.environ['SECRET_KEY'] = 'test'
for stale in ('BUSINESS_NAME', 'FROM_EMAIL', 'OWNER_EMAIL', 'NOTIFY_EMAIL'):
    os.environ.pop(stale, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda *a, **k: (True, 'ok')

from extensions import db
from models import BusinessSetting, CommercialQuote

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

import app as app_module

# ── Recreate the live database exactly as it was: quotes on file, and a
#    business_name row that never existed.
boot = app_module.create_app()
with boot.app_context():
    BusinessSetting.set('business_name', '')
    BusinessSetting.set('brand_settings_migrated', '')
    db.session.add(CommercialQuote(company='Palm Grove Apartments',
                                   contact_name='Dana Reid', email='pm@example.com',
                                   brand='lm', property_type='Apartment complex',
                                   token='tok-legacy-1'))
    db.session.commit()

print('\n1. The failure that reached a real customer')
with boot.app_context():
    import branding, importlib
    importlib.reload(branding)
    BusinessSetting.set('brand_settings_migrated', '')
    BusinessSetting.set('business_name', '')
    db.session.commit()
    check(BusinessSetting.get('business_name') == '',
          'the business name was never a row in the database')

print('\n2. Booting the app repairs it, without anyone typing anything')
live = app_module.create_app()
with live.app_context():
    import branding, brands, legacy_brands
    check(BusinessSetting.get('business_name') == 'Dazzle & Shine Maids',
          'the name is restored from the instance\'s own data')
    check(branding.biz_name() == 'Dazzle & Shine Maids',
          'so customers see the business, not "Your Cleaning Company"')

    print('\n3. And everything the missing name had blocked')
    check(brands.get_brand('commercial')['name'] == 'L & M Commercial Cleaners',
          'the commercial brand is back')
    check(brands.get_brand('primary')['accent'] == '#d3a84f', 'the gold palette is back')
    from blueprints.ratings import review_link
    check(review_link() == 'https://g.page/r/CZLGfXgsWHtVEBM/review',
          'and the Google review link is back')

    print('\n4. It does not run twice or overwrite an edit')
    BusinessSetting.set('commercial_name', 'L & M Commercial Cleaners LLC')
    db.session.commit()
    check(legacy_brands.restore_if_original() is False, 'a second run does nothing')
    check(BusinessSetting.get('commercial_name') == 'L & M Commercial Cleaners LLC',
          'an edited name is never clobbered')

# ── A different company's CRM must be untouched by any of this.
print('\n5. Another company\'s instance is never given this identity')
TMP2 = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP2}/other.db'
import importlib, extensions
importlib.reload(extensions)
for mod in ('models', 'app'):
    if mod in sys.modules:
        importlib.reload(sys.modules[mod])
import app as app_module2
from models import BusinessSetting as BS2
other = app_module2.create_app()
with other.app_context():
    import legacy_brands as lb2, branding as br2
    importlib.reload(lb2); importlib.reload(br2)
    check(lb2.restore_if_original() is False,
          'a fresh instance with no quote history is not treated as the original')
    check((BS2.get('business_name') or '') == '', 'it is given no name')
    check((BS2.get('commercial_name') or '') == '', 'and no commercial brand')
    check((BS2.get('google_review_link') or '') == '',
          'and crucially no review link pointing at another company')
    check(br2.biz_name() == 'Your Cleaning Company',
          'it shows the neutral placeholder until its owner sets a name')

print('\n🎉 The original business gets its identity back; nobody else inherits it.')
