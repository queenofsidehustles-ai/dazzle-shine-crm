"""A Sales rep's numbers: a daily call target, the owner's view of the team,
and the rep's own page with what they have earned.

What would go wrong without each of these:
  * "how many calls did Sam make this week" with no answer -- a lead only
    remembers its latest call, not who made it or when;
  * a rep's call sheet counting everybody's calls against their target, or
    stopping at twenty whatever the owner expects;
  * the owner setting a target of "abc", or a rep setting their own;
  * a rep seeing a teammate's numbers or commission;
  * a rep's page and the owner's commission report disagreeing about what the
    rep is owed;
  * a call at 9pm local filed under tomorrow, because it is stored in UTC.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import os
import pathlib
import sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_sales_rep_numbers')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append((a, k)) or (True, 'stub'))
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import (BusinessSetting, CommercialAccount, CommissionPayment, Prospect,
                    ProspectActivity, User)
from scheduling import local_today
import provisioning
import rep_activity
import tenancy
import va_commission

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SLUG = 'brisk'
HOST = f'http://{SLUG}.akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Brisk Cleaning', quiet=True)
    db.session.remove()
provisioning.seed(app, SLUG)
fresh_postgres.set_company_plan(SLUG, 'scale')
c = fresh_postgres.owner_client(app, SLUG, 'akye.test')
TODAY = local_today()


def rep_client(name, email):
    from auth import _auth_fingerprint
    with app.app_context(), tenancy.use_tenant(SLUG):
        u = User(name=name, username=email, role='sales', active=True)
        u.set_password('a-perfectly-fine-password')
        db.session.add(u)
        db.session.commit()
        uid, fp = u.id, _auth_fingerprint(u.password_hash)
        db.session.remove()
    client = app.test_client()
    with client.session_transaction(base_url=HOST) as sess:
        sess.update(logged_in=True, role='sales', user_id=uid, user_name=name,
                    auth_fingerprint=fp, tenant_slug=SLUG)
    return client, uid


def in_tenant(fn):
    with app.app_context(), tenancy.use_tenant(SLUG):
        try:
            return fn()
        finally:
            db.session.remove()


def lead_id(name):
    return in_tenant(lambda: Prospect.query.filter_by(business_name=name).first().id)


def acts(name, kind=None):
    def q():
        rows = ProspectActivity.query.filter_by(user_name=name)
        if kind:
            rows = rows.filter_by(kind=kind)
        return rows.count()
    return in_tenant(q)


def page(client, path):
    return client.get(path, base_url=HOST).get_data(as_text=True)


def text_of(html):
    """The words on a page, tags and line breaks out of the way."""
    import re
    return ' '.join(re.sub(r'<[^>]+>', ' ', html).split())


sam, sam_id = rep_client('Sam Sales', f'sam@{SLUG}.test')
riley, riley_id = rep_client('Riley Rep', f'riley@{SLUG}.test')
for name, phone in (('Numbers One Dental', '4045550401'), ('Numbers Two Gym', '4045550402'),
                    ('Numbers Three Office', '4045550403')):
    c.post('/find-leads/add', base_url=HOST, data={'business_name': name, 'category': 'office',
                                                   'phone': phone, 'city': 'Atlanta'})
one, two, three = (lead_id(n) for n in ('Numbers One Dental', 'Numbers Two Gym', 'Numbers Three Office'))
c.post('/find-leads/assign', base_url=HOST, data={'ids': [str(one), str(two)], 'agent': 'Sam Sales'})
c.post('/find-leads/assign', base_url=HOST, data={'ids': [str(three)], 'agent': 'Riley Rep'})
c.get('/find-leads/', base_url=HOST)   # (the assignments' messages)


print('\n1. Everything a rep does on a lead is written down, with who did it')
sam.post(f'/find-leads/call/{one}/log', base_url=HOST, data={'outcome': 'no_answer'})
sam.post(f'/find-leads/{two}/status', base_url=HOST, data={
    'mode': 'log', 'status': 'interested', 'log_note': 'Wants a look round',
    'walkthrough_date': (TODAY + timedelta(days=3)).isoformat()})
check(acts('Sam Sales', 'call') == 2, 'a call from the call sheet and one from the list are both counted')
check(acts('Sam Sales', 'walkthrough_booked') == 1, 'a call that books a walkthrough counts the booking too')
sam.post(f'/find-leads/{one}/text', base_url=HOST, data={'body': 'Hi, tried you earlier!'})
import blueprints.messages as _msgs
_real = _msgs.send_sms
_msgs.send_sms = lambda *a, **k: (False, 'carrier refused')
sam.post(f'/find-leads/{one}/text', base_url=HOST, data={'body': 'This one fails'})
_msgs.send_sms = _real
check(acts('Sam Sales', 'text') == 1, 'a text is counted when it went, not when it failed')
sam.post(f'/find-leads/{one}/walkthrough/book', base_url=HOST,
         data={'date': (TODAY + timedelta(days=2)).isoformat(), 'time': '10am'})
sam.post(f'/find-leads/{one}/walkthrough', base_url=HOST, data={'sqft': '2000', 'frequency': 'weekly',
                                                                 'services': ['floors']})
sam.post(f'/find-leads/{one}/walkthrough', base_url=HOST, data={'sqft': '2200', 'frequency': 'weekly',
                                                                 'services': ['floors']})
check(acts('Sam Sales', 'walkthrough_booked') == 2 and acts('Sam Sales', 'walkthrough') == 1,
      'a walkthrough booked and done -- saved twice, it is still one walkthrough')
check(acts('Sam Sales', 'handoff') == 1
      and sum('Ready to quote: Numbers One Dental' in str(k.get('subject', '')) for _a, k in SENT) == 1,
      'and the hand-off it made to the owner -- once, and one email, however often it is re-saved')
c.post(f'/find-leads/call/{three}/log', base_url=HOST, data={'outcome': 'voicemail'})
check(acts('Owner', 'call') == 1 and acts('Riley Rep') == 0,
      'the owner\'s own call is filed under the owner, not under the rep whose lead it is')
got = in_tenant(lambda: rep_activity.counts([sam_id], TODAY, TODAY)[sam_id])
check(got['call'] == 2 and got['conversations'] == 1,
      f'calls, and how many of them reached somebody ({got["call"]}, {got["conversations"]})')


print('\n2. Days are the business\'s days, not the server\'s')
def edge():
    start, end = rep_activity.utc_bounds(TODAY, TODAY)
    for when in (start - timedelta(minutes=1), start, end - timedelta(minutes=1), end):
        db.session.add(ProspectActivity(user_id=990001, user_name='Edge Case', kind='call', outcome='called',
                                        business_name='Edge', created_at=when))
    db.session.commit()
    return rep_activity.counts([990001], TODAY, TODAY)[990001]['call']
check(in_tenant(edge) == 2, 'a call a minute before local midnight is yesterday\'s; one at midnight is today\'s')


print('\n3. A daily target: the company\'s, or the rep\'s own')
check(in_tenant(rep_activity.default_target) == 20, 'twenty a day until the owner says otherwise')
body = page(sam, '/find-leads/')
check('2 of 20 calls today' in body and 'id="myProgress"' in body,
      'a rep\'s list opens with their calls today against their target')
check('📈 My numbers' in body and '👥 Team' not in body, 'and a way to their own numbers, not the team\'s')
check('2 of 20 calls today' in page(sam, f'/find-leads/call/{one}'), 'so does the call sheet')
check('id="myProgress"' not in page(c, '/find-leads/'), 'the owner has no target bar')

r = c.post('/find-leads/team/targets', base_url=HOST,
           data={'default': '3', f'target_{riley_id}': 'abc', f'target_{sam_id}': ''})
check(in_tenant(rep_activity.default_target) == 20,
      'a target that is not a number is refused, and nothing else on the form is saved either')
c.get('/find-leads/team', base_url=HOST)   # (the refusal)
c.post('/find-leads/team/targets', base_url=HOST,
       data={'default': '3', f'target_{riley_id}': '40', f'target_{sam_id}': ''})
targets = in_tenant(lambda: (rep_activity.default_target(),
                             rep_activity.target_for(db.session.get(User, sam_id)),
                             rep_activity.target_for(db.session.get(User, riley_id))))
check(targets == (3, 3, 40), f'the company\'s number, and a rep\'s own over it ({targets})')
c.post('/find-leads/team/targets', base_url=HOST, data={'default': '0'})
check(in_tenant(rep_activity.default_target) == 3, 'a target of nought is not a target')
c.get('/find-leads/team', base_url=HOST)   # (the refusal)
c.post('/find-leads/team/targets', base_url=HOST, data={'default': '', f'target_{riley_id}': '12'})
check(in_tenant(lambda: (rep_activity.default_target(), db.session.get(User, riley_id).daily_call_target)) == (3, 40),
      'nor is a blank company number -- refused, and the rep\'s change with it')
c.get('/find-leads/team', base_url=HOST)   # (the refusal)
check(sam.post('/find-leads/team/targets', base_url=HOST, data={f'target_{sam_id}': '1'}).status_code == 403
      and in_tenant(lambda: db.session.get(User, sam_id).daily_call_target) is None,
      'a rep cannot set their own target')

sam.post(f'/find-leads/call/{one}/log', base_url=HOST, data={'outcome': 'no_answer'})
done = page(sam, '/find-leads/call')
check('today\'s target of 3 made' in done, 'the call sheet stops at the rep\'s own target, with a "keep going"')
check('That\'s today\'s target' not in page(riley, '/find-leads/call'),
      'which is theirs: a teammate\'s calls do not count toward it')


print('\n4. The owner\'s Team page')
# A predecessor who had the same name: their calls are theirs, not Riley's.
def ghost():
    for _ in range(4):
        db.session.add(ProspectActivity(user_id=990002, user_name='Riley Rep', kind='call',
                                        outcome='called', business_name='Ghost Lead'))
    db.session.commit()
in_tenant(ghost)
team_html = page(c, '/find-leads/team?period=week')
team = text_of(team_html)
check('Ghost Lead' not in team and '0 of 40 calls today' in team,
      'a rep\'s numbers are their login\'s -- a former rep with the same name does not count toward them')
check(f'month={TODAY.year:04d}-{TODAY.month:02d}' in team_html,
      'the commission link opens the same month the card shows')
check('Sam Sales' in team and 'Riley Rep' in team and '3 of 3 calls today' in team and '0 of 40 calls today' in team,
      'each rep, with calls today against their target')
check('Sam Sales · Call' in team and 'Numbers One Dental' in team, 'and the latest of what they did')
check('Handed to you to quote' in team and '👥 Team' in page(c, '/find-leads/'),
      'what the calling turned into, from a Team tab on Find leads')
only = text_of(page(c, '/find-leads/team?rep=Riley+Rep'))
check('Sam Sales · Call' not in only, 'the feed can be narrowed to one rep')
check(sam.get('/find-leads/team', base_url=HOST).status_code == 403,
      'a rep cannot open the team page -- their numbers are between them and the owner')


print('\n5. A rep\'s own numbers and earnings')
def sign():
    # Noon UTC on the business's today: the same day and month on the business's
    # clock and on UTC's, whatever the hour the suite runs at. The commission report
    # counts months in UTC and this page picks its month by the business's day, so
    # a payment stamped in the first hours of the 1st is a different month to each.
    now = datetime.combine(TODAY, datetime.min.time()).replace(hour=12)
    db.session.add(CommercialAccount(business_name='Numbers Won Clinic', agent='Sam Sales', status='active',
                                     frequency='weekly', billing_type='monthly', billing_amount=1800,
                                     first_paid_at=now))
    db.session.add(CommercialAccount(business_name='Riley Won Bistro', agent='Riley Rep', status='active',
                                     frequency='weekly', billing_type='monthly', billing_amount=900,
                                     first_paid_at=now))
    last = (TODAY.replace(day=1) - timedelta(days=1))
    db.session.add(CommissionPayment(agent='Sam Sales', year=last.year, month=last.month, amount=42))
    db.session.commit()
    return va_commission.commission_for_month('Sam Sales', TODAY.year, TODAY.month)['total']
owed = in_tenant(sign)
me = text_of(page(sam, '/find-leads/me'))
check(f'${owed:.2f}' in me and 'Commercial signed — Numbers Won Clinic' in me,
      f'what they have earned this month, line by line -- the commission report\'s figure (${owed:.2f})')
check('✅ Paid' in me and '$42.00' in me, 'and whether last month has been paid out')
check('Riley Won Bistro' not in me and 'Riley Rep' not in me, 'never a teammate\'s accounts or numbers')
check('Ghost Lead' not in text_of(page(riley, '/find-leads/me')),
      'nor, on a rep\'s own page, the calls of somebody who had their name before them')
check('How I earn' in me and 'of 3 calls' in me and 'Became accounts' in me,
      'with how the commission is worked out, today against target, and their leads')
check(c.get('/find-leads/me', base_url=HOST).status_code == 302, 'the owner is sent to the Team page instead')
team = text_of(page(c, '/find-leads/team?period=month'))
check(f'${owed:.2f}' in team, 'and the owner sees the same figure on the Team page')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ A rep\'s calls are counted against their target, the owner sees the team, and the rep sees what they earned.')
