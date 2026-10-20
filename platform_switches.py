"""Emergency switches for the whole product, set from the console.

Four things cost money or cannot be taken back, and until now the only way to
stop any of them was to change an environment variable and redeploy:

    signups          new companies signing themselves up
    ai               everything that calls Claude on Akye's credits
    sms              every text, from every company, through Akye's Twilio
    partner_payouts  sending money to affiliate partners

The console flips them in the `product_switches` table that the email switches
already use, under a `platform.` prefix so the two can never collide.

## On unless somebody turned it off

An unreadable table, a missing control plane (a single-business install), a
database hiccup: all mean ON. A kill switch that fails closed would take the
product down whenever the database blinked, which is the opposite of what an
emergency control is for.

## Except the one that sends money

`partner_payouts` is the exception: it fails CLOSED. An unreadable table or an
unreachable control plane means no transfer is sent, because a switch that
cannot be read is not permission to move money. `PARTNER_PAYOUTS_OPEN=0` shuts
it from the environment too, whatever the console says, the same way
`SIGNUPS_OPEN=0` holds the door shut: it works when the database does not.

## Cached for a few seconds

Signups are checked on every marketing page and texts on every send, so the
answer is kept for CACHE_SECONDS. A switch thrown in the console takes effect
here at once and in other workers within that window.

## The environment still wins for signups

`SIGNUPS_OPEN=0` closes signup whatever this says: it is the documented
containment switch and a console that could quietly reopen it would defeat it.
The console shows when the environment is what is holding the door shut.
"""
import os
import time

CACHE_SECONDS = 8
PREFIX = 'platform.'

# (key, label, what turning it OFF does, and the caution that goes with it)
SWITCHES = [
    ('signups', 'New signups',
     'Stops new companies opening an account. Existing companies are untouched.',
     None),
    ('ai', 'AI features',
     'Turns off Nana, the setup chat, drafted content and translation for every '
     'company. They behave as if no Claude key were set.',
     None),
    ('sms', 'Texting',
     'Stops every text from every company, including job and reminder texts a '
     'cleaner is waiting on. Use it for a runaway bill or abuse, not routinely.',
     'This stops operational texts too.'),
    ('partner_payouts', 'Partner payouts',
     'Stops sending money to affiliate partners. Commissions keep accruing and '
     'nothing is lost; paying resumes when it is turned back on.',
     None),
]
KEYS = [k for k, *_ in SWITCHES]

# Switches that mean OFF when they cannot be read, and the environment variable
# that closes each one whatever the console says (set to 0).
FAIL_CLOSED = {'partner_payouts': 'PARTNER_PAYOUTS_OPEN'}

_cache = {'at': 0.0, 'map': {}}


def clear_cache():
    _cache['at'] = 0.0
    _cache['map'] = {}


def _engine():
    import provisioning
    return provisioning._engine()


def _load(engine=None):
    """{key: enabled}, or None when the table could not be read."""
    now = time.monotonic()
    if _cache['at'] and now - _cache['at'] < CACHE_SECONDS:
        return _cache['map']
    try:
        import control_plane
        raw = control_plane.switches_checked(engine or _engine())
        loaded = {k[len(PREFIX):]: v for k, v in raw.items() if k.startswith(PREFIX)}
    except Exception:
        loaded = None
    _cache['map'] = loaded
    _cache['at'] = now
    return loaded


def is_on(key, engine=None):
    """Whether this part of the product may run. True unless turned off, and
    for the fail-closed switches, False unless the answer could be read."""
    env = FAIL_CLOSED.get(key)
    if env and os.environ.get(env) == '0':
        return False
    try:
        loaded = _load(engine)
    except Exception:
        loaded = None
    if loaded is None:
        return key not in FAIL_CLOSED
    return bool(loaded.get(key, True))


def set_switch(engine, key, on, by=None):
    import control_plane
    if key not in KEYS:
        raise ValueError(f'{key!r} is not a platform switch')
    control_plane.set_switch(engine, PREFIX + key, on, by)
    clear_cache()


def states(engine):
    """[{key, label, blurb, caution, on, by, at, held_by_env}] for the console."""
    import control_plane
    rows = {}
    try:
        with engine.connect() as conn:
            from sqlalchemy import select
            for r in conn.execute(select(control_plane.product_switches)).mappings():
                if r['key'].startswith(PREFIX):
                    rows[r['key'][len(PREFIX):]] = r
    except Exception:
        pass
    out = []
    for key, label, blurb, caution in SWITCHES:
        r = rows.get(key)
        out.append({'key': key, 'label': label, 'blurb': blurb, 'caution': caution,
                    'on': bool(r['enabled']) if r else True,
                    'by': r['updated_by'] if r else None,
                    'at': r['updated_at'] if r else None,
                    'held_by_env': (key == 'signups' and os.environ.get('SIGNUPS_OPEN') == '0')
                                or os.environ.get(FAIL_CLOSED.get(key, '')) == '0'})
    return out
