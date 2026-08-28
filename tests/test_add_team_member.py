"""Putting someone on the team without running them through hiring.

Not everyone arrives through an application. Some you meet on Nextdoor, some
are rehires, and the job is on Thursday. The route to add them directly existed
but nothing linked to it, so the only visible way onto the team was the full
pipeline — application, offer, background check, hire — and until a Staff row
exists they don't appear in the job assignment list at all.

Pay is the other half. It wasn't asked for on that form, so anyone added this
way silently became 50% of the job, which is the model default and a real amount
of money to decide by accident.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/team.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Staff, Booking
app = create_app()

# PLAN FOR THIS TEST. A fresh database starts on the free plan, which allows two
# cleaners and sends no texts -- correct for a brand-new signup, and not what
# this file is about. Say which plan is being exercised rather than leaving it
# to a default that will change again.
with app.app_context():
    from models import BusinessSetting as _BS
    from extensions import db as _db
    _BS.set('plan', 'scale')
    _BS.set('plan_status', 'active')
    _db.session.commit()
import entitlements as _ent
_ent._clear_cache()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. The team page offers a way on that is not the hiring pipeline')
    page = c.get('/contractors/team').get_data(as_text=True)
    check('/staff/new' in page,
          'there is a link to add someone directly — there was no link at all before')

    print('\n2. Adding someone takes their pay rather than assuming it')
    form = c.get('/staff/new').get_data(as_text=True)
    check('name="pay_type"' in form and 'name="pay_rate"' in form,
          'the form asks how they are paid')
    check('skips the application' in form,
          'and says plainly what it is skipping, so it is a choice not a surprise')

    r = c.post('/staff/new', data={
        'name': 'Nextdoor Neighbour', 'phone': '407 555 7788',
        'email': 'neighbour@example.com', 'color': '#7c3aed',
        'pay_type': 'hourly', 'pay_rate': '$22.50', 'is_active': 'on',
    }, follow_redirects=True)
    check(r.status_code == 200, 'she is added')
    s = Staff.query.filter_by(email='neighbour@example.com').first()
    check(s is not None, 'a team record exists')
    check(s.pay_type == 'hourly' and s.pay_rate == 22.50,
          'paid what was agreed, not the 50% default')
    check(s.is_active, 'and active')

    print('\n3. Which is the whole point — she can be given a job')
    b = Booking(service_type='deep', name='A Customer', price=300,
                email='cust@example.com', address='1 St', preferred_date='2026-08-28')
    db.session.add(b); db.session.commit()
    detail = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('Nextdoor Neighbour' in detail,
          'she appears in the job assignment list on a booking')

    print('\n4. A typed rate is read the way a person would type it')
    for n, (typed, expect) in enumerate((('50%', 50.0), ('$18', 18.0),
                                         ('  27.5 ', 27.5))):
        who = f'Rate Test {n}'
        c.post('/staff/new', data={'name': who, 'pay_type': 'percent',
                                   'pay_rate': typed, 'is_active': 'on'},
               follow_redirects=True)
        got = Staff.query.filter_by(name=who).first()
        check(got.pay_rate == expect, f'"{typed}" is read as {expect}')

    c.post('/staff/new', data={'name': 'Fat Finger', 'pay_type': 'percent',
                               'pay_rate': 'abc', 'is_active': 'on'},
           follow_redirects=True)
    check(Staff.query.filter_by(name='Fat Finger').first().pay_rate == 50.0,
          'nonsense falls back to the default instead of 500-ing mid-hire')

    print('\n5. Editing someone does not quietly reset their pay')
    # The form posts pay now, so the edit route has to save it — otherwise
    # changing a phone number would silently put a rate back to 50%.
    r = c.post(f'/staff/{s.id}', data={
        'name': s.name, 'phone': '407 555 0000', 'email': s.email,
        'color': s.color, 'pay_type': 'hourly', 'pay_rate': '25', 'is_active': 'on',
    }, follow_redirects=True)
    s = Staff.query.get(s.id)
    check(s.phone == '407 555 0000', 'the edit saves')
    check(s.pay_rate == 25.0 and s.pay_type == 'hourly',
          'and the pay comes with it rather than reverting')

    print('\n6. Deactivating takes them out of the assignment list')
    c.post(f'/staff/{s.id}', data={'name': s.name, 'email': s.email,
                                   'pay_type': 'hourly', 'pay_rate': '25'},
           follow_redirects=True)
    s = Staff.query.get(s.id)
    check(not s.is_active, 'unticking Active deactivates them')
    detail = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('Nextdoor Neighbour' not in detail, 'and they drop off the job picker')

    print('\nAll add-team-member checks passed.')
