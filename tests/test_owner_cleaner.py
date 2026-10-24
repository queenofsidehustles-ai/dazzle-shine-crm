"""The owner is their own first cleaner.

A new owner often has nobody to hire yet, and a job can only be assigned to a
team row, so "add a cleaner" used to be a step they had to invent somebody for.
Signup now makes the owner that row (owner_cleaner.py). This walks the parts
that would go wrong if it were only half done:

  * the row exists, is the owner's, and is not a contractor to chase or pay;
  * setup no longer asks for a cleaner, and activation is a customer plus a job;
  * the owner is not on their own payroll or 1099 list, and nothing is queued
    to pay them for their own work.
"""
import os, sys, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def postgres_url():
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      'postgresql://app_user:localtest@127.0.0.1:5432/postgres',
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres'):
        if not candidate:
            continue
        try:
            from sqlalchemy import create_engine, text
            e = create_engine(candidate)
            with e.connect() as c:
                c.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n  ⚠️  SKIPPED: needs PostgreSQL schemas and found no server.\n')
    sys.exit(0)

DB = 'dsm_owner_cleaner_test'
TEST_URL = f'{PG.rsplit("/", 1)[0]}/{DB}'

from sqlalchemy import create_engine, text
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as c:
    c.execute(text(f'DROP DATABASE IF EXISTS {DB}'))
    c.execute(text(f'CREATE DATABASE {DB}'))

env = dict(os.environ, DATABASE_URL=TEST_URL, SECRET_KEY='test',
           BASE_DOMAIN='rollcall.test', SIGNUPS_OPEN='1')
env.pop('ADMIN_USER', None)
env.pop('ADMIN_PASS', None)


def run(code, label):
    r = subprocess.run([sys.executable, '-c', code], capture_output=True,
                       text=True, cwd=ROOT, env=env)
    if 'OK' not in r.stdout:
        raise AssertionError(f'{label}:\n{r.stdout}\n{r.stderr}')
    return r.stdout


STUB = '''
import notifications
notifications.send_sms = lambda *a, **k: (True, "s")
notifications.send_email = lambda *a, **k: (True, "s")
'''

print('\n1. Signing up makes the owner their first cleaner')
out = run(STUB + '''
from app import create_app
app = create_app()
c = app.test_client()
r = c.post("/signup", data={
    "business": "Sparkle Cleaning Services", "slug": "sparkle",
    "name": "Dana Reed", "email": "dana@sparkle.test",
    "password": "a-perfectly-fine-password", "terms_accepted": "1",
    "zip_code": "32801",
}, headers={"Host": "rollcall.test"})
print("REDIRECT:", r.status_code)
import tenancy
with app.app_context():
    with tenancy.use_tenant("sparkle"):
        from models import Staff, User
        rows = Staff.query.all()
        print("ROWS:", len(rows))
        s = rows[0]
        owner = User.query.filter_by(role="owner").first()
        print("NAME:", s.name)
        print("IS OWNER:", s.is_owner, "ACTIVE:", s.is_active)
        print("LINKED:", s.user_id == owner.id)
        print("PAY:", float(s.pay_rate))
        print("MY DAY LINK:", bool(s.agreement_token), "NO AGREEMENT:", s.agreement_signed_at is None)
print("OK")
''', 'signup')
check('REDIRECT: 302' in out, 'signup still works')
check('ROWS: 1' in out and 'NAME: Dana Reed' in out, 'one team row, named for the owner')
check('IS OWNER: True ACTIVE: True' in out, 'marked as the owner and active')
check('LINKED: True' in out, 'linked to their login')
check('PAY: 0.0' in out, 'and not paid')
check('MY DAY LINK: True NO AGREEMENT: True' in out,
      'with a My day link, and no contractor agreement to chase')

print('\n2. Setup asks for a customer and a job, not a cleaner')
out = run(STUB + '''
from app import create_app
app = create_app()
import tenancy
with app.test_request_context("/", headers={"Host": "sparkle.rollcall.test"}):
    pass
with app.app_context():
    with tenancy.use_tenant("sparkle"):
        import onboarding, owner_cleaner
        steps = {s["key"]: s for s in onboarding.journey()}
        order = [s["key"] for s in onboarding.journey() if not s.get("required")]
        print("ORDER:", order)
        print("TEAM DONE:", steps["team"]["done"])
        print("HIRED:", owner_cleaner.hired_team_count())
        print("ACTIVATED:", onboarding.progress()["activated"])
        print("CHECKLIST TEAM:", [i["done"] for i in onboarding.checklist() if i["key"] == "team"][0])
print("OK")
''', 'journey')
check("ORDER: ['payments', 'booking_page', 'client', 'job', 'team']" in out,
      'customer, then job, then (when you hire) a team member')
check('TEAM DONE: False' in out and 'HIRED: 0' in out,
      'the owner alone is not "a team", so the hire step stays an offer')
check('ACTIVATED: False' in out, 'nothing is activated until a customer and a job exist')
check('CHECKLIST TEAM: False' in out, 'the older checklist agrees')

print('\n3. A customer and a job given to yourself is activated, and costs nothing to pay')
out = run(STUB + '''
from app import create_app
app = create_app()
import tenancy
with app.app_context():
    with tenancy.use_tenant("sparkle"):
        from extensions import db
        from models import Staff, Client, Booking
        import onboarding, contractor_pay
        me = Staff.query.filter_by(is_owner=True).first()
        cl = Client(name="Pat Lee", email="pat@example.test", phone="5551112222")
        db.session.add(cl); db.session.commit()
        b = Booking(client_id=cl.id, service_type="standard", name="Pat Lee",
                    email="pat@example.test", preferred_date="2026-11-02",
                    assigned_cleaner=me.name, status="completed", price=150, estimated_hours=3)
        db.session.add(b); db.session.commit()
        print("ACTIVATED:", onboarding.progress()["activated"])
        print("SUGGESTED:", b.default_crew_pay(me))
        print("OWED:", contractor_pay.staff_for_booking(b))
        print("QUEUED:", len(contractor_pay.queue_for_booking(b)))
print("OK")
''', 'activation')
check('ACTIVATED: True' in out, 'a customer plus a job assigned to yourself is activated')
check('SUGGESTED: 0.0' in out, 'the suggested pay for the owner is nothing')
check('OWED: []' in out and 'QUEUED: 0' in out, 'and nobody is queued to be paid for it')

print('\n4. Not on their own tax forms or payroll; ensure() adds no second row')
out = run(STUB + '''
from app import create_app
app = create_app()
import tenancy
with app.app_context():
    with tenancy.use_tenant("sparkle"):
        from models import Staff, User
        import owner_cleaner
        again = owner_cleaner.ensure(User.query.filter_by(role="owner").first())
        print("ROWS:", Staff.query.count(), "SAME:", again.is_owner)
        from extensions import db
        db.session.add(Staff(name="Maria Gomez", is_active=True)); db.session.commit()
        print("HIRED:", owner_cleaner.hired_team_count())
print("OK")
''', 'ensure')
check('ROWS: 1 SAME: True' in out, 'ensure() is idempotent')
check('HIRED: 1' in out, 'a real hire is counted, and only that')

src = open(os.path.join(ROOT, 'blueprints', 'money.py')).read()
check('Staff.is_owner.isnot(True)' in src, 'the 1099 list leaves the owner out')
src = open(os.path.join(ROOT, 'blueprints', 'contractors.py')).read()
check('the owner is not on their own payroll' in src, 'and so does payroll')
src = open(os.path.join(ROOT, 'lifecycle.py')).read()
check(src.count('s.is_owner') >= 2, 'and the insurance and onboarding reminders')

print('\n5. The owner gets the day-before reminder and a My day page')
out = run(STUB + '''
from app import create_app
app = create_app()
import tenancy
from datetime import timedelta
with app.app_context():
    with tenancy.use_tenant("sparkle"):
        from extensions import db
        from models import Staff, Booking, BusinessSetting
        import lifecycle, scheduling, notifications
        me = Staff.query.filter_by(is_owner=True).first()
        tomorrow = (scheduling.local_today() + timedelta(days=1)).isoformat()
        db.session.add(Booking(service_type="standard", name="Sam Ortiz", email="sam@example.test",
                               preferred_date=tomorrow, assigned_cleaner=me.name, status="confirmed"))
        BusinessSetting.set("phone", "5553334444")
        db.session.commit()
        sent = []
        lifecycle._send_transactional = lambda key, to, name, ctx: sent.append(("email", key, to))
        notifications.send_sms = lambda to, body, *a, **k: (sent.append(("sms", to)) or (True, "s"))
        n = lifecycle.send_cleaner_schedule_reminders()
        print("REMINDERS:", n, sent)
        token = me.agreement_token
c = app.test_client()
r = c.get("/contractors/my-day/" + token, headers={"Host": "sparkle.rollcall.test"})
print("MY DAY:", r.status_code, "Sam Ortiz" in r.get_data(as_text=True))
print("OK")
''', 'reminder')
check("REMINDERS: 1" in out and "('email', 'cleaner_schedule_reminder', 'dana@sparkle.test')" in out,
      'the owner gets the day-before email for their own job')
check("('sms', '5553334444')" in out, 'and a text, to the business phone they gave')
check('MY DAY: 200 True' in out, 'and My day shows them their jobs')

print('\n6. An explicit crew split cannot pay the owner, and a blank assignment is no assignment')
out = run(STUB + '''
from app import create_app
app = create_app()
import tenancy
with app.app_context():
    with tenancy.use_tenant("sparkle"):
        from extensions import db
        from models import Staff, Booking, BookingCrew
        import onboarding, contractor_pay
        me = Staff.query.filter_by(is_owner=True).first()
        b = Booking.query.first()
        db.session.add(BookingCrew(booking_id=b.id, staff_id=me.id, pay_amount=40))
        db.session.commit()
        print("CREW PAY:", b.pay_for(me), contractor_pay.summary_for(me)["owed"])
        BookingCrew.query.delete()
        Booking.query.update({"assigned_cleaner": ""})
        db.session.commit()
        job = [s for s in onboarding.journey() if s["key"] == "job"][0]
        print("BLANK ASSIGNED:", job["done"])
        Booking.query.update({"assigned_cleaner": me.name})
        db.session.commit()
        job = [s for s in onboarding.journey() if s["key"] == "job"][0]
        print("NAMED ASSIGNED:", job["done"])
print("OK")
''', 'review findings')
check('CREW PAY: 0.0 0.0' in out, 'a typed crew split still earns the owner nothing, on My day and in what is owed')
check('BLANK ASSIGNED: False' in out, 'an empty cleaner field is not an assignment')
check('NAMED ASSIGNED: True' in out, 'a named one is')

print('\n✅ The owner starts as their own first cleaner, and nothing treats them as a contractor.')
