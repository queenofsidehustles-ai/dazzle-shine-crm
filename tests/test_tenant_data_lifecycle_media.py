"""Private-media purge must remain bounded to the exact tenant prefix."""
import sys
from types import SimpleNamespace

import private_media
import tenant_data_lifecycle as lifecycle


def test_unconfigured_private_media_has_no_provider_delete(monkeypatch):
    monkeypatch.setattr(private_media, 'is_ready', lambda: False)
    result = lifecycle._delete_private_media('alpha')
    assert result == {'provider': 'cloudinary', 'configured': False, 'deleted': 0}


def test_cloudinary_delete_uses_only_exact_tenant_prefix_and_follows_cursor(monkeypatch):
    monkeypatch.setattr(private_media, 'is_ready', lambda: True)
    monkeypatch.setattr(private_media, '_configure', lambda: None)
    calls = []

    def delete_resources_by_prefix(prefix, **kwargs):
        calls.append((prefix, dict(kwargs)))
        if len(calls) == 1:
            return {'deleted': {'a': 'deleted', 'b': 'deleted'}, 'next_cursor': 'page-2'}
        return {'deleted': {'c': 'deleted'}}

    api = SimpleNamespace(delete_resources_by_prefix=delete_resources_by_prefix)
    cloudinary = SimpleNamespace(api=api)
    monkeypatch.setitem(sys.modules, 'cloudinary', cloudinary)
    monkeypatch.setitem(sys.modules, 'cloudinary.api', api)

    result = lifecycle._delete_private_media('alpha')

    assert result['configured'] is True
    assert result['deleted'] == 3
    assert [c[0] for c in calls] == ['akye-private/alpha/', 'akye-private/alpha/']
    assert calls[0][1]['type'] == 'authenticated'
    assert calls[0][1]['resource_type'] == 'image'
    assert calls[1][1]['next_cursor'] == 'page-2'
    assert all('beta' not in prefix for prefix, _ in calls)
