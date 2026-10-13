"""Telling Meta a signup happened, and the ways that quietly goes wrong.

None of this talks to Meta. Every failure it guards against is one where the
request succeeds, the report looks populated, and the number is meaningless:

  * a click id that was lower-cased on the way through, which still looks
    like a click id and matches nobody;
  * an email hashed differently from the way Meta hashes it, which matches
    nobody either, and fails identically for every single signup;
  * the same account counted twice because a deploy replayed a request;
  * and the one that is not silent at all -- an exception from an
    advertising report taking down the signup that it was reporting on.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import attribution
import meta_capi


def _on():
    os.environ['META_PIXEL_ID'] = '123'
    os.environ['META_CAPI_TOKEN'] = 'tok'


def _off():
    os.environ.pop('META_PIXEL_ID', None)
    os.environ.pop('META_CAPI_TOKEN', None)


def test_does_nothing_at_all_until_both_halves_are_configured():
    _off()
    assert meta_capi.enabled() is False
    ok, why = meta_capi.send(meta_capi.REGISTRATION, 'acme')
    assert ok is False and 'not set' in why

    # Half-configured is still off: a dataset with no token cannot be
    # written to, and a token with no dataset has nowhere to go.
    os.environ['META_PIXEL_ID'] = '123'
    assert meta_capi.enabled() is False
    _off()


def test_a_failure_to_report_never_breaks_the_thing_being_reported():
    """The entry points are called from the signup request and from a
    template context processor. Neither may raise."""
    _on()
    try:
        meta_capi.registration('acme', 'owner@example.com',
                               attribution={'fbc': 'fb.1.1.abc'})
        meta_capi.activation({'slug': 'acme', 'owner_email': 'o@e.com'})
        meta_capi.activation(None)          # no company at all
        meta_capi.registration('acme', None)
    finally:
        _off()


def test_email_is_hashed_the_way_meta_hashes_it():
    """Trimmed, lower-cased, SHA-256. Different normalisation is not a near
    miss -- it matches nothing, for everybody, forever."""
    _on()
    p = meta_capi.build(meta_capi.REGISTRATION, 'acme',
                        email='  Owner@Example.COM ')
    assert p['user_data']['em'] == [
        hashlib.sha256(b'owner@example.com').hexdigest()]
    _off()


def test_click_id_goes_verbatim_and_is_never_hashed():
    """Meta issued it; Meta expects it back exactly. Hashing it, or putting
    it through attribution.clean(), produces a plausible-looking string that
    matches no ad."""
    _on()
    fbc = 'fb.1.1791935541332.IwAR2xQ-AbC_dEf.GhI-JkL'
    p = meta_capi.build(meta_capi.REGISTRATION, 'acme', fbc=fbc)
    assert p['user_data']['fbc'] == fbc
    _off()


def test_the_click_id_survives_the_whole_journey_with_its_case():
    """attribution.clean() lower-cases, and for a click id that is
    destruction rather than cleaning. The two modules have to agree."""
    raw = 'IwAR2xQ-AbC_dEf.GhI-JkL'
    found = attribution.from_request(
        {'utm_source': 'facebook', 'fbclid': raw}, '', 'akyehq.com', '/signup')
    assert found['fbc'].endswith(raw), found['fbc']
    assert found['fbc'].startswith('fb.1.')

    _on()
    p = meta_capi.build(meta_capi.REGISTRATION, 'acme', fbc=found['fbc'])
    assert p['user_data']['fbc'].endswith(raw)
    _off()


def test_the_same_account_cannot_be_counted_twice():
    """A cron that fires twice, or a deploy that replays a request, must not
    produce a second conversion. Meta dedupes on event_id."""
    _on()
    a = meta_capi.build(meta_capi.REGISTRATION, 'acme', when=1)
    b = meta_capi.build(meta_capi.REGISTRATION, 'acme', when=999)
    assert a['event_id'] == b['event_id']
    # ...but the two different events for one company are distinct, or
    # activation would be swallowed as a duplicate of the signup.
    c = meta_capi.build(meta_capi.ACTIVATION, 'acme')
    assert c['event_id'] != a['event_id']
    _off()


def test_a_signup_with_nothing_to_match_on_is_still_a_valid_event():
    """Somebody who typed the address in by hand has no click id and may
    have given an email we cannot read here. That is a weaker event, not a
    malformed one."""
    _on()
    p = meta_capi.build(meta_capi.ACTIVATION, 'acme')
    assert p['user_data'] == {}
    assert p['event_name'] == 'Activated'
    assert p['action_source'] == 'website'
    _off()
