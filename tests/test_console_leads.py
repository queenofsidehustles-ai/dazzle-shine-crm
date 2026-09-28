"""Console → New Leads: uploading a prospect list and inviting people on it.

Against a real disposable Postgres, same as the rest of the console suite --
product_leads and console_log both live in the `public` schema, which SQLite
does not have.
"""
import os
import secrets
import sys

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io

SENT = []
import notifications
notifications.send_email = lambda to, *a, **k: (SENT.append(to), (True, 'stub'))[1]
notifications.send_sms = lambda *a, **k: (True, 'stub')

from sqlalchemy import select, text

from app import create_app
from extensions import db
import control_plane
import provisioning

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


TAG = secrets.token_hex(4)
CONSOLE_EMAIL = f'console-{TAG}@example.com'
CONSOLE_PASSWORD = 'a-real-console-password-1'
HELPER_EMAIL = f'helper-{TAG}@example.com'

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()

    control_plane.add_console_user(engine, CONSOLE_EMAIL, 'Console Manager',
                                   CONSOLE_PASSWORD, role='manager')
    control_plane.add_console_user(engine, HELPER_EMAIL, 'Console Helper',
                                   CONSOLE_PASSWORD, role='helper')
    db.session.remove()

    c = app.test_client()

    print('\n1. Signed out, the page is not reachable')
    r = c.get('/console/leads', follow_redirects=False)
    check(r.status_code == 302 and 'login' in (r.headers.get('Location') or ''),
          'redirected to the console login')

    print('\n2. It is a tab under Funnel, not its own top-level item')
    c.post('/console/login', data={'email': CONSOLE_EMAIL, 'password': CONSOLE_PASSWORD})
    body = c.get('/console/leads').data.decode()
    bar = body.split('class="con-bar"', 1)[1].split('</div>', 1)[0]
    tabs = body.split('aria-label="Funnel views"', 1)[1].split('</nav>', 1)[0]
    check('New Leads' not in bar, 'the top bar has no New Leads item')
    check('class="on">Funnel' in bar, 'and Funnel is highlighted there while on New Leads')
    check('New Leads' in tabs, 'the Funnel tabs include New Leads')
    check(tabs.index('>Funnel<') < tabs.index('New Leads') < tabs.index('>Sales<'),
          'between Funnel and Sales')
    funnel = c.get('/console/funnel').data.decode()
    check('New Leads' in funnel.split('aria-label="Funnel views"', 1)[1].split('</nav>', 1)[0],
          'and the Funnel page shows the same tab')

    print('\n3. Uploading a CSV accepts email or phone and skips only uncontactable rows')
    csv_text = (
        'Name,Company,Email,Phone,Cleaners,Note\n'
        f'Prospect One,One Co,one-{TAG}@example.com,555-0100,3,met at a trade show\n'
        f'Prospect Two,Two Co,TWO-{TAG}@EXAMPLE.COM,,,\n'
        'Phone Only,Three Co,,555-0300,2,Google Maps prospect\n'
        'No Contact,Four Co,,,,\n'
    )
    r = c.post('/console/leads/upload',
               data={'file': (io.BytesIO(csv_text.encode()), 'prospects.csv')},
               content_type='multipart/form-data', follow_redirects=True)
    check(r.status_code == 200, 'the upload is accepted')
    body = r.data.decode()
    check('Added 3 lead' in body, 'email and phone-only rows were added')
    check('Skipped 1' in body, 'only the row with neither email nor phone was skipped')
    check('no usable email or phone' in body, 'the result explains the actual contact rule')

    with engine.connect() as conn:
        one = conn.execute(select(control_plane.product_leads).where(
            control_plane.product_leads.c.email == f'one-{TAG}@example.com')
        ).mappings().first()
        two = conn.execute(select(control_plane.product_leads).where(
            control_plane.product_leads.c.email == f'two-{TAG}@example.com')
        ).mappings().first()
    check(one is not None and one['company'] == 'One Co' and one['phone'] == '555-0100',
          'the row is stored with its other columns')
    check(one['source'] == 'console upload', 'tagged as a console upload, not early access')
    check(two is not None, 'the second row is stored even with blank optional columns')
    check(two['email'] == f'two-{TAG}@example.com',
          'and the email was lower-cased, matching "TWO@..." to a real address')
    with engine.connect() as conn:
        phone_only = conn.execute(select(control_plane.product_leads).where(
            control_plane.product_leads.c.phone == '555-0300')).mappings().first()
    check(phone_only is not None and not phone_only['email'],
          'a phone-only prospect is stored without inventing an email address')
    body = c.get('/console/leads').data.decode()
    check('555-0300' in body, 'the phone-only prospect is visible in New Leads')

    print('\n3b. Re-uploading the same identities does not duplicate outreach')
    dup_text = (
        'Name,Company,Email,Phone,Cleaners,Note\n'
        f'Email Duplicate,Elsewhere,ONE-{TAG}@EXAMPLE.COM,999-9999,,\n'
        'Phone Duplicate,Elsewhere,,(555) 0300,,\n'
    )
    before_dup = len(control_plane.all_leads(engine))
    r = c.post('/console/leads/upload',
               data={'file': (io.BytesIO(dup_text.encode()), 'duplicates.csv')},
               content_type='multipart/form-data', follow_redirects=True)
    after_dup = len(control_plane.all_leads(engine))
    check(after_dup == before_dup, 'duplicate email and normalized phone add no new rows')
    check('Added 0 leads' in r.data.decode(), 'the upload reports that nothing new was added')

    print('\n4. A helper can see the list but cannot upload or invite')
    h = app.test_client()
    h.post('/console/login', data={'email': HELPER_EMAIL, 'password': CONSOLE_PASSWORD})
    body = h.get('/console/leads').data.decode()
    check(f'one-{TAG}@example.com' in body, 'a helper can read the list')
    check('Upload CSV' not in body, 'but sees no upload form')
    r = h.post('/console/leads/upload',
               data={'file': (io.BytesIO(csv_text.encode()), 'x.csv')},
               content_type='multipart/form-data')
    check(r.status_code == 302, 'and a direct POST is refused, not silently accepted')
    with engine.connect() as conn:
        n = conn.execute(select(control_plane.product_leads.c.id).where(
            control_plane.product_leads.c.email == f'one-{TAG}@example.com')).all()
    check(len(n) == 1, 'so the row was not added a second time')

    print('\n5. Inviting one lead sends the email and stamps invited_at, once')
    SENT.clear()
    r = c.post(f'/console/leads/{one["id"]}/invite', follow_redirects=True)
    check(r.status_code == 200, 'the invite posts')
    check(SENT == [f'one-{TAG}@example.com'], 'and the email actually goes to that address')
    with engine.connect() as conn:
        invited = conn.execute(select(control_plane.product_leads.c.invited_at).where(
            control_plane.product_leads.c.id == one['id'])).scalar()
    check(invited is not None, 'invited_at is written')
    body = c.get('/console/leads').data.decode()
    check('Re-invite' in body, 'the row now offers to re-invite rather than invite')

    print('\n6. "Invite all" reaches everybody not yet invited, and only them')
    # This runs against a shared Postgres, alongside the rest of the console
    # suite, so other untouched leads may legitimately also get one here --
    # what matters is that our two are handled correctly relative to each
    # other, not that SENT is only ever these two.
    SENT.clear()
    r = c.post('/console/leads/invite-all', follow_redirects=True)
    check(r.status_code == 200, 'the bulk invite posts')
    check(f'two-{TAG}@example.com' in SENT, 'the lead never invited before gets one this time')
    check(f'one-{TAG}@example.com' not in SENT,
          'the one already invited individually does not get a second copy')
    check('555-0300' not in SENT, 'phone-only prospects are never treated as email-invitable')
    with engine.connect() as conn:
        both = conn.execute(select(control_plane.product_leads.c.invited_at).where(
            control_plane.product_leads.c.email.in_(
                [f'one-{TAG}@example.com', f'two-{TAG}@example.com']))).all()
    check(all(row[0] is not None for row in both), 'both are now marked invited')

    print('\n7. Every invite and upload is on the record')
    with engine.connect() as conn:
        actions = {row[0] for row in conn.execute(text(
            "SELECT action FROM public.console_log WHERE actor = :a"),
            {'a': CONSOLE_EMAIL}).all()}
    check({'uploaded', 'invited'} <= actions, f'uploaded and invited both logged ({actions})')

    print('\n8. The nav pill counts leads nobody has acted on yet')
    # Delta rather than an absolute number: this Postgres is shared with the
    # rest of the console suite, which may itself leave an untouched lead
    # behind, so "1" is not a safe thing to assert here -- "went up by
    # exactly the one just added" is.
    before = control_plane.new_leads_count(engine)
    fresh_email = f'fresh-{TAG}@example.com'
    control_plane.add_lead(engine, name='Fresh', email=fresh_email, source='console upload')
    body = c.get('/console/leads').data.decode()
    after = control_plane.new_leads_count(engine)
    check(after == before + 1, f'the untouched lead is counted ({before} -> {after})')
    check(f'New Leads<span class="pill">{after}</span>' in body,
          'and the New Leads tab pill shows that same number')
    check(f'Funnel<span class="pill" title="New leads nobody has contacted yet">{after}</span>' in body,
          'and so does the Funnel item in the top bar')

    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM public.product_leads WHERE email = ANY(:emails)"),
            {'emails': [f'one-{TAG}@example.com', f'two-{TAG}@example.com', fresh_email]})
        conn.execute(text("DELETE FROM public.product_leads WHERE phone = '555-0300'"))
        conn.execute(text("DELETE FROM public.console_log WHERE actor IN (:a, :h)"),
                     {'a': CONSOLE_EMAIL, 'h': HELPER_EMAIL})
        conn.execute(text("DELETE FROM public.console_users WHERE email IN (:a, :h)"),
                     {'a': CONSOLE_EMAIL, 'h': HELPER_EMAIL})

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Prospect lists can be uploaded, invited once each, and only by someone who may act.')
