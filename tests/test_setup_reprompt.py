"""A business that finished the old list is asked the new questions.

`setup_complete` is written once and read on every page after, so an
established business is not recomputing its onboarding forever. That is the
right trade until the list changes -- and it changed: the timezone, the terms,
payments and how balances are collected were all added to it.

Every company already carrying the old flag would have gone on being told it
had finished a list it was never shown. No banner, no meter, no Nana: the
flag suppresses all three. Ten of twelve live companies have never chosen how
balances are collected, which means they collect nothing, and none of them
would have been asked.

What this holds:
- An old flag does not count as having finished the current list.
- Once the current list really is done, the flag latches again and the page
  stops recomputing.
- Nana can set the timezone and the balance choice herself, and only ever to
  a value that means something.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/re.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting
import onboarding, setup_assistant, automations, integrations

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def owner():
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'
    return c


with app.app_context():
    db.create_all()
    # A company as it stood before the list changed: everything the old
    # required list asked for, and the flag to say so.
    BusinessSetting.set('business_name', 'Established Cleaning')
    BusinessSetting.set('phone', '(407) 555-0100')
    BusinessSetting.set('email', 'hello@established.test')
    BusinessSetting.set('pricing_reviewed', '1')
    BusinessSetting.set('booking_page_shared', '1')
    BusinessSetting.set('setup_complete', '1')
    db.session.commit()

print('\n1. The old flag is not the current list')
check(onboarding.SETUP_VERSION != '1', 'the list has moved on from the old flag')
c = owner()
r = c.get('/settings/getting-started')
check(r.status_code == 200, 'the getting-started page loads')
with app.app_context():
    p = onboarding.progress()
check(p['complete'] is False, 'they are not finished after all')
missing = [s['key'] for s in p['steps'] if s.get('required') and not s['done']]
check(set(missing) == {'business', 'terms', 'balance'},
      f'and the questions they were never asked are open: {missing}')

print('\n2. They are actually prompted, not silently incomplete')
body = r.data.decode()
check('Getting started' in body, 'the setup list is on the page')
dash = c.get('/').data.decode()
check('setup-meter' in dash or 'Getting started' in dash,
      'and the meter is back on every screen')

print('\n3. Nana will not set a timezone nobody meant')
with app.test_request_context():
    text, card = setup_assistant.tool_offer_timezone(zone='somewhere')
    check(card is None and 'Eastern' in text, 'a zone she does not know is refused')
    text, card = setup_assistant.tool_offer_timezone(zone='central')
    check(card is not None and 'America/Chicago' in card['lines'][0],
          'and a real one becomes a card, not a saved value')
check(setup_assistant.set_timezone({'timezone': 'Mars/Olympus'})[0] is False,
      'the save refuses it too, not only the offer')

print('\n4. The cards save what they showed')
with app.app_context():
    ok, said = setup_assistant.set_timezone({'timezone': 'America/Chicago'})
    check(ok and BusinessSetting.get('timezone') == 'America/Chicago',
          'the timezone card writes the timezone')
    ok, said = setup_assistant.set_balance_mode({'mode': 'auto'})
    check(ok and automations.balance_mode() == 'auto',
          'the balance card writes the choice')
    check(automations.is_enabled('charge-balances') is True,
          'and "auto" really does switch the charging on')
check(setup_assistant.set_balance_mode({'mode': 'whenever'})[0] is False,
      'a mode that is not one of the three is refused')

print('\n5. Being able to trade does not latch the flag')
with app.app_context():
    BusinessSetting.set('terms_reviewed', '1')
    integrations.set('stripe_secret_key', 'sk_live_reprompt')
    db.session.commit()
    check(onboarding.progress()['complete'] is True, 'every required step is done')
c.get('/')
with app.app_context():
    check(BusinessSetting.get('setup_complete') != onboarding.SETUP_VERSION,
          'but the flag stays open while optional steps remain')
    check(onboarding.progress()['next'] is not None,
          'because there is still something to offer')

print('\n6. Nothing left at all latches it')
from models import Staff, Client, Booking, BookingCrew
with app.app_context():
    db.session.add(Staff(name='Ama', is_active=True))
    db.session.add(Client(name='Rita', email='r@x.test'))
    b = Booking(service_type='standard', name='First job',
                status='confirmed', price=180.0)
    db.session.add(b)
    db.session.commit()
    db.session.add(BookingCrew(booking_id=b.id, staff_id=1, pay_amount=90.0))
    db.session.commit()
    check(onboarding.progress()['next'] is None, 'every step is done')
c.get('/')
with app.app_context():
    check(BusinessSetting.get('setup_complete') == onboarding.SETUP_VERSION,
          'and now the flag is written, so no page recomputes it again')

if failures:
    print(f'\n❌ {len(failures)} re-prompt check(s) failed')
    sys.exit(1)
print('\n✅ The old flag does not hide the new questions.')
