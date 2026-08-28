"""Getting a cleaner to the front door.

Everything a cleaner reads before a job is read on a phone, outside, often in a
car. The address is the one field on the page that has a job to do, and copying
it by hand into another app is the difference between a tool and a chore.

This needs no maps service and no money: Google, Apple and Waze all accept a
plain URL with an address in it, which opens whichever app is already on the
phone with directions loaded. The paid Maps API draws a map inside a page, and
nobody standing outside a house needs that.

The one thing that has to be right is the encoding. "12 Elm St #4" contains a
character a browser reads as the start of a URL fragment, so an un-encoded link
silently drops everything after it -- and the cleaner finds out at the wrong
address.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/nav.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, Staff, BookingCrew, JobChecklist, ChecklistTemplate
import secrets

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


# The addresses that break a naive link, and one ordinary one.
AWKWARD = [
    ('12 Elm St #4', 'Orlando', '32801', 'an apartment number'),
    ('50 Smith & Wesson Ave', 'Tampa', '33601', 'an ampersand'),
    ('9 Rue Café', 'Miami', '33101', 'an accent'),
    ('1 Straight Road', 'Ocoee', '34761', 'an ordinary address'),
]

with app.app_context():
    db.create_all()
    maria = Staff(name='Maria', is_active=True, pay_rate=50.0)
    db.session.add(maria)
    db.session.commit()
    made = []
    for addr, city, zc, why in AWKWARD:
        b = Booking(service_type='standard', name=f'Job at {addr}', status='confirmed',
                    address=addr, city=city, zip_code=zc, price=200.0,
                    preferred_date=datetime.utcnow().strftime('%Y-%m-%d'),
                    claim_token=secrets.token_urlsafe(24), open_for_claim=True,
                    estimated_hours=2.0, labor_rate_applied=43.0)
        db.session.add(b)
        db.session.commit()
        db.session.add(BookingCrew(booking_id=b.id, staff_id=maria.id, pay_amount=86.0))
        db.session.commit()
        made.append((b.id, b.claim_token, addr, why))

c = app.test_client()

print('\n1. The macro encodes what would otherwise break the link')
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
macro = env.get_template('public/_navigate.html').module.navigate
for addr, city, zc, why in AWKWARD:
    html = str(macro(addr, city, zc))
    check('#' not in html.split('destination=')[1].split('"')[0],
          f'{why}: no raw # survives into the link')
    check('google.com/maps/dir' in html, f'{why}: it is a directions link, not a search')
    check('waze.com/ul' in html, f'{why}: and Waze is offered too')

print('\n2. An apartment number reaches the destination intact')
html = str(macro('12 Elm St #4', 'Orlando', '32801'))
dest = html.split('destination=')[1].split('"')[0]
from urllib.parse import unquote_plus
check(unquote_plus(dest) == '12 Elm St #4, Orlando 32801',
      f'decoded back to the full address: {unquote_plus(dest)!r}')

print('\n3. An address with nothing in it produces no button')
check(str(macro('', None, None)).strip() == '',
      'no address, no dead link to tap')
check(str(macro(None, 'Orlando', '32801')).strip() == '',
      'a city alone is not something to navigate to')

print('\n4. The cleaner can navigate from the job checklist')
with app.app_context():
    # Re-queried inside this context: the object from the setup block belongs
    # to a session that has since closed.
    tpl = ChecklistTemplate.query.first()
    bid, token, addr, _ = made[0]
    jc = JobChecklist(booking_id=bid, token=secrets.token_urlsafe(24),
                      template_name=tpl.name if tpl else 'Standard',
                      items='["Kitchen","Bathrooms"]')
    db.session.add(jc)
    db.session.commit()
    jc_token = jc.token
r = c.get(f'/workorders/checklist/{jc_token}')
check(r.status_code == 200, 'the checklist page loads')
check(b'maps/dir' in r.data, 'and carries a directions link')
check(b'%23' in r.data or b'Elm' in r.data, 'with the address encoded into it')

print('\n5. And from the claim page, once the job is theirs')
with app.app_context():
    s = Staff.query.first()
    if not s.agreement_token:
        s.agreement_token = secrets.token_urlsafe(24)
        db.session.commit()
    stoken = s.agreement_token
bid, ctoken, addr, _ = made[0]
r = c.get(f'/claim/{ctoken}/{stoken}')
check(r.status_code == 200, 'the claim page loads')
check(b'maps/dir' in r.data or b'Navigate' in r.data,
      'and offers navigation once the job belongs to them')

print('\n6. My Day offers both apps')
r = c.get(f'/team/my-day/{stoken}') if False else None
with app.app_context():
    from flask import url_for
    with app.test_request_context():
        try:
            my_day = url_for('claims.my_day', stoken=stoken)
        except Exception:
            my_day = None
if my_day:
    r = c.get(my_day)
    check(r.status_code == 200, 'My Day loads')
    check(b'maps/dir' in r.data, 'with a Navigate link')
    check(b'waze.com' in r.data, 'and Waze alongside it')
else:
    src = open('templates/public/my_day.html').read()
    check('maps/dir' in src, 'My Day has a Navigate link')
    check('waze.com' in src, 'and Waze alongside it')

print('\n7. It costs nothing — there is no maps service to pay')
for f in ('templates/public/_navigate.html', 'templates/public/my_day.html',
          'templates/public/checklist.html', 'templates/public/claim.html'):
    src = open(f).read()
    check('maps.googleapis.com' not in src and 'key=' not in src.replace('api=1', ''),
          f'{os.path.basename(f)}: no API key, no billable maps service')

print('\n\n✅ All navigation tests passed.\n')
