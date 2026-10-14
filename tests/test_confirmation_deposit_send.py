"""Sending a client the booking confirmation with the $50 deposit link.

Two separate faults made that impossible, and they hid each other.

The control vanished. Eight ways to message a customer were consolidated behind
one "What do you want to send?" chooser, and nothing in that chooser was marked
selected -- so the browser opened on its first option, which for a booking
nobody had answered yet was the Yes/No confirm request. The script then set
display:none on every other panel, including the only one carrying "+ ask for
the deposit". The send she wanted was on the page and invisible, and the button
she could see took no money.

And when she did find it, a failure said it had worked. send_email reports a
refused send by *returning* (False, detail) -- no email key in Settings ->
Connections, a mistyped address, Resend rejecting the call -- it does not raise.
Every sender here called it bare inside a try block and recorded success on the
next line, so "Sent the confirmation and deposit request 💳" was printed for a
send that reached nobody. Same shape as the drip bug in lifecycle.py: the caller
has to read `ok`.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/confdep.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications

# The switchable stubs. `email_ok` / `sms_ok` stand in for a connected key.
state = {'email_ok': True, 'sms_ok': True}
sent = []


def _email(**k):
    if not state['email_ok']:
        return False, 'Email not connected — add your email service key in Settings → Connections.'
    sent.append(k)
    return True, 'ok'


def _sms(to_phone, message):
    if not state['sms_ok']:
        return False, 'No text service connected.'
    sent.append({'to': to_phone, 'sms': message})
    return True, 'ok'


notifications.send_email = _email
notifications.send_sms = _sms

from app import create_app
from extensions import db
from models import Booking
import blueprints.bookings as bk
from blueprints.payments import send_payment_link, send_payment_link_detail

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def a_booking(name='Susan Reyes', **kw):
    b = Booking(service_type='standard', name=name, email='susan@example.com',
                phone='+12565550100', status='pending', price=300.0,
                preferred_date='2026-11-02', preferred_time='9:00 AM',
                address='1 Oak St', city='Huntsville', zip_code='35801', **kw)
    db.session.add(b)
    db.session.commit()
    return b


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. The deposit send is the one the page opens on')
    b = a_booking()
    page = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('id="sendKind"' in page, 'the chooser is on the page')
    chooser = page.split('id="sendKind"', 1)[1].split('</select>', 1)[0]
    opts = [o.split('value="', 1)[1].split('"', 1)[0]
            for o in chooser.split('<option ')[1:]]
    check(opts and opts[0] == 'confirmation',
          'and it opens on the booking confirmation, not the Yes/No request')
    check('selected' in chooser.split('<option ')[1],
          'marked selected, so the browser cannot pick a different one')
    check('ask for the $50 deposit' in page,
          'the deposit option names the figure, so she can see it is still $50')

    print('\n2. A confirmation that could not be delivered says so')
    state['email_ok'] = state['sms_ok'] = False
    sent.clear()
    ok, why = bk._send_booking_confirmation(b)
    check(ok is False, 'the sender reports failure rather than nothing')
    check('Settings' in why, f'and carries the reason: {why[:48]}…')
    # Through the real button, so what she is told is what the route flashes.
    page = c.post(f'/bookings/{b.id}/send-confirmation', data={'pay_kind': 'deposit'},
                  follow_redirects=True).get_data(as_text=True)
    check('Could not send' in page, 'the page says it could not be sent')
    check('Sent the confirmation' not in page, 'and never claims it was')
    check('Settings' in page, 'naming the fix, so she is not left guessing')

    print('\n3. A deposit request that could not be delivered says so')
    ok, why = send_payment_link_detail(b, kind='deposit')
    check(ok is False, 'the deposit link reports failure')
    check(send_payment_link(b, kind='deposit') is False,
          'and the plain bool form agrees with it')

    print('\n4. With email connected, both actually go and are reported once')
    state['email_ok'] = state['sms_ok'] = True
    sent.clear()
    page = c.post(f'/bookings/{b.id}/send-confirmation', data={'pay_kind': 'deposit'},
                  follow_redirects=True).get_data(as_text=True)
    check('confirmation' in page and 'deposit request' in page,
          'both the confirmation and the deposit request are reported')
    check('Could not send' not in page, 'and nothing is reported as failed')
    subjects = [m.get('subject', '') for m in sent if 'subject' in m]
    check(any('tap to pay' in x.lower() for x in subjects),
          'a pay-by-card email really went out')
    check(any('pay-deposit/' in (m.get('sms') or '') for m in sent),
          'and the text carries the deposit link, not the full-balance one')

    print('\n5. A send with nothing to send to is not a success either')
    quiet = a_booking('No Contact Nora')
    quiet.email = ''
    quiet.phone = ''
    db.session.commit()
    ok, why = bk._send_booking_confirmation(quiet)
    check(ok is False, 'no email and no phone is a failure')
    check('no email address' in why, f'and says which: {why}')

    print('\n6. send_triggered_email stops claiming every send worked')
    state['email_ok'] = False
    check(notifications.send_triggered_email(
        trigger='booking_confirmed', to_email='x@example.com', to_name='X') is False,
        'a refused template email returns False')

if failures:
    print(f'\n❌ {len(failures)} failed')
    for f in failures:
        print('  -', f)
    raise SystemExit(1)
print('\n🎉 She can see the deposit send, and it never lies about going out.')
