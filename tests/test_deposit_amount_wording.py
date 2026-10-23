"""Every message about the deposit says the deposit this business set.

The amount charged has followed the Pricing setting for a while, but the
words around it did not: the deposit request email and text, the owner's
alerts, the "send a deposit link" option, the lead emails and the reports
card all said "$50". A business that set $75 charged $75 and told its
customers $50.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/dep.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, ROOT)

SENT = []
import notifications
notifications.send_email = lambda *a, **k: SENT.append(('email', k.get('subject', ''), k.get('html', ''))) or (True, 'stub')
notifications.send_sms = lambda to, body, *a, **k: SENT.append(('sms', '', body)) or (True, 'stub')

from app import create_app
from extensions import db
from models import Booking, PricingSetting, EmailTemplate
import blueprints.api as api

api.send_email = notifications.send_email
api.send_sms = notifications.send_sms

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
    PricingSetting.set('deposit_amount', 75)
    db.session.commit()

print('\n1. The deposit request says $75')
with app.test_request_context():
    b = Booking(service_type='standard', name='Rita Vance', email='rita@x.com',
                phone='4075550000', price=225, bedrooms=2, bathrooms=2,
                deposit_token='tok123', status='pending', balance_due=150)
    db.session.add(b)
    db.session.commit()
    SENT.clear()
    api._send_deposit_request(b)
everything = ' '.join(s + ' ' + h for _k, s, h in SENT)
check('$75' in everything, 'the amount set on Pricing is used')
check('$50' not in everything, 'and "$50" appears nowhere')
sms = [h for k, _s, h in SENT if k == 'sms']
check(sms and '$75 deposit' in sms[0], 'the text says $75 too')
check(any('$75.00' in h for _k, _s, h in SENT), 'the email table shows $75.00')

print('\n2. Whole and part dollars read naturally')
check(api._dollars(75) == '$75' and api._dollars(49.5) == '$49.50', '$75 and $49.50')

print('\n3. The new booking form offers a $75 link')
c = owner()
r = c.get('/bookings/new')
check(b'Send a $75 deposit link now' in r.data, 'radio option shows $75')

print('\n4. Lead emails use the setting, including copies already saved')
with app.app_context():
    t = EmailTemplate.query.filter_by(trigger='lead_quote').first()
    check(t is not None and '{{deposit}}' in t.body and '$50' not in t.body,
          'the default quote email uses {{deposit}}')
    # An older saved copy, with an owner's own line added.
    t.body = 'Hi! My own intro. Ready to book? All we need is a $50 deposit to hold your spot — thanks.'
    db.session.commit()
    from app import _seed_email_templates
    _seed_email_templates()
    t = EmailTemplate.query.filter_by(trigger='lead_quote').first()
    check(t.body.startswith('Hi! My own intro.') and '${{deposit}} deposit' in t.body,
          'an old saved copy has only the $50 phrase swapped')
    SENT.clear()
    notifications.send_triggered_email('lead_quote', 'a@b.com', 'Ann Lee', {})
    check(SENT and '$75 deposit' in SENT[-1][2], 'and it goes out saying $75')

print('\n5. The reports card counts real deposits')
with app.app_context():
    b = Booking.query.first()
    b.deposit_paid = True
    b.deposit_amount_paid = 60
    db.session.add(Booking(service_type='standard', name='Old Job', email='o@x.com',
                           phone='1', price=200, deposit_paid=True))
    db.session.commit()
r = c.get('/reports')
check(b'$135 in deposits' in r.data, 'a recorded $60 plus an unrecorded one at today\'s $75')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ All deposit wording tests passed.')
