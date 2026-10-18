"""The Health page tells the truth about the platform's own background work.

Backups, the scheduler, the product's daily jobs and Stripe's webhook all run
where nobody is watching. The failure that matters is the quiet one: a backup
that stopped a week ago looks exactly like one that ran last night. So this
checks the four states (ok, stale, failed, never), that each thing really
reports in, that the console shows it, and that the emergency switches really
stop what they say they stop.

The ways it could go wrong that would matter:

  * a job that stopped being reported as fine (the whole point);
  * a console that cries wolf on day one, before anything has reported;
  * the report endpoint accepting anything from anybody;
  * a switch that does not actually stop the thing, or that fails closed and
    takes the product down when the database blinks.
"""
import os
import secrets
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def postgres_url():
    from sqlalchemy import create_engine, text
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      'postgresql://app_user:localtest@127.0.0.1:5432/postgres',
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres'):
        if not candidate:
            continue
        try:
            e = create_engine(candidate)
            with e.connect() as c:
                c.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n  ⚠️  SKIPPED: no PostgreSQL server found.')
    sys.exit(0)

from sqlalchemy import create_engine, text

DB = 'dsm_platform_health_test'
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as conn:
    conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
    conn.execute(text(f'CREATE DATABASE {DB}'))
os.environ.update(DATABASE_URL=f'{PG.rsplit("/", 1)[0]}/{DB}', SECRET_KEY='health-test',
                  BASE_DOMAIN='akyehq.test', SIGNUPS_OPEN='1', REMINDER_API_KEY='cron-key',
                  ANTHROPIC_API_KEY='sk-ant-test')
for k in ('ADMIN_USER', 'ADMIN_PASS', 'CANONICAL_HOST'):
    os.environ.pop(k, None)

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append((a, k)) or (True, 'stub'))

import control_plane
import platform_health
import platform_switches
import provisioning
from app import create_app

try:
    app = create_app()
    PRODUCT = {'Host': 'akyehq.test'}
    KEY = {'X-Api-Key': 'cron-key'}
    TAG = secrets.token_hex(3)
    with app.app_context():
        engine = provisioning._engine()
        control_plane.ensure_table(engine)

    # In the past, so the runs the endpoints write at the real time are newer
    # than the ones this test injects.
    NOW = datetime.utcnow().replace(second=0, microsecond=0) - timedelta(days=3)

    def run_at(kind, hours_ago, ok=True, detail=None, items=None):
        control_plane.record_platform_run(
            engine, kind, ok=ok, items=items, detail=detail,
            now=NOW - timedelta(hours=hours_ago, minutes=3))   # minute != 0 mod 10: no prune

    def state(kind, stale=36):
        return platform_health.run_state(engine, kind, stale, now=NOW)

    print('\n1. Four states, and "never" is not an alarm')
    check(state('backup:akye')['state'] == 'never', 'nothing reported yet: not reported yet')
    with app.app_context():
        check(not platform_health.attention(engine, NOW),
              'and an untouched deployment does not light the alarm on day one')
        run_at('backup:akye', 5, items=1000, detail='ok')
        check(state('backup:akye')['state'] == 'ok', 'reported 5 hours ago: ok')
        run_at('backup:stale', 50)
        check(state('backup:stale')['state'] == 'stale' and state('backup:stale')['age_hours'] >= 49,
              'last success 50 hours ago: stale')
        run_at('backup:bad', 2, ok=False, detail='restore check failed')
        bad = state('backup:bad')
        check(bad['state'] == 'failed' and 'restore check failed' in bad['detail'],
              'a failure is shown with what it said')
        run_at('backup:recovered', 30)
        run_at('backup:recovered', 1, ok=False)
        run_at('backup:recovered', 0.2)
        check(state('backup:recovered')['state'] == 'ok', 'a failure followed by a success is ok again')
        check(platform_health.ago(0.5) == '30 min ago' and platform_health.ago(5) == '5 hours ago'
              and platform_health.ago(72) == '3 days ago' and platform_health.ago(None) == 'never',
              'ages read as a person would say them')

    print('\n2. What lights the alarm')
    with app.app_context():
        found = platform_health.attention(engine, NOW)
    text_ = ' | '.join(p['text'] for p in found)
    check('Dazzle' not in text_ and 'backup:bad' in text_ or 'backup · bad' in text_,
          f'the failed backup is listed ({text_[:120]})')
    check(any('backup · stale' in p['text'] and '2 days' in p['text'] for p in found),
          'and the stale one, with how long')
    check(not any('recovered' in p['text'] for p in found), 'the recovered one is not')
    with app.app_context():
        run_at('scheduler:daily', 40)
        run_at('job:trial-nudges', 2, ok=False, detail='2 failed')
        run_at('stripe:webhook', 1, ok=False, detail='customer.subscription.updated: boom')
        found = platform_health.attention(engine, NOW)
    wheres = {p['where'] for p in found}
    check({'Background jobs', 'Stripe'} <= wheres, f'scheduler, product job and Stripe failures all count ({wheres})')
    check(platform_health.stripe_webhook(engine, NOW)['state'] == 'failed', "Stripe's webhook is failed, never stale")

    print('\n3. Reporting in: the endpoint')
    c = app.test_client()
    body = {'kind': 'backup:akye', 'ok': True, 'items': 123, 'detail': 'nightly'}
    check(c.post('/api/platform-run', headers=PRODUCT, json=body).status_code == 403,
          'no key: refused')
    check(c.post('/api/platform-run', headers=dict(PRODUCT, **{'X-Api-Key': 'wrong'}), json=body).status_code == 403,
          'wrong key: refused')
    h = dict(PRODUCT, **KEY)
    r = c.post('/api/platform-run', headers=h, json=body)
    check(r.status_code == 200 and r.get_json()['ok'], 'the right key is accepted')
    check(c.post('/api/platform-run', headers=h, json={'kind': 'job:trial-nudges', 'ok': True}).status_code == 400,
          "a kind the product records itself cannot be written from outside")
    check(c.post('/api/platform-run', headers=h, json={'kind': 'whatever', 'ok': True}).status_code == 400,
          'nor an invented one')
    check(c.post('/api/platform-run', headers=h, json={'kind': 'backup:' + 'x' * 80, 'ok': True}).status_code == 400,
          'nor an enormous one')
    with app.app_context():
        got = control_plane.platform_runs_for(engine, 'backup:akye', 1)[0]
    check(got['items'] == 123 and got['detail'] == 'nightly' and got['ok'], 'and it is recorded as sent')

    print('\n4. Reporting in: the client never breaks a job')
    import platform_report
    saved = {k: os.environ.pop(k) for k in ('REMINDER_API_KEY',) if k in os.environ}
    sent, msg = platform_report.report('backup:akye', True, 1, 'x')
    check(not sent and 'not set' in msg, f'no key: says so instead of raising ({msg!r})')
    check(platform_report.main(['backup:akye', '--ok', 'false']) == 0, 'and the command still exits 0')
    os.environ.update(saved)

    import scheduler
    calls = []
    real_report = platform_report.report
    platform_report.report = lambda kind, ok=True, items=None, detail=None: (
        calls.append((kind, ok, items, detail)) or (True, 'stub'))
    real_run = scheduler.run
    scheduler.run = lambda jobs, only=None, quiet=False, product_jobs=(): [('acme', 'reminders', 'HTTP 500')]
    argv = sys.argv
    sys.argv = ['scheduler.py', '--cadence', 'daily', '--quiet']
    rc = scheduler.main()
    check(rc == 1 and calls and calls[-1][0] == 'scheduler:daily' and calls[-1][1] is False
          and 'acme/reminders' in calls[-1][3], 'the scheduler reports a failed run, and still exits 1')
    scheduler.run = lambda jobs, only=None, quiet=False, product_jobs=(): []
    rc = scheduler.main()
    check(rc == 0 and calls[-1][1] is True, 'and a clean run as ok')
    n = len(calls)
    sys.argv = ['scheduler.py', '--cadence', 'hourly', '--only', 'acme', '--quiet']
    scheduler.main()
    check(len(calls) == n, 'a single-company test run is not reported as the real schedule')
    platform_report.report = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('network down'))
    sys.argv = ['scheduler.py', '--cadence', 'daily', '--quiet']
    check(scheduler.main() == 0, 'and a reporting failure never changes the scheduler result')
    platform_report.report, scheduler.run, sys.argv = real_report, real_run, argv

    print("\n5. The product's own jobs and Stripe record themselves")
    with app.app_context():
        before = len(control_plane.platform_runs_for(engine, 'job:trial-nudges', 50))
    r = c.post('/api/trial-nudges', headers=h)
    r2 = c.post('/api/lead-nurture', headers=h)
    with app.app_context():
        nudge = control_plane.platform_runs_for(engine, 'job:trial-nudges', 50)
        nurture = control_plane.platform_runs_for(engine, 'job:lead-nurture', 50)
    check(r.status_code == 200 and len(nudge) == before + 1, 'a trial-email run is recorded')
    check(r2.status_code == 200 and len(nurture) == 1, 'and so is a lead-email run')
    check(c.post('/api/trial-nudges?dry_run=1', headers=h).status_code == 200
          and len(control_plane.platform_runs_for(engine, 'job:trial-nudges', 50)) == before + 1,
          'a dry run is not mistaken for a real one')
    from blueprints import billing_routes
    with app.app_context():
        billing_routes._note_webhook({'type': 'invoice.paid'}, True, 'acme: payment received')
        hook = control_plane.platform_runs_for(engine, 'stripe:webhook', 1)[0]
    check(hook['ok'] and 'invoice.paid' in hook['detail'], "Stripe's webhook outcome is recorded")

    print('\n6. Platform errors')
    from models import ErrorLog
    with app.app_context():
        ErrorLog.record(kind='KeyError', message='boom', path='/pricing', method='GET',
                        endpoint='marketing.pricing', fingerprint='fp-health-1')
        ErrorLog.record(kind='blocked', message='cross-site', path='/x', method='POST',
                        endpoint='x', fingerprint='fp-health-2')
        rows, total = platform_health.platform_errors(engine)
    check(total == 1 and rows[0]['kind'] == 'KeyError', 'a fault outside any company is listed')
    check(all(r['kind'] != 'blocked' for r in rows), 'a refused cross-site form is not a fault')
    with app.app_context():
        platform_health.resolve_platform_errors(engine, rows[0]['id'])
        check(platform_health.platform_errors(engine)[1] == 0, 'resolving one clears it')
        ErrorLog.record(kind='KeyError', message='boom', path='/pricing', method='GET',
                        endpoint='marketing.pricing', fingerprint='fp-health-1')
        check(platform_health.platform_errors(engine)[1] == 1, 'and it reopens when it comes back')

    print('\n7. Usage against each limit')
    orgs = [{'slug': 'busy', 'name': 'Busy Co', 'plan': 'pro', 'subscription_status': 'active',
             'stripe_subscription_id': 'sub_1'},
            {'slug': 'quiet', 'name': 'Quiet Co', 'plan': 'pro', 'subscription_status': 'active',
             'stripe_subscription_id': 'sub_2'},
            {'slug': 'idle', 'name': 'Idle Co', 'plan': 'solo', 'subscription_status': 'active'}]
    snaps = {'busy': {'ok': True, 'usage': {'sms': 1000, 'nana': 10, 'setup_chat': 0, 'lead_searches': 170}},
             'quiet': {'ok': True, 'usage': {'sms': 5, 'nana': 0, 'setup_chat': 0, 'lead_searches': 0}},
             'idle': {'ok': True, 'usage': {'sms': 0, 'nana': 0, 'setup_chat': 0, 'lead_searches': 0}}}
    rows, totals = platform_health.usage_rows(orgs, snaps)
    check([r['slug'] for r in rows] == ['busy', 'quiet'], 'busiest first, and a company that used nothing is left out')
    check(rows[0]['sms']['state'] == 'over' and rows[0]['sms']['limit'] == 1000, 'at the text limit: over')
    check(rows[0]['searches']['state'] == 'near', '85% of the searches: near')
    check(totals['sms'] == 1005, 'with a total across companies')
    zero = [{'slug': 'free', 'name': 'Free Co', 'plan': 'solo', 'subscription_status': 'active'}]
    zrows, _ = platform_health.usage_rows(zero, {'free': {'ok': True, 'usage': {
        'sms': 7, 'nana': 0, 'setup_chat': 0, 'lead_searches': 2}}})
    check(zrows and zrows[0]['sms']['limit'] == 0 and zrows[0]['sms']['state'] == 'over'
          and zrows[0]['searches']['state'] == 'over',
          'a free company that used texts or searches is over a limit of zero, not "unlimited"')
    zrows, _ = platform_health.usage_rows(zero, {'free': {'ok': True, 'usage': {
        'sms': 0, 'nana': 3, 'setup_chat': 0, 'lead_searches': 0}}})
    check(zrows[0]['sms']['state'] == '' and zrows[0]['nana']['limit'] == 300,
          'and one that used none of it is not flagged')

    print('\n8. The switches')
    with app.app_context():
        check(all(platform_switches.is_on(k) for k in platform_switches.KEYS), 'everything is on unless turned off')
        check(platform_switches.is_on('nonsense'), 'and an unknown switch is on, not an error')
        import llm
        check(llm.key() == 'sk-ant-test' and llm.ready(), 'the AI key is live to begin with')
        platform_switches.set_switch(engine, 'ai', False, 'staff@x')
        check(not platform_switches.is_on('ai') and llm.key() == '' and not llm.ready(),
              'AI off: the Claude key reads as not set, so callers fall back as they do with no key')
        import assistant
        check(assistant._api_key() == '', 'including the older route')
        platform_switches.set_switch(engine, 'ai', True, 'staff@x')
        check(llm.key() == 'sk-ant-test', 'and back on')

        platform_switches.set_switch(engine, 'sms', False, 'staff@x')
        ok, detail = notifications.send_sms('+14075550100', 'hi')
        check(not ok and 'switched off' in detail, f'texting off: a text is refused ({detail!r})')
        platform_switches.set_switch(engine, 'sms', True, 'staff@x')
        ok2, detail2 = notifications.send_sms('+14075550100', 'hi')
        check('switched off' not in detail2, 'and back on it goes on to the normal checks')

        import affiliates
        partner = {'name': 'Rae', 'payout_account_id': 'acct_1', 'payout_ready': True}
        os.environ['STRIPE_PLATFORM_SECRET_KEY'] = 'sk_test_x'
        check(affiliates.can_pay_by_stripe(partner)[0], 'a ready partner can be paid')
        platform_switches.set_switch(engine, 'partner_payouts', False, 'staff@x')
        allowed, why = affiliates.can_pay_by_stripe(partner)
        check(not allowed and 'switched off' in why, 'payouts off: nobody can be paid, and it says why')
        platform_switches.set_switch(engine, 'partner_payouts', True, 'staff@x')

        from blueprints.signup import signups_open
        check(signups_open(), 'signups are open to begin with')
        platform_switches.set_switch(engine, 'signups', False, 'staff@x')
        check(not signups_open(), 'signups off from the console: closed')
        os.environ['SIGNUPS_OPEN'] = '0'
        platform_switches.set_switch(engine, 'signups', True, 'staff@x')
        check(not signups_open(), 'the environment still wins: SIGNUPS_OPEN=0 stays closed')
        check([s for s in platform_switches.states(engine) if s['key'] == 'signups'][0]['held_by_env'],
              'and the console is told it is the environment holding the door')
        os.environ['SIGNUPS_OPEN'] = '1'
        platform_switches.clear_cache()
        check(signups_open(), 'reopened')
        try:
            platform_switches.set_switch(engine, 'bogus', False)
            check(False, 'an unknown switch cannot be written')
        except ValueError:
            check(True, 'an unknown switch cannot be written')
        platform_switches.set_switch(engine, 'signups', False, 'staff@x')
    check(app.test_client().get('/signup', headers=PRODUCT).status_code == 404,
          'and with signups off the signup page is not there')
    with app.app_context():
        platform_switches.set_switch(engine, 'signups', True, 'staff@x')

        class Broken:
            def connect(self):
                raise RuntimeError('database blinked')
        platform_switches.clear_cache()
        check(platform_switches.is_on('ai', Broken()) and platform_switches.is_on('sms', Broken()),
              'an unreadable database means ON: a kill switch must not fail closed')

    print('\n8b. The switches reach every path (review findings)')
    with app.app_context():
        import speech
        os.environ['OPENAI_API_KEY'] = 'sk-test'
        check(speech.provider() is not None, 'speech has a provider while AI is on')
        platform_switches.set_switch(engine, 'ai', False, 'staff@x')
        check(speech.provider() is None, 'AI off: no paid speech either, the page falls back to the free voice')
        platform_switches.set_switch(engine, 'ai', True, 'staff@x')
        os.environ.pop('OPENAI_API_KEY', None)

        import lead_outreach
        platform_switches.set_switch(engine, 'sms', False, 'staff@x')
        ok, detail = lead_outreach.send_text(
            engine, {'id': 1, 'phone': '4075550100', 'name': 'x'}, 'Hi', 'test')
        check(not ok and 'switched off' in detail,
              'texting off: console outreach is refused too, not only the company send path')
        platform_switches.set_switch(engine, 'sms', True, 'staff@x')

        # Pruning keeps the evidence that something stopped.
        old = NOW - timedelta(days=120)
        control_plane.record_platform_run(engine, 'backup:gone', ok=True, now=old)
        control_plane.record_platform_run(engine, 'backup:gone', ok=False, detail='broke',
                                          now=old + timedelta(days=1))
        control_plane.record_platform_run(engine, 'job:other', ok=True,
                                          now=NOW.replace(minute=10))   # minute % 10 == 0: prunes
        kept = control_plane.platform_runs_for(engine, 'backup:gone', 10)
        check(len(kept) == 2 and control_plane.last_ok_platform_run(engine, 'backup:gone'),
              'an outage older than the retention window still shows: newest row and last success survive pruning')
        check(platform_health.run_state(engine, 'backup:gone', 36, now=NOW)['state'] == 'failed',
              'so it is failed, not quietly "not reported yet"')

    print('\n9. The console')
    mgr, mpass = f'mgr-{TAG}@example.com', 'a-real-console-password-1'
    hlp, hpass = f'hlp-{TAG}@example.com', 'a-real-console-password-2'
    with app.app_context():
        control_plane.add_console_user(engine, mgr, 'Manager', mpass, role='manager')
        control_plane.add_console_user(engine, hlp, 'Helper', hpass, role='helper')
    cc = app.test_client()
    cc.post('/console/login', data={'email': mgr, 'password': mpass})
    page = cc.get('/console/health').data.decode()
    for needle, label in (('Backups', 'backups'), ('Background jobs', 'background jobs'),
                          ('Platform errors', 'platform errors'), ('Usage this month', 'usage'),
                          ('id="switches"', 'switches'), ('Needs a look', 'the alarm')):
        check(needle in page, f'the Health page has {label}')
    check('restore check failed' in page, 'a failed backup says what it said')
    check('built-in method' not in page and '&lt;' not in page.split('Backups', 1)[1].split('Platform errors')[0],
          'a run with no detail shows nothing odd (a dict key called "items" once rendered as its method)')
    check('title="Backups, background jobs, Stripe or platform errors that need a look"' in page,
          'and the Health tab carries a count of what needs a look')
    if os.environ.get('DUMP_HEALTH_PAGE'):
        open(os.environ['DUMP_HEALTH_PAGE'], 'w').write(page)

    n = len(control_plane.platform_runs_for(engine, 'backup:akye', 50))
    r = cc.post('/console/health/switch', data={'key': 'ai', 'on': '0'}, follow_redirects=True)
    check('AI features is now OFF' in r.data.decode() and not platform_switches.is_on('ai'),
          'a manager can switch AI off, and is told')
    with app.app_context():
        record = [x['action'] for x in control_plane.console_log_all(engine)]
    check('platform switch off' in record, 'and it is in the Record')
    cc.post('/console/health/switch', data={'key': 'ai', 'on': '1'})
    check(platform_switches.is_on('ai'), 'and back on')
    r = cc.post('/console/health/switch', data={'key': 'bogus', 'on': '0'}, follow_redirects=True)
    check('not a switch' in r.data.decode(), 'an invented switch is refused')

    hc = app.test_client()
    hc.post('/console/login', data={'email': hlp, 'password': hpass})
    hc.post('/console/health/switch', data={'key': 'sms', 'on': '0'})
    check(platform_switches.is_on('sms'), 'a helper cannot flip a switch')
    check(b'Turn off' not in hc.get('/console/health').data, 'and is not offered the buttons')

    cc.post('/console/health/errors/resolve', data={})
    check(platform_health.platform_errors(engine)[1] == 0, 'a manager can mark platform errors as looked at')
finally:
    try:
        from extensions import db
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        provisioning._engine().dispose()
    except Exception:
        pass
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
    admin.dispose()

if failures:
    print(f'\n❌ {len(failures)} platform health check(s) failed.')
    sys.exit(1)
print('\n✅ The platform says when its own background work stops, and the emergency switches do what they say.')
