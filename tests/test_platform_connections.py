"""Texting, email, job photos and lead search are Akye's on hosted Akye.

Every company uses one master Twilio, Resend, Cloudinary and Google account,
from the environment. Only Stripe is a company's own. What would go wrong if
this regressed:
  * every owner reading the master account's Twilio SID, phone number and
    Cloudinary key -- and the ends of its secrets -- off her Connections page;
  * an owner pressing Save on a pre-filled form and freezing copies of the
    master keys into her company, so rotating them later breaks her quietly;
  * a hand-made form post pointing a company at some other Twilio account;
  * the setup checklist and other pages telling owners to connect things
    there is nothing for them to connect.
A single-business install, where the environment *is* the business, keeps
its editable keys.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_platform_connections')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
MASTER = {
    'TWILIO_ACCOUNT_SID': 'ACmaster0000000000000000000000beef',
    'TWILIO_AUTH_TOKEN': 'mastertoken0000000000000000cafe',
    'TWILIO_PHONE': '+15550001111',
    'RESEND_API_KEY': 're_master_resend_key_123456',
    'CLOUDINARY_CLOUD_NAME': 'mastercloud',
    'CLOUDINARY_API_KEY': '987654321012345',
    'CLOUDINARY_API_SECRET': 'mastercloudinarysecretXYZ',
    'GOOGLE_PLACES_API_KEY': 'AIzaMasterPlacesKey000000000000000',
}
os.environ.update(MASTER)
for k in ('STRIPE_SECRET_KEY', 'STRIPE_PUBLISHABLE_KEY', 'STRIPE_WEBHOOK_SECRET'):
    os.environ.pop(k, None)

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import integrations
import onboarding
import places_finder
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SLUG = 'sparkle'
HOST = f'http://{SLUG}.akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Sparkle Cleaning', quiet=True)
    db.session.remove()
c = fresh_postgres.owner_client(app, SLUG, 'akye.test')

print('\n1. The Connections page shows a company none of the master keys')
r = c.get('/settings/connections', base_url=HOST)
page = r.get_data(as_text=True)
check(r.status_code == 200, 'the page opens')
leaked = [k for k, v in MASTER.items()
          if v in page or v[:7] in page or v[-4:] + '<' in page]
check(not leaked, f'no master value, or the start of one, is on the page ({leaked})')
check(not any(f'name="{n}"' in page for n in integrations._PLATFORM),
      'and there is no field to type one into')
check('provides these for you' in page and page.count('Working') >= 4,
      'it says Akye provides texting, email, photos and lead search, and that they work')
check('name="stripe_secret_key"' in page and 'name="stripe_publishable_key"' in page,
      'Stripe is still the company\'s to fill in')

print('\n2. Saving the form cannot set them, and Stripe still saves')
r = c.post('/settings/connections', base_url=HOST, data={
    'twilio_account_sid': 'ACsomebodyelse00000000000000000000',
    'twilio_phone': '+15559999999',
    'cloudinary_cloud_name': 'othercloud',
    'stripe_publishable_key': 'pk_test_company_own_1234567890',
    'stripe_secret_key': 'sk_test_company_own_1234567890'})
with app.app_context(), tenancy.use_tenant(SLUG):
    check(integrations._stored('twilio_account_sid') == ''
          and integrations._stored('cloudinary_cloud_name') == '',
          'a posted Twilio or Cloudinary value is not saved')
    check(integrations.twilio_account_sid() == MASTER['TWILIO_ACCOUNT_SID']
          and integrations.twilio_phone() == MASTER['TWILIO_PHONE'],
          'texting still goes through the master account')
    check(integrations.stripe_secret_key() == 'sk_test_company_own_1234567890',
          'the company\'s own Stripe key is saved')

    print('\n3. A key a company saved before this is ignored')
    integrations.set('twilio_auth_token', 'old-company-token-that-was-saved')
    integrations.set('google_places_api_key', 'AIzaOldCompanyOwnKey00000000000000')
    check(integrations.twilio_auth_token() == MASTER['TWILIO_AUTH_TOKEN']
          and integrations.source('twilio_auth_token') == 'environment',
          'the master token is used, not the saved copy')
    check(not places_finder.own_key(),
          'and an old Google key does not lift the plan\'s lead-search allowance')

    print('\n4. The setup checklist does not ask for what Akye provides')
    keys = {i['key'] for i in onboarding.checklist()}
    check('email' not in keys and 'texting' not in keys and 'payments' in keys,
          f'no "connect email/texting" steps; Stripe is still one ({sorted(keys)})')
    db.session.remove()

print('\n5. The pages that used to say "connect it yourself" do not')
saved_sid = os.environ.pop('TWILIO_ACCOUNT_SID')    # as if Akye's Twilio were down
r = c.get('/messages/sent', base_url=HOST)
os.environ['TWILIO_ACCOUNT_SID'] = saved_sid
body = r.get_data(as_text=True)
check(r.status_code == 200 and 'Texting is not connected' in body,
      'the sent-messages log still says when texting is down')
check('provides texting and email for you' in body and 'Connect these yourself' not in body
      and 'Twilio account SID' not in body,
      'but says it is Akye\'s to fix, not a list of keys for the owner to find')

print('\n6. A single-business install keeps its editable keys')
base = os.environ.pop('BASE_DOMAIN')
with app.app_context(), tenancy.use_tenant(SLUG):
    check(not integrations.hosted_company() and integrations.editable('twilio_auth_token'),
          'with no BASE_DOMAIN every key is editable')
    check(integrations.twilio_auth_token() == 'old-company-token-that-was-saved',
          'and a saved key wins over the environment, as before')
    db.session.remove()
os.environ['BASE_DOMAIN'] = base
with app.app_context():
    check(not integrations.hosted_company(),
          'the product site itself is not a company, so nothing changes there')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Only Stripe is a company\'s own; everything else is Akye\'s, unseen and unchangeable.')
