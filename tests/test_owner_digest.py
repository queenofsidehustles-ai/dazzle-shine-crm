"""The push half of Nana: the same specific facts daily_plan already computes,
mailed to the owner instead of waiting for them to open the app and look.

Two things must hold or this is worse than not existing at all:

  * it never invents a number of its own — everything in the email already
    passed through daily_plan.items()'s own "nothing is added unless its
    count is real" rule
  * a quiet day sends nothing, so the day something does need attention
    arrives in an inbox that is still being read
"""
import os, sys, tempfile
from datetime import timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/digest.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['REMINDER_API_KEY'] = 'testkey'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
MAIL = []
notifications.send_email = lambda to, n, s, b, **k: (MAIL.append((to, n, s, b)), (True, 'ok'))[1]
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import BusinessSetting, Lead

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
    BusinessSetting.set('email', 'monica@kojo.test')
    db.session.commit()
    # Not this test's business: db.create_all() on SQLite trips an unrelated
    # boot-time error email (multi-schema control-plane DDL SQLite cannot
    # run), which would otherwise be mistaken for mail the digest sent.
    MAIL.clear()

    print('\n1. A quiet day sends nothing')
    import owner_digest, daily_plan
    # Isolated from daily_plan's own idea of "quiet" on purpose: a brand-new
    # database already has a real thing on it (an empty diary next week), so
    # a true quiet day is faked at the boundary between the two modules
    # rather than by trying to construct an account with nothing at all
    # going on — what matters here is only "when daily_plan has nothing to
    # say, neither does the digest."
    real_items = daily_plan.items
    daily_plan.items = lambda: []
    try:
        subject, html = owner_digest.compose()
        check(subject is None and html is None,
              'daily_plan reporting nothing — compose() returns nothing to send')
        sent, detail = owner_digest.run()
        check(not sent and not MAIL, 'run() sends no mail on a quiet day')
        check(detail == 'nothing worth sending today', f'and says why ({detail!r})')
    finally:
        daily_plan.items = real_items

    print('\n2. A real day is specific, not generic')
    db.session.add(Lead(name='Priya Shah', email='priya@x.test', status='new'))
    db.session.commit()
    subject, html = owner_digest.compose()
    check(subject is not None, 'compose() has something to send once there is a real gap')
    check('enquir' in subject.lower(), f'the subject names what it is, not just a count ({subject})')
    check('/leads/' in html, 'the email links to the actual page for it, not just the dashboard')

    print('\n3. Sending it')
    MAIL.clear()
    sent, detail = owner_digest.run()
    check(sent, f'run() sends when there is something real ({detail})')
    check(len(MAIL) == 1, 'exactly one email, not one per item')
    to, _name, sent_subject, sent_html = MAIL[0]
    check(to == 'monica@kojo.test', 'to the business owner')
    check(sent_subject == subject and sent_html == html,
          'the email sent is exactly what compose() built — nothing recomputed on the way out')

    print('\n4. No owner email on file — recorded, not silently dropped')
    BusinessSetting.set('email', '')
    db.session.commit()
    sent, detail = owner_digest.run()
    check(not sent and 'email' in detail, f'fails loudly in the logs, not silently ({detail})')
    BusinessSetting.set('email', 'monica@kojo.test')
    db.session.commit()

c = app.test_client()

print('\n5. Off by default — unlike every message automation before it')
import automations
check(any(k == 'owner-digest' for k, _l, _b, _c in automations.JOBS),
      'it is a job on the automations page')
check([c2 for k, _l, _b, c2 in automations.JOBS if k == 'owner-digest'] == ['daily'],
      'and runs daily')
with app.app_context():
    check(not automations.is_enabled('owner-digest'),
          'a business that has never touched this setting gets nothing — opt-in, not opt-out')

print('\n6. The nightly run respects that switch')
check(c.post('/api/owner-digest', headers={'X-Api-Key': 'wrong'}).status_code == 403,
      'the wrong key is refused')
r = c.post('/api/owner-digest', headers={'X-Api-Key': 'testkey'})
check(r.get_json() == {'ok': True, 'skipped': 'turned off by this business'},
      f'skipped while off, same shape as every other job ({r.get_json()})')

print('\n7. Turning it on')
with app.app_context():
    automations.set_enabled('owner-digest', True)
    db.session.commit()
    check(automations.is_enabled('owner-digest'), 'the switch actually flips it on')
MAIL.clear()
r = c.post('/api/owner-digest', headers={'X-Api-Key': 'testkey'})
body = r.get_json()
check(body['ok'] and body['sent'], f'and once on, the nightly run actually sends ({body})')
check(len(MAIL) == 1, 'one email')

print('\n8. Turning it back off leaves the setting readable the other way')
with app.app_context():
    automations.set_enabled('owner-digest', False)
    db.session.commit()
    check(not automations.is_enabled('owner-digest'), 'off again')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ The morning email says exactly what the in-app list says, or says nothing at all.')
