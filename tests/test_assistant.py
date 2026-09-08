"""Kye answers from the books, and cannot be talked into anything else.

The design this suite exists to hold: the model picks which question was asked
and nothing else. Every figure, name and date is read from the database and
written by ordinary Python, so the worst a wrong guess can do is answer a
different question — visibly — rather than state a number that is not true.

The other half is what it will not do. It does not send email, does not text
anybody, does not charge a card, and marking a job finished is offered rather
than done. Anything that reaches a customer or moves money should be a button a
person pressed, not a sentence a model understood.
"""
import os, sys, tempfile
from datetime import datetime, date, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/kye.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (SENT.append('sms'), (True, 'stub'))[1]
notifications.send_email = lambda *a, **k: (SENT.append('email'), (True, 'stub'))[1]

from app import create_app
from extensions import db
from models import Booking, Client, Staff
import assistant

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
    import scheduling
    today = scheduling.local_today()

    db.session.add(Staff(name='Laura Moreira', phone='4075550001',
                         email='l@x.com', is_active=True))
    db.session.add(Client(name='Rita Vance', email='rita@x.com',
                          phone='4079990000', address='1 Elm'))

    def job(name, when, price, paid=None, cleaner='Laura Moreira', status='confirmed'):
        b = Booking(service_type='standard', name=name, email=f'{name[:4]}@x.com',
                    phone='4079990000', address='1 Elm', city='Orlando',
                    bedrooms='3', bathrooms='2', price=price, status=status,
                    preferred_date=when.isoformat(), preferred_time='10:00 AM',
                    assigned_cleaner=cleaner, paid_at=paid,
                    amount_collected=(price if paid else 0))
        db.session.add(b)
        db.session.commit()
        return b

    job('Rita Vance', today, 260.0, paid=datetime.utcnow())
    job('Paid Earlier', today - timedelta(days=2), 190.0, paid=datetime.utcnow())
    job('Owes Money', today - timedelta(days=1), 300.0)
    job('Nobody On It', today + timedelta(days=2), 220.0, cleaner=None)

    print('\n1. The numbers come from the books, not the model')
    said = assistant.money_made('this month')
    check('450.00' in said, f'takes what was actually paid: {said!r}')
    check('2 paid' in said, 'and counts the jobs behind it')
    check('300' not in said, 'unpaid work is not counted as money made')

    said = assistant.money_owed()
    # 300 done-and-unpaid plus 220 booked-and-unpaid. "Booked or already done"
    # is what the figure means, and a job in two days' time is money owed even
    # though nobody has cleaned anything yet.
    check('520.00' in said, f'owed covers booked as well as done: {said!r}')

    print('\n2. It answers in the words somebody would use')
    said = assistant.jobs_on('today')
    check('today' in said and 'Rita Vance' in said, f'{said.splitlines()[0]!r}')
    check('Laura Moreira' in said, 'and says who is cleaning it')
    check(str(today) not in said, 'no ISO dates — a person would not say 2026-09-07')

    said = assistant.jobs_on('tomorrow')
    check('Nothing is booked tomorrow' in said, 'an empty day says so plainly')

    said = assistant.unassigned_jobs()
    check('Nobody On It' in said, 'a job with no cleaner is findable')

    print('\n3. A wrong guess answers a different question — it cannot invent one')
    # The model returns a tool name. Anything it makes up is dropped.
    name, args = assistant.choose('anything', api_key='')
    check(name is None, 'with no key it declines rather than guessing')
    for made_up in ('delete_everything', 'charge_all_cards', '', None):
        check(made_up not in assistant.TOOLS,
              f'{made_up!r} is not a tool it could pick')

    print('\n4. It will not send anything')
    SENT.clear()
    out = assistant.draft_email(about='say sorry we were late', to='rita@x.com')
    check('draft' in out, 'it drafts')
    check('do not send' in out['say'], 'and says plainly that it does not send')
    check(SENT == [], 'nothing left the building')

    print('\n5. Finishing a job is offered, not done')
    out = assistant.finish_job(customer='Owes Money')
    check('confirm' in out, 'it comes back as something to confirm')
    check(out['confirm']['action'] == 'complete_booking', 'naming the action')
    b = Booking.query.filter_by(name='Owes Money').first()
    check(b.status == 'confirmed', 'and the job is untouched until somebody presses it')

    print('\n6. It asks rather than guessing between two people')
    job('Rita Vance', today - timedelta(days=3), 200.0)
    out = assistant.finish_job(customer='Rita')
    check('More than one' in out['say'], 'two matches is a question, not a coin toss')
    check('confirm' not in out, 'and nothing is offered to press')

    out = assistant.finish_job(customer='')
    check('Which job' in out['say'], 'no name at all is also a question')

    print('\n7. There is no tool that spends money or texts anybody')
    for bad in ('charge', 'refund', 'pay', 'text', 'sms', 'send_email', 'delete'):
        hits = [t for t in assistant.TOOLS if bad in t and t != 'draft_email']
        check(not hits, f'nothing named like {bad!r} ({hits})')
    # Only one tool changes anything at all, and it proposes.
    writers = [n for n, (_f, d, _a) in assistant.TOOLS.items()
               if 'mark' in d or 'finished' in d]
    check(writers == ['finish_job'], f'exactly one tool touches data: {writers}')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ It reads the books, says what it found, and presses nothing.')
