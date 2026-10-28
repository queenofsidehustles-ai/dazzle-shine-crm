"""Customer messaging: partial channels, selective retry, paid-state recheck
(AKY-004, AKY-005, AKY-006).

  1. Every combination of email and text going or not, for a confirmation on
     its own, with a deposit request and with a payment link: the owner is
     told exactly what reached the customer, and the send log says the same.
  2. Pressing Send again after a partial send sends only what did not go --
     not a second copy of the email she already has. Once everything has gone,
     a later press is a deliberate resend and sends it all; so does ticking
     "Send everything again". A corrected address is somebody the message has
     not reached. After a day, a press is a fresh send.
  3. Money already paid is never asked for. The payment state is read again
     when Send is pressed, not taken from the page: a deposit paid from an
     earlier link while the owner was looking is not requested, and neither
     is a payment link on a job with nothing owed.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/sendretry.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications

state = {'email_ok': True, 'sms_ok': True}
sent = []


def _email(**k):
    if not state['email_ok']:
        return False, 'Email not connected.'
    sent.append({'email': k.get('to_email'), 'subject': k.get('subject', '')})
    return True, 'ok'


def _sms(to_phone, message):
    if not state['sms_ok']:
        return False, 'No text service connected.'
    sent.append({'to': to_phone, 'sms': message})
    return True, 'ok'


notifications.send_email = _email
notifications.send_sms = _sms

from sqlalchemy import text

from app import create_app
from extensions import db
from models import Booking

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def a_booking(**kw):
    b = Booking(service_type='standard', name='Susan Reyes', email='susan@example.com',
                phone='+12565550100', status='pending', price=300.0,
                preferred_date='2026-11-02', preferred_time='9:00 AM',
                address='1 Oak St', city='Huntsville', zip_code='35801', **kw)
    db.session.add(b)
    db.session.commit()
    return b


def press(c, b, kind, **extra):
    c.post(f'/bookings/{b.id}/send-confirmation', data={'pay_kind': kind, **extra})
    with c.session_transaction() as s:
        told = ' | '.join(m for _, m in s.pop('_flashes', []))
    print(f'     told: {told}')
    return told


def later(b, seconds=120):
    """Past the double-click guard."""
    db.session.execute(text('UPDATE booking SET customer_send_at = :t WHERE id = :i'),
                       {'t': datetime.utcnow() - timedelta(seconds=seconds), 'i': b.id})
    db.session.commit()


def log(b):
    db.session.expire_all()
    return json.loads(db.session.get(Booking, b.id).customer_send_log or '{}')


def confirmations():
    return [m for m in sent if 'email' in m and 'invoice' not in m['subject']]


def requests():
    return [m for m in sent if ('email' in m and 'invoice' in m['subject'])
            or ('sms' in m and ('deposit' in m['sms'] or 'invoice' in m['sms']))]


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. Every partial-channel combination is reported as it happened')
    for kind in ('none', 'deposit', 'full'):
        for email_ok in (True, False):
            for sms_ok in (True, False):
                print(f'   {kind}: email {"goes" if email_ok else "fails"}, '
                      f'text {"goes" if sms_ok else "fails"}')
                b = a_booking()
                sent.clear()
                state.update(email_ok=email_ok, sms_ok=sms_ok)
                told = press(c, b, kind)
                lg = log(b)
                notes = ['confirmation'] + ([kind] if kind != 'none' else [])
                want_missed = sorted((['email'] if not email_ok else []) +
                                     (['text'] if not sms_ok else []))
                for n in notes:
                    check(lg.get('missed', {}).get(n) == want_missed,
                          f'{n}: the log says {want_missed or "nothing"} missed '
                          f'(got {lg.get("missed", {}).get(n)})')
                if email_ok and sms_ok:
                    check('⚠️' not in told and 'Sent the' in told, 'reported as sent, no warning')
                elif email_ok or sms_ok:
                    gone = 'text' if not sms_ok else 'email'
                    check('Only part of the' in told and f"the {gone} didn't go" in told,
                          f'reported as partial, naming the {gone}')
                else:
                    check('Sent the' not in told and 'Could not send' in told,
                          'reported as not sent at all')
                    check(not lg.get('sent', {}).get('confirmation'),
                          'and the log records nothing delivered')
    state.update(email_ok=True, sms_ok=True)

    print('\n2. A retry sends only what did not go')
    b = a_booking()
    sent.clear()
    state.update(email_ok=True, sms_ok=False)
    press(c, b, 'deposit')
    check(len(confirmations()) == 1 and not [m for m in sent if 'sms' in m],
          'first press: the emails went, the texts did not')
    state.update(sms_ok=True)
    later(b)
    sent.clear()
    told = press(c, b, 'deposit')
    check(not [m for m in sent if 'email' in m],
          f'the retry sends no second email ({len([m for m in sent if "email" in m])} sent)')
    check(len([m for m in sent if 'sms' in m]) == 2,
          'it sends the confirmation text and the deposit text')
    check(told.count('by text') == 2, 'and says each went by text only')
    check(not any(log(b)['missed'].values()), 'and now nothing is missed')
    later(b)
    sent.clear()
    press(c, b, 'deposit')
    check(len([m for m in sent if 'email' in m]) == 2 and len([m for m in sent if 'sms' in m]) == 2,
          'once everything has gone, pressing again is a deliberate resend of it all')

    b = a_booking()
    state.update(email_ok=True, sms_ok=False)
    press(c, b, 'none')
    page = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('Send everything again' in page, 'after a partial send the page offers "Send everything again"')
    state.update(sms_ok=True)
    later(b)
    sent.clear()
    press(c, b, 'none', resend_all='1')
    check(len(confirmations()) == 1 and len([m for m in sent if 'sms' in m]) == 1,
          'and ticking it sends the email again as well as the text')

    b = a_booking()
    state.update(email_ok=True, sms_ok=False)
    press(c, b, 'none')
    bb = db.session.get(Booking, b.id)
    bb.email = 'susan.reyes@example.com'
    db.session.commit()
    state.update(sms_ok=True)
    later(b)
    sent.clear()
    press(c, b, 'none')
    check([m['email'] for m in confirmations()] == ['susan.reyes@example.com'],
          'a corrected address is sent to: the message never reached it')

    b = a_booking()
    state.update(email_ok=True, sms_ok=False)
    press(c, b, 'none')
    bb = db.session.get(Booking, b.id)
    bb.preferred_date = '2026-11-05'              # rescheduled since
    db.session.commit()
    state.update(sms_ok=True)
    later(b)
    sent.clear()
    press(c, b, 'none')
    check(len(confirmations()) == 1 and len([m for m in sent if 'sms' in m]) == 1,
          'a rescheduled booking is a fresh send: the email she has carries the old date')

    b = a_booking()
    state.update(email_ok=True, sms_ok=False)
    press(c, b, 'none')
    lg = log(b)
    lg['at'] = (datetime.utcnow() - timedelta(hours=30)).isoformat(timespec='seconds')
    bb = db.session.get(Booking, b.id)
    bb.customer_send_log = json.dumps(lg)
    db.session.commit()
    state.update(sms_ok=True)
    later(b)
    sent.clear()
    press(c, b, 'none')
    check(len(confirmations()) == 1, 'a day later, a press is a fresh send of everything')

    b = a_booking()
    state.update(email_ok=True, sms_ok=False)
    press(c, b, 'none')
    state.update(sms_ok=True)
    later(b)
    sent.clear()
    press(c, b, 'deposit')
    check(len(confirmations()) == 1,
          'a different request (now with the deposit) is a fresh send, not a retry')

    print('\n3. Money already paid is never asked for')
    state.update(email_ok=True, sms_ok=True)
    b = a_booking()
    c.get(f'/bookings/{b.id}')                         # the owner has the page open
    # The customer pays from an earlier link; the webhook records it outside
    # this request, so the copy of the booking already loaded here is stale.
    db.session.execute(text('UPDATE booking SET deposit_paid = 1, deposit_amount_paid = 50, '
                            'amount_collected = 50 WHERE id = :i'), {'i': b.id})
    db.session.commit()
    sent.clear()
    told = press(c, b, 'deposit')
    check(not requests(), f'no deposit request goes ({len(requests())} sent)')
    check('already paid' in told, 'and she is told why')
    check(len(confirmations()) == 1, 'the confirmation still goes')

    b = a_booking()
    db.session.execute(text('UPDATE booking SET amount_collected = 300, paid_at = :t WHERE id = :i'),
                       {'t': datetime.utcnow(), 'i': b.id})
    db.session.commit()
    sent.clear()
    told = press(c, b, 'full')
    check(not requests(), 'no payment link on a job with nothing owed')
    check('Nothing is owed' in told, 'and she is told why')

    from blueprints.payments import send_payment_link_detail
    b = a_booking(deposit_paid=True)
    sent.clear()
    ok, why = send_payment_link_detail(b, kind='deposit')
    check(not ok and 'already paid' in why and not sent,
          'the sender itself refuses a deposit request on a paid deposit')
    b = a_booking(paid_at=datetime.utcnow(), amount_collected=300)
    ok, why = send_payment_link_detail(b, kind='full')
    check(not ok and 'nothing is owed' in why and not sent,
          'and a payment link on a job with nothing owed')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print('   -', f)
    sys.exit(1)
print('\n🎉 Each notification reaches each address once, and paid money is never asked for.')
