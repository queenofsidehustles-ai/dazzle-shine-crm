"""Telling Meta that an ad actually produced a cleaning company.

The pixel on getakye.com can only see the landing page and a click on "Start
free". It cannot see the thing being paid for, because the thing being paid
for happens on another domain, after a form, on the server -- and the server
is where this file sends it from.

## Why not a pixel on akyehq.com

Signup finishes on the company's *own* subdomain, acme.akyehq.com. Putting
Meta's tracker there would load an advertising script inside a customer's
private workspace, next to their clients' addresses and their cleaners' pay.
That is not a tradeoff worth making for attribution, and it would have to be
disclosed to every one of them. A browser pixel also loses whatever share of
events an ad blocker or an iOS prompt decides to drop, and it could not see
activation at all -- activation is not a page, it is a condition noticed on
the server.

## Two events, deliberately

    CompleteRegistration   an account exists
    Activated              a real cleaner and a real customer are in it

The first is common enough for Meta to learn from: an ad set needs roughly
fifty conversions a week before it leaves the learning phase, and optimising
toward an event that fires twice a week starves it. The second is the one
that means something -- it is the difference between somebody who opened an
account and somebody who is using one -- so it is sent from the first day in
order to accumulate history, and becomes the optimisation target later, when
there is enough of it.

## Matching

An event only earns its ad credit if Meta can tie it back to the click. The
strongest signal is `fbc`, their click id, which arrived on the landing URL
at getakye.com and reached us only because pixel.js carries it across the
domain boundary (see attribution.py). The email is hashed and sent as a
second, weaker signal, so a signup still matches something when the click id
is missing -- somebody who typed the address in by hand, or clicked an old
link.

Nothing here is allowed to be the reason a signup fails. Every entry point
swallows its own errors, the timeout is short, and a dropped conversion costs
a row in a report. A raised exception would cost the account.
"""
import hashlib
import os
import time

import product

API_VERSION = 'v21.0'
# Short on purpose. This runs inside a request that a person is waiting on,
# and a conversion is worth far less than the page.
TIMEOUT = 4

REGISTRATION = 'CompleteRegistration'
ACTIVATION = 'Activated'


def enabled():
    """Both halves, or nothing happens. There is no partial mode: a dataset
    with no token cannot be written to, and a token with no dataset has
    nowhere to write."""
    return bool(product.meta_pixel_id() and product.meta_capi_token())


def _hashed(value):
    """Lower-cased, trimmed, SHA-256 -- Meta's required normalisation.

    They match on the hash, so our normalisation has to be identical to
    theirs or every email silently matches nothing.
    """
    value = (value or '').strip().lower()
    if not value:
        return None
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _user_data(email, fbc, ip, user_agent):
    out = {}
    em = _hashed(email)
    if em:
        out['em'] = [em]
    if fbc:
        # Never hashed, unlike the email: it is an identifier Meta issued
        # itself and expects back verbatim.
        out['fbc'] = fbc
    if ip:
        out['client_ip_address'] = ip
    if user_agent:
        out['client_user_agent'] = user_agent
    return out


def build(event, slug, email=None, fbc=None, ip=None, user_agent=None,
          when=None, source_url=None):
    """One event, as Meta's payload. Pure, so the tests can read it."""
    return {
        'event_name': event,
        'event_time': int(when or time.time()),
        'action_source': 'website',
        # Same slug and same event name produce the same id, so a retry --
        # or a cron that runs twice, or a deploy that replays a request --
        # is counted once. Meta dedupes on this for 48 hours.
        'event_id': f'{event}:{slug}',
        'event_source_url': source_url or product.base_url() or None,
        'user_data': _user_data(email, fbc, ip, user_agent),
    }


def send(event, slug, email=None, fbc=None, ip=None, user_agent=None,
         when=None, source_url=None):
    """Returns (ok, detail). Never raises, whatever happens."""
    if not enabled():
        return False, 'META_PIXEL_ID or META_CAPI_TOKEN not set'
    try:
        import requests
        payload = {'data': [build(event, slug, email, fbc, ip, user_agent,
                                  when, source_url)]}
        test_code = product.meta_test_event_code()
        if test_code:
            payload['test_event_code'] = test_code
        resp = requests.post(
            f'https://graph.facebook.com/{API_VERSION}/'
            f'{product.meta_pixel_id()}/events',
            params={'access_token': product.meta_capi_token()},
            json=payload, timeout=TIMEOUT)
        if resp.status_code >= 300:
            # The body carries Meta's reason, and the reason is almost always
            # the token. Printed rather than swallowed, because a silent 400
            # for a fortnight is how a campaign gets optimised against
            # nothing at all.
            return False, f'HTTP {resp.status_code}: {resp.text[:300]}'
        return True, resp.text[:200]
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def _say(event, slug, ok, detail):
    print(f'  {"✓" if ok else "⚠️ "} meta {event} {slug}: {detail}')


def registration(slug, email, attribution=None, ip=None, user_agent=None):
    """An account was created. Called from signup, where the attribution is
    still a cookie rather than a row -- it is written to the company in the
    same request, but reading it back would be a second query for a fact we
    are already holding."""
    if not enabled():
        return
    a = attribution or {}
    ok, detail = send(REGISTRATION, slug, email=email, fbc=a.get('fbc'),
                      ip=ip, user_agent=user_agent)
    _say(REGISTRATION, slug, ok, detail)


def activation(org):
    """A cleaner and a customer are in the account. Called once, from
    wherever the trial clock is started, and reading `signup_fbc` off the
    company because by now that is where it lives."""
    if not enabled() or not org:
        return
    ok, detail = send(ACTIVATION, org.get('slug') or '',
                      email=org.get('owner_email'),
                      fbc=org.get('signup_fbc'))
    _say(ACTIVATION, org.get('slug') or '?', ok, detail)
