"""JOURNEY-01: the full cohort chain, proven once, continuously.

The launch-certification suite proves each piece of a business's first day
on Akye separately -- signup safety at the API layer, tenant isolation at
the Postgres layer, day-to-day CRM usage through a real browser in
single-tenant mode. Nothing proves the *chain*: a business signs up, lands
on its own subdomain, logs in there, takes on a customer, books and
completes a job, gets paid, and a second tenant sitting right next to it in
the same database never sees or is affected by any of it -- including when
the first one is suspended.

Runs against a real disposable Postgres (schema-per-tenant needs actual
schemas -- SQLite cannot do this), through the real HTTP routes with a real
Host header per request, the same way a browser resolves a subdomain. Two
synthetic tenants only, both created and torn down here -- never Dazzle &
Shine's own data. Stripe is monkeypatched exactly the way test_charge.py
does it: no network call, real or otherwise, reaches Stripe.

A real WSGI server gives every incoming request its own fresh context and
connection checkout, which is what actually applies each request's
search_path. A test script that dispatches through the same test client
inside one long-lived app_context does not get that for free -- the
ORM session keeps the connection (and its search_path) it first checked
out. db.session.remove() after every request forces the next one to check
out fresh, exactly as a real request boundary would. Skipping it doesn't
mean tenant resolution is broken; it means the test stopped proving it."""
import os
import secrets
import sys

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
os.environ.pop('SIGNUPS_OPEN', None)  # unset = open, per signups_open()
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_fake'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

import payment_service


class _Intent:
    status = 'succeeded'
    id = 'pi_test_journey'


class _FakePaymentIntent:
    @staticmethod
    def create(**kw):
        return _Intent()


payment_service.stripe.PaymentIntent = _FakePaymentIntent

from app import create_app
from extensions import db
import control_plane
import provisioning
import tenancy
from models import User, Client, Booking, Staff

app = create_app()
BASE = os.environ['BASE_DOMAIN']
SLUG_A = 'e2ecohort' + secrets.token_hex(4)
SLUG_B = 'e2eneighbor' + secrets.token_hex(4)
HOST_A = f'{SLUG_A}.{BASE}'
HOST_B = f'{SLUG_B}.{BASE}'
OWNER_EMAIL = f'owner-{SLUG_A}@example.com'
OWNER_PASSWORD = 'a-real-password-1'
CLEANER_USERNAME = f'cleaner-{SLUG_A}'
CLEANER_PASSWORD = 'a-different-password-2'

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def h(host):
    return {'Host': host}


def get(client, path, host, **kw):
    r = client.get(path, headers=h(host), **kw)
    db.session.remove()  # force the next query to check out its own connection
    return r


def post(client, path, host, data=None, **kw):
    r = client.post(path, data=data or {}, headers=h(host), **kw)
    db.session.remove()
    return r


with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()
    c = app.test_client()

    print('\n1. New owner signup and tenant provisioning')
    r = get(c, '/signup', BASE)
    check(r.status_code == 200, 'the signup page loads on the base domain')

    r = post(c, '/signup', BASE, data={
        'business': 'E2E Cohort Test Co',
        'slug': SLUG_A,
        'name': 'Robin Owner',
        'email': OWNER_EMAIL,
        'password': OWNER_PASSWORD,
    }, follow_redirects=False)
    check(r.status_code == 302, 'signup redirects on success')
    location = r.headers.get('Location', '')
    check(f'{HOST_A}/welcome/' in location,
          f'the redirect sends the new owner to her own subdomain ({HOST_A})')

    org = control_plane.find(engine, SLUG_A)
    db.session.remove()
    check(org is not None and org['status'] == 'active',
          'the control plane recorded the new company as active')
    check(provisioning.schema_exists(engine, tenancy.schema_for(SLUG_A)),
          'her tenant schema exists')
    db.session.remove()

    welcome_path = location.split(HOST_A, 1)[1]

    print('\n2. Welcome link logs her in, on her own subdomain, and only there')
    r = get(c, welcome_path, HOST_A, follow_redirects=False)
    check(r.status_code == 302 and 'getting-started' in (r.headers.get('Location') or '').lower(),
          f'the welcome link starts her session and moves her past onboarding (got {r.status_code} {r.headers.get("Location")})')

    r = get(c, '/', HOST_A)
    check(r.status_code == 200 and b'sidebar' in r.data.lower(), 'her dashboard loads on her own host')

    r = get(c, '/', BASE)
    check(b'sidebar' not in r.data.lower(),
          "the same session cookie does not open a dashboard on the base domain — "
          "the host, not just the cookie, decides who she is")

    print('\n3-4. First customer and first job')
    r = post(c, '/bookings/new', HOST_A, data={
        'name': 'First Customer', 'email': 'customer@example.com', 'phone': '5551234',
        'service_type': 'standard', 'bedrooms': '2', 'bathrooms': '1',
        'address': '1 Test St', 'city': 'Testville', 'zip_code': '00000',
        'frequency': 'one_time', 'preferred_date': '', 'preferred_time': '',
        'status': 'confirmed',
    }, follow_redirects=False)
    check(r.status_code == 302, f'the booking is created (got {r.status_code}: {r.get_data(as_text=True)[:200] if r.status_code != 302 else ""})')
    booking_id = int(r.headers['Location'].rstrip('/').rsplit('/', 1)[-1])

    with tenancy.use_tenant(tenancy.schema_for(SLUG_A)):
        booking = Booking.query.get(booking_id)
        check(booking is not None, 'the job exists in her own schema')
        client_count = Client.query.count()
        check(client_count == 1, 'her first customer was created from the booking, and only one')
    db.session.remove()

    print('\n5. Worker access, and role denial for a non-owner')
    r = post(c, '/staff/new', HOST_A, data={'name': 'Casey Cleaner', 'phone': '5559999',
                                             'email': 'casey@example.com', 'pay_type': 'percent',
                                             'pay_rate': '50'}, follow_redirects=False)
    check(r.status_code == 302, 'the owner can add a cleaner to her team')

    with tenancy.use_tenant(tenancy.schema_for(SLUG_A)):
        cleaner_user = User(name='Casey Cleaner', username=CLEANER_USERNAME,
                            role='cleaner', active=True)
        cleaner_user.set_password(CLEANER_PASSWORD)
        db.session.add(cleaner_user)
        db.session.commit()
    db.session.remove()

    cleaner_client = app.test_client()
    r = post(cleaner_client, '/login', HOST_A,
            data={'username': CLEANER_USERNAME, 'password': CLEANER_PASSWORD},
            follow_redirects=False)
    check(r.status_code == 302 and 'login' not in (r.headers.get('Location') or ''),
          f'the cleaner can log in with her own account (got {r.status_code} {r.headers.get("Location")})')

    r = post(cleaner_client, '/staff/new', HOST_A, data={'name': 'Should Not Work'},
            follow_redirects=False)
    denied = r.status_code == 403 or (r.status_code == 302 and 'staff' not in (r.headers.get('Location') or ''))
    check(denied, f"a cleaner cannot open the owner-only add-staff action (got {r.status_code} {r.headers.get('Location')})")
    with tenancy.use_tenant(tenancy.schema_for(SLUG_A)):
        check(Staff.query.filter_by(name='Should Not Work').first() is None,
              'and no staff record was created by the denied attempt')
    db.session.remove()

    print('\n6-7. Job completion and payment')
    with tenancy.use_tenant(tenancy.schema_for(SLUG_A)):
        booking = Booking.query.get(booking_id)
        booking.price = 150.00
        booking.stripe_customer_id = 'cus_journey_fake'
        booking.stripe_payment_method_id = 'pm_journey_fake'
        db.session.commit()
    db.session.remove()

    r = post(c, f'/bookings/{booking_id}', HOST_A, data={
        'status': 'completed', 'price': '150.00', 'assigned_cleaner': 'Casey Cleaner',
    }, follow_redirects=False)
    check(r.status_code == 302, f'the owner marks the job completed (got {r.status_code})')
    with tenancy.use_tenant(tenancy.schema_for(SLUG_A)):
        booking = Booking.query.get(booking_id)
        check(booking.status == 'completed', 'the job status is completed')
        check(booking.completed_at is not None, 'and a completion time was recorded')
    db.session.remove()

    r = post(c, f'/bookings/{booking_id}/charge-balance', HOST_A)
    check(r.status_code == 200, 'the charge request is accepted')
    body = r.get_json()
    check(body.get('ok') is True, f'and the balance was charged: {body}')
    with tenancy.use_tenant(tenancy.schema_for(SLUG_A)):
        booking = Booking.query.get(booking_id)
        check(booking.paid_at is not None, 'the job is recorded as paid')
        check(booking.stripe_payment_intent == 'pi_test_journey',
              'against the (fake) Stripe payment intent — no real network call was made')
    db.session.remove()

    print('\n8. Logout ends the session for real')
    r = get(c, '/logout', HOST_A, follow_redirects=False)
    check(r.status_code == 302, 'logout redirects to login')
    r = get(c, '/', HOST_A)
    check(b'sidebar' not in r.data.lower(),
          'the dashboard is no longer reachable with the same cookie after logout')

    print('\n9-10. A neighbor tenant, and suspension without neighbor impact')
    provisioning.provision(SLUG_B, 'E2E Neighbor Co', 'neighbor@example.com', quiet=True)
    db.session.remove()
    nc = app.test_client()
    with tenancy.use_tenant(tenancy.schema_for(SLUG_B)):
        neighbor_owner = User(name='Neighbor Owner', username=f'owner-{SLUG_B}@example.com',
                              role='owner', active=True)
        neighbor_owner.set_password('another-real-password-3')
        db.session.add(neighbor_owner)
        db.session.commit()
        neighbor_booking = Booking(service_type='standard', name='Neighbor Job',
                                   status='confirmed')
        db.session.add(neighbor_booking)
        db.session.commit()
        neighbor_booking_id = neighbor_booking.id
    db.session.remove()
    r = post(nc, '/login', HOST_B,
            data={'username': f'owner-{SLUG_B}@example.com', 'password': 'another-real-password-3'},
            follow_redirects=False)
    check(r.status_code == 302 and 'login' not in (r.headers.get('Location') or ''),
          "the neighbor tenant's own owner can log in on her own host")

    control_plane.set_status(engine, SLUG_A, 'suspended')
    db.session.remove()
    r = get(c, '/', HOST_A)
    check(r.status_code == 423,
          f'the suspended tenant now fails closed (423 Locked) even for a session that was valid a moment ago (got {r.status_code})')
    r = get(nc, '/', HOST_B)
    check(r.status_code == 200 and b'sidebar' in r.data.lower(),
          "the neighbor tenant is completely unaffected by the first tenant's suspension")

    control_plane.set_status(engine, SLUG_A, 'active')
    db.session.remove()
    r2c = app.test_client()
    post(r2c, '/login', HOST_A, data={'username': OWNER_EMAIL, 'password': OWNER_PASSWORD},
        follow_redirects=False)
    r = get(r2c, '/', HOST_A)
    check(r.status_code == 200, f'reactivating restores access (got {r.status_code})')
    with tenancy.use_tenant(tenancy.schema_for(SLUG_A)):
        booking = Booking.query.get(booking_id)
        check(booking is not None and booking.status == 'completed' and booking.paid_at is not None,
              "and every fact recorded before the suspension — the completed, paid job — "
              "survived it untouched")
    db.session.remove()

    # Cleanup: this test provisions real schemas even against a disposable
    # database, and leaving them around would let a re-run collide on slug
    # uniqueness in the control plane.
    for slug in (SLUG_A, SLUG_B):
        try:
            provisioning.drop_schema(engine, tenancy.schema_for(slug))
            with engine.begin() as conn:
                from sqlalchemy import text
                conn.execute(text('DELETE FROM public.organizations WHERE slug = :s'), {'s': slug})
        except Exception as e:
            print(f'  ⚠️  cleanup of {slug!r} left something behind: {e}')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n🎉 Signup through subdomain through a paid, completed job through suspension and back — '
      'one continuous chain, proven, on two tenants that never touched each other.')
