"""Answer a commercial quote the way a customer's browser does: open the
link, take the terms reference the page shows, and post it back with a
typed name. Accept and decline both refuse a post without the reference."""
import re


def shown_hash(client, token, host):
    page = client.get(f'/quotes/view/{token}', base_url=host).get_data(as_text=True)
    m = re.search(r'name="terms_hash" value="([0-9a-f]{64})"', page)
    return m.group(1) if m else ''


def answer(client, token, host, what='accept', name='Pat Signer', title='', terms_hash=None, **extra):
    data = {'terms_hash': shown_hash(client, token, host) if terms_hash is None else terms_hash,
            'signer_name': name, 'signer_title': title}
    return client.post(f'/quotes/view/{token}/{what}', base_url=host, data=data, **extra)
