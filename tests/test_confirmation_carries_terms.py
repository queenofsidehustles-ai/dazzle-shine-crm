"""The booking confirmation carries the terms, because most customers ring up.

A customer who books through the website passes a checkout page, and paying is
what records their acceptance: customer_terms.record_acceptance snapshots the
exact wording, the time and the IP. That is strong evidence in a dispute.

A customer who telephones never passes through any of it. No checkout, no tick,
no acceptance recorded — and until now, no mention of the terms anywhere they
would see. The first they heard of a 24-hour window was being quoted it after
they had already asked for a refund, which is the worst possible moment and does
not read as a rule. It reads as an excuse.

So the confirmation carries the wording itself, not a link: links are not
opened, and a link cannot be produced to a card network months later. Sending it
also puts the exact text in the Sent log with the date it went, which is what a
chargeback response actually needs.

The window leads, because it is the clause that decides a dispute and nobody
reads to the bottom of a terms block.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/terms.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SENT = []
import notifications
# captured before the stub below replaces it, or this is just the stub again
_REAL_SEND = notifications.send_email
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to_email=None, to_name=None, subject='', html='', **k: (
    SENT.append({'to': to_email, 'subject': subject, 'html': html}), (True, 'stub'))[1]

from app import create_app
from extensions import db
from models import Booking, BusinessSetting
import customer_terms

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
    BusinessSetting.set('business_name', 'Dazzle & Shine Maids')
    db.session.commit()

    print('\n1. A job taken over the phone')
    b = Booking(name='Susan Reed', email='susan@example.com', phone='4075550111',
                service_type='deep', bedrooms='3', bathrooms='2',
                preferred_date='2026-10-09', address='9 Larch Way',
                city='Orlando', status='confirmed', price=320.00)
    db.session.add(b); db.session.commit()
    check(b.terms_accepted_at is None,
          'nothing is recorded as accepted — she never saw a checkout page')

    print('\n2. Her confirmation carries the window, and the terms themselves')
    import blueprints.bookings as bk
    subject, html, sms = bk.confirmation_content(b)
    check('24 hours' in html, 'the 24-hour window is in the email')
    flat = ' '.join(html.split())
    check('re-clean the affected areas at no charge' in flat,
          'stated as the remedy, in the words the terms use')
    terms = customer_terms.get_terms()
    sample = terms.strip().splitlines()[0][:40]
    check(sample and sample in html,
          'and the full terms are in the body, not behind a link')
    check('href=' not in html.split('24 hours')[0][-200:],
          'the window is not a link she has to follow to read')

    print('\n3. It leads, rather than sitting under everything else')
    i_window = html.index('24 hours')
    i_terms = html.index(sample)
    check(i_window < i_terms,
          'the clause that decides a dispute comes before the wall of terms')

    print('\n4. The text message says it too — a phone booker may never open email')
    check('24 hours' in sms, f'the SMS names the window ({sms[-90:].strip()})')

    print('\n5. Sending it puts the wording in the record, dated')
    SENT.clear()
    bk._send_booking_confirmation(b)
    check(len(SENT) == 1, 'the confirmation sent')
    check('24 hours' in SENT[0]['html'], 'carrying the window')

    # The stub above replaces send_email, so nothing reaches the logger. The
    # real one is what writes the Sent log, and it writes it whether or not the
    # provider accepts -- which is the point: the record exists either way.
    import notifications as n
    stub, n.send_email = n.send_email, _REAL_SEND
    try:
        bk._send_booking_confirmation(b)
    finally:
        n.send_email = stub
    from models import OutboundLog
    logged = OutboundLog.query.filter_by(channel='email').all()
    check(logged, 'the send is recorded at all')
    check(any('24 hours' in (r.body or '') for r in logged),
          'and the Sent log holds the exact wording that went out')
    check(any(r.created_at for r in logged),
          'with the date it went — what a card network asks for')

    print('\n6. An owner who rewrites her template cannot drop the terms')
    import inspect
    import blueprints.api as api
    src = inspect.getsource(api)
    check('always_append=_confirmation_terms()' in src,
          'the website confirmation appends them unconditionally')
    check('append_unless' not in src.split('always_append')[1][:200],
          'not behind the guard that lets a template opt out')
    body = api._confirmation_terms()
    check('24 hours' in body and body.index('24 hours') < body.index('FULL SERVICE TERMS'),
          'and in the same order: the window first')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 Every customer is told the rule before they need it.')
