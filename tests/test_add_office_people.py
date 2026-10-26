"""Adding somebody who is not a cleaner.

The Team page's Add button used to open the cleaner form for everybody, so an
office admin or a business-development hire became a cleaner: pay settings they
would never use, a W-9 to chase, a place on the job list and a cleaner seat on
the plan -- and nothing there said Team logins existed. Now the button asks
first and points office and sales people at the Team logins page (one form, not
two). That page records employee or contractor, and the add route itself
enforces the plan's office-login limit.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/office.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
import blueprints.account as account
INVITES = []
account._send_invite = lambda u, url: INVITES.append((u.username, url))
from app import create_app
from extensions import db
from models import Staff, User, BusinessSetting
import entitlements

app = create_app()
failures = []
H = {'Origin': 'http://localhost'}


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


def owner():
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(logged_in=True, role='owner', user_name='Owner')
    return c


def plan(name):
    BusinessSetting.set('plan', name)
    BusinessSetting.set('plan_status', 'active')
    db.session.commit()
    # The plan is read once per app context and cached on g; this test keeps one
    # context open across requests, so say the plan changed.
    from flask import g
    g.pop('_entitlement_state', None)


def add(c, **kw):
    data = {'name': 'Pat Office', 'email': 'pat@example.com',
            'role': 'admin', 'worker_model': 'employee'}
    data.update(kw)
    return c.post('/logins/add', data=data, headers=H)


with app.app_context():
    db.create_all()
    plan('scale')
    c = owner()

    print('1. The chooser')
    page = c.get('/staff/choose').get_data(as_text=True)
    check('/staff/new' in page, 'a cleaner goes to the cleaner form')
    check('/logins/' in page, 'an office or sales person goes to Team logins')
    check('name="worker_model"' not in page and 'name="email"' not in page,
          'it is two doors, not a second copy of the login form')
    anon = app.test_client().get('/staff/choose')
    check(anon.status_code in (302, 401, 403), 'signed out, you cannot open it')
    cleaner = app.test_client()
    with cleaner.session_transaction() as s:
        s.update(logged_in=True, role='cleaner')
    check(cleaner.get('/staff/choose').status_code in (302, 401, 403),
          'and a cleaner cannot')

    print('\n2. An office admin is a login, not a cleaner')
    before = Staff.query.count()
    r = add(c)
    u = User.query.filter_by(username='pat@example.com').one()
    check(u.role == 'admin' and u.worker_model == 'employee', 'role and employee are saved')
    check(Staff.query.count() == before, 'no cleaner row, so no cleaner seat and no W-9 to chase')
    check(INVITES and INVITES[-1][0] == 'pat@example.com', 'an invite goes to them')
    check(r.status_code == 302 and r.headers['Location'].endswith('/logins/'),
          'and you land back on Team logins')

    print('\n3. Sales / business development, as a contractor')
    r = add(c, name='Sam Seller', email='sam@example.com', role='sales', worker_model='contractor')
    sam = User.query.filter_by(username='sam@example.com').one()
    check(sam.role == 'sales' and sam.worker_model == 'contractor', 'a contractor sales login')

    print('\n4. What is refused')
    n = User.query.count()
    add(c, name='X', email='x@example.com', role='owner')
    check(User.query.filter_by(username='x@example.com').first() is not None,
          'the Logins page still allows any role (unchanged)')
    n = User.query.count()
    add(c, name='Y', email='y@example.com', worker_model='volunteer')
    check(User.query.count() == n, 'an unknown worker type is refused')
    add(c, name='Z', email='not-an-email')
    check(User.query.count() == n, 'a bad email is refused')
    add(c, name='Dup', email='pat@example.com')
    check(User.query.count() == n, 'an address that already has a login is refused')
    add(c, name='Pat Office', email='pat2@example.com', role='sales')
    check(User.query.count() == n, 'a Sales login with somebody else\'s name is refused (commission is filed by name)')
    r = add(c, name='W', email='w@example.com', worker_model='')
    check(User.query.filter_by(username='w@example.com').one().worker_model is None,
          'worker type is optional on the old route, so a login made the old way is unchanged')

    print('\n5. The plan\'s office-login limit')
    plan('solo')
    n = User.query.count()
    page = c.get('/staff/choose').get_data(as_text=True)
    check('Pro plan' in page and '/logins/' not in page,
          'on Solo the chooser says logins are a Pro feature, with no link to a page they cannot use')
    r = add(c, name='Nope', email='nope@example.com')
    check(User.query.count() == n and '/billing' in r.headers.get('Location', '') or
          User.query.filter_by(username='nope@example.com').first() is None,
          'and the add route refuses too, not just the page')
    plan('pro')
    r = add(c, name='Yes', email='yes@example.com')
    check(User.query.filter_by(username='yes@example.com').first() is not None, 'on Pro it is allowed')
    # A capped plan: lower the cap and check the message.
    entitlements.PLANS['pro']['limits']['office_logins'] = User.query.filter_by(active=True).count()
    r = add(c, name='Over', email='over@example.com')
    check(User.query.filter_by(username='over@example.com').first() is None,
          'at the limit a new login is refused')
    entitlements.PLANS['pro']['limits']['office_logins'] = None

    print('\n6. The logins list shows how they work with you')
    plan('scale')
    lst = c.get('/logins/').get_data(as_text=True)
    check('name="worker_model"' in lst and 'Independent contractor' in lst,
          'the existing Create a login form asks employee or contractor')
    check('Works as' in lst and 'Contractor' in lst and 'Employee' in lst, 'and the list shows it')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
