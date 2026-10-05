"""A company sends from its own domain only once it has proved it owns one.

Transactional email goes out on Akye's shared domain and needs nothing from
the company. Cold outreach does not get that: one company sending bad cold
email from akyehq.com would cost every other company its deliverability, and
the ones paying that price would be the ones whose work orders stopped
arriving.

The control this replaces was a dropdown the owner set herself, checked by
nobody. Ticking it without doing the DNS did not make mail send from her
domain -- it made it fail, silently, while the setting read "verified".

What is worth protecting here:

  * verified means the email service says so, never what anyone typed
  * an unproven domain falls back to the shared sender rather than failing
  * a domain somebody else proved is not yours
  * the self-declared dropdowns are gone, not merely ignored
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/domain.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
# The hosted product: many companies, one verified sender behind them all.
os.environ['BASE_DOMAIN'] = 'akyehq.com'
os.environ['PRODUCT_FROM_EMAIL'] = 'support@akyehq.com'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
import email_domains, brands

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


with app.app_context():
    db.create_all()
    from models import BusinessSetting
    BusinessSetting.set('business_name', 'Bright Clean')
    BusinessSetting.set('email', 'sarah@brightclean.com')
    db.session.commit()

    print('1. Nothing proved yet')
    check(email_domains.verified_domain() == '', 'no domain is verified')
    check(email_domains.may_send_as('sarah@brightclean.com') is False,
          'and her own address may not be used — she has not proved it yet')

    print('\n2. Registered, but the DNS is not in place')
    email_domains.save(name='brightclean.com', domain_id='d_1', state='pending')
    check(email_domains.verified_domain() == '',
          'pending is not verified — half-done is not done')
    check(email_domains.may_send_as('sarah@brightclean.com') is False,
          'so she still cannot send as herself')

    print('\n3. Verified')
    email_domains.save(state='verified')
    check(email_domains.verified_domain() == 'brightclean.com', 'the domain is hers')
    check(email_domains.may_send_as('sarah@brightclean.com') is True,
          'and an address on it may be used')
    check(email_domains.may_send_as('SARAH@BrightClean.COM') is True,
          'whatever case she typed it in')
    check(email_domains.may_send_as('sarah@gmail.com') is False,
          'but not a free mailbox')
    check(email_domains.may_send_as('sales@someoneelse.com') is False,
          'and not a domain somebody else proved')
    check(email_domains.may_send_as('') is False, 'and not an empty address')

    print('\n4. What the recipient sees')
    email_domains.save(state='pending')
    name, addr, _ = brands.send_identity(brands.PRIMARY)
    check(name == 'Bright Clean', 'her business name, always — never Akye')
    check(addr == 'support@akyehq.com',
          'unproven falls back to the shared verified sender, so it still sends')
    email_domains.save(state='verified')
    name, addr, _ = brands.send_identity(brands.PRIMARY)
    check(name == 'Bright Clean', 'still her name')
    check(addr.endswith('@brightclean.com'), 'and now her own address behind it')

    print('\n5. Rubbish in is refused before it reaches the email service')
    for bad in ('', 'not a domain', 'https://brightclean.com/x y'):
        ok, _, err = email_domains.register(bad)
        check(ok is False, f'refused: {bad!r}')

    print('\n6. Cold outreach waits for the domain')
    import notifications, prospecting
    from models import Prospect
    sent = []
    real_send = notifications.send_email
    notifications.send_email = lambda *a, **k: (sent.append(a[0]), (True, 'stub'))[1]
    try:
        pr = Prospect(business_name='Lakeside PM', category='property_manager',
                      email='dana@lakeside.com', status='new', stage='new')
        db.session.add(pr); db.session.commit()

        email_domains.save(name='brightclean.com', domain_id='d_1', state='pending')
        BusinessSetting.set('commercial_from_email', 'sales@brightclean.com')
        db.session.commit()
        ok, said = prospecting.send_outreach(pr, 'Hello', 'We clean offices.')
        check(ok is False, 'an unproven domain cannot send cold introductions')
        check('Sending Domain' in said, 'and she is told exactly where to fix it')
        check(not sent, 'nothing left the building')

        email_domains.save(state='verified')
        ok, said = prospecting.send_outreach(pr, 'Hello', 'We clean offices.')
        check(ok is True, 'proven, and it goes')
        check(sent == ['dana@lakeside.com'], 'to the address she took on the call')

        ok, said = prospecting.send_outreach(pr, 'Hello', 'Hi', to='')
        check(ok is True, 'the saved address is used when none is given')
    finally:
        notifications.send_email = real_send

print('\n7. The dropdown that lied is gone')
for f in ('templates/admin/settings_business.html', 'blueprints/settings.py'):
    src = open(f, encoding='utf-8').read()
    check('brand_domain_verified' not in src and 'commercial_domain_verified' not in src,
          f'no self-declared verification left in {f}')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
