"""Golden payroll fixtures: what an imported team sheet pays, end to end.

P1-04 from the 25 Oct report (wage integrity): Excel percent cells, CSV,
blank pay and hourly rates, read by the real importer, saved by the real
save, and paid by the real pay rules -- each against a figure worked out by
hand. If one of these moves, a cleaner's pay moved: do not change the number
to make it pass; say in the commit that the change was meant.

  * 45% in an Excel percent cell is 45 points, not 0.45, and pays $90.00 of a $200 job
  * 7.5% pays $15.00; "45%" typed in a CSV pays the same as the Excel cell
  * $22.50 an hour pays $67.50 for 3 hours
  * a blank pay is saved as not set (never the 50% column default), and a
    job with nothing else to pay from is refused rather than offered at $0
"""
import io
import os
import sys
import tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/payroll.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
from app import create_app
from extensions import db
from models import Booking, BusinessSetting, Staff
import setup_assistant

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Name', 'Email', 'Commission'])
    for r in rows:
        ws.append(r)
    for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
        for c in row:
            if isinstance(c.value, float) and c.value < 1:
                c.number_format = '0.0%'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# (name, how the sheet says it, the file, pay_type, pay_rate stored)
FIXTURES = [
    ('Ana Lopez', 'Excel 45% cell', 'xlsx', 'percent', 45.0),
    ('Bo Chen', 'Excel 7.5% cell', 'xlsx', 'percent', 7.5),
    ('Cy Diaz', 'CSV "45%"', 'csv', 'percent', 45.0),
    ('Di Evans', 'CSV "$22.50" under Hourly rate', 'csv-hourly', 'hourly', 22.5),
    ('Ed Fox', 'CSV blank', 'csv', None, None),
]

with app.app_context():
    db.create_all()
    BusinessSetting.set('plan', 'scale'); BusinessSetting.set('plan_status', 'active')
    db.session.commit()

    print('\n1. Read by the importer')
    got = {}
    rows, err = setup_assistant.read_team_file('team.xlsx', xlsx(
        [['Ana Lopez', 'ana@x.test', 0.45], ['Bo Chen', 'bo@x.test', 0.075]]))
    check(err is None, 'the Excel file reads')
    got.update({r['name']: r for r in rows})
    rows, err = setup_assistant.read_team_file(
        'team.csv', b'Name,Email,Commission\nCy Diaz,cy@x.test,45%\nEd Fox,ed@x.test,\n')
    check(err is None, 'the CSV reads')
    got.update({r['name']: r for r in rows})
    rows, err = setup_assistant.read_team_file(
        'hourly.csv', b'Name,Email,Hourly rate\nDi Evans,di@x.test,$22.50\n')
    got.update({r['name']: r for r in rows})
    check(set(got) == {f[0] for f in FIXTURES}, f'every person came through ({sorted(got)})')

    print('\n2. Saved by the real save, all or nothing')
    ok, msg = setup_assistant.save_team({'others': [
        {k: got[n].get(k) for k in ('name', 'email', 'phone', 'pay_type', 'pay_rate')}
        for n in got]})
    check(ok, f'saved ({msg[:60]})')
    staff = {s.name: s for s in Staff.query.all()}
    for name, how, _f, ptype, rate in FIXTURES:
        s = staff.get(name)
        stored = (s.pay_type if s and s.pay_rate is not None else None,
                  float(s.pay_rate) if s and s.pay_rate is not None else None)
        check(stored == (ptype, rate), f'{how}: stored as {stored}, expected {(ptype, rate)}')

    print('\n3. Paid by the real rules')
    job = Booking(service_type='standard', name='Pat', price=200.0, status='confirmed')
    db.session.add(job); db.session.commit()
    for name, expect in (('Ana Lopez', 90.00), ('Bo Chen', 15.00), ('Cy Diaz', 90.00)):
        pay = staff[name].calc_pay(job_price=200.0)
        check(abs(pay - expect) < 0.005, f'{name} on a $200 job: ${pay:.2f} (expected ${expect:.2f})')
    pay = staff['Di Evans'].calc_pay(hours_worked=3)
    check(abs(pay - 67.50) < 0.005, f'Di Evans, 3 hours at $22.50: ${pay:.2f} (expected $67.50)')

    print('\n4. "Not set" is never paid as $0')
    ed = staff['Ed Fox']
    check(ed.pay_rate is None, 'a blank pay is saved as not set, not the 50% column default')
    check(job.pay_unset_for(ed), 'a job with nothing else to pay from is flagged for him')
    check(not job.pay_unset_for(staff['Ana Lopez']), 'and not for somebody whose pay is set')
    job.estimated_hours = 3; job.labor_rate_applied = 25; db.session.commit()
    check(not job.pay_unset_for(ed) and job.default_crew_pay(ed) == 75,
          'with hours on the job he is paid from them: 3 x $25 = $75')

print()
if failures:
    print(f'❌ {len(failures)} golden payroll figure(s) moved')
    sys.exit(1)
print('✅ every imported pay figure is the one worked out by hand')
