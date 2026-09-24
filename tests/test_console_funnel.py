"""The funnel: how people become paying customers, and who needs a nudge.

Two halves. The arithmetic (funnel.compute) is checked against hand-built rows
with exact expected numbers, because a funnel that is off by one company is
worse than no funnel -- it gets believed. The page is then checked against a
real disposable Postgres, because the control plane lives in the `public`
schema and SQLite has no such thing.
"""
import os
import secrets
import sys
from datetime import datetime, timedelta

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import funnel

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


NOW = datetime(2026, 9, 24, 12, 0)


def ago(days, hours=0):
    return NOW - timedelta(days=days, hours=hours)


def org(name, created, **kw):
    row = {'slug': name.lower(), 'name': name, 'owner_email': f'{name.lower()}@co.test',
           'status': 'active', 'subscription_status': 'trialing',
           'created_at': created, 'trial_ends_at': created + timedelta(days=30),
           'activated_at': None, 'stripe_subscription_id': None,
           'grandfathered': False, 'plan': 'scale'}
    row.update(kw)
    return row


ORGS = [
    # The founding business: never came through the funnel.
    org('Dazzle', ago(400), grandfathered=True, subscription_status='active',
        stripe_subscription_id='sub_d', activated_at=ago(399)),
    # Paying: activated a day after signup, then subscribed.
    org('Alpha', ago(10), owner_email='A@x.test', activated_at=ago(9),
        stripe_subscription_id='sub_a', subscription_status='active'),
    # Activated, trial ran out yesterday, never chose a plan.
    org('Bravo', ago(20), activated_at=ago(15), trial_ends_at=ago(1)),
    # Signed up five days ago and has not assigned a job.
    org('Charlie', ago(5)),
    # Activated, two days of trial left, no plan: call today.
    org('Delta', ago(13), activated_at=ago(12), trial_ends_at=NOW + timedelta(days=2, hours=1)),
    # Closed, outside the 30-day window.
    org('Echo', ago(40), status='closed'),
    # Chose a plan without ever assigning a job, and the card is failing.
    org('Foxtrot', ago(8), stripe_subscription_id='sub_f', subscription_status='past_due'),
    # Subscribed then cancelled, outside the 30-day window.
    org('Golf', ago(50), stripe_subscription_id='sub_g', subscription_status='canceled',
        activated_at=None),
]

LEADS = [
    # Went on to sign up as Alpha; email differs only in case and spacing.
    {'id': 1, 'email': ' a@X.test', 'name': 'Ann', 'created_at': ago(15),
     'source': 'https://www.google.com/search?q=cleaning+crm', 'contacted_at': None},
    {'id': 2, 'email': 'b@y.test', 'name': 'Bo', 'created_at': ago(3),
     'source': 'https://www.facebook.com/groups/123', 'contacted_at': None},
    # Already replied to, and older than 90 days.
    {'id': 3, 'email': 'c@z.test', 'name': 'Cy', 'created_at': ago(100),
     'source': 'direct', 'contacted_at': ago(99)},
]


def stage(f, key):
    return next(s for s in f['stages'] if s['key'] == key)


print('\n1. All time: every stage counts the right companies')
f = funnel.compute(ORGS, LEADS, now=NOW, days=None)
check(f['excluded'] == 1, 'the grandfathered company is left out, and the page says so')
check(stage(f, 'signed_up')['n'] == 7, f"7 signups ({stage(f, 'signed_up')['n']})")
check(stage(f, 'activated')['n'] == 3, f"3 activated ({stage(f, 'activated')['n']})")
check(stage(f, 'chose_plan')['n'] == 3,
      'a company that picked a plan before assigning a job still counts as choosing one')
check(stage(f, 'paying')['n'] == 1, 'only the active subscription counts as paying')
check(stage(f, 'activated')['pct'] == 43, 'rates are a share of signups (3/7 = 43%)')
check(f['lost'] == {'closed': 1, 'canceled': 1, 'trial_over': 1} and f['lost_total'] == 3,
      f"lost: one closed, one cancelled, one trial over ({f['lost']})")
check(f['past_due'] == 1, 'a failing card is counted separately, not as lost')
check(f['days_to_activate'] == 1.0,
      f"median signup-to-first-job is 1 day across 1, 5, 1 ({f['days_to_activate']})")

print('\n2. Leads are matched to signups by email, ignoring case and spaces')
check(f['leads'] == 3 and f['leads_signed_up'] == 1 and f['leads_pct'] == 33,
      f"3 leads, 1 signed up, 33% ({f['leads']}, {f['leads_signed_up']}, {f['leads_pct']})")
check(f['sources'] == [('direct', {'leads': 1, 'signed_up': 0}),
                       ('facebook.com', {'leads': 1, 'signed_up': 0}),
                       ('google.com', {'leads': 1, 'signed_up': 1})],
      f"sources grouped by site, not by full URL ({f['sources']})")

print('\n3. A 30-day window narrows the funnel but not the follow-up list')
f30 = funnel.compute(ORGS, LEADS, now=NOW, days=30)
check(stage(f30, 'signed_up')['n'] == 5, 'Echo and Golf fall outside 30 days')
check(stage(f30, 'chose_plan')['n'] == 2 and stage(f30, 'chose_plan')['pct'] == 40,
      'chose a plan: 2 of 5 = 40%')
check(stage(f30, 'paying')['pct'] == 20, 'paying: 1 of 5 = 20%')
check(f30['lost'] == {'closed': 0, 'canceled': 0, 'trial_over': 1},
      'only in-window companies count as lost')
check(f30['leads'] == 2 and f30['leads_pct'] == 50, '2 leads in 30 days, 1 signed up')
check(f30['follow_up'] == f['follow_up'], 'the follow-up list is the same whatever the window')

print('\n4. Who to get in touch with')
fu = f['follow_up']
check([o['name'] for o in fu['not_started']] == ['Charlie'],
      'signed up and never assigned a job')
check(fu['not_started'][0]['days_left'] == 25, 'with 25 days left to start')
check([o['name'] for o in fu['ending']] == ['Delta'] and fu['ending'][0]['days_left'] == 2,
      'trial ending in 2 days with no plan')
check([o['name'] for o in fu['failing']] == ['Foxtrot'], 'card failing')
check([l['email'] for l in fu['leads_waiting']] == ['b@y.test'],
      'leads waiting: not the one who signed up, not the one already contacted')

print('\n5. Nothing recorded yet does not divide by zero')
empty = funnel.compute([], [], now=NOW, days=30)
check(all(s['n'] == 0 and s['pct'] is None for s in empty['stages']),
      'every stage is zero with no rate, not a crash or a fake 0%')
check(empty['days_to_activate'] is None and empty['leads_pct'] is None, 'no median, no lead rate')

print('\n6. Referrers become site names')
check(funnel.lead_source('https://www.google.com/url?q=1') == 'google.com', 'strips www and path')
check(funnel.lead_source('') == 'direct' and funnel.lead_source(None) == 'direct',
      'no referrer is "direct"')
check(funnel.lead_source('m.facebook.com/groups/x') == 'm.facebook.com',
      'a referrer without a scheme still resolves to its host')


# --------------------------------------------------------------------------
# The page, against real Postgres

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from sqlalchemy import select, text

from app import create_app
from extensions import db
import control_plane
import provisioning

app = create_app()
TAG = secrets.token_hex(4)
CONSOLE_EMAIL = f'console-{TAG}@example.com'
CONSOLE_PASSWORD = 'a-real-console-password-1'
LEAD_EMAIL = f'lead-{TAG}@example.com'

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()

    ending_slug = f'e2efunnelend{TAG}'
    idle_slug = f'e2efunnelidle{TAG}'
    control_plane.create(engine, ending_slug, f'Funnel Ending {TAG}', f'end-{TAG}@example.com')
    control_plane.create(engine, idle_slug, f'Funnel Idle {TAG}', f'idle-{TAG}@example.com')
    now = datetime.utcnow()
    control_plane.set_billing(engine, ending_slug, activated_at=now - timedelta(days=12),
                              trial_ends_at=now + timedelta(days=1, hours=2))
    control_plane.add_lead(engine, name='Lead Person', company='Lead Co', email=LEAD_EMAIL,
                           cleaners='3', source='https://www.google.com/search?q=x')
    control_plane.add_console_user(engine, CONSOLE_EMAIL, 'Console Tester',
                                   CONSOLE_PASSWORD, role='helper')
    with engine.connect() as conn:
        lead_id = conn.execute(select(control_plane.product_leads.c.id).where(
            control_plane.product_leads.c.email == LEAD_EMAIL)).scalar()
    db.session.remove()

    c = app.test_client()

    print('\n7. Signed out, the page is not reachable')
    r = c.get('/console/funnel', follow_redirects=False)
    check(r.status_code == 302 and 'login' in (r.headers.get('Location') or ''),
          'redirected to the console login')

    print('\n8. Signed in, it shows the funnel and who to call')
    r = c.post('/console/login', data={'email': CONSOLE_EMAIL, 'password': CONSOLE_PASSWORD})
    check(r.status_code == 302, 'console login succeeds')
    r = c.get('/console/funnel?window=all')
    body = r.data.decode()
    check(r.status_code == 200, 'the page loads')
    check('>Funnel</a>' in body, 'and is in the console navigation')
    for label in ('Signed up', 'Activated', 'Chose a plan', 'Paying now'):
        check(label in body, f'the "{label}" stage is shown')
    check(f'Funnel Ending {TAG}' in body.split('Trial ends in')[1].split('</table>')[0],
          'the company with a day of trial left is under "trial ends"')
    check(f'Funnel Idle {TAG}' in body.split('never assigned a job')[1].split('</table>')[0],
          'the company that never started is under "never assigned a job"')
    check(LEAD_EMAIL in body, 'the uncontacted lead is listed')
    check(c.get('/console/funnel?window=nonsense').status_code == 200,
          'an unknown window falls back instead of erroring')

    print('\n9. Marking a lead contacted takes it off the list, and is recorded')
    r = c.post(f'/console/leads/{lead_id}/contacted',
               headers={'Origin': 'https://evil.example'})
    check(r.status_code == 403, 'a submit from another site is refused')
    r = c.post(f'/console/leads/{lead_id}/contacted', data={'window': 'all'})
    check(r.status_code == 302 and 'window=all' in (r.headers.get('Location') or ''),
          'back to the same window')
    body = c.get('/console/funnel?window=all').data.decode()
    check(LEAD_EMAIL not in body, 'the lead is off the waiting list')
    with engine.connect() as conn:
        first = conn.execute(select(control_plane.product_leads.c.contacted_at).where(
            control_plane.product_leads.c.id == lead_id)).scalar()
    check(first is not None, 'contacted_at is written')
    c.post(f'/console/leads/{lead_id}/contacted')
    with engine.connect() as conn:
        again = conn.execute(select(control_plane.product_leads.c.contacted_at).where(
            control_plane.product_leads.c.id == lead_id)).scalar()
        logged = conn.execute(text(
            "SELECT count(*) FROM public.console_log WHERE actor = :a "
            "AND action = 'contacted' AND target = :t"),
            {'a': CONSOLE_EMAIL, 't': f'lead #{lead_id}'}).scalar()
    check(again == first, 'pressing it twice keeps the first time')
    check(logged == 1, f'the record shows who marked it, once ({logged})')

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM public.organizations WHERE slug IN (:a, :b)"),
                     {'a': ending_slug, 'b': idle_slug})
        conn.execute(text('DELETE FROM public.product_leads WHERE email = :e'), {'e': LEAD_EMAIL})
        conn.execute(text('DELETE FROM public.console_log WHERE actor = :e'), {'e': CONSOLE_EMAIL})
        conn.execute(text('DELETE FROM public.console_users WHERE email = :e'),
                     {'e': CONSOLE_EMAIL})

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ The funnel adds up, and the people who need a nudge are on one list.')
