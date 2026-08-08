"""The Business Settings page holds several separate forms. Saving one of them
must never blank out the others — that would quietly wipe a business's phone
number or its terms the moment it edited something unrelated."""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/set.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda *a, **k: (True, 'ok')
from app import create_app
from extensions import db
from models import BusinessSetting

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

app = create_app()
with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. Fill in the main business details')
    c.post('/settings/business', data={
        'business_name': 'Sparkle Pros Cleaning', 'phone': '(407) 555-0142',
        'email': 'hello@sparklepros.com', 'address': '9 Palm Ave', 'city': 'Tampa',
        'state': 'FL', 'zip_code': '33602', 'website': 'sparklepros.com'},
        follow_redirects=True)
    check(BusinessSetting.get('business_name') == 'Sparkle Pros Cleaning', 'name saved')
    check(BusinessSetting.get('phone') == '(407) 555-0142', 'phone saved')

    print('\n2. Now save the Branding card only')
    c.post('/settings/business', data={
        'google_review_link': 'https://g.page/r/sparkle/review',
        'brand_tagline': 'Spotless Every Time', 'brand_dark': '#0f172a',
        'brand_accent': '#16a34a', 'brand_accent_text': '#ffffff',
        'brand_domain_verified': '1', 'content_business_description': ''},
        follow_redirects=True)
    check(BusinessSetting.get('brand_accent') == '#16a34a', 'branding saved')
    check(BusinessSetting.get('business_name') == 'Sparkle Pros Cleaning',
          'and the business name was NOT wiped by that save')
    check(BusinessSetting.get('phone') == '(407) 555-0142', 'nor the phone number')
    check(BusinessSetting.get('city') == 'Tampa', 'nor the city')

    print('\n3. Save the Commercial card only')
    c.post('/settings/business', data={
        'commercial_name': 'Sparkle Commercial Group',
        'commercial_reply_to': 'offices@sparklepros.com',
        'commercial_tagline': '', 'commercial_from_email': '', 'commercial_phone': '',
        'commercial_website': '', 'commercial_dark': '', 'commercial_accent': '',
        'commercial_accent_text': '', 'commercial_domain_verified': ''},
        follow_redirects=True)
    check(BusinessSetting.get('commercial_name') == 'Sparkle Commercial Group', 'commercial saved')
    check(BusinessSetting.get('brand_accent') == '#16a34a', 'branding survived')
    check(BusinessSetting.get('business_name') == 'Sparkle Pros Cleaning', 'main details survived')
    check(BusinessSetting.get('google_review_link') == 'https://g.page/r/sparkle/review',
          'and the review link survived')

    print('\n4. The two brands now differ, as intended')
    import brands
    check(brands.get_brand('primary')['name'] == 'Sparkle Pros Cleaning', 'residential brand')
    check(brands.get_brand('commercial')['name'] == 'Sparkle Commercial Group', 'commercial brand')
    check(brands.get_brand('commercial')['reply_to'] == 'offices@sparklepros.com',
          'commercial replies go to its own inbox')
    check(brands.get_brand('commercial')['phone'] == '(407) 555-0142',
          'but it inherits the phone number it did not override')

    print('\n5. Clearing the commercial name folds it back into one brand')
    c.post('/settings/business', data={'commercial_name': ''}, follow_redirects=True)
    check(brands.get_brand('commercial')['name'] == 'Sparkle Pros Cleaning',
          'commercial quotes go out under the single trading name again')

    print('\n6. The page still renders with everything set')
    page = c.get('/settings/business').get_data(as_text=True)
    check('Sparkle Pros Cleaning' in page, 'the page shows the saved name')
    check('#16a34a' in page, 'and the saved accent colour')

print('\n🎉 Each card saves independently; nothing gets wiped.')
