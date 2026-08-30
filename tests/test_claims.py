"""Sending a job to the team, and the first cleaner to take it keeping it.

This is the feature no competitor has, and it had no test at all. That was
found the hard way: a helper function got inserted between `@route` and the
view it decorates, so Flask registered the helper as the handler and every
claim link in the field returned "Something went wrong on our end". Nothing
went red. It surfaced because a screenshot for the marketing site happened to
capture the error page.

What is worth protecting here:

  * the page renders for a cleaner holding a real link
  * the pay on it is the pay she will actually be owed
  * the full address is NOT on the page before she takes the job -- a
    broadcast goes to everybody, and it must not be a list of the customers'
    home addresses
  * exactly one person can win a plain job
  * somebody already booked elsewhere at that hour is told before they claim
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/claims.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_sms = lambda to, body, **k: (SENT.append((to, body)), (True, 'stub'))[1]
notifications.send_email = lambda *a, **k: (True, 'stub')

from datetime import date, timedelta
from app import create_app
from extensions import db
from models import Booking, Staff

app = create_app()

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def fresh():
    """A job nobody is on, and three cleaners who could take it."""
    with app.app_context():
        db.drop_all()
        db.create_all()
        crew = []
        for i, name in enumerate(('Maria Alvarez', 'Jennifer Whitfield', 'Rosa Nguyen')):
            s = Staff(name=name, email=f'c{i}@example.com', phone=f'40755510{i:02d}',
                      is_active=True, pay_type='percent', pay_rate=50.0,
                      worker_model='contractor')
            db.session.add(s)
            crew.append(s)
        b = Booking(name='Sunrise Daycare', email='d@example.com', phone='4075559999',
                    address='3300 Colonial Drive', city='Fairview', zip_code='32803',
                    service_type='commercial', price=430.0, balance_due=430.0,
                    estimated_hours=5.0, status='confirmed',
                    preferred_date=TOMORROW, preferred_time='8:30 AM')
        db.session.add(b)
        db.session.commit()
        return b.id, [s.id for s in crew]


print('\n1. Sending a job out texts the team a personal link')
bid, sids = fresh()
with app.app_context():
    import blueprints.claims as claims
    b = db.session.get(Booking, bid)
    SENT.clear()
    sent = claims.broadcast_job(b)
    b = db.session.get(Booking, bid)
    check(b.open_for_claim is True, 'the job is on the board')
    check(bool(b.claim_token), 'and has a claim token')
    check(sent == 3, f'all three cleaners were texted (got {sent})')
    check(all('/claim/' in body for _, body in SENT),
          'and each text carries a claim link')
    # Each link must be personal: two cleaners must not share one.
    links = {body.split('/claim/')[1].split()[0] for _, body in SENT}
    check(len(links) == 3, 'the links differ per cleaner, so we know who claimed')
    ctoken = b.claim_token
    stokens = []
    for sid in sids:
        stokens.append(db.session.get(Staff, sid).agreement_token)

c = app.test_client()

print('\n2. The claim page renders — this is the one that was returning 500')
r = c.get(f'/claim/{ctoken}/{stokens[0]}')
body = r.data.decode('utf8', 'replace')
check(r.status_code == 200, f'the page loads (HTTP {r.status_code})')
check('went wrong' not in body, 'and is not the error page')
check('Claim this job' in body, 'with a button to take the job')

print('\n3. It says what the job pays, before anybody commits')
with app.app_context():
    b = db.session.get(Booking, bid)
    s = db.session.get(Staff, sids[0])
    expected = b.default_crew_pay(s) if b.is_crew_job else b.pay_for(s)
check(f'{expected:.2f}' in body,
      f'the page shows ${expected:.2f}, the figure she will actually be owed')

print('\n4. The address is withheld until somebody owns the job')
# A broadcast goes to every active cleaner. If the street address were on it,
# one text would hand the whole customer list to anybody who ever worked here.
check('3300 Colonial' not in body,
      'the street address is NOT on an unclaimed job')
check('Fairview' in body, 'the area is, which is enough to decide')

print('\n5. Exactly one person can win a plain job')
# Taking the job is a POST to .../claim -- the bare URL is the page itself.
r1 = c.post(f'/claim/{ctoken}/{stokens[0]}/claim', follow_redirects=True)
r2 = c.post(f'/claim/{ctoken}/{stokens[1]}/claim', follow_redirects=True)
with app.app_context():
    b = db.session.get(Booking, bid)
    winner = b.assigned_cleaner
    check(winner == 'Maria Alvarez',
          f'the first to claim holds it (assigned: {winner!r})')
    check(b.open_for_claim is False, 'and the job comes off the board')

second = r2.data.decode('utf8', 'replace')
check('Claim this job' not in second,
      'the second cleaner is not offered a button for a job already gone')

print('\n6. Now that it is hers, she gets the address')
mine = c.get(f'/claim/{ctoken}/{stokens[0]}').data.decode('utf8', 'replace')
check('3300 Colonial' in mine, 'the full address appears for the cleaner who owns it')

print('\n7. Somebody already working at that hour is warned')
bid2, sids2 = fresh()
with app.app_context():
    import blueprints.claims as claims
    # Give the first cleaner a job at the same time on the same day.
    clash = Booking(name='Other Customer', email='o@example.com', phone='4075558888',
                    address='9 Pine Avenue', city='Fairview', zip_code='32803',
                    service_type='standard', price=200.0, status='confirmed',
                    preferred_date=TOMORROW, preferred_time='8:30 AM',
                    assigned_cleaner='Maria Alvarez')
    db.session.add(clash)
    db.session.commit()
    b2 = db.session.get(Booking, bid2)
    claims.broadcast_job(b2)
    b2 = db.session.get(Booking, bid2)
    t2 = b2.claim_token
    st2 = db.session.get(Staff, sids2[0]).agreement_token
    reason = claims.clash_reason(db.session.get(Staff, sids2[0]), b2)
check(bool(reason), f'a double-booking is detected ({reason!r})')
import html as _html
# The apostrophe in "can't" is escaped in the markup; compare the text a
# person actually reads, not the bytes.
page = _html.unescape(c.get(f'/claim/{t2}/{st2}').data.decode('utf8', 'replace'))
check(reason in page,
      'and the exact warning is on the claim page, before she takes it')
check('two places at once' in page,
      'in words rather than a code')


if failures:
    print(f'\n\n❌ {len(failures)} claim check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Broadcast and claim work end to end.\n')
