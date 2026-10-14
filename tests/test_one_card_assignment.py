"""Who's doing this job — one card, one control.

Three cards used to answer the same question. Picking a named cleaner was
buried at the bottom of the pay card; "offer it to the whole team", much the
rarer choice, had a card of its own and the bigger gold button; and the
checklist a cleaner needs to do the work was a third card further down. An
owner trying to get somebody onto a job had to find all three, in that order,
past the hours-times-rate arithmetic that opened the card.

Now: one dropdown holding every cleaner AND the team, the pay beside it, and
the work order as a tickbox on the same press.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/onecard.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
mail, texts = [], []
notifications.send_email = lambda **k: (mail.append(k), (True, 'ok'))[1]
notifications.send_sms = lambda to, body: (texts.append((to, body)), (True, 'ok'))[1]

from app import create_app
from extensions import db
from models import Booking, Staff
import rbac

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def a_booking(**kw):
    b = Booking(service_type='standard', name='Eric Rosebro', email='eric@example.com',
                phone='+17165550100', status='confirmed', price=430.0,
                preferred_date='2026-11-02', address='1 Oak St', city='Huntsville',
                bedrooms=5, bathrooms=3, estimated_hours=1.5, **kw)
    db.session.add(b)
    db.session.commit()
    return b


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    maya = Staff(name='Maya Johnson', is_active=True,
                 email='maya@example.com', phone='+12565550111')
    trina = Staff(name='Trina Edwards', is_active=True,
                  email='trina@example.com', phone='+12565550112')
    db.session.add_all([maya, trina])
    db.session.commit()

    print('\n1. One control carries every way of answering "who is doing this?"')
    b = a_booking()
    page = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    chooser = page.split('id="assignTo"', 1)[1].split('</select>', 1)[0]
    check('Maya Johnson' in chooser and 'Trina Edwards' in chooser,
          'every available cleaner is in the dropdown')
    check('value="team"' in chooser, 'and so is offering it to the whole team')
    check('data-card-key="offer-team"' not in page, 'the separate Offer card is gone')
    check('data-card-key="work-order"' not in page, 'and so is the separate Checklist card')
    check('How this pay is worked out' in page,
          'the hours-times-rate arithmetic is folded away, not deleted')

    print('\n2. Assigning sends her the job and the checklist in one press')
    mail.clear(); texts.clear()
    r = c.post(f'/bookings/{b.id}/assign',
               data={'assign_to': str(maya.id), 'add_pay': '64.50', 'send_checklist': '1'},
               follow_redirects=True)
    check(r.status_code == 200, 'the form posts')
    db.session.refresh(b)
    check(len(b.crew) == 1 and b.crew[0].staff_id == maya.id, 'Maya is on the job')
    check(abs(b.crew[0].pay_amount - 64.50) < 0.01, 'at the pay that was typed')
    check(b.open_for_claim is False, 'and the job is off the claim board')
    check(bool(mail or texts), 'the work order actually went to her')

    print('\n3. Untick the box and she is put on the job quietly')
    b2 = a_booking()
    mail.clear(); texts.clear()
    c.post(f'/bookings/{b2.id}/assign', data={'assign_to': str(trina.id)},
           follow_redirects=True)
    db.session.refresh(b2)
    check(len(b2.crew) == 1, 'Trina is on the job')
    check(not mail and not texts, 'but nothing was sent to her')

    print('\n4. Blank pay falls back to the chart, it does not fail')
    b3 = a_booking()
    c.post(f'/bookings/{b3.id}/assign', data={'assign_to': str(maya.id)},
           follow_redirects=True)
    db.session.refresh(b3)
    check(len(b3.crew) == 1 and b3.crew[0].pay_amount > 0,
          f'pay was worked out for her: ${b3.crew[0].pay_amount:.2f}')

    print('\n5. A second cleaner raises the headcount instead of being refused')
    db.session.refresh(b)
    before = b.crew_size or 1
    c.post(f'/bookings/{b.id}/assign', data={'assign_to': str(trina.id)},
           follow_redirects=True)
    db.session.refresh(b)
    check(len(b.crew) == 2, 'both cleaners are on the job')
    check((b.crew_size or 1) > before,
          f'and the headcount went {before} → {b.crew_size} to make room')

    print('\n6. "Offer it to the whole team" still reaches the team')
    b4 = a_booking()
    texts.clear()
    r = c.post(f'/bookings/{b4.id}/assign', data={'assign_to': 'team'},
               follow_redirects=True)
    db.session.refresh(b4)
    check(r.status_code == 200 and b4.open_for_claim is True,
          'the job went on the claim board')

    print('\n7. Picking nobody is a warning, not a crash or a silent no-op')
    b5 = a_booking()
    r = c.post(f'/bookings/{b5.id}/assign', data={'assign_to': ''}, follow_redirects=True)
    db.session.refresh(b5)
    check(r.status_code == 200 and not b5.crew, 'nobody was assigned')
    check('Pick a cleaner' in r.get_data(as_text=True), 'and it says so')

    print('\n8. The combined control does not hand dispatch to a pay-only role')
    check(rbac.required_permission('bookings.assign', 'POST') == 'pay.manage',
          'assigning is registered under the money permission')
    check(not rbac.has_permission('dispatcher', 'pay.manage'),
          'a dispatcher has no pay permission, so cannot reach the endpoint at all')
    check(rbac.has_permission('owner', 'pay.manage')
          and rbac.has_permission('owner', 'dispatch.manage'),
          'and the owner holds both halves it needs')

if failures:
    print(f'\n❌ {len(failures)} failed')
    for f in failures:
        print('  -', f)
    raise SystemExit(1)
print('\n🎉 One card, one dropdown, one press.')
