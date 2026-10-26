"""The one Send button on a booking (#167): confirmation plus deposit request,
by email and by text. What the 26 Oct report asked to be certified:

  - one channel failing while the other goes: she must be told which;
  - a double-click: the customer must not get everything twice;
  - the amount the customer is told is the amount the deposit page charges;
  - a deposit request on a booking whose deposit is already paid.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/channels.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications

state = {'email_ok': True, 'sms_ok': True}
sent = []


def _email(**k):
    if not state['email_ok']:
        return False, 'Email not connected — add your email service key in Settings → Connections.'
    sent.append({'email': k.get('to_email'), 'subject': k.get('subject', ''), 'html': k.get('html', '')})
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


def press_send(c, b, kind='deposit'):
    """What she is told: the flash messages the press leaves, nothing else."""
    c.post(f'/bookings/{b.id}/send-confirmation', data={'pay_kind': kind})
    with c.session_transaction() as s:
        told = ' | '.join(m for _, m in s.pop('_flashes', []))
    print(f'     told: {told}')
    return told


emails = lambda: [m for m in sent if 'email' in m]
texts = lambda: [m for m in sent if 'sms' in m]

with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. Email goes, the text does not')
    b = a_booking()
    state.update(email_ok=True, sms_ok=False)
    sent.clear()
    page = press_send(c, b)
    check(len(emails()) == 2 and not texts(), 'the confirmation and deposit emails went; no texts')
    check('text' in page.lower() and ('could not' in page.lower() or "didn't" in page.lower()),
          'she is told the text did not go, so she knows the customer has email only')

    print('\n2. The text goes, the email does not')
    state.update(email_ok=False, sms_ok=True)
    sent.clear()
    page = press_send(c, b)
    check(len(texts()) == 2 and not emails(), 'both texts went; no emails')
    check('email' in page.lower() and 'could not' in page.lower(),
          'she is told the email did not go')

    print('\n3. A double-click')
    state.update(email_ok=True, sms_ok=True)
    b2 = a_booking()
    sent.clear()
    press_send(c, b2)
    once = len(sent)
    press_send(c, b2)
    check(once == 4, f'one press sends confirmation + deposit request, by email and text (got {once})')
    check(len(sent) == once,
          f'a second press straight after does not send it all again (got {len(sent)} messages)')
    page = c.get(f'/bookings/{b2.id}').get_data(as_text=True)
    form = page.split('bookings/%d/send-confirmation' % b2.id, 1)[1].split('</form>', 1)[0] \
        if f'/bookings/{b2.id}/send-confirmation' in page else ''
    check('onsubmit' in form or 'data-once' in form,
          'the Send button cannot be pressed twice while the first send is going')

    print('\n4. The amount she is told is the amount the deposit page charges')
    from pricing import get_deposit
    b3 = a_booking()
    sent.clear()
    press_send(c, b3)
    dep = get_deposit()
    told = [m['sms'] for m in texts()] + [m['html'] for m in emails() if 'tap to pay' in m['subject'].lower()]
    check(told and all(f'${dep:.0f}' in t for t in told if 'deposit' in t.lower()),
          f'the deposit request quotes ${dep:.0f}')
    import blueprints.deposit as dp
    asked = {}

    class _PI:
        @staticmethod
        def create(**kw):
            asked.update(kw)
            return type('I', (), {'id': 'pi_dep', 'client_secret': 'cs'})()
    dp.stripe.PaymentIntent = _PI
    import blueprints.payments as pay
    pay.stripe_customer_id_for = lambda bk: 'cus_x'
    dp.integrations.stripe_secret_key = lambda *a, **k: 'sk_test_fake'
    db.session.refresh(b3)
    r = c.post(f'/pay-deposit/{b3.deposit_token}/intent')
    check(asked.get('amount') == int(round(dep * 100)),
          f'and the deposit page charges the same (asked Stripe for {asked.get("amount")} cents)')

    print('\n5. The deposit is already paid')
    b4 = a_booking(deposit_paid=True, deposit_amount_paid=dep)
    sent.clear()
    page = c.get(f'/bookings/{b4.id}').get_data(as_text=True)
    card = page.split('name="pay_kind"', 1)[1].split('</select>', 1)[0] if 'name="pay_kind"' in page else ''
    check('value="deposit" selected' not in card and 'value="deposit"  selected' not in card,
          'the deposit request is not chosen by default once it is paid')
    press_send(c, b4, kind='deposit')
    check(not any('deposit' in (m.get('sms') or '').lower() for m in sent),
          'and pressing it anyway does not ask her to pay the deposit a second time')

if failures:
    print(f'\n❌ {len(failures)} failed')
    for f in failures:
        print('  -', f)
    raise SystemExit(1)
print('\n🎉 The one Send button says exactly what reached the customer, once.')
