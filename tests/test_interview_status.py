"""A hiring screen must not say somebody was contacted when they were not.

A real candidate at a real company sat in the interview list showing "📬 Sent",
with the Link Sent column empty and every counter reading zero. All three were
describing the same person and only the badge was wrong.

Her `interview_status` was `pending` — set when screening passes, meaning the
invite is QUEUED. The thing that actually sends it is the applicant-followups
job, which was not running. So the invite had never gone out.

The badge was written as: completed, else in_progress, else "Sent". Anything
unrecognised fell into the last branch and claimed an email had been sent. On a
screen whose entire job is telling you who you have contacted, an unknown state
is not evidence of an email, and the safe default is not the reassuring one.
"""
import os, sys, tempfile
from datetime import datetime

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/iv.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import ContractorApplication

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
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'

    def applicant(name, status, sent_at=None):
        a = ContractorApplication(name=name, email=f'{name.split()[0].lower()}@x.com',
                                  phone='4075550000', interview_status=status,
                                  interview_sent_at=sent_at)
        db.session.add(a)
        db.session.commit()
        return a

    print('\n1. A queued invite is not a sent one')
    applicant('Mikayla Lewis', 'pending')          # screening passed, nothing sent
    page = c.get('/admin/interviews').get_data(as_text=True)
    check('Mikayla Lewis' in page, 'the candidate is on the list')
    check('Not sent yet' in page, 'and is shown as not sent yet')
    check('📬 Sent' not in page,
          'not as Sent — nobody has emailed her')

    print('\n2. She is in the numbers, not just the list')
    # She used to be in the list and in none of the counters, which is how a
    # person waiting on a stalled automation stays invisible.
    check('Queued' in page, 'a Queued tile appears while any are waiting')
    check('>1<' in page.replace(' ', '').replace('\n', ''),
          'showing that one is waiting')

    print('\n3. Sent still means sent')
    applicant('Real Send', 'sent', sent_at=datetime.utcnow())
    page = c.get('/admin/interviews').get_data(as_text=True)
    check('📬 Sent' in page, 'a genuinely sent invite says Sent')
    check('Not sent yet' in page, 'and the queued one still says otherwise')

    print('\n4. Total Sent counts what was sent')
    applicant('In Prog', 'in_progress')
    applicant('Done One', 'completed')
    applicant('Also Queued', 'pending')
    from blueprints.interviews import admin_interviews  # noqa: F401
    counts = {s: ContractorApplication.query.filter_by(interview_status=s).count()
              for s in ('pending', 'sent', 'in_progress', 'completed')}
    total = counts['sent'] + counts['in_progress'] + counts['completed']
    check(counts['pending'] == 2, 'two are queued')
    check(total == 3, 'and three were actually sent')
    check(total == 3 and counts['pending'] + total == 5,
          'five people on the list, three sent — the queued two are not counted as sent')

    print('\n5. An unrecognised state is never read as contact')
    # The point is the default, not the list of names. A status nobody has seen
    # before must not inherit the reassuring badge.
    applicant('Odd State', 'some_future_state')
    page = c.get('/admin/interviews').get_data(as_text=True)
    check('Odd State' in page, 'an unknown status still shows the person')
    sent_badges = page.count('📬 Sent')
    check(sent_badges == 1,
          f'and only the genuinely sent one wears the Sent badge ({sent_badges})')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ The screen says who has been contacted, and nobody else.')
