"""Closing, exporting and purging a company from the console.

These delete customer data, so the interesting tests are the ones that say NO.
What has to be true:

  * only the console owner can close, reopen or purge; a manager can export;
  * nothing happens without a written reason, the company's address typed out,
    and the person's password again (and their authenticator code when two-factor
    is on), and wrong attempts count toward the sign-in lockout;
  * a company with a live Stripe subscription cannot be closed out from under it;
  * closing really ends access (the company's address stops answering) and the
    neighbours carry on;
  * purge is refused before the 30-day retention ends, whatever the form says,
    and when it does run it removes only that company, is safe to repeat, and
    leaves the company closed if anything fails;
  * an export carries only the business data it names, from one company, and not
    a password hash, a card number or a token;
  * reopening brings a company back SUSPENDED, never active on its own.
"""
import io
import os
import secrets
import sys
import time
import zipfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def postgres_url():
    from sqlalchemy import create_engine, text
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      'postgresql://app_user:localtest@127.0.0.1:5432/postgres',
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres'):
        if not candidate:
            continue
        try:
            e = create_engine(candidate)
            with e.connect() as c:
                c.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n  ⚠️  SKIPPED: no PostgreSQL server found.')
    sys.exit(0)

from sqlalchemy import create_engine, text

DB = 'dsm_console_lifecycle_test'
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as conn:
    conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
    conn.execute(text(f'CREATE DATABASE {DB}'))
os.environ.update(DATABASE_URL=f'{PG.rsplit("/", 1)[0]}/{DB}', SECRET_KEY='lifecycle-test',
                  BASE_DOMAIN='akyehq.test', SIGNUPS_OPEN='1')
for k in ('ADMIN_USER', 'ADMIN_PASS', 'CANONICAL_HOST', 'CONSOLE_REQUIRE_2FA'):
    os.environ.pop(k, None)

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

import control_plane
import provisioning
import tenancy
import tenant_data_lifecycle as lifecycle
import totp
from app import create_app

try:
    app = create_app()
    PRODUCT = {'Host': 'akyehq.test'}
    TAG = secrets.token_hex(3)
    with app.app_context():
        engine = provisioning._engine()
        control_plane.ensure_table(engine)

    def signup(slug):
        c = app.test_client()
        r = c.post('/signup', headers=PRODUCT, data={
            'business': f'{slug.title()} Cleaning', 'slug': slug, 'name': 'Owner Person',
            'email': f'{slug}@example.com', 'password': 'a-perfectly-fine-password',
            'terms_accepted': '1', 'zip_code': '10001'})
        assert r.status_code == 302, (slug, r.status_code)

    def seed(slug, client_name, extra=False):
        from extensions import db
        from models import Booking, Client, ContractorPayment, Expense, Staff
        with app.app_context(), tenancy.use_tenant(slug):
            c = Client(name=client_name, email=f'{slug}-c@example.com', phone='4075550101',
                       address='1 Main St', city='Orlando', zip_code='32801',
                       notes='likes lavender', card_brand='visa', card_last4='4242',
                       stripe_customer_id=f'cus_{slug}', portal_token=f'tok_{slug}_secret')
            db.session.add(c)
            s = Staff(name='Kim Cleaner', phone='4075550102', email='kim@example.com',
                      pay_type='per_job', pay_rate=60, w9_url='https://private/w9.pdf',
                      stripe_account_id=f'acct_{slug}')
            db.session.add(s)
            db.session.flush()
            b = Booking(name=client_name, email=c.email, phone='4075550101',
                        address='1 Main St', city='Orlando', service_type='standard',
                        frequency='one_time', status='confirmed', price=120.0,
                        preferred_date='2026-10-20', preferred_time='09:00')
            db.session.add(b)
            db.session.flush()
            db.session.add(ContractorPayment(staff_id=s.id, booking_id=b.id, amount=60.0,
                                             method='cash', status='paid',
                                             stripe_transfer_id=f'tr_{slug}'))
            db.session.add(Expense(date='2026-10-01', category='supplies', amount=19.99,
                                   vendor='Bleach Co', note='monthly', method='card',
                                   receipt_url='https://private/receipt.jpg'))
            db.session.commit()
            db.session.remove()

    def status(slug):
        with app.app_context():
            return control_plane.find(engine, slug)

    def schema_exists(slug):
        return provisioning.schema_exists(engine, tenancy.schema_for(slug))

    def host_code(slug):
        return app.test_client().get('/', headers={'Host': f'{slug}.akyehq.test'}).status_code

    def backdate_closure(slug, days=31):
        with engine.begin() as conn:
            conn.execute(text('update public.organizations set closed_at = :t where slug = :s'),
                         {'t': datetime.utcnow() - timedelta(days=days), 's': slug})

    def log_actions(slug):
        with app.app_context():
            return [r['action'] for r in control_plane.console_log_for(engine, slug, limit=50)]

    # ---- the cast -----------------------------------------------------
    OWNER, OPW = f'owner-{TAG}@example.com', 'owner-console-password-1'
    OWNER2, OPW2 = f'owner2-{TAG}@example.com', 'owner-console-password-2'
    MGR, MPW = f'mgr-{TAG}@example.com', 'manager-console-password-1'
    HLP, HPW = f'hlp-{TAG}@example.com', 'helper-console-password-1'
    with app.app_context():
        control_plane.add_console_user(engine, OWNER, 'Owner', OPW, role='owner')
        control_plane.add_console_user(engine, OWNER2, 'Owner Two', OPW2, role='owner')
        control_plane.add_console_user(engine, MGR, 'Manager', MPW, role='manager')
        control_plane.add_console_user(engine, HLP, 'Helper', HPW, role='helper')

    def console(email, pw):
        c = app.test_client()
        c.post('/console/login', data={'email': email, 'password': pw})
        return c

    owner, mgr, helper = console(OWNER, OPW), console(MGR, MPW), console(HLP, HPW)

    VICTIM, NEIGHBOR, PAYING, DEMO, FAIL, READY = (
        f'victim{TAG}', f'neighbor{TAG}', f'paying{TAG}', f'demo{TAG}', f'failco{TAG}', f'ready{TAG}')
    for slug in (VICTIM, NEIGHBOR, PAYING, DEMO, FAIL, READY):
        signup(slug)
    seed(VICTIM, 'Ada Lovelace')
    seed(NEIGHBOR, 'Neighbour Customer')
    with app.app_context():
        control_plane.set_demo_company(engine, DEMO)
        control_plane.set_billing(engine, PAYING, stripe_customer_id='cus_p',
                                  stripe_subscription_id='sub_p', subscription_status='active')

    def form(slug, **over):
        data = dict(reason='The owner asked us to close the account', confirm=slug, password=OPW)
        data.update(over)
        return {k: v for k, v in data.items() if v is not None}

    def post(client, slug, action, **over):
        return client.post(f'/console/companies/{slug}/lifecycle/{action}',
                           data=form(slug, **over), follow_redirects=True)

    print('\n1. Who may do what')
    for who, client in (('a helper', helper), ('a manager', mgr)):
        post(client, VICTIM, 'close', password=MPW if client is mgr else HPW)
        check(status(VICTIM)['status'] == 'active', f'{who} cannot close a company')
    r = post(helper, VICTIM, 'export', password=HPW)
    check(r.headers.get('Content-Type', '').startswith('text/html'), 'a helper cannot export')
    r = mgr.post(f'/console/companies/{VICTIM}/lifecycle/export', data=form(VICTIM, password=MPW))
    check(r.status_code == 200 and r.mimetype == 'application/zip', 'a manager can export')
    post(mgr, VICTIM, 'purge', password=MPW, ack='1')
    check(schema_exists(VICTIM), 'and cannot purge')

    print('\n2. Nothing happens without all of the confirmations')
    before = status(VICTIM)
    page = lambda r: r.data.decode()
    r = post(owner, VICTIM, 'close', password='wrong-password')
    check(status(VICTIM)['status'] == 'active' and 'password was not right' in page(r),
          'wrong password: nothing changes, and it says so')
    r = post(owner, VICTIM, 'close', confirm='not-the-address')
    check(status(VICTIM)['status'] == 'active' and 'exactly to confirm' in page(r),
          'the wrong address typed: nothing changes')
    r = post(owner, VICTIM, 'close', reason='')
    check(status(VICTIM)['status'] == 'active' and 'Say why' in page(r), 'no reason: nothing changes')
    r = post(owner, VICTIM, 'close', password=None)
    check(status(VICTIM)['status'] == 'active', 'no password at all: nothing changes')
    check(log_actions(VICTIM).count('closed company') == 0, 'and none of it is logged as a closure')

    print('\n3. Wrong passwords count toward the lockout')
    o2 = console(OWNER2, OPW2)
    for _ in range(control_plane.LOCK_AFTER):
        post(o2, VICTIM, 'close', password='guess-guess-guess')
    r = post(o2, VICTIM, 'close', password=OPW2)
    check(status(VICTIM)['status'] == 'active' and 'Too many wrong attempts' in page(r),
          'enough wrong guesses locks the account, so even the right password is refused')

    print('\n4. Two-factor: the code is asked for too')
    secret = totp.generate_secret()
    with engine.begin() as conn:
        conn.execute(text('update public.console_users set totp_secret=:s, totp_enabled=true where email=:e'),
                     {'s': secret, 'e': OWNER})
    r = owner.get(f'/console/companies/{VICTIM}')
    check('Authenticator code' in page(r), 'the form asks for the authenticator code')
    r = post(owner, VICTIM, 'close')
    check(status(VICTIM)['status'] == 'active', 'a password alone is no longer enough')
    r = post(owner, VICTIM, 'close', code='000000')
    check(status(VICTIM)['status'] == 'active' and 'code was not right' in page(r), 'a wrong code is refused')

    print('\n5. What cannot be closed')
    r = post(owner, DEMO, 'close', code=totp._code_at(secret, int(time.time() // 30)), confirm=DEMO)
    check(status(DEMO)['status'] == 'active' and 'demo company' in page(r), 'the demo company')
    r = post(owner, PAYING, 'close', code=totp._code_at(secret, int(time.time() // 30)), confirm=PAYING)
    check(status(PAYING)['status'] == 'active' and 'Stripe subscription' in page(r),
          'a company with a live Stripe subscription: cancel that first')
    check(host_code(PAYING) != 404, 'and it keeps working')
    r = owner.get(f'/console/companies/{PAYING}')
    check('Cancel it in Stripe first' in page(r) and 'btn-danger' not in page(r),
          'the page says why instead of offering the button')

    print('\n6. Closing')
    code = lambda: totp._code_at(secret, int(time.time() // 30))
    check(host_code(VICTIM) != 404 and host_code(NEIGHBOR) != 404, 'both companies answer before')
    r = post(owner, VICTIM, 'close', code=code())
    st = status(VICTIM)
    check(st['status'] == 'closed' and st['closed_at'], 'closed, with a closure date')
    check('is closed' in page(r) and 'kept until' in page(r), 'and the owner of the console is told when it is kept until')
    check(host_code(VICTIM) == 404, "the company's address stops answering")
    check(host_code(NEIGHBOR) != 404, 'while the neighbour is untouched')
    check(schema_exists(VICTIM), 'and its data is still there')
    check('closed company' in log_actions(VICTIM), 'in the record')
    r = post(owner, VICTIM, 'close', code=code())
    check('Only an active or suspended company' in page(r), 'closing twice is refused')

    print('\n7. Purge is refused during retention, whatever the form says')
    r = post(owner, VICTIM, 'purge', code=code(), ack='1')
    check(schema_exists(VICTIM) and status(VICTIM)['status'] == 'closed'
          and not status(VICTIM)['purged_at'] and 'Purge refused' in page(r) and 'retention' in page(r),
          'refused with the date, and nothing deleted')
    check(not any(a.startswith('purged') for a in log_actions(VICTIM)), 'and not logged as a purge')
    page_ = owner.get(f'/console/companies/{VICTIM}').data.decode()
    check('cannot be purged before then' in page_ and 'btn-danger' not in page_,
          'the page shows the countdown instead of a purge button')

    print('\n8. Export: one company, named columns, nothing secret')
    def export(client, slug, pw, **extra):
        data = form(slug, password=pw)
        data.update(extra)
        return client.post(f'/console/companies/{slug}/lifecycle/export', data=data)
    r = export(owner, VICTIM, OPW, code=code())
    check(r.status_code == 200 and r.mimetype == 'application/zip', 'a closed company can still be exported')
    check('no-store' in r.headers.get('Cache-Control', ''), 'and the download is not cached')
    z = zipfile.ZipFile(io.BytesIO(r.data))
    names = sorted(z.namelist())
    check(names == ['README.txt', 'customers.csv', 'expenses.csv', 'jobs.csv',
                    'worker-payments.csv', 'workers.csv'], f'the files it names ({names})')
    blob = '\n'.join(z.read(n).decode('utf-8-sig') for n in names if n.endswith('.csv'))
    check('Ada Lovelace' in blob and 'Kim Cleaner' in blob and 'Bleach Co' in blob and '120.00' in blob,
          'their customers, jobs, workers and expenses are in it')
    check('Neighbour Customer' not in blob and NEIGHBOR not in blob, "and nobody else's")
    for secret_bit in ('4242', 'visa', 'tok_', 'cus_', 'acct_', 'tr_', 'w9.pdf', 'receipt.jpg',
                       'pbkdf2', 'password', 'sk_'):
        check(secret_bit not in blob, f'nothing like {secret_bit!r} (card, token, provider id, hash)')
    readme = z.read('README.txt').decode()
    check('deliberately not in it' in readme and 'Victim' in readme, 'the README says what is left out')
    check('exported company data' in log_actions(VICTIM), 'the export is in the record')
    r = export(owner, VICTIM, 'wrong', code=code())
    check(r.mimetype != 'application/zip', 'no download without the password')
    from tenant_export import safe
    check(safe('=HYPERLINK("x")') == "'=HYPERLINK(\"x\")" and safe('+1') == "'+1" and safe(5) == 5
          and safe('plain') == 'plain', 'formulas in names and notes are defused; numbers are not')
    r = owner.get(f'/console/companies/{VICTIM}')
    check('Last exported' in page(r), 'and the page says an export was made')

    print('\n9. Reopening comes back suspended, never active on its own')
    r = post(mgr, VICTIM, 'reopen', password=MPW)
    check(status(VICTIM)['status'] == 'closed', 'a manager cannot reopen')
    r = post(owner, VICTIM, 'reopen', code=code(), confirm=None)
    st = status(VICTIM)
    check(st['status'] == 'suspended' and not st['closed_at'], 'reopened as suspended, closure date cleared')
    check(host_code(VICTIM) == 423, 'and still locked out: it must be reactivated on purpose')
    owner.post(f'/console/companies/{VICTIM}/reactivate')
    check(status(VICTIM)['status'] == 'active' and host_code(VICTIM) != 404, 'reactivating brings it back')
    check('reopened company' in log_actions(VICTIM), 'in the record')

    print('\n10. Purge, once retention has passed')
    post(owner, VICTIM, 'close', code=code())
    backdate_closure(VICTIM, 31)
    r = post(owner, VICTIM, 'purge', code=code())
    check(schema_exists(VICTIM) and 'owner has been offered' in page(r),
          'without the tick that the owner was offered their data: refused')
    page_ = owner.get(f'/console/companies/{VICTIM}').data.decode()
    check('can now be purged' in page_ and 'Purge ' in page_, 'the page now offers the purge')
    r = post(owner, VICTIM, 'purge', code=code(), ack='1', confirm='wrong')
    check(schema_exists(VICTIM), 'the wrong address typed: refused')
    r = post(owner, VICTIM, 'purge', code=code(), ack='1')
    st = status(VICTIM)
    check(not schema_exists(VICTIM), "the company's data is gone")
    check(st['purged_at'] and st['name'] == f'Purged tenant {VICTIM}' and not st['owner_email'],
          'with only a minimal record kept')
    check(schema_exists(NEIGHBOR), 'the neighbour is untouched')
    with app.app_context(), tenancy.use_tenant(NEIGHBOR):
        from models import Client
        check(Client.query.filter_by(name='Neighbour Customer').count() == 1, "and so is the neighbour's data")
    check('purged company' in log_actions(VICTIM), 'it is in the record')
    r = post(owner, VICTIM, 'purge', code=code(), ack='1')
    check('already purged' in page(r), 'purging again is safe')
    r = post(owner, VICTIM, 'reopen', code=code(), confirm=None)
    check(status(VICTIM)['purged_at'] and 'Not reopened' in page(r), 'a purged company cannot be reopened')
    r = export(owner, VICTIM, OPW, code=code())
    check(r.mimetype != 'application/zip', 'or exported: there is nothing left')

    print('\n11. A failed purge leaves the company closed, and it is safe to retry')
    seed(FAIL, 'Failing Customer')
    post(owner, FAIL, 'close', code=code(), confirm=FAIL)
    backdate_closure(FAIL, 40)
    real = lifecycle._delete_private_media
    lifecycle._delete_private_media = lambda slug: (_ for _ in ()).throw(RuntimeError('storage unreachable'))
    try:
        r = post(owner, FAIL, 'purge', code=code(), ack='1', confirm=FAIL)
    finally:
        lifecycle._delete_private_media = real
    st = status(FAIL)
    check(schema_exists(FAIL) and st['status'] == 'closed' and not st['purged_at'],
          'the data is intact and the company is still closed')
    check('did not complete' in page(r) and 'safe to try again' in page(r), 'and the page says so')
    check('purge failed' in log_actions(FAIL), 'the failure is in the record')
    r = post(owner, FAIL, 'purge', code=code(), ack='1', confirm=FAIL)
    check(not schema_exists(FAIL) and status(FAIL)['purged_at'], 'retrying then succeeds')

    print('\n12. What the pages show')
    post(owner, READY, 'close', code=code(), confirm=READY)
    health = owner.get('/console/health').data.decode()
    check('in retention' in health and 'terminal command still works' in health,
          'Health lists a company in retention and points at the new controls')
    backdate_closure(READY, 31)
    if os.environ.get('DUMP_LIFECYCLE_PAGE'):
        open(os.environ['DUMP_LIFECYCLE_PAGE'], 'w').write(
            owner.get(f'/console/companies/{READY}').data.decode())
    health = owner.get('/console/health').data.decode()
    check('ready to purge' in health, 'and flags it once retention has passed')
    page_ = mgr.get(f'/console/companies/{NEIGHBOR}').data.decode()
    check('Export their data' in page_ and 'Close this company' not in page_
          and 'Only the console owner can close' in page_, 'a manager sees export, and why not close')
    page_ = helper.get(f'/console/companies/{NEIGHBOR}').data.decode()
    check('Export their data' not in page_, 'a helper sees neither')
    page_ = owner.get(f'/console/companies/{VICTIM}').data.decode()
    check('Permanently purged' in page_ and 'Export their data' not in page_, 'a purged company shows its tombstone')

    print('\n13. Review findings: cells, countdown, sign-in time, retention, ordering')
    import threading
    LATE = f'late{TAG}'
    signup(LATE)
    seed(LATE, 'Late Customer')
    from extensions import db
    from models import Booking
    with app.app_context(), tenancy.use_tenant(LATE):
        db.session.add(Booking(name='Hostile', email='h@example.com', phone='4075550199',
                               address='1 Main St', city='Orlando', service_type='standard',
                               frequency='=1+1', status='@SUM(1)', price=-5.0,
                               preferred_date='=cmd|calc', preferred_time='+1+2',
                               bedrooms='-2+3'))
        db.session.commit()
        db.session.remove()
    with app.app_context():
        before = control_plane.console_user(engine, OWNER)['last_login_at']
    r = post(owner, LATE, 'close', code=code())
    check('30 more days' in page(r), 'right after closing, the countdown reads 30 days, not 29')
    r = export(owner, LATE, OPW, code=code())
    jobs = zipfile.ZipFile(io.BytesIO(r.data)).read('jobs.csv').decode('utf-8-sig')
    check("'=cmd|calc" in jobs and "'+1+2" in jobs and "'=1+1" in jobs and "'@SUM(1)" in jobs
          and "'-2+3" in jobs, 'every text column is defused, including ones a customer fills in')
    check('-5.00' in jobs and "'-5.00" not in jobs, 'while a negative amount stays a number')
    with app.app_context():
        after = control_plane.console_user(engine, OWNER)['last_login_at']
    check(before == after, "confirming a password for an export does not change 'Last in'")

    backdate_closure(LATE, 31)
    r = post(owner, LATE, 'reopen', code=code(), confirm=None)
    check(status(LATE)['status'] == 'closed' and 'Not reopened' in page(r) and 'retention' in page(r),
          'once retention has ended, reopening is refused')
    page_ = owner.get(f'/console/companies/{LATE}').data.decode()
    check('can no longer be reopened' in page_ and 'name="confirm"' in page_, 'and the page stops offering it')

    # A reopen and a purge of the same company cannot both go ahead.
    RACE = f'race{TAG}'
    signup(RACE)
    owner_post = post(owner, RACE, 'close', code=code())
    backdate_closure(RACE, 10)
    outcome = {}

    def reopen_in_thread():
        try:
            lifecycle.reopen_tenant(engine, RACE)
            outcome['reopen'] = 'reopened'
        except lifecycle.LifecycleError as exc:
            outcome['reopen'] = f'refused: {exc}'

    seen = {}

    def media(slug):
        t = threading.Thread(target=reopen_in_thread)
        t.start()
        t.join(1.5)
        seen['still_waiting'] = t.is_alive()
        seen['thread'] = t
        return {'configured': False}

    with app.app_context():
        done = lifecycle.purge_tenant(engine, RACE, media_delete=media,
                                      now=datetime.utcnow() + timedelta(days=25))
    seen['thread'].join(10)
    check(seen['still_waiting'], 'a reopen started while a purge is deleting has to wait for it')
    check(outcome.get('reopen', '').startswith('refused') and status(RACE)['purged_at']
          and not schema_exists(RACE), f"and then finds the company purged ({outcome.get('reopen')})")
    # Nothing is deleted before the state is confirmed: media is not touched for a reopened company.
    called = []
    SAFE = f'safe{TAG}'
    signup(SAFE)
    post(owner, SAFE, 'close', code=code())
    backdate_closure(SAFE, 10)
    lifecycle.reopen_tenant(engine, SAFE)
    try:
        lifecycle.purge_tenant(engine, SAFE, media_delete=lambda s: called.append(s) or {},
                               now=datetime.utcnow() + timedelta(days=25))
        refused = False
    except lifecycle.LifecycleError:
        refused = True
    check(refused and not called and schema_exists(SAFE),
          'a purge of a company that was reopened deletes no media and no data')
finally:
    try:
        from extensions import db
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        provisioning._engine().dispose()
    except Exception:
        pass
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
    admin.dispose()

if failures:
    print(f'\n❌ {len(failures)} lifecycle check(s) failed.')
    sys.exit(1)
print('\n✅ Closing, exporting and purging need the owner, a reason, the address and the password, and delete only what they name.')
