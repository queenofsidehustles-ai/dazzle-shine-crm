"""Trial reminders: scheduled once a day, on the product's own address.

The endpoint existed for weeks and nothing called it, so no company on a trial
was ever reminded of anything. These pin the schedule down: the daily run
calls it exactly once, on the apex (never per company), never during a
single-company test run, and a failure or a failed send turns the run red.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scheduler


def _setup(monkeypatch, posted, reply=None):
    monkeypatch.setenv('BASE_DOMAIN', 'akyehq.com')
    monkeypatch.setenv('REMINDER_API_KEY', 'test-key')
    monkeypatch.setattr(scheduler, 'companies', lambda: [
        {'slug': 'alpha', 'status': 'active'}, {'slug': 'bravo', 'status': 'active'}])
    monkeypatch.setattr(scheduler.time, 'sleep', lambda _n: None)

    def fake_post(url, key, raw=False):
        posted.append(url)
        if url.endswith('/api/trial-nudges'):
            return reply or (True, json.dumps({
                'ok': True, 'sent': 2, 'start_7': 1, 'ending': 1, 'failed': 0,
                'considered': 7, 'dry_run': False,
                'plan': [['alpha', 'start_7', 'owner@alpha.test']]}))
        return True, '{"ok": true}'
    monkeypatch.setattr(scheduler, '_post', fake_post)


def test_daily_run_calls_trial_reminders_once_on_the_apex(monkeypatch):
    posted = []
    _setup(monkeypatch, posted)
    failures = scheduler.run(scheduler.jobs_for('daily'), quiet=True,
                             product_jobs=scheduler.product_jobs_for('daily'))
    assert failures == []
    trial = [u for u in posted if u.endswith('/api/trial-nudges')]
    assert trial == ['https://akyehq.com/api/trial-nudges']
    assert 'https://alpha.akyehq.com/api/reminders' in posted


def test_daily_cadence_includes_trial_reminders_hourly_does_not():
    assert scheduler.product_jobs_for('daily') == ['trial-nudges']
    assert scheduler.product_jobs_for('hourly') == []


def test_single_company_run_never_emails_every_company(monkeypatch):
    posted = []
    _setup(monkeypatch, posted)
    scheduler.run(scheduler.jobs_for('daily'), only='alpha', quiet=True,
                  product_jobs=scheduler.product_jobs_for('daily'))
    assert not any(u.endswith('/api/trial-nudges') for u in posted)


def test_output_carries_counts_not_owner_emails(monkeypatch, capsys):
    posted = []
    _setup(monkeypatch, posted)
    scheduler.run([], product_jobs=['trial-nudges'])
    out = capsys.readouterr().out
    assert 'sent 2' in out and 'start_7 1' in out
    assert 'owner@alpha.test' not in out


def test_a_failed_send_or_refusal_turns_the_run_red(monkeypatch):
    posted = []
    _setup(monkeypatch, posted, reply=(True, json.dumps({'ok': True, 'failed': 1})))
    assert scheduler.run([], quiet=True, product_jobs=['trial-nudges'])
    _setup(monkeypatch, posted, reply=(False, 'HTTP 403 (REMINDER_API_KEY does not match)'))
    failures = scheduler.run([], quiet=True, product_jobs=['trial-nudges'])
    assert failures and failures[0][1] == 'trial-nudges'


def test_main_wires_the_daily_cadence(monkeypatch):
    seen = {}
    monkeypatch.setattr(scheduler, 'run', lambda jobs, only=None, quiet=False,
                        product_jobs=(): seen.update(jobs=jobs, product=product_jobs) or [])
    monkeypatch.setattr(sys, 'argv', ['scheduler.py', '--cadence', 'daily'])
    assert scheduler.main() == 0
    assert seen['product'] == ['trial-nudges'] and 'reminders' in seen['jobs']
    monkeypatch.setattr(sys, 'argv', ['scheduler.py', '--job', 'trial-nudges'])
    scheduler.main()
    assert seen == {'jobs': [], 'product': ['trial-nudges']}
