"""Business-development pay: a flat $80 for each walkthrough booked, weekly.

What counts: the first booking of a business, by a Sales login, on a day of the
week (Monday to Sunday, the business's own days). What does not: a second
booking of the same business, the owner's own bookings, a rep who is not a Sales
login. Paying a week is recorded once and flows into the books.
"""
import os, sys, tempfile
from datetime import date, datetime, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/walk.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
from extensions import db
from models import User, Prospect, ProspectActivity, WalkthroughPayment, BusinessSetting, PricingSetting
import entitlements
import walkthrough_pay as wp
import finance

app = create_app()
failures = []
H = {'Origin': 'http://localhost'}


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


def login(user=None):
    c = app.test_client()
    with c.session_transaction() as s:
        if user is None:
            s.update(logged_in=True, role='owner', user_name='Owner')
        else:
            from auth import _auth_fingerprint
            s.update(logged_in=True, role=user.role, user_id=user.id, user_name=user.name,
                     auth_fingerprint=_auth_fingerprint(user.password_hash))
    return c


def book(user, prospect, when):
    db.session.add(ProspectActivity(
        prospect_id=prospect.id, business_name=prospect.business_name,
        user_id=user.id if user else None, user_name=user.name if user else 'Owner',
        kind='walkthrough_booked', created_at=when))


def mk_user(name, role='sales', model=None):
    u = User(name=name, username=name.lower().replace(' ', '') + '@example.com',
             role=role, active=True, worker_model=model)
    u.set_password('x' * 12)
    db.session.add(u)
    db.session.commit()
    return u


with app.app_context():
    db.create_all()
    BusinessSetting.set('plan', 'scale')
    BusinessSetting.set('plan_status', 'active')
    BusinessSetting.set('timezone', 'America/New_York')
    db.session.commit()

    # A Monday well in the past, so "last week" logic is not what is under test.
    monday = date(2026, 9, 7)
    noon = lambda d, h=16: datetime(d.year, d.month, d.day, h)       # 16:00 UTC = noon in New York
    sam = mk_user('Sam Seller', model='contractor')
    ana = mk_user('Ana Closer', model='employee')
    boss = mk_user('Office Admin', role='admin')
    ps = []
    for i in range(8):
        p = Prospect(business_name=f'Biz {i}')
        db.session.add(p)
        ps.append(p)
    db.session.commit()

    print('1. The rate')
    check(wp.rate() == 80.0, 'a walkthrough is $80 until the owner says otherwise')
    check(wp.week_of(date(2026, 9, 13)) == monday and wp.week_of(monday) == monday,
          'a week runs Monday to Sunday')

    print('\n2. What is counted')
    book(sam, ps[0], noon(monday))
    book(sam, ps[1], noon(monday + timedelta(days=6)))          # Sunday, still this week
    book(sam, ps[2], noon(monday + timedelta(days=7)))          # next Monday
    book(ana, ps[3], noon(monday + timedelta(days=2)))
    book(None, ps[4], noon(monday + timedelta(days=1)))         # the owner's own
    book(boss, ps[5], noon(monday + timedelta(days=1)))         # not a Sales login
    book(sam, ps[3], noon(monday + timedelta(days=3)))          # Ana booked ps[3] first
    book(sam, ps[0], noon(monday + timedelta(days=4)))          # the same business again
    db.session.commit()
    got = wp.credited(monday)
    check(len(got.get(sam.id, [])) == 2, "Sam: two businesses, the second booking of Biz 0 is not paid again")
    check(len(got.get(ana.id, [])) == 1, 'Ana: one')
    check(set(got) == {sam.id, ana.id}, 'the owner and a non-Sales login are never paid this way')
    check(len(wp.credited(monday + timedelta(days=7)).get(sam.id, [])) == 1, "next Monday's booking is next week's")
    check(not any(r.business_name == 'Biz 3' for r in got.get(sam.id, [])),
          'a business a teammate booked first is theirs, not Sam\'s')

    print("\n3. The week's days are the business's days")
    late = Prospect(business_name='Late Sunday')
    db.session.add(late); db.session.commit()
    book(ana, late, datetime(2026, 9, 14, 2, 30))              # 22:30 Sunday in New York = still last week
    db.session.commit()
    check(len(wp.credited(monday).get(ana.id, [])) == 2, '10:30pm Sunday in New York is that Sunday, not Monday UTC')

    print('\n4. The statement')
    s = wp.statement(monday)
    by = {l['user'].name: l for l in s['lines']}
    check(by['Sam Seller']['amount'] == 160.0 and by['Ana Closer']['amount'] == 160.0, '2 x $80 each')
    check(s['owed'] == 320.0, 'and $320 owed in all')

    print('\n5. Paying a week')
    owner = login()
    page = owner.get(f'/commissions/walkthroughs?week={monday.isoformat()}')
    html = page.get_data(as_text=True)
    check(page.status_code == 200 and 'Sam Seller' in html and 'Contractor' in html and 'Employee' in html,
          'the owner sees each rep and whether they are an employee or a contractor')
    r = owner.post('/commissions/walkthroughs/mark-paid', headers=H,
                   data={'user_id': sam.id, 'week': monday.isoformat(), 'method': 'zelle', 'amount': '9999'})
    pay = WalkthroughPayment.query.filter_by(user_id=sam.id).one()
    check(float(pay.amount) == 160.0 and pay.walkthroughs == 2, 'the amount is worked out, never taken from the form')
    owner.post('/commissions/walkthroughs/mark-paid', headers=H,
               data={'user_id': sam.id, 'week': (monday + timedelta(days=3)).isoformat()})
    check(WalkthroughPayment.query.filter_by(user_id=sam.id).count() == 1, 'a second click does not pay the week twice')
    PricingSetting.set('va_walkthrough_booked', 100)
    db.session.commit()
    sam_line = [l for l in wp.statement(monday)['lines'] if l['user'].id == sam.id][0]
    check(sam_line['payment'] is not None and float(sam_line['payment'].amount) == 160.0,
          'a later change of rate does not rewrite a week already paid')
    owner.post('/commissions/walkthroughs/mark-paid', headers=H, data={'user_id': boss.id, 'week': monday.isoformat()})
    check(WalkthroughPayment.query.filter_by(user_id=boss.id).count() == 0, 'a non-Sales login cannot be paid this way')
    empty_week = (monday - timedelta(days=14)).isoformat()
    owner.post('/commissions/walkthroughs/mark-paid', headers=H, data={'user_id': ana.id, 'week': empty_week})
    check(WalkthroughPayment.query.filter_by(user_id=ana.id).count() == 0, 'a week with nothing booked is not payable')
    PricingSetting.set('va_walkthrough_booked', 80)
    db.session.commit()

    print('\n6. The books')
    pay.paid_at = datetime(2026, 9, 15, 12)
    db.session.commit()
    check(finance.commissions_paid_between(date(2026, 9, 1), date(2026, 9, 30)) == 160.0,
          'a paid week is an expense in that month\'s Profit & Loss')
    owner.post(f'/commissions/walkthroughs/unmark-paid/{pay.id}', headers=H)
    check(WalkthroughPayment.query.count() == 0, 'it can be undone')

    print('\n7. The rep sees their own')
    rep = login(sam)
    mine = rep.get('/find-leads/me').get_data(as_text=True)
    check('Walkthrough pay' in mine and '$80' in mine, 'My numbers shows the rate and the week')
    check(rep.get('/commissions/walkthroughs').status_code in (302, 401, 403), 'a rep cannot open the owner\'s pay page')
    check(rep.post('/commissions/walkthroughs/mark-paid', headers=H,
                   data={'user_id': sam.id, 'week': monday.isoformat()}).status_code in (302, 401, 403)
          and WalkthroughPayment.query.count() == 0, 'or mark themselves paid')

    print('\n8. The rate is a setting')
    st = owner.get('/commissions/settings').get_data(as_text=True)
    check('va_walkthrough_booked' in st, 'the owner can change it with the other rates')

print()
if failures:
    print(f'{len(failures)} FAILED:'); [print(' -', f) for f in failures]; sys.exit(1)
print('🎉 Walkthrough pay holds.')
