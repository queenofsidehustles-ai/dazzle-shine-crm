"""A business decides what this software does on its behalf.

The six jobs were all-or-nothing for everybody, which is fine until you notice
that businesses collect money differently. Some take the balance off the card,
some take cash at the door, some invoice afterwards — and taking the deposit
through the booking page saves the customer's card either way, so "we only take
cash" was no protection at all.

Charging a card cannot be undone, so it defaults to `ask`: nothing is charged
and the balance shows as owed. A business that wants it automatic says so.

Everything is checked by the job itself rather than by whatever woke it, so the
answer holds however the job is triggered — the nightly run, a run by hand, or
anything built later that nobody has thought of yet.
"""
import os, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/ac.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['REMINDER_API_KEY'] = 'the-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import automations

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
    KEY = {'X-Api-Key': 'the-key'}

    print('\n1. Nobody has their customers charged by a default')
    check(automations.balance_mode() == 'ask',
          'a business that has said nothing is on "ask", not "charge"')
    check(automations.is_enabled('charge-balances') is False,
          'so the charge job does nothing for them')

    print('\n2. The five that only send messages are on')
    for job in ('reminders', 'lifecycle-emails', 'send-drips',
                'applicant-followups', 'lsa-followups'):
        check(automations.is_enabled(job), f'{job} runs without being switched on')

    print('\n3. The job itself refuses, not the thing that woke it')
    # So the answer holds however it is triggered.
    r = c.post('/api/charge-balances', headers=KEY)
    check(r.status_code == 200, 'the charge endpoint answers politely')
    check(r.get_json().get('skipped') == 'turned off by this business',
          'and says it skipped because the business turned it off')

    print('\n4. Turning one off stops it, and only it')
    automations.set_enabled('reminders', False)
    db.session.commit()
    check(automations.is_enabled('reminders') is False, 'reminders are off')
    check(automations.is_enabled('send-drips') is True, 'drips are untouched')
    r = c.post('/api/reminders', headers=KEY)
    check(r.get_json().get('skipped'), 'and the reminders endpoint skips')
    r = c.post('/api/send-drips', headers=KEY)
    check(not r.get_json().get('skipped'), 'while drips still runs')
    automations.set_enabled('reminders', True)
    db.session.commit()

    print('\n5. Off on purpose is not the same as broken')
    automations.set_enabled('lsa-followups', False)
    db.session.commit()
    rows = {r['key']: r for r in automations.overview()}
    check(rows['lsa-followups']['state'] == 'off',
          'a job somebody switched off reads as off')
    check(rows['lsa-followups'] not in automations.summary()['broken'],
          'and is not counted among the ones that are not running')
    check(rows['reminders']['state'] != 'off', 'an untouched job is unaffected')
    automations.set_enabled('lsa-followups', True)
    db.session.commit()

    print('\n6. Choosing "charge automatically" is a deliberate act')
    automations.set_balance_mode('auto')
    db.session.commit()
    check(automations.is_enabled('charge-balances') is True,
          'having said so, the charge job runs')
    r = c.post('/api/charge-balances', headers=KEY)
    check(not r.get_json().get('skipped'), 'and the endpoint does not skip')

    print('\n7. "Never" is a different answer from "ask"')
    for mode in ('ask', 'never'):
        automations.set_balance_mode(mode)
        db.session.commit()
        check(automations.balance_mode() == mode, f'{mode!r} is remembered')
        check(automations.is_enabled('charge-balances') is False,
              f'and nothing is charged on {mode!r}')

    print('\n8. A nonsense value is read as the cautious one')
    # A hand-edited row, or a future version writing something this one does not
    # know, must not be read as permission to charge somebody.
    automations.set_balance_mode('something-else')
    db.session.commit()
    check(automations.balance_mode() == 'ask',
          'an unrecognised setting falls back to "ask"')

    print('\n9. The page saves what was chosen')
    r = c.post('/settings/automations/save',
               data={'job': 'charge-balances', 'mode': 'auto'},
               follow_redirects=True)
    check(r.status_code == 200, 'the form posts')
    check(automations.balance_mode() == 'auto', 'and the choice is recorded')

    r = c.post('/settings/automations/save',
               data={'job': 'reminders', 'on': '0'}, follow_redirects=True)
    check(automations.is_enabled('reminders') is False, 'a switch is recorded too')

    r = c.post('/settings/automations/save',
               data={'job': 'not-a-real-job', 'on': '1'}, follow_redirects=True)
    check(r.status_code == 200, 'an unknown job is refused without erroring')

print('\n10. A managed business is not told to set up a cron service')
# The page still carried the self-hosted instructions: sign up to cron-job.org,
# paste six URLs. That is the exact chore the central scheduler removes, and
# leaving it on screen would have told every company to go and do it anyway.
tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates', 'admin', 'automations.html')
body = open(tpl).read()
check('{% if not managed %}' in body,
      'the cron-job.org instructions are behind a check')
check(body.count('cron-job.org') > 0 and '{% if managed %}' in body,
      'and a managed business gets different words instead')
i = body.find('cron-job.org')
check('{% if not managed %}' in body[:i],
      'the instructions come after that check, not before it')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ Each business decides, and the default cannot charge anybody.')
