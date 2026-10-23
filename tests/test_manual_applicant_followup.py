"""An applicant typed in by hand must not be silently unreachable.

A candidate applied through Indeed, never reached the pipeline (the advert's
apply link 404'd, so Indeed's own Apply button was used instead), and was added
to the CRM by hand. No interview link ever went out.

The cause was the manual-add form's Experience dropdown. Its first option is
"Unknown" with a value of "", and it is the default. The applicant-followups
backstop -- the thing whose entire job is catching anybody who never got a link
-- required a non-empty `years_experience`. So every hand-entered applicant left
on the default was skipped. Permanently, and with nothing on any screen saying
so: the row looked identical to one that had been contacted.

The rule that replaced it: a blank answer on a form somebody filled in about
themselves is a refusal to answer, but a blank field on a record an owner typed
in is a question nobody was asked. Anybody who actually said "no experience" on
the public form is auto-rejected at screening and never reaches this query, so
an empty value here means unknown, not none.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/ma.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['REMINDER_API_KEY'] = 'test-cron-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import ContractorApplication

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


def add(name, **kw):
    """An applicant old enough for the backstop to consider."""
    kw.setdefault('status', 'new')
    kw.setdefault('interview_status', 'not_sent')
    a = ContractorApplication(
        name=name, email=f'{name.split()[0].lower()}@example.test',
        created_at=datetime.utcnow() - timedelta(hours=1),
        **kw)
    db.session.add(a)
    db.session.commit()
    return a


def sweep(c):
    return c.post('/api/applicant-followups',
                  headers={'X-Api-Key': 'test-cron-key'}, json={})


with app.app_context():
    db.create_all()
    c = app.test_client()

    print('1. The applicant this was found on')
    # Exactly what the manual-add form produces when Experience is left alone:
    # empty string, and the "Has reliable car" box checked by default.
    unknown = add('Dana Unknown', years_experience='', has_transportation=True)
    r = sweep(c)
    check(r.status_code == 200, f'the sweep runs (got {r.status_code})')
    unknown = ContractorApplication.query.get(unknown.id)
    check(unknown.interview_status == 'sent',
          'an unknown experience level no longer disqualifies anybody')
    check(unknown.interview_sent_at is not None,
          'and the send is stamped, so the screen can stop claiming otherwise')

    print('\n2. A stated "no experience" is still an answer, and still a no')
    none = add('Sam None', years_experience='No experience', has_transportation=True)
    sweep(c)
    none = ContractorApplication.query.get(none.id)
    check(none.interview_status == 'not_sent',
          'somebody who said they have no experience is not invited')

    print('\n3. No transport is still disqualifying')
    nocar = add('Pat Nocar', years_experience='3-5 years', has_transportation=False)
    sweep(c)
    nocar = ContractorApplication.query.get(nocar.id)
    check(nocar.interview_status == 'not_sent',
          'the transport rule is unchanged')

    print('\n4. A company is read by a person, not sent a video interview')
    # The apply form refuses to auto-invite a company: the interview asks
    # somebody about their own cleaning, and what a company needs is its
    # insurance checked. The backstop quietly did what the form refuses to,
    # because nothing in it looked at applicant_kind.
    firm = add('Acme Cleaning Co', years_experience='5+ years',
               has_transportation=True, applicant_kind='company',
               status='reviewing')
    sweep(c)
    firm = ContractorApplication.query.get(firm.id)
    check(firm.interview_status == 'not_sent',
          'a company applicant is left for a human to read')

    print('\n5. Somebody already rejected is never chased')
    gone = add('Rex Rejected', years_experience='3-5 years',
               has_transportation=True, status='rejected')
    sweep(c)
    gone = ContractorApplication.query.get(gone.id)
    check(gone.interview_status == 'not_sent',
          'a rejected applicant stays rejected')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
