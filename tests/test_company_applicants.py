"""A cleaning company applying is a vendor, not a hire.

The application asked how many years somebody had been cleaning and whether
they had their own car, and auto-rejected the wrong answers. Both are the
right question for a person and the wrong one for a company with its own LLC,
its own crew and its own vans -- which is who has actually been applying.

The interesting half is not the extra fields. It is that a real subcontractor
was being turned away by a form, and that the paperwork which replaces those
questions has dates on it.
"""
import os, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/co.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append('e'), (True, 'stub'))[1]
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_triggered_email = lambda *a, **k: (SENT.append('t'), (True, 'stub'))[1]

from app import create_app
from extensions import db
from models import ContractorApplication as CA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


with app.app_context():
    db.create_all()
c = app.test_client()

COMPANY = {
    'applicant_kind': 'company', 'name': 'Dana Ofori',
    'email': 'dana@harborside.test', 'phone': '4075551212',
    'company_name': 'Harborside Cleaning LLC', 'ein': '12-3456789',
    'crew_size': '4', 'service_areas': 'Orlando, Winter Park',
    'has_liability_insurance': 'on', 'insurance_carrier': 'State Farm',
    'insurance_expires': '2027-03-01', 'workers_comp': 'yes',
    'workers_comp_expires': '2027-01-15', 'business_license': 'ORL-99231',
    'crew_checks_agreed': 'on', 'agrees_to_ic_terms': 'on',
}

print('\n1. A company is not rejected for failing an individual\'s test')
# No years of personal cleaning experience, no personal car ticked. Under the
# old rules this was an automatic rejection email to a real subcontractor.
r = c.post('/contractors/apply', data=COMPANY, follow_redirects=True)
check(r.status_code == 200, 'the application is accepted')
with app.app_context():
    a = CA.query.filter_by(email='dana@harborside.test').first()
    check(a is not None, 'and saved')
    check(a.status != 'rejected',
          f'and not auto-rejected ({a.status})')
    check(a.applicant_kind == 'company', 'recorded as a company')

print('\n2. The paperwork that replaces those questions')
with app.app_context():
    a = CA.query.filter_by(email='dana@harborside.test').first()
    check(a.company_name == 'Harborside Cleaning LLC' and a.ein == '12-3456789',
          'who they are, and their tax number')
    check(a.crew_size == '4' and 'Orlando' in (a.service_areas or ''),
          'how many cleaners, and where they work')
    # The dates are the point. A certificate collected once and never looked
    # at again is worse than none, because by then you believe you are covered.
    check(a.has_liability_insurance and a.insurance_expires == '2027-03-01',
          'general liability, and when it stops being true')
    check(a.workers_comp == 'yes' and a.workers_comp_expires == '2027-01-15',
          "workers' compensation, and when that stops too")
    check(a.business_license == 'ORL-99231', 'and the licence number')

print('\n3. Their cleaners are still checked')
with app.app_context():
    a = CA.query.filter_by(email='dana@harborside.test').first()
    check(a.crew_checks_agreed is True,
          'the company agrees its cleaners are background checked')
form = open(os.path.join(ROOT, 'templates', 'public', 'apply.html')).read()
check("before entering a customer's home" in form,
      'and the form says so plainly, because companies assume it is waived')

print('\n4. A person reads it, not an automated interview')
with app.app_context():
    a = CA.query.filter_by(email='dana@harborside.test').first()
    # The video interview asks somebody about their own cleaning. A company
    # needs its certificates read, and the insurance is the part that has to
    # be checked before anybody is sent to a customer's house.
    check(a.status == 'reviewing', 'it lands for review')
    check('certificate of insurance' in (a.admin_notes or '').lower(),
          'with a note saying what to check first')
    check(a.interview_status != 'pending',
          'and no automated interview invite is scheduled')

print('\n5. An individual application is exactly as it was')
r = c.post('/contractors/apply', data={
    'name': 'Ama Mensah', 'email': 'ama@x.test', 'phone': '4075550000',
    'years_experience': '3-5 years', 'has_transportation': 'on',
    'agrees_to_ic_terms': 'on'}, follow_redirects=True)
with app.app_context():
    a = CA.query.filter_by(email='ama@x.test').first()
    check(a is not None and a.applicant_kind == 'individual',
          'somebody applying as themselves is still an individual')
    check(a.status != 'rejected', 'and passes as before')
    check(a.company_name is None, 'with none of the company fields set')

# And the filter still works on the people it was written for.
r = c.post('/contractors/apply', data={
    'name': 'No Car', 'email': 'nocar@x.test', 'phone': '4075550002',
    'years_experience': '3-5 years', 'agrees_to_ic_terms': 'on'},
    follow_redirects=True)
with app.app_context():
    a = CA.query.filter_by(email='nocar@x.test').first()
    check(a.status == 'rejected',
          'an individual with no transport is still turned down')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ A company is onboarded as a company.')
