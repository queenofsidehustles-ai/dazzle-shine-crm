"""P0 exact-money display gate.

A cleaner must never be offered one amount in SMS and see another amount on the
claim page, email, or payment notice.  Use $64.50 deliberately: it catches the
historical class of bug where one surface rounded to whole dollars while
another preserved cents.
"""
import os
import sys
import tempfile
from types import SimpleNamespace

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/money-display.db'
os.environ['SECRET_KEY'] = 'money-display-test-secret'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import Booking, Staff

app = create_app()
app.config.update(TESTING=True)


def _money_fixture():
    with app.app_context():
        db.drop_all()
        db.create_all()
        cleaner = Staff(
            name='Cents Cleaner',
            email='cents@example.test',
            phone='3015550101',
            is_active=True,
            pay_type='percent',
            pay_rate=50.0,
            worker_model='contractor',
        )
        # No estimated-hours override: legacy percentage pay makes this exactly
        # 50% of $129.00 = $64.50, the amount that exposed the original defect.
        booking = Booking(
            name='Exact Cents Customer',
            email='customer@example.test',
            phone='3015550199',
            city='Germantown',
            zip_code='20874',
            service_type='standard',
            price=129.0,
            status='confirmed',
            preferred_date='2026-09-20',
            preferred_time='9:00 AM',
        )
        db.session.add_all([cleaner, booking])
        db.session.commit()
        return booking.id, cleaner.id


def test_job_offer_sms_and_claim_page_show_identical_cents(monkeypatch):
    booking_id, cleaner_id = _money_fixture()
    sent = []

    import blueprints.claims as claims
    monkeypatch.setattr(claims, 'send_sms',
                        lambda to, body, **k: (sent.append((to, body)), (True, 'stub'))[1])

    with app.app_context():
        booking = db.session.get(Booking, booking_id)
        cleaner = db.session.get(Staff, cleaner_id)
        assert booking.pay_for(cleaner) == 64.5
        assert claims.broadcast_job(booking) == 1
        booking = db.session.get(Booking, booking_id)
        cleaner = db.session.get(Staff, cleaner_id)
        claim_url = f'/claim/{booking.claim_token}/{cleaner.agreement_token}'

    assert len(sent) == 1
    sms = sent[0][1]
    assert '$64.50' in sms
    assert '$64 for the job' not in sms

    response = app.test_client().get(claim_url)
    assert response.status_code == 200
    page = response.data.decode('utf-8', 'replace')
    assert '$64.50' in page
    assert '$64</' not in page


def test_payment_notification_email_and_sms_preserve_same_cents(monkeypatch):
    import contractor_pay

    emails = []
    texts = []

    def fake_email(**kwargs):
        emails.append(kwargs)
        return True, 'stub'

    def fake_sms(to, body, **kwargs):
        texts.append((to, body))
        return True, 'stub'

    monkeypatch.setattr(notifications, 'send_email', fake_email)
    monkeypatch.setattr(notifications, 'send_sms', fake_sms)

    staff = SimpleNamespace(
        name='Cents Cleaner', email='cents@example.test', phone='3015550101'
    )
    emailed, texted = contractor_pay.notify_paid(
        staff, amount=64.50, method='zelle', job_label='Exact Cents Job'
    )

    assert emailed is True
    assert texted is True
    assert len(emails) == 1
    assert len(texts) == 1

    email = emails[0]
    assert '$64.50' in email['subject']
    assert '$64.50' in email['html']
    assert '$64.50' in texts[0][1]
    assert '$64 from' not in texts[0][1]
