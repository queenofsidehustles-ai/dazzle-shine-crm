"""Certificates stop being true, and somebody has to be told before they do.

Collecting a subcontractor's insurance once is not the same as being covered.
A certificate taken in March and never looked at again is worse than none,
because by then you believe you are covered -- and the day you find out is the
day somebody has already been sent to a customer's house uninsured.
"""
import os, sys, tempfile
from datetime import date, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/ins.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['REMINDER_API_KEY'] = 'testkey'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
MAIL = []
notifications.send_email = lambda to, n, s, b, **k: (MAIL.append((to, s, b)), (True, 'ok'))[1]
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import BusinessSetting, ContractorApplication as CA

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


T = date.today()


def d(days):
    return (T + timedelta(days=days)).isoformat()


with app.app_context():
    db.create_all()
    BusinessSetting.set('email', 'monica@kojo.test')
    for co, ins, wc, status in [
        ('Harborside LLC',  d(-3),  d(200), 'hired'),
        ('Beacon Cleaning', d(4),   d(90),  'hired'),
        ('Lakeside Crew',   d(22),  None,   'reviewing'),
        ('Far Off Ltd',     d(300), d(300), 'hired'),
        ('Turned Down Co',  d(-1),  None,   'rejected'),
    ]:
        db.session.add(CA(name=co, email=co.replace(' ', '').lower() + '@x.test',
                          applicant_kind='company', company_name=co,
                          status=status, insurance_expires=ins,
                          workers_comp_expires=wc))
    # Somebody applying as themselves has no certificates to watch.
    db.session.add(CA(name='Ama Mensah', email='ama@x.test',
                      applicant_kind='individual', status='hired'))
    db.session.commit()

    import compliance

    print('\n1. Worst first, because that is the order you act in')
    rows = compliance.expiring(today=T)
    names = [(r['company'], r['band']) for r in rows]
    check(names[0] == ('Harborside LLC', 'expired'),
          f'an expired certificate leads ({names[0]})')
    check(('Beacon Cleaning', 'urgent') in names, 'then the one running out this week')
    check(('Lakeside Crew', 'soon') in names, 'then the one to ask about')
    check(not any(c == 'Far Off Ltd' for c, _ in names),
          'and nothing about a policy that is fine for months')

    print('\n2. Only people you would actually send work to')
    # Chasing a certificate belonging to somebody turned down eight months ago
    # is noise, and noise is how a real warning gets ignored.
    check(not any(c == 'Turned Down Co' for c, _ in names),
          'a rejected company is not chased, even with expired cover')
    check(not any(c == 'Ama Mensah' for c, _ in names),
          'and an individual has no certificates to expire')

    print('\n3. A blank is not reassuring')
    gaps = {g['company'] for g in compliance.missing()}
    check('Lakeside Crew' in gaps,
          'a company with nothing on file at all is listed separately')
    check('Ama Mensah' not in gaps, 'and individuals are left out of that too')

    print('\n4. It says what to do, not just what is wrong')
    worst = compliance.sentence(rows[0])
    check('Do not send them work' in worst,
          f'an expired certificate says to stop sending work ({worst[:60]}…)')
    check('3 days ago' in worst, 'and how long it has been true')

c = app.test_client()

print('\n5. The nightly run')
check(c.post('/api/insurance-expiry', headers={'X-Api-Key': 'wrong'}).status_code == 403,
      'the wrong key is refused')
MAIL.clear()
r = c.post('/api/insurance-expiry', headers={'X-Api-Key': 'testkey'})
body = r.get_json()
check(r.status_code == 200 and body['expiring'] == 3,
      f'the right key runs it ({body})')
check(len(MAIL) == 1, 'and sends one email, not one per company')
to, subject, html = MAIL[0]
check(to == 'monica@kojo.test', 'to the business, not to the subcontractor')
# The subject is all that gets read on a phone before somebody decides whether
# to open it, so it carries the worst of what is inside.
check('uninsured' in subject.lower(),
      f'with the worst of it in the subject ({subject})')
check('Harborside' in html and 'Beacon' in html, 'and every company listed')
check('Nobody has been emailed about this except you' in html,
      'saying plainly that the subcontractor was not contacted')

print('\n6. Silence when there is nothing to say')
# An email every morning saying "nothing expiring" is how the one that matters
# stops being read.
with app.app_context():
    CA.query.filter(CA.applicant_kind == 'company').delete()
    db.session.commit()
MAIL.clear()
r = c.post('/api/insurance-expiry', headers={'X-Api-Key': 'testkey'})
check(r.get_json()['expiring'] == 0 and not MAIL,
      'nothing expiring means no email at all')

print('\n7. A business can switch it off, like every other job')
import automations
check(any(k == 'insurance-expiry' for k, _l, _b, _c in automations.JOBS),
      'it is a job on the automations page')
check([c for k, _l, _b, c in automations.JOBS if k == 'insurance-expiry'] == ['daily'],
      'and it runs daily')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ Nobody is sent to a house on a certificate that ran out.')
