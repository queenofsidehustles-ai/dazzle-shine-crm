import tenant_data_lifecycle as lifecycle
import tenant_lifecycle_cli as cli


def test_purge_cli_preflight_contract_exists():
    """The operator purge command must never point at a missing lifecycle API."""
    assert callable(lifecycle.purge_eligible)
    assert callable(lifecycle.purge_tenant)


def test_purge_cli_checks_eligibility_before_destructive_call(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(lifecycle, 'purge_eligible', lambda slug: False)
    monkeypatch.setattr(
        lifecycle,
        'purge_tenant',
        lambda slug: calls.append(slug) or (_ for _ in ()).throw(
            AssertionError('destructive purge must not run for ineligible tenant')
        ),
    )

    rc = cli.main(['purge', 'retained-tenant'])

    assert rc == 1
    assert calls == []
    assert 'not eligible' in capsys.readouterr().out.lower()


def test_purge_cli_requires_explicit_confirmation(monkeypatch):
    calls = []

    monkeypatch.setattr(lifecycle, 'purge_eligible', lambda slug: True)
    monkeypatch.setattr(lifecycle, 'purge_tenant', lambda slug: calls.append(slug))
    monkeypatch.setattr('builtins.input', lambda prompt='': 'NO')

    rc = cli.main(['purge', 'eligible-tenant'])

    assert rc == 1
    assert calls == []
