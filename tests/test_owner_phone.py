"""The owner's phone number: asked for at signup so somebody can ring them.

Signup (blueprints/signup.py) is covered by test_signup, which refuses a
missing or unusable number and checks what is stored. This is the rest:

  * the console shows the number the same way on every page that shows an
    owner, from one macro and not four copies of the same markup
  * the one list of starter seeds is shared by signup, the demo company and the
    command line, and strict means a failed seed fails the caller
  * the form tells people up front that they will be called
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/phone.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


from app import create_app
app = create_app()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

print('1. The console shows an owner\'s number as a link, formatted for a person')
contact = app.jinja_env.get_template('console/_contact.html').module
org = {'owner_email': 'dana@x.example', 'owner_phone': '+14075550123'}
with app.test_request_context():
    both = str(contact.owner(org))
    only_phone = str(contact.owner({'owner_phone': '+14075550123'}))
    only_email = str(contact.owner({'owner_email': 'dana@x.example'}))
    neither = str(contact.owner({}))
    odd = str(contact.phone({'owner_phone': '<b>1</b>'}))
check('href="tel:+14075550123"' in both and '(407) 555-0123' in both, 'a tel: link, written as (407) 555-0123')
check('mailto:dana@x.example' in both and ' · ' in both, 'beside the email')
check('(407)' in only_phone and 'mailto' not in only_phone and '·' not in only_phone, 'a number alone has no stray separator')
check('mailto' in only_email and 'tel:' not in only_email, 'a company from before the number was asked for reads as it did')
check(neither.strip() == '', 'and with neither, nothing at all')
check('<b>' not in odd, 'a value that is not a number is escaped, not trusted')

print('\n2. Every page that shows an owner uses it')
for page in ('companies', 'company', 'funnel'):
    src = open(f'{ROOT}/templates/console/{page}.html').read()
    check('console/_contact.html' in src, f'{page}.html imports the macro')
check('mailto:{{ o.owner_email }}' not in open(f'{ROOT}/templates/console/funnel.html').read(),
      'the funnel lists no longer carry their own copy of the markup')

print('\n3. One list of starter seeds, and strict means strict')
import provisioning
import app as app_module


class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeApp:
    def app_context(self): return _Ctx()


calls = []
saved = {n: getattr(app_module, n) for n in provisioning.SEEDS}
for n in provisioning.SEEDS:
    setattr(app_module, n, (lambda n=n: calls.append(n)))
setattr(app_module, '_seed_sops', lambda: (_ for _ in ()).throw(RuntimeError('sops failed')))
try:
    calls.clear()
    provisioning.seed(FakeApp(), 'tenant_x')
    check(len(calls) == len(provisioning.SEEDS) - 1,
          'tolerant (the command line, the nightly repair): a failed seed is reported and the rest still run')
    try:
        provisioning.seed(FakeApp(), 'tenant_x', strict=True)
        check(False, 'strict: a failed seed fails the caller')
    except RuntimeError:
        check(True, 'strict (signup, the demo company): a failed seed fails the caller, so a company is never declared ready half-seeded')
finally:
    for n, fn in saved.items():
        setattr(app_module, n, fn)
src = open(f'{ROOT}/blueprints/signup.py').read()
check('_seed_strict' not in src and 'provisioning.seed(current_app, schema, strict=True)' in src,
      'signup uses the shared one')
check('_seed_strict' not in open(f'{ROOT}/demo_company.py').read(), 'and so does the demo company')

print('\n4. The form says they will be called, and asks for the number')
html = app.test_client().get('/signup', base_url='http://akyehq.test').get_data(as_text=True) \
    if os.environ.get('BASE_DOMAIN') else open(f'{ROOT}/templates/admin/signup.html').read()
check('name="phone" type="tel" required' in html, 'the field is required')
check('call to welcome you' in html, 'and says why, before they give it')
check('name="sms_consent"' in html and 'Text me' in html, 'a text is still its own, separate, unticked box')

print()
if failures:
    print(f'❌ {len(failures)} owner-phone check(s) failed.')
    sys.exit(1)
print('🎉 An owner can be rung, and it is said up front.')
