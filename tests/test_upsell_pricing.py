"""The recurring-cleaning upsell quoted a discount off whatever the customer last
paid, and went to people who were already on a plan.

A customer whose last job was a deep clean was offered fortnightly cleaning at
nearly the deep-clean price — and if her ongoing plan had been set up before that
deep clean finished, which is the normal order, she got sold the plan she was
already booked on.
"""
import os, sys, tempfile, re
from datetime import datetime, timedelta, date
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/upsell.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['CRM_BASE'] = 'https://crm.example.com'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda **k: (SENT.append(k), (True, 'ok'))[1]

from app import create_app
from extensions import db
from models import Booking, BusinessSetting
import recurring, lifecycle
from pricing import calculate_price

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

def upsells_to(email):
    return [s for s in SENT if email in (s.get('to_email') or '')
            and 'Loved your clean' in (s.get('subject') or '')]

app = create_app()
LONG_AGO = datetime.utcnow() - timedelta(days=20)

with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Test Cleaning Co'); db.session.commit()

    def deep_clean(email, name, done_days_ago=3, beds='3', baths='2', price=395):
        b = Booking(service_type='deep', name=name, email=email, address='1 St',
                    bedrooms=beds, bathrooms=baths, price=price, frequency='one_time',
                    preferred_date=date.today().isoformat(), status='completed',
                    created_at=LONG_AGO,
                    completed_at=datetime.utcnow() - timedelta(days=done_days_ago))
        db.session.add(b); db.session.commit()
        return b

    print('\n1. A one-off customer is quoted the real maintenance price')
    deep_clean('solo@example.com', 'Solo Customer')
    SENT.clear()
    lifecycle.run_lifecycle_emails()
    mail = upsells_to('solo@example.com')
    check(len(mail) == 1, 'she gets the upsell')
    body = mail[0]['html']
    real = calculate_price('standard', '3', '2', extras='', frequency='biweekly')
    check(f'{real:.2f}' in body, f'quoting the real fortnightly price (${real:.2f})')
    check('355.50' not in body, 'not a discount off the $395 deep clean')
    check('395' not in body, 'and the deep-clean price is nowhere in it')

    print('\n2. Someone already on a plan is left alone')
    tasha = deep_clean('tasha@example.com', 'Tasha Bright')
    seed = Booking(service_type='standard', name='Tasha Bright', email='tasha@example.com',
                   address='1 St', bedrooms='3', bathrooms='2', price=165,
                   frequency='biweekly', status='confirmed', created_at=LONG_AGO,
                   preferred_date=(date.today() + timedelta(days=14)).isoformat())
    db.session.add(seed); db.session.commit()
    recurring.generate_series(seed)
    for b in Booking.query.filter_by(recurring_group=seed.recurring_group).all():
        b.created_at = LONG_AGO           # the plan predates the deep clean finishing
    db.session.commit()

    SENT.clear()
    lifecycle.run_lifecycle_emails()
    check(upsells_to('tasha@example.com') == [],
          'no upsell to a customer already booked fortnightly')
    check(Booking.query.filter_by(recurring_group=seed.recurring_group).count() >= 7,
          'her plan is untouched')

    print('\n3. Nor is she chased a week later')
    tasha.upsell_sent_at = datetime.utcnow() - timedelta(days=8)
    db.session.commit()
    SENT.clear()
    lifecycle.run_lifecycle_emails()
    check(not [s for s in SENT if 'tasha@example.com' in (s.get('to_email') or '')],
          'the follow-up nudge is skipped too')

    print('\n4. No home size means no quote, rather than a made-up one')
    vague = deep_clean('vague@example.com', 'No Size Recorded', beds=None, baths=None)
    SENT.clear()
    lifecycle.run_lifecycle_emails()
    check(upsells_to('vague@example.com') == [],
          'nothing is sent when there is nothing real to quote')
    check(lifecycle._freq_prices(vague) is None, 'and the pricing helper says so plainly')

    print('\n5. The quote follows the home, not the last invoice')
    small = deep_clean('small@example.com', 'Small Home', beds='1', baths='1', price=395)
    big = deep_clean('big@example.com', 'Big Home', beds='5', baths='3', price=395)
    SENT.clear()
    lifecycle.run_lifecycle_emails()
    small_body = upsells_to('small@example.com')[0]['html']
    big_body = upsells_to('big@example.com')[0]['html']
    small_price = calculate_price('standard', '1', '1', extras='', frequency='biweekly')
    big_price = calculate_price('standard', '5', '3', extras='', frequency='biweekly')
    check(f'{small_price:.2f}' in small_body, f'the 1-bed is quoted ${small_price:.2f}')
    check(f'{big_price:.2f}' in big_body, f'the 5-bed is quoted ${big_price:.2f}')
    check(big_price > small_price,
          'the bigger home costs more — both paid $395 for their deep clean, so the '
          'old code quoted them the same')

print('\n🎉 The upsell quotes a real maintenance price, and never to someone already on a plan.')
