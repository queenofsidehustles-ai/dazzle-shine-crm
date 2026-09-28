"""The product's own front door, and where it must never appear.

Until this, the root of the product domain redirected to a login form — a page
for people who already have an account. Nobody could find out what the thing
was or sign up for it.

The interesting half is not the landing page. It is that there are now two
brands in one codebase, and they must not mix:

    branding.py   whose CRM is this — the cleaning company's name, on the job
                  texts their cleaners read and the invoices their customers get
    product.py    what they subscribe to — the marketing site and the signup

If the product's name ever turns up on a cleaning company's invoice, the
white-label work that came before it is undone. Most of this file is about that.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/mk.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['SIGNUPS_OPEN'] = '1'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import BusinessSetting
import product
import entitlements

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


PRODUCT_HOST = {'Host': 'akye.test'}
TENANT_HOST = {'Host': 'acme.akye.test'}

with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Sparkle Cleaning Services')
    db.session.commit()

c = app.test_client()

print('\n1. The product has a front door')
r = c.get('/', headers=PRODUCT_HOST)
check(r.status_code == 200, 'the root of the product domain is a real page')
check(b'Akye' in r.data, 'carrying the product name')
check(b'calendar' in r.data, 'and the positioning — not just a login box')
check(b'/signup' in r.data, 'with a way to sign up on it')

print('\n2. It says how the name is pronounced, once')
# The name is unfamiliar on purpose. Leaving every visitor to guess is a cost
# on the exact motion this depends on -- somebody cold-calling cleaning
# companies -- and the meaning is the story.
check(b'ah-CHEH' in r.data, 'the pronunciation is on the page')
check(b'good morning' in r.data, 'and so is what it means')

print('\n3. Pricing is rendered from the plans the software enforces')
r = c.get('/pricing', headers=PRODUCT_HOST)
check(r.status_code == 200, 'the pricing page loads')
for key in ('solo', 'pro', 'scale'):
    label = entitlements.PLANS[key]['label'].encode()
    check(label in r.data, f'{label.decode()} is listed')
# Read the prices from the plan table rather than restating them. Written out
# by hand, these assertions passed for months and then failed the moment the
# price changed -- which is a test failing at the news, not at a bug.
_pro   = ('$%d' % entitlements.PLANS['pro']['price']).encode()
_scale = ('$%d' % entitlements.PLANS['scale']['price']).encode()
check(_pro in r.data and _scale in r.data,
      'at the prices the billing code actually charges')
# The numbers on the page come from the same table as the limits. A pricing
# page kept separately drifts, and it always drifts the same way: it promises
# something the product then refuses to do.
solo = entitlements.PLANS['solo']['limits']
check(str(solo['field_workers']).encode() in r.data,
      f'and the free plan says {solo["field_workers"]} cleaners, which is what it allows')
check(str(solo['jobs_per_month']).encode() in r.data,
      f'and {solo["jobs_per_month"]} jobs, which is what it allows')

print('\n4. None of it appears on a cleaning company\'s own CRM')
# The thing that would undo the white-label work.
r = c.get('/', headers=TENANT_HOST)
check(r.status_code in (301, 302), 'a company subdomain redirects to their CRM, not the marketing site')
for path in ('/home', '/pricing'):
    r = c.get(path, headers=TENANT_HOST)
    check(r.status_code == 404, f'{path} does not exist on a company subdomain')

print('\n5. Nor on the pages a cleaner and a customer actually read')
r = c.get('/login', headers=TENANT_HOST)
check(b'Akye' not in r.data,
      'the product name is nowhere on a company sign-in page')

print('\n6. And not at all on a single-business deployment')
# Dazzle & Shine, and every private deployment. No product domain, so there is
# no product -- just their CRM, exactly as before.
import subprocess, textwrap
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOLO = f'''
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{{TMP}}/solo.db"
os.environ["SECRET_KEY"] = "test"
os.environ.pop("BASE_DOMAIN", None)
os.environ["ADMIN_USER"] = "owner"
os.environ["ADMIN_PASS"] = "pw-for-the-test"
sys.path.insert(0, {ROOT!r})
import notifications
notifications.send_sms = lambda *a, **k: (True, "stub")
notifications.send_email = lambda *a, **k: (True, "stub")
from app import create_app
import product
app = create_app()
c = app.test_client()
print("IS PRODUCT SITE:", product.domain() != "")
r = c.get("/", follow_redirects=True)
print("ROOT STATUS:", r.status_code)
print("PRODUCT NAME LEAKED:", b"Akye" in r.data)
print("MARKETING REACHABLE:", c.get("/home").status_code, c.get("/pricing").status_code)
print("OK")
'''
r = subprocess.run([sys.executable, '-c', SOLO], capture_output=True, text=True)
assert 'OK' in r.stdout, f'FAILED:\n{r.stdout}\n{r.stderr}'
check('IS PRODUCT SITE: False' in r.stdout, 'no product domain means no product site')
check('PRODUCT NAME LEAKED: False' in r.stdout,
      'the product name appears nowhere on their CRM')
check('MARKETING REACHABLE: 404 404' in r.stdout,
      'and the marketing pages do not exist there at all')

print('\n7. The name is a placeholder, and moves without a code change')
os.environ['PRODUCT_NAME'] = 'Something Else'
os.environ['PRODUCT_TAGLINE'] = 'A different promise'
check(product.name() == 'Something Else', 'the name comes from the environment')
check(product.tagline() == 'A different promise', 'and so does the tagline')
del os.environ['PRODUCT_NAME'], os.environ['PRODUCT_TAGLINE']
check(product.name() == 'Akye', 'falling back to the placeholder when unset')

print('\n8. With the door shut, nothing invites anybody in')
import subprocess as sp
SHUT = SOLO.replace('os.environ.pop("BASE_DOMAIN", None)',
                    'os.environ["BASE_DOMAIN"] = "akye.test"\nos.environ["SIGNUPS_OPEN"] = "0"')
SHUT = SHUT.replace('r = c.get("/", follow_redirects=True)',
                    'r = c.get("/", headers={"Host": "akye.test"})')
SHUT = SHUT.replace('print("MARKETING REACHABLE:", c.get("/home").status_code, c.get("/pricing").status_code)',
                    'print("SIGNUP LINK SHOWN:", b"/signup" in r.data)\n'
                    'print("SIGNUP PAGE:", c.get("/signup", headers={"Host": "akye.test"}).status_code)')
r = sp.run([sys.executable, '-c', SHUT], capture_output=True, text=True)
assert 'OK' in r.stdout, f'FAILED:\n{r.stdout}\n{r.stderr}'
check('SIGNUP LINK SHOWN: False' in r.stdout,
      'SIGNUPS_OPEN=0 removes every "start free" button')
check('SIGNUP PAGE: 404' in r.stdout, 'and the signup page itself is gone')
check('ROOT STATUS: 200' in r.stdout,
      'while the landing page still explains what the product is')

print('\n9. Somebody who already pays can get back in from a phone')
# The header hid every non-button link under 760px. On a phone that left one
# control -- "Get early access" -- so an existing customer standing in a
# doorway had no way back into their own CRM. It was on the desktop site the
# whole time, which is exactly why it went unnoticed.
shell = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'templates', 'marketing', '_shell.html')).read()
mobile = shell.split('@media (max-width:760px){')[1].split('}')[0] \
    if '@media (max-width:760px){' in shell else ''
check('@media (max-width:760px){' in shell, 'there is still a phone-sized layout')
check('nav a:not(.btn){ display:none; }' not in shell,
      'the phone layout no longer hides every link that is not the button')

header = shell.split('<header>')[1].split('</header>')[0]
login = [ln for ln in header.split('\n') if '/login' in ln]
check(len(login) == 1, 'the header has a sign-in link')
check('wide-only' not in login[0],
      'and it is not one of the things a narrow screen drops')

# The name is unfamiliar on purpose, so how it sounds stays on every screen.
# Only the meaning steps aside on a phone, and it lands in the footer.
check('ah-CHEH<span class="wide-only">' in shell,
      'the pronunciation itself survives on a phone')
footer = shell.split('<footer>')[1]
check('good morning' in footer,
      'and what the name means is in the footer, where there is room')
print('\nFeedback can be sent from any page, by anybody logged in')
import os as _o
_r = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
shell = open(_o.path.join(_r, 'templates', 'base_admin.html')).read()
widget = open(_o.path.join(_r, 'templates', '_feedback.html')).read()

# On every screen. A tester who has to go and find somewhere to report a
# problem mostly does not, and the ones who do send "it broke".
check("include '_feedback.html'" in shell, 'the widget is in the shell, not on one page')
check("session.get('logged_in')" in shell, 'and only for somebody signed in')

# Captured, not asked for. "It broke" from somebody who cannot remember which
# page is the most common and least useful thing a beta tester sends.
for field in ('page:', 'endpoint:', 'viewport:'):
    check(field in widget, f'the report carries {field.strip(":")} by itself')
check('release=_release()' in open(_o.path.join(_r, 'blueprints', 'feedback.py')).read(),
      'and the release it was running')

# Said out loud or photographed, not only typed.
check('SpeechRecognition' in widget, 'it can be spoken instead of typed')
check("accept=\"image/*\"" in widget, 'and a screenshot can be attached')
check("toDataURL('image/jpeg', 0.7)" in widget,
      'shrunk in the browser, because a phone photo of a screen is megabytes')

# One place to read it all. Feedback inside each company's own database means
# logging into every company to find out what the beta said.
cp = open(_o.path.join(_r, 'control_plane.py')).read()
check("'feedback', control_metadata" in cp,
      'it is stored in the control plane, not in a tenant schema')
# By name rather than by the whole list, which grows. Anchored on the real
# call, not the first mention of create_all -- which is in a docstring.
_call = cp.split('control_metadata.create_all')[1][:220]
check('feedback' in _call, 'and the table is created with the others')

# A note that arrives beats a note refused for being too big.
fb = open(_o.path.join(_r, 'blueprints', 'feedback.py')).read()
check('shot, shot_type = None, None' in fb and 'MAX_SHOT_BYTES' in fb,
      'an oversized screenshot loses the picture, not the words')
print('\n\n✅ All marketing tests passed.\n')
