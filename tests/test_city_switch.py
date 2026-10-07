"""One owner, two cities, one login — without a session crossing between them.

Orlando and Huntsville are separate companies because a company holds exactly
one price book and the two markets are priced differently on purpose. Keeping
them apart is what makes each city's prices right; the cost was a second login,
and this closes that and nothing else.

A session cannot simply be carried over. auth.bind_session_to_current_tenant
says why: a cookie minted for one company, replayed by hand against another,
would otherwise be honoured there. So a switch hands the browser a signed token
and the destination issues a session of its own, after checking for itself that
the person belongs.

What has to hold, and what this proves:

- a token works once, at the city it names, for ninety seconds;
- a token for Huntsville is refused by Orlando;
- an edited token is refused;
- a spent token is refused the second time;
- a stranger's token is refused however well-formed;
- and a switch never creates access -- the account must already exist there.

Against a real disposable Postgres, because two companies in one database is
the whole point.
"""
import os
import secrets
import sys
import time

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret-for-switching'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import control_plane
import provisioning
import tenancy
import city_switch

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


TAG = secrets.token_hex(4)
ORL, HSV, OTHER = f'orl{TAG}', f'hsv{TAG}', f'other{TAG}'
OWNER = f'owner-{TAG}@example.com'
STRANGER = f'stranger-{TAG}@example.com'

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()

    for slug, name, email in ((ORL, 'Dazzle Orlando', OWNER),
                              (HSV, 'Dazzle Huntsville', OWNER),
                              (OTHER, 'Someone Else Cleaning', STRANGER)):
        provisioning.provision(slug, name, owner_email=email, quiet=True)
        control_plane.record_tenant_login(engine, email, slug)
        db.session.remove()
        with tenancy.use_tenant(slug):
            from models import User
            u = User(name='Owner', username=email, role='owner', active=True)
            u.set_password('a-real-password-123')
            db.session.add(u); db.session.commit()
        db.session.remove()

    print('\n1. The menu offers the owner both of her cities, and nobody else\'s')
    mine = {c['slug'] for c in city_switch.cities_for(OWNER)}
    check(mine == {ORL, HSV}, f'both of hers, and only hers ({sorted(mine)})')
    check(OTHER not in mine, "another company's city is not in her menu")
    theirs = {c['slug'] for c in city_switch.cities_for(STRANGER)}
    check(theirs == {OTHER}, 'and the stranger sees only their own')

    print('\n2. The menu says the city, not the company name again')
    # Derived from the names alone. The first version read each company's own
    # `city` setting, which meant entering other tenants' schemas from a context
    # processor that runs on every render -- and removing the session
    # mid-request, which 500'd every page. A label is cosmetic and must not go
    # near the session.
    for names, want, why in [
        ({'a': 'Dazzle & Shine Maids \u2014 Huntsville',
          'b': 'Dazzle & Shine Maids \u2014 Orlando'},
         {'a': 'Huntsville', 'b': 'Orlando'}, 'brand and city split by a dash'),
        ({'a': 'Dazzle & Shine Maids Huntsville',
          'b': 'Dazzle & Shine Maids Orlando'},
         {'a': 'Huntsville', 'b': 'Orlando'}, 'no dash, shared opening words'),
        ({'a': 'Huntsville', 'b': 'Orlando'},
         {'a': 'Huntsville', 'b': 'Orlando'}, 'already just cities'),
        ({'a': 'Sparkle Co'}, {'a': 'Sparkle Co'},
         'one company, nothing to strip'),
    ]:
        got = city_switch._labels(names)
        check(got == want, f'{why}: {list(got.values())}')

    labels = {c['slug']: c['label'] for c in city_switch.cities_for(OWNER)}
    check(all(labels.values()), f'every city in the real menu has a label ({list(labels.values())})')

    print('\n3. Entitlement is checked, not assumed')
    check(city_switch.may_switch(OWNER, HSV), 'she may switch to Huntsville')
    check(not city_switch.may_switch(OWNER, OTHER),
          "she may not switch into a company she does not own")
    check(not city_switch.may_switch(STRANGER, ORL),
          'and a stranger may not switch into hers')

    print('\n4. A token works once, at the city it names')
    t = city_switch.mint(OWNER, HSV)
    check(city_switch.verify(t, HSV) == OWNER, 'it verifies at Huntsville')
    check(city_switch.verify(t, HSV) is None,
          'and is refused the second time — a leaked token is spent, not reusable')

    print('\n5. A token is useless anywhere but its destination')
    t2 = city_switch.mint(OWNER, HSV)
    check(city_switch.verify(t2, ORL) is None,
          'a Huntsville token is refused by Orlando')
    check(city_switch.verify(t2, HSV) == OWNER,
          'while still being good for Huntsville')

    print('\n6. A token cannot be edited into something else')
    t3 = city_switch.mint(OWNER, HSV)
    body, sig = t3[len(city_switch._PREFIX):].split('.', 1)
    forged = city_switch._PREFIX + body + '.' + ('A' * len(sig))
    check(city_switch.verify(forged, HSV) is None, 'a replaced signature is refused')
    import base64, json
    raw = json.loads(city_switch._unb64(body))
    raw['email'] = STRANGER
    swapped = (city_switch._PREFIX
               + city_switch._b64(json.dumps(raw, separators=(',', ':'), sort_keys=True).encode())
               + '.' + sig)
    check(city_switch.verify(swapped, HSV) is None,
          'and swapping the email inside it invalidates the signature')

    print('\n7. A token expires')
    old = city_switch.TTL_SECONDS
    try:
        city_switch.TTL_SECONDS = -1
        stale = city_switch.mint(OWNER, HSV)
    finally:
        city_switch.TTL_SECONDS = old
    check(city_switch.verify(stale, HSV) is None, 'an expired token is refused')

    print('\n8. A stranger cannot mint their way in')
    bad = city_switch.mint(STRANGER, ORL)
    check(city_switch.verify(bad, ORL) is None,
          'a well-formed token for a city they do not own is still refused')

    print('\n9. The switch actually works, end to end through the routes')
    # The gap that let a broken happy path ship: every check above exercised a
    # refusal, and refusals return before a session is ever created. A route
    # calling a function that does not exist passes all of them and 500s the
    # one time it matters.
    # A real login, not hand-assigned session keys. A session without the
    # credential fingerprint is rejected on its next request -- which is what
    # bind_authenticated_session's docstring warns about, and what made the
    # first version of this check redirect to a login page instead of leaving.
    c = app.test_client()
    r0 = c.post('/login', data={'username': OWNER, 'password': 'a-real-password-123'},
                headers={'Host': f'{ORL}.akyehq.test'}, follow_redirects=False)
    check(r0.status_code in (301, 302), f'the owner can log into Orlando (got {r0.status_code})')
    db.session.remove()
    r = c.get(f'/switch-city/{HSV}', headers={'Host': f'{ORL}.akyehq.test'},
              follow_redirects=False)
    check(r.status_code in (301, 302), f'leaving Orlando redirects (got {r.status_code})')
    dest = r.headers.get('Location') or ''
    check(f'{HSV}.akyehq.test' in dest, 'to Huntsville')
    check('/switch-city/accept?t=' in dest, 'carrying a token')

    token = dest.split('t=', 1)[1]
    arrive = app.test_client()
    r2 = arrive.get(f'/switch-city/accept?t={token}',
                    headers={'Host': f'{HSV}.akyehq.test'}, follow_redirects=False)
    check(r2.status_code in (301, 302), f'arriving is handled (got {r2.status_code})')
    loc = r2.headers.get('Location') or ''
    check('login' not in loc, f'and is NOT bounced to a login ({loc[-40:]})')
    # Checked by using the session rather than reading the cookie: the cookie is
    # host-scoped, and session_transaction() has no Host, so it would inspect a
    # different session than the one just created. A protected page answering
    # 200 on the next request is the real proof -- it is also the thing that
    # broke silently for new signups when the fingerprint was missing.
    r3 = arrive.get('/bookings/', headers={'Host': f'{HSV}.akyehq.test'},
                    follow_redirects=False)
    check(r3.status_code == 200,
          f'the next request at Huntsville is authenticated (got {r3.status_code})')

    # And the session belongs to Huntsville only: the same cookie at Orlando
    # must not be honoured, which is the boundary auth.py exists to hold.
    r4 = arrive.get('/bookings/', headers={'Host': f'{ORL}.akyehq.test'},
                    follow_redirects=False)
    check(r4.status_code != 200,
          f'and that same session is refused back at Orlando (got {r4.status_code})')
    db.session.remove()

    print('\n10. The switcher is actually on the page, and not hidden')
    # Nothing covered the rendering, so a switcher that worked perfectly could
    # still be invisible -- which is what happened: it shipped inside a
    # collapsed <details> behind a small uppercase summary, and was reported as
    # "I do not see the cities".
    page = c.get('/bookings/', headers={'Host': f'{ORL}.akyehq.test'})
    check(page.status_code == 200, 'a page loads for the signed-in owner')
    body = page.get_data(as_text=True)
    check('Switch city' in body, 'the switcher is on the page')
    check('Huntsville' in body, 'and names the other city')
    check(f'/switch-city/{HSV}' in body, 'linking to it')
    check('Orlando' not in body.split('city-switch')[1][:400] if 'city-switch' in body else True,
          'without offering the city you are already in')
    # Visible on load: no disclosure element wrapping it.
    seg = body.split('city-switch', 1)[1][:500] if 'city-switch' in body else ''
    check('<details' not in body[max(0, body.find('city-switch') - 300):body.find('city-switch')],
          'and is not tucked inside a collapsed <details>')

    print('\n11. Switching never creates access')
    nouser = f'ghost-{TAG}@example.com'
    # record_tenant_login alone is enough for may_switch to pass: that is the
    # point of this check. Entitlement says yes, and the switch still refuses,
    # because there is no account at that company to hand a session to.
    control_plane.record_tenant_login(engine, nouser, HSV)
    check(city_switch.may_switch(nouser, HSV),
          'entitlement says yes for somebody with no account there')
    ghost = city_switch.mint(nouser, HSV)
    db.session.remove()
    c = app.test_client()
    r = c.get(f'/switch-city/accept?t={ghost}', headers={'Host': f'{HSV}.akyehq.test'},
              follow_redirects=False)
    check(r.status_code in (301, 302), 'the request is handled')
    check('login' in (r.headers.get('Location') or ''),
          'somebody with no account there is sent to log in, not given a session')
    db.session.remove()

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 One login, two cities, and nothing carried across that should not be.')
