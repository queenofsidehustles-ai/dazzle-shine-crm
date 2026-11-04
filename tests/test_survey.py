"""The "what got in the way" survey (survey.py, blueprints/survey.py).

What it guards:

  * only the two groups it is for are asked, in windows that sit between the
    other notes, and never a paying, test, opted-out or closed company
  * it is asked once, and an owner who answers is never asked again
  * opening the emailed link records nothing; only the button does
  * a link works on its own company's address only, and a bad one says so
  * answering twice is one company, not two answers
  * the console adds the answers up per group, and lists who said call me
  * it ships switched off
"""
import os
import re
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


import fresh_postgres
URL = fresh_postgres.url('akye_survey_test')
os.environ.update(DATABASE_URL=URL, SECRET_KEY='survey-test',
                  BASE_DOMAIN='rollcall.test', SIGNUPS_OPEN='1',
                  SIGNUP_LIMITS='0', FLASK_ENV='development')
os.environ.pop('ADMIN_USER', None)
os.environ.pop('ADMIN_PASS', None)

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to_email, to_name, subject, html, **k: (
    SENT.append({'to': to_email, 'subject': subject, 'html': html}), (True, 'stub'))[1]

import billing
import communications
import control_plane
import provisioning
import survey
import trial_nudges as tn
from app import create_app

NOW = datetime.utcnow()


def org(days_old=0, **kw):
    created = NOW - timedelta(days=days_old)
    base = {'slug': 'brightside', 'name': 'Brightside Cleaning',
            'owner_email': 'dana@brightside.example', 'status': 'active',
            'created_at': created, 'plan': 'scale',
            'subscription_status': 'trialing',
            'trial_ends_at': created + timedelta(days=billing.TRIAL_DAYS),
            'activated_at': None, 'nudges_sent': None, 'owner_active_at': None}
    base.update(kw)
    return base


def quiet_after_setup(away, days_old=20, **kw):
    """Got it working, then the owner stopped coming back `away` days ago."""
    return org(days_old=days_old, activated_at=NOW - timedelta(days=days_old - 2),
               owner_active_at=NOW - timedelta(days=away), **kw)


print('\n1. Who counts as which group')
check(survey.segment(org(days_old=3)) is None, 'three days in: too early to ask')
check(survey.segment(org(days_old=5)) == 'A', 'a week of nothing set up: group A')
check(survey.segment(quiet_after_setup(away=5)) is None,
      'set up and in this week: nobody to ask')
check(survey.segment(quiet_after_setup(away=14)) == 'B', 'set up, away two weeks: group B')
check(survey.segment(org(days_old=20, activated_at=NOW - timedelta(days=15))) is None,
      'set up but never seen using it: not guessed at')

print('\n2. When each group is asked')
check(tn.due(org(days_old=13, nudges_sent='day1,day2,day4,day5,start_7')) is None,
      'A: day 13, start_7 already sent: not yet')
check(tn.due(org(days_old=15, nudges_sent='day1,day2,day4,day5,start_7')) == 'survey',
      'A: day 15, after the reminders: asked')
check(tn.due(org(days_old=8)) == 'start_7',
      'A: day 8 still gets start_7, which keeps its day')
check(tn.due(org(days_old=22, nudges_sent='start_7')) == 'start_21',
      'A: start_21 still keeps its day')
check(tn.due(org(days_old=15, nudges_sent='start_7,survey')) is None,
      'A: never twice')
check(tn.due(quiet_after_setup(away=10)) == 'quiet',
      'B: away 10 days gets the quiet note, not the survey')
check(tn.due(quiet_after_setup(away=15, nudges_sent='quiet')) == 'survey',
      'B: away 15 days, trial running: asked')
check(tn.due(quiet_after_setup(away=15, nudges_sent='quiet,survey')) is None,
      'B: never twice')
lapsed = dict(trial_ends_at=NOW - timedelta(days=6))
check(tn.due(org(days_old=36, **lapsed)) == 'survey', 'A: six days after the trial: asked')
check(tn.due(org(days_old=200, trial_ends_at=NOW - timedelta(days=170))) is None,
      'A: a trial that lapsed months ago is history, not asked')
check(tn.due(quiet_after_setup(away=40, days_old=90, **dict(
    trial_ends_at=NOW - timedelta(days=50), nudges_sent='free_quiet'))) == 'survey',
      'B: on the free plan, away 40 days: asked')

print('\n3. Who is never asked')
check(tn.due(org(days_old=15, is_test=True)) is None, 'a test account')
check(tn.due(org(days_old=15, nudges_opted_out=True)) is None, 'someone who opted out')
check(tn.due(org(days_old=15, status='suspended')) is None, 'a suspended company')
check(tn.due(org(days_old=15, subscription_status='active')) is None, 'a paying company')
check(tn.due(org(days_old=15, nudge_last_at=NOW - timedelta(hours=3))) is None,
      'someone emailed this morning (one a day)')
check(tn.due(org(days_old=15), skip=('survey',)) is None, 'when the survey is switched off')

print('\n4. The email')
for who in (org(days_old=15), quiet_after_setup(away=16, slug='brightside')):
    subject, html = tn.compose(who, 'survey')
    check('Brightside Cleaning' in subject, f'names the company ({subject})')
    check('https://brightside.rollcall.test/survey/' in html,
          'links to their own address')
    check(html.count('?a=') >= 6, 'offers one-tap answers')
    check('—' not in html.split('Questions?')[0], 'no em dashes in what we wrote')
check('Did it stop being useful' in tn.compose(quiet_after_setup(away=16), 'survey')[1]
      and 'What got in the way' in tn.compose(org(days_old=15), 'survey')[1],
      'each group gets its own question')
check('survey' in tn.ALL and 'survey' in communications.DEFAULT_OFF
      and 'survey' in communications.LABELS,
      'it is in the catalog and ships switched off')

print('\n5. The link')
tok = survey.token('brightside', 'A')
check(survey.read_token(tok) == ('brightside', 'A'), 'a link reads back')
check(survey.read_token(tok + 'x') == (None, None), 'a tampered link does not')
check(survey.read_token('nonsense') == (None, None), 'nor does rubbish')

app = create_app()
engine = provisioning._engine()
c = app.test_client()
for slug, email in (('sparkle', 'dana@sparkle.test'), ('gleam', 'sam@gleam.test')):
    c.post('/signup', data={'business': slug.title() + ' Cleaning', 'slug': slug,
                            'name': 'Owner Reed', 'email': email,
                            'password': 'a-perfectly-fine-password',
                            'terms_accepted': '1', 'zip_code': '32801',
                            'phone': '4075550123'}, headers={'Host': 'rollcall.test'})
# Sparkle signed up 15 days ago and never got going.
with engine.begin() as conn:
    conn.execute(control_plane.organizations.update()
                 .where(control_plane.organizations.c.slug == 'sparkle')
                 .values(created_at=NOW - timedelta(days=15)))
sparkle = control_plane.find(engine, 'sparkle')
check(survey.segment(sparkle) == 'A', 'the signed-up company is in group A')
tok = survey.token('sparkle', 'A')
HOST = {'Host': 'sparkle.rollcall.test'}

print('\n6. Opening the link records nothing')
r = c.get(f'/survey/{tok}?a=time', headers=HOST)
page = r.data.decode()
check(r.status_code == 200 and 'What got in the way' in page, 'the page opens')
check(re.search(r'value="time"\s+checked', page) is not None,
      'the tapped answer is already ticked')
check(survey.existing(engine, 'sparkle') is None, 'and nothing has been recorded')

print('\n7. Pressing the button does')
r = c.post(f'/survey/{tok}', headers=HOST, data={
    'blockers': ['time', 'start'], 'stuck_at': 'client',
    'wish': 'A way to import my list', 'wants_call': 'yes'})
check(r.status_code == 200 and 'Thank you' in r.data.decode(), 'it says thank you')
row = survey.existing(engine, 'sparkle')
check(row and row['blockers'] == 'time,start' and row['segment'] == 'A'
      and row['stuck_at'] == 'client' and row['wants_call'] is True
      and row['activated'] is False and row['org_age_days'] == 15,
      'the answer and the state at the time are saved')
check('survey' in (control_plane.find(engine, 'sparkle')['nudges_sent'] or ''),
      'the survey email is marked as done')
check(tn.due(control_plane.find(engine, 'sparkle')) is None,
      'so they are never asked again')

r = c.post(f'/survey/{tok}', headers=HOST, data={
    'blockers': ['price', 'time', 'missing'], 'stuck_at': 'bogus',
    'other_text': 'x' * 5000})
row = survey.existing(engine, 'sparkle')
check(row['blockers'] == 'price,time' and row['stuck_at'] is None
      and len(row['other_text']) == survey.MAX_TEXT,
      'a second answer replaces the first, trimmed to two choices and a sane length')
check(len(survey.responses(engine)) == 1, 'still one company, one answer')

r = c.post(f'/survey/{tok}', headers=HOST, data={'blockers': ['nonsense']})
check(r.status_code == 400 and survey.existing(engine, 'sparkle')['blockers'] == 'price,time',
      'an empty answer is refused and keeps the earlier one')

print('\n8. A link is only good on its own address')
r = c.post(f'/survey/{tok}', headers={'Host': 'gleam.rollcall.test'},
           data={'blockers': ['time']})
check(r.status_code == 400 and survey.existing(engine, 'gleam') is None,
      "another company's address will not take it")
r = c.get('/survey/garbage', headers=HOST)
check(r.status_code == 400 and 'out of date' in r.data.decode(), 'a bad link says so')
check(c.get(f'/survey/{tok}', headers={'Host': 'rollcall.test'}).status_code == 404,
      'the product site has no such page')

print('\n9. The console')
control_plane.add_console_user(engine, 'mgr-survey@example.com', 'Manager',
                               'a-real-console-password-1', role='manager')
m = app.test_client()
check(m.get('/console/survey').status_code in (301, 302), 'signed out: sent to sign in')
m.post('/console/login', data={'email': 'mgr-survey@example.com',
                               'password': 'a-real-console-password-1'})
page = m.get('/console/survey').data.decode()
check('Never got set up' in page and 'too expensive' in page
      and 'Wants a call' not in page, 'it shows the tally for the group')
survey.save(engine, control_plane.find(engine, 'gleam'), 'B',
            survey.clean(type('F', (), {
                'getlist': lambda s, k: ['missing'], 'get': lambda s, k, d=None: {
                    'wants_call': 'yes', 'wish': 'Texting'}.get(k, d)})()))
page = m.get('/console/survey').data.decode()
check('Set up, then went quiet' in page and 'Wants a call' in page
      and 'sam@gleam.test' in page, 'a group B answer who wants a call is listed with how to reach them')
t = survey.tally(survey.responses(engine))
check(t['A']['n'] == 1 and t['B']['n'] == 1 and t['B']['calls'] == 1, 'counted per group')

print('\n10. It ships switched off')
SENT.clear()
counts = tn.run(engine, now=NOW, dry_run=False)
check(counts.get('survey') == 0 and not any('got in the way' in s['subject'] for s in SENT),
      'the daily run sends no survey until it is turned on')

engine.dispose()
if failures:
    print(f'\n\n❌ {len(failures)} survey check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ The survey asks the right people once, records only real answers, and ships off.\n')
