"""What a customer can do from their own link, without phoning anybody.

The market leader's version of this page is the feature its reviewers single
out, and the gap here was not the page -- upcoming visits, history, invoices
and a saved card were already on it -- but three things missing from it:

  who is coming, which is what somebody letting a stranger into their house
  most wants to know;
  the quote sitting unanswered in an inbox somewhere, reachable only from the
  one email it went out in;
  and any way to ask for more work that is not a telephone call.
"""
import os, sys, tempfile
from datetime import date, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/hub.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append('email'), (True, 'stub'))[1]
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import Booking, Client, Lead, Staff

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


with app.app_context():
    db.create_all()
    from blueprints.portal import ensure_portal_token
    db.session.add(Staff(name='Ama Mensah', is_active=True))
    c = Client(name='Rita Vance', email='rita@x.test', phone='4079990000',
               zip_code='32801', address='1 Elm')
    db.session.add(c)
    db.session.commit()
    for off, cleaner in [(3, 'Ama Mensah'), (10, None)]:
        db.session.add(Booking(
            service_type='standard', name='Rita Vance', email='rita@x.test',
            phone='4079990000', address='1 Elm', city='Orlando', bedrooms='3',
            bathrooms='2', price=180, status='confirmed', client_id=c.id,
            preferred_date=(date.today() + timedelta(days=off)).isoformat(),
            preferred_time='10:00 AM', assigned_cleaner=cleaner))
    db.session.add(Lead(name='Rita Vance', email='rita@x.test',
                        service_type='Deep clean', quote_token='qt-1',
                        quoted_price=420, status='quoted'))
    db.session.commit()
    token = ensure_portal_token(c)
    client_id = c.id

    cl = app.test_client()

    print('\n1. It still asks who you are first')
    r = cl.get(f'/portal/{token}')
    check(b'answer' in r.data, 'a link alone does not open somebody\'s account')
    cl.post(f'/portal/{token}/verify', data={'answer': '32801'})
    page = cl.get(f'/portal/{token}').data.decode()
    check('Rita' in page, 'the right answer opens it')

    print('\n2. Who is coming')
    # Somebody is being let into a house. A name beforehand is the difference
    # between an appointment and a stranger at the door.
    check('Ama Mensah is coming' in page, 'the assigned cleaner is named')
    check(page.count('is coming') == 1,
          'and nothing is promised for a visit nobody is on yet')

    print('\n3. The quote they never answered')
    check('Waiting on you' in page and 'Deep clean' in page,
          'an unanswered quote is findable again')
    check('qt-1' in page, 'and links to the quote itself')

    print('\n4. Asking for more work')
    before = Booking.query.count()
    r = cl.post(f'/portal/{token}/request',
                data={'what': 'A deep clean before Christmas',
                      'when': 'Any weekday morning'},
                follow_redirects=True)
    lead = Lead.query.filter_by(source='Customer portal').first()
    check(lead is not None, 'it arrives as an enquiry')
    note = (lead.notes or '').lower()
    check('deep clean before christmas' in note and 'weekday morning' in note,
          'carrying what they asked for and when suits them')
    # A customer picking a date is not that date being free, and a booking the
    # business has not seen is how two crews get promised the same Tuesday.
    check(Booking.query.count() == before, 'and books nothing by itself')
    check(SENT, 'the business is told straight away')
    check('we have your request' in r.data.decode(),
          'and the customer is told it landed')

    print('\n5. Somebody else\'s link is somebody else\'s')
    other = app.test_client()
    r = other.post(f'/portal/{token}/request', data={'what': 'anything'})
    check(r.status_code == 404,
          'requesting work without verifying is refused')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ A customer can see, answer and ask without telephoning anybody.')
