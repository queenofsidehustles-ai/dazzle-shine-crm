"""Pointing each person at the features they have not found yet.

Help tips (help_tips.py) say what a feature is for, but only to somebody who
goes looking. This is the other half: per person, which menu features they
have opened, so the app can

  * put a dot on a few menu items they have never opened -- a few, chosen
    from DISCOVER in order of what pays back most, never the whole menu at
    once, which is how every dot gets ignored;
  * show one "Did you know?" when they sign in, for the first of those they
    have not been shown lately or turned down;
  * count, across every company, which tips are read and whether the feature
    is opened afterwards (control_plane.tip_events), so the wording that does
    not work can be rewritten.

Per person, not per company: a new dispatcher has opened none of it, whatever
the owner has. Nothing here may break a page -- every entry point swallows its
own failures and leaves the page as it would have been.
"""
import hashlib
from datetime import datetime, timedelta

# A feature opened within this long of reading its tip counts for the tip.
USED_WITHIN = timedelta(days=7)
# "Not now" is never asked again; a suggestion simply ignored comes back after this.
SUGGEST_AGAIN_AFTER = timedelta(days=7)
# More dots than this and they stop meaning anything.
MAX_DOTS = 3
# A menu tip is read, then its item clicked: the read is sent as the page
# changes and can land just after the visit it led to. A read from the menu
# arriving this soon after the first visit was the reason for that visit.
READ_RACE = timedelta(seconds=15)


def user_key():
    """Who this is, by login: 'u<id>', 'owner' for the env login, or None."""
    from flask import session
    if not session.get('logged_in'):
        return None
    uid = session.get('user_id')
    return f'u{uid}' if uid else 'owner'


def _menu(nav):
    """{endpoint: locked} for every menu item and tab this person can see."""
    out = {}
    for section in nav or []:
        for item in section.get('items', []):
            out[item['endpoint']] = bool(item.get('locked'))
            for t in item.get('tabs', []):
                out.setdefault(t['endpoint'], bool(t.get('locked')))
    return out


def _table():
    from models import FeatureSeen
    return FeatureSeen.__table__


def _rows():
    """{endpoint: {column: value}} for this person, once per request.

    Read and written on a connection of its own, never the request's session:
    this runs while a page renders, and committing the request's session there
    would also save whatever the page changed but meant to throw away -- a
    quote previewed and not saved, say.
    """
    from flask import g
    from extensions import db
    from sqlalchemy import select
    if '_feature_seen' not in g:
        key = user_key()
        rows = {}
        if key:
            t = _table()
            with db.engine.connect() as conn:
                for r in conn.execute(select(t).where(t.c.user_key == key)).mappings():
                    rows[r['endpoint']] = dict(r)
        g._feature_seen = rows
    return g._feature_seen


def _set(endpoint, **fields):
    """Write fields on this person's row for endpoint, creating it if needed."""
    from extensions import db
    from sqlalchemy import insert, update
    from sqlalchemy.exc import IntegrityError
    t = _table()
    key = user_key()
    where = (t.c.user_key == key) & (t.c.endpoint == endpoint)
    try:
        with db.engine.begin() as conn:
            if not conn.execute(update(t).where(where).values(**fields)).rowcount:
                conn.execute(insert(t).values(user_key=key, endpoint=endpoint, **fields))
    except IntegrityError:
        # Two tabs writing the same first visit: the other one inserted it.
        with db.engine.begin() as conn:
            conn.execute(update(t).where(where).values(**fields))
    _rows().setdefault(endpoint, {'endpoint': endpoint}).update(fields)


def _event(tip, event):
    """One line in the cross-company tip report. Hosted only, never fatal."""
    try:
        import auth
        import control_plane
        import provisioning
        from flask import session
        slug = auth.current_tenant_slug()
        if not slug:
            return
        person = hashlib.sha256(f'{slug}:{user_key()}'.encode()).hexdigest()[:16]
        control_plane.record_tip_event(provisioning._engine(), slug, person,
                                       session.get('role'), tip, event)
    except Exception:
        pass


def note_visit(endpoint, nav):
    """The page on screen is a menu feature this person can use: remember the
    first time they opened it, and credit its tip if they read it first."""
    try:
        import navigation
        target = navigation._resolve(endpoint or '')
        menu = _menu(nav)
        if target not in menu or menu[target] or user_key() is None:
            return
        row = _rows().get(target) or {}
        if row.get('first_seen_at'):
            return
        now = datetime.utcnow()
        _set(target, first_seen_at=now)
        if row.get('tip_opened_at') and now - row['tip_opened_at'] <= USED_WITHIN:
            _event(target, 'used')
    except Exception:
        pass


def _locked(key):
    """A feature this company's plan does not include. Reading its tip says
    nothing about whether the tip works -- they could not open it if they
    wanted to -- so it is not counted, and stays uncounted until they can."""
    try:
        import entitlements
        import navigation
        feature = navigation.feature_for(key)
        return bool(feature) and not entitlements.can(feature)
    except Exception:
        return False


def record_open(key, source=None):
    """They read a tip -- the first time counts, for the report.

    `source` 'menu' is a tip read from the sidebar, which can be overtaken by
    the click it prompted (READ_RACE): then the visit came from the read, and
    counts for it."""
    import help_tips
    if key not in help_tips.TIPS or user_key() is None or _locked(key):
        return
    row = _rows().get(key) or {}
    if row.get('tip_opened_at'):
        return
    now = datetime.utcnow()
    _set(key, tip_opened_at=now)
    _event(key, 'open')
    seen = row.get('first_seen_at')
    if source == 'menu' and seen and timedelta(0) <= now - seen <= READ_RACE:
        _event(key, 'used')


def _candidates(nav):
    """Features from DISCOVER this person can use and has never opened."""
    import help_tips
    menu = _menu(nav)
    rows = _rows()
    return [ep for ep in help_tips.DISCOVER
            if ep in menu and not menu[ep]
            and not (rows.get(ep) or {}).get('first_seen_at')]


def dots(nav, setup_done=True):
    """The few menu items to mark as not opened yet. None while an owner is
    still setting up: then Getting started is the one thing to look at."""
    try:
        if not setup_done or user_key() is None:
            return set()
        return set(_candidates(nav)[:MAX_DOTS])
    except Exception:
        return set()


def suggestion(nav, setup_done=True):
    """At most one "Did you know?" per sign-in, on a menu page: the first
    unopened feature they have neither turned down nor been shown lately."""
    from flask import g, request, session
    try:
        if '_suggestion' in g:
            return g._suggestion
        g._suggestion = None
        if (not setup_done or request.method != 'GET' or session.get('tip_suggested')
                or session.get('demo_tour') or user_key() is None):
            return None
        import help_tips
        import navigation
        if navigation._resolve(request.endpoint or '') != request.endpoint \
                or request.endpoint not in _menu(nav):
            return None                     # a list page, not a form or a record
        now = datetime.utcnow()
        rows = _rows()
        for ep in _candidates(nav):
            row = rows.get(ep) or {}
            if row.get('dismissed_at') or (
                    row.get('suggested_at') and now - row['suggested_at'] < SUGGEST_AGAIN_AFTER):
                continue
            tip = help_tips.get(ep)
            if not tip:
                continue
            _set(ep, suggested_at=now)
            session['tip_suggested'] = ep
            _event(ep, 'suggested')
            g._suggestion = tip
            return tip
    except Exception:
        return None
    return None


def dismiss(key):
    import help_tips
    if key not in help_tips.TIPS or user_key() is None:
        return
    _set(key, dismissed_at=datetime.utcnow())
    _event(key, 'dismissed')


def clicked(key):
    _event(key, 'clicked')
