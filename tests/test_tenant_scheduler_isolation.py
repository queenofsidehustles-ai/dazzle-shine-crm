"""TEN-05: central scheduler must preserve tenant boundaries and release provenance."""
from pathlib import Path

import pytest

import scheduler


def test_scheduler_calls_each_active_tenant_on_its_own_host(monkeypatch):
    monkeypatch.setenv('BASE_DOMAIN', 'akyehq.com')
    monkeypatch.setenv('REMINDER_API_KEY', 'test-key')
    monkeypatch.setattr(scheduler, 'companies', lambda: [
        {'slug': 'alpha', 'status': 'active'},
        {'slug': 'bravo', 'status': 'active'},
        {'slug': 'suspended', 'status': 'suspended'},
    ])
    monkeypatch.setattr(scheduler.time, 'sleep', lambda _n: None)

    calls = []

    def fake_call(slug, job, base, key):
        calls.append((slug, job, base, key))
        return True, 'ok'

    monkeypatch.setattr(scheduler, 'call', fake_call)

    failures = scheduler.run(['reminders'], quiet=True)

    assert failures == []
    assert calls == [
        ('alpha', 'reminders', 'akyehq.com', 'test-key'),
        ('bravo', 'reminders', 'akyehq.com', 'test-key'),
    ]


def test_one_tenant_failure_does_not_stop_other_tenants(monkeypatch):
    monkeypatch.setenv('BASE_DOMAIN', 'akyehq.com')
    monkeypatch.setenv('REMINDER_API_KEY', 'test-key')
    monkeypatch.setattr(scheduler, 'companies', lambda: [
        {'slug': 'alpha', 'status': 'active'},
        {'slug': 'bravo', 'status': 'active'},
        {'slug': 'charlie', 'status': 'active'},
    ])
    monkeypatch.setattr(scheduler.time, 'sleep', lambda _n: None)

    seen = []

    def fake_call(slug, job, base, key):
        seen.append(slug)
        if slug == 'bravo':
            return False, 'HTTP 500'
        return True, 'ok'

    monkeypatch.setattr(scheduler, 'call', fake_call)

    failures = scheduler.run(['reminders'], quiet=True)

    assert seen == ['alpha', 'bravo', 'charlie']
    assert failures == [('bravo', 'reminders', 'HTTP 500')]


def test_only_never_falls_back_to_another_tenant(monkeypatch):
    monkeypatch.setenv('BASE_DOMAIN', 'akyehq.com')
    monkeypatch.setenv('REMINDER_API_KEY', 'test-key')
    monkeypatch.setattr(scheduler, 'companies', lambda: [
        {'slug': 'alpha', 'status': 'active'},
        {'slug': 'bravo', 'status': 'active'},
    ])
    monkeypatch.setattr(scheduler.time, 'sleep', lambda _n: None)

    calls = []
    monkeypatch.setattr(
        scheduler, 'call',
        lambda slug, job, base, key: (calls.append(slug) or (True, 'ok')),
    )

    assert scheduler.run(['reminders'], only='bravo', quiet=True) == []
    assert calls == ['bravo']

    with pytest.raises(SystemExit, match="No active company called 'missing'"):
        scheduler.run(['reminders'], only='missing', quiet=True)


def test_automation_workflow_uses_triggering_revision_not_hardcoded_branch():
    workflow = Path('.github/workflows/automations.yml').read_text()

    assert 'ref: akye-stable' not in workflow
    assert 'actions/checkout@v4' in workflow
    assert 'git rev-parse HEAD' in workflow
    assert 'Scheduler source:' in workflow
