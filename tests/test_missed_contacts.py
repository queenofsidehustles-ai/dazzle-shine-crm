"""Chasing somebody you missed, however they tried to reach you.

The follow-up texts were good and almost nobody could use them. The only way
into the sequence was uploading a CSV exported from Google Local Services Ads,
so the whole feature silently belonged to companies who advertise with Google
— and the screen said so, twice, in copy about what Google had and had not
charged for.

Most missed contacts are not a Google ad. A voicemail. A text nobody got back
to. A form on the website. Somebody who asked what a clean would cost and went
quiet. Afterwards they are all the same conversation, and none of them arrive
in a CSV.

Fixing the wording alone would have been worse than leaving it: the page would
have promised to chase a missed voicemail while offering no way to enter one.
That is the same fault as the pricing page that edited settings nothing read —
a screen that describes something the software does not do.

So: a way in by hand, and words that do not assume where somebody came from.

The one rule underneath: the two tracks stay separate. Apologising for missing
a call reads badly to a person you already gave a price to, and that is not a
detail — it is the difference between a text that sounds like you and one that
sounds automated.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/mc.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications

SENT = []
notifications.send_sms = lambda to, msg: (SENT.append((to, msg)), (True, 'stub'))[1]
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import LsaLead
import lsa

app = create_app()
c = app.test_client()
with c.session_transaction() as sess:
    sess['logged_in'] = True
    sess['role'] = 'owner'

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def add(phone, track='missed', **extra):
    return c.post('/leads/lsa/add',
                  data=dict(phone=phone, track=track, **extra),
                  follow_redirects=True)


print('\n1. Somebody can be added without a Google account')
# The gap. Before this there was no way in at all that did not begin with a
# CSV export from an advertising platform.
r = add('(407) 555-0134', 'missed', note='3 bed, wants weekly', start_now='1')
check(r.status_code == 200, f'the form posts ({r.status_code})')
with app.app_context():
    lead = LsaLead.query.filter_by(phone='4075550134').first()
check(lead is not None, 'and the person is on the list')
if lead:
    check(lead.track == 'missed', 'in the track that was chosen')
    check(lead.lead_type == 'by_hand', 'marked as entered by hand, not imported')
    check(lead.charge_status is None,
          "with no Google billing word attached — they never came from Google")
    check(lead.seq_started_at is not None, 'and the texts have started')


print('\n2. A number typed any of the ways a person types it')
for raw, want in (('407-555-0155', '4075550155'), ('(407) 555 0166', '4075550166'),
                  ('+1 407 555 0177', '4075550177'), ('407.555.0188', '4075550188')):
    add(raw)
    with app.app_context():
        check(LsaLead.query.filter_by(phone=want).first() is not None,
              f'{raw!r} is stored as {want}')


print('\n3. The same person twice is still one person')
# Somebody rings on Monday and again on Thursday. Adding them again would put
# them into the sequence twice and text them twice, which is how a follow-up
# becomes a complaint.
before = None
with app.app_context():
    before = LsaLead.query.filter_by(phone='4075550134').count()
add('407 555 0134', 'quoted')
with app.app_context():
    after = LsaLead.query.filter_by(phone='4075550134').count()
check(before == after == 1, f'still one row ({after})')


print('\n4. Nothing is added that cannot be texted')
r = add('', 'missed')
check(b'phone number is needed' in r.data,
      'a missing number is refused, and says why')
with app.app_context():
    n = LsaLead.query.count()
r = add('abc', 'missed')
with app.app_context():
    check(LsaLead.query.count() == n, 'and nothing unusable is written')


print('\n5. The two conversations stay different')
# The reason there are two tracks at all.
with app.app_context():
    missed = lsa.template_for('missed', 1)
    quoted = lsa.template_for('quoted', 1)
check(missed != quoted, 'a missed contact and a quoted one get different texts')
check("didn't get to connect" in missed or 'sorry' in missed.lower(),
      'the missed one apologises for not connecting')
check('sorry' not in quoted.lower(),
      'and the quoted one does not — they already spoke to you')

add('407 555 0199', 'quoted', start_now='1')
with app.app_context():
    q = LsaLead.query.filter_by(phone='4075550199').first()
    check(q.track == 'quoted', 'somebody who asked for a price lands in that track')


print('\n6. Adding without starting is allowed')
# Somebody entering five people from a notepad should not fire five texts
# before they have looked at what they typed.
SENT.clear()
add('407 555 0211', 'missed')      # no start_now
with app.app_context():
    later = LsaLead.query.filter_by(phone='4075550211').first()
check(later is not None and later.seq_started_at is None,
      'the person is on the list with nothing sent yet')


print('\n7. The screen no longer says Google to people who do not use Google')
# The copy this started from: "people who called through Google Ads", and
# "Google didn't charge you for it".
import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent

page = c.get('/leads/lsa/').data.decode('utf8', 'replace')
check('Missed Contacts' in page, 'the page is about missed contacts')
check('/leads/lsa/add' in page, 'and offers a way to add one')
for phrase in ('voicemail', 'website'):
    check(phrase in page.lower(), f'naming {phrase} as one of the ways in')

texts = c.get('/settings/followup-texts').data.decode('utf8', 'replace')
check('called through Google Ads' not in texts,
      'the follow-up settings no longer say the leads came from Google Ads')
check("Google didn't charge you" not in texts,
      'nor explain them in terms of what Google billed')
check('voicemail' in texts.lower() or 'form on your website' in texts.lower(),
      'and it names the other ways somebody reaches you')

# Google is still named where it is genuinely the subject — the importer.
imp = (ROOT / 'templates' / 'admin' / 'lsa_import.html').read_text()
check('Google' in imp,
      'the CSV importer still says Google, because that is what it imports')


print('\n8. Importing still works, and lands in the same list')
# The new door must not have replaced the old one.
rows, problems = lsa.parse_csv(
    b'Lead ID,Phone number,Charge status,Job type,Received\n'
    b'L-1,4075550300,Not charged,House cleaning,2026-08-20\n'
    b'L-2,4075550301,Charged,House cleaning,2026-08-21\n')
with app.app_context():
    added, updated = lsa.import_rows(rows)
check(added == 2, f'two imported rows ({added})')
with app.app_context():
    a = LsaLead.query.filter_by(phone='4075550300').first()
    b = LsaLead.query.filter_by(phone='4075550301').first()
check(a and a.track == 'missed', 'an uncharged Google lead is still a missed one')
check(b and b.track == 'quoted', 'and a charged one is still a quoted one')
check(a.lead_type != 'by_hand', 'imported rows are not marked as hand-entered')


if failures:
    print(f'\n\n❌ {len(failures)} missed-contact check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Anybody you missed can be chased, however they reached you.\n')
