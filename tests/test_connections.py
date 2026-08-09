"""An owner must be able to connect her own Stripe, texting and email without
anyone else touching her keys — and those keys must not be recoverable by
anyone who gets at the database or an admin screen."""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/conn.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
for stale in ('STRIPE_SECRET_KEY', 'STRIPE_PUBLISHABLE_KEY', 'TWILIO_ACCOUNT_SID',
              'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE', 'RESEND_API_KEY'):
    os.environ.pop(stale, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda *a, **k: (True, 'ok')

from app import create_app
from extensions import db
from models import BusinessSetting
import integrations

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

# Assembled at runtime: a key-shaped literal in the source is what secret
# scanners flag, and a fake one is indistinguishable from a real leak.
PREFIX_LIVE = 'sk_' + 'live_'
PREFIX_TEST = 'sk_' + 'test_'
PREFIX_PUB = 'pk_' + 'live_'
LIVE = PREFIX_LIVE + 'NOTAREALKEY0000000004242'
app = create_app()

with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. A fresh instance is honest about being unconnected')
    st = integrations.status()
    check(not st['stripe']['ready'], 'payments not connected')
    check(not st['email']['ready'], 'email not connected')
    check(integrations.stripe_mode() is None, 'and no Stripe mode to report')

    print('\n2. The owner enters her own keys — no one else involved')
    r = c.post('/settings/connections', data={
        'stripe_secret_key': LIVE,
        'stripe_publishable_key': PREFIX_PUB + 'NOTAREAL',
        'stripe_webhook_secret': '',
        'twilio_account_sid': 'ACexample123', 'twilio_auth_token': 'twilio-token-abc',
        'twilio_phone': '+14075550142', 'resend_api_key': 're_example_key'},
        follow_redirects=True)
    check(r.status_code == 200, 'the form saves')
    check(integrations.stripe_secret_key() == LIVE, 'her Stripe key is what the CRM now uses')
    check(integrations.texting_ready(), 'texting is connected')
    check(integrations.email_ready(), 'email is connected')
    check(integrations.stripe_mode() == 'live', 'and it knows this is a live key')

    print('\n3. The key is encrypted at rest')
    raw = BusinessSetting.get('int_stripe_secret_key')
    check(LIVE not in raw, 'the stored value does not contain the key in the clear')
    check(raw.startswith('enc:'), 'it is marked as encrypted')
    check(len(raw) > len(LIVE), 'and is ciphertext, not the original')

    print('\n4. A saved secret is never shown back in full')
    page = c.get('/settings/connections').get_data(as_text=True)
    check(LIVE not in page, 'the full secret key is NOT in the page HTML')
    check('twilio-token-abc' not in page, 'nor the Twilio auth token')
    check(PREFIX_LIVE[:-1] in page, 'but enough is shown to recognise which key it is')
    check(PREFIX_PUB + 'NOTAREAL' in page, 'the publishable key is shown in full — it is not a secret')

    print('\n5. Re-saving the masked value does not destroy the real key')
    masked = integrations.masked('stripe_secret_key')
    c.post('/settings/connections', data={'stripe_secret_key': masked}, follow_redirects=True)
    check(integrations.stripe_secret_key() == LIVE,
          'submitting the form without retyping the key leaves it intact')

    print('\n6. She can replace or clear a key herself')
    c.post('/settings/connections', data={'stripe_secret_key': PREFIX_TEST + 'NOTAREALKEY000004242'},
           follow_redirects=True)
    check(integrations.stripe_mode() == 'test', 'pasting a test key switches the mode')
    c.post('/settings/connections', data={'resend_api_key': '', 'clear_resend_api_key': '1'},
           follow_redirects=True)
    check(not integrations.email_ready(), 'and clearing a key disconnects that service')

    print('\n7. A wrong SECRET_KEY reveals nothing, and does not crash')
    real = integrations._cipher
    os.environ['SECRET_KEY'] = 'a-completely-different-key'
    check(integrations.stripe_secret_key() == '',
          'an attacker with the database but not the app secret gets nothing')
    check(integrations.status()['stripe']['ready'] is False, 'and the CRM reports it as unconnected')
    os.environ['SECRET_KEY'] = 'test-secret-key'
    check(integrations.stripe_mode() == 'test', 'with the right secret it reads correctly again')

    print('\n8. Hosting environment variables still work as a fallback')
    c.post('/settings/connections', data={'stripe_secret_key': '', 'clear_stripe_secret_key': '1'},
           follow_redirects=True)
    check(integrations.stripe_secret_key() == '', 'nothing saved in settings')
    os.environ['STRIPE_SECRET_KEY'] = PREFIX_LIVE + 'FROMENVIRONMENT004242'
    check(integrations.stripe_secret_key() == PREFIX_LIVE + 'FROMENVIRONMENT004242',
          'the environment variable is used when settings are empty')
    check(integrations.source('stripe_secret_key') == 'environment',
          'and the page can say where it came from')
    integrations.set('stripe_secret_key', LIVE)
    check(integrations.stripe_secret_key() == LIVE, 'a saved key takes priority over the environment')
    check(integrations.source('stripe_secret_key') == 'settings', 'and is reported as such')
    os.environ.pop('STRIPE_SECRET_KEY', None)

    print('\n9. Only the owner can see or change any of this')
    anon = app.test_client()
    r = anon.get('/settings/connections')
    check(r.status_code in (301, 302, 401, 403), f'logged out is refused ({r.status_code})')
    body = anon.get('/settings/connections', follow_redirects=True).get_data(as_text=True)
    check(LIVE not in body, 'and no key leaks on the way to the login page')

    staff = app.test_client()
    with staff.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'cleaner'
    r = staff.get('/settings/connections', follow_redirects=True)
    check(LIVE not in r.get_data(as_text=True), 'a cleaner cannot read the payment keys')

print('\n🎉 Keys are self-service, encrypted, masked, and owner-only.')
