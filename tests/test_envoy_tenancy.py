"""Envoy on hosted Akye: one company can never see another's Envoy, a company
it has not been released to has no Envoy at all, and the console's switches
stop it for real.

Three companies in one PostgreSQL database, one schema each:

  dazzleandshine   in the default cohort
  otherco          released for this test through ENVOY_TENANTS
  notreleased      a company Envoy has not been released to

Every business Envoy finds for a company is named with that company's canary,
and each company's search also returns one listing the other company already
has -- de-duplication is per company, so it must not leak or block across the
boundary either.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
import fresh_postgres
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_envoy_tenancy')
os.environ['SECRET_KEY'] = 'envoy-tenancy-secret-at-least-32-characters'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['SIGNUPS_OPEN'] = '0'
os.environ['FLASK_ENV'] = 'development'
os.environ['REMINDER_API_KEY'] = 'cron-key'
os.environ['ANTHROPIC_API_KEY'] = 'sk-test'
os.environ['ENVOY_TENANTS'] = 'dazzleandshine,otherco'
os.environ.pop('ENVOY_SINGLE_BUSINESS', None)
for k in ('ADMIN_USER', 'ADMIN_PASS'):
    os.environ.pop(k, None)

import notifications
MAIL = []
notifications.send_email = lambda to, n, s, b, **k: (MAIL.append((to, s)), (True, 'ok'))[1]
notifications.send_sms = lambda *a, **k: (True, 'stub')

import control_plane
import envoy
import llm
import places_finder
import platform_switches
import provisioning
import tenancy
from app import create_app
from extensions import db

A, B, C = 'dazzleandshine', 'otherco', 'notreleased'
CANARY = {A: 'ALPHA-ENVOY-CANARY', B: 'BRAVO-ENVOY-CANARY'}
SHARED_PLACE = 'shared-place-id'
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def fake_search(category, location, api_key=None, center=None, radius_m=None):
    slug = envoy.current_slug()
    tag = CANARY.get(slug, 'NOBODY')
    rows = [{'place_id': f'{slug}-{i}', 'business_name': f'{tag} Realty {i}',
             'phone': f'(407) 555-{(2000 if slug == A else 3000) + i:04d}',
             'website': '', 'address': f'{i} Oak St', 'city': location, 'rating': 4.5}
            for i in range(4)]
    rows.append({'place_id': SHARED_PLACE, 'business_name': f'{tag} Shared Listing',
                 'phone': '', 'website': '', 'address': '1 Shared Way', 'city': location,
                 'rating': 4.0})
    return True, rows, ''


places_finder.search_businesses = fake_search
places_finder.api_key_present = lambda: True
places_finder.allowance = lambda: (False, False)
envoy._local_hour = lambda: 9
envoy._fetch = lambda url: ''

CLAUDE = {'calls': 0}


def fake_post(body, timeout=30):
    CLAUDE['calls'] += 1
    return {'type': 'message', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps({
        'first_line': 'I came across your listings around Orlando.',
        'email_subject': 'Cleaning help',
        'email_body': 'Hi there,\n\nCould we set up a free walkthrough and send a written quote?',
        'call_script': 'Hi, this is Monica. Could I offer a free walkthrough and a written quote?',
        'followup_day3': 'Hi there, following up on the free walkthrough.',
        'followup_day7': 'Hi there, one last note about a free walkthrough.'})}]}


llm.post = fake_post

for slug, name in ((A, 'Dazzle & Shine Maids'), (B, 'Other Co Cleaning'), (C, 'Not Released Cleaning')):
    provisioning.provision(slug, name, quiet=True)
engine = provisioning._engine()
for slug in (A, B, C):
    control_plane.set_billing(engine, slug, plan='scale', subscription_status='active')

app = create_app()
app.config.update(TESTING=True)
OWNER_ID = {A: 8101, B: 8102, C: 8103}

with app.app_context():
    from models import BusinessSetting, User
    for slug in (A, B, C):
        with tenancy.use_tenant(slug):
            u = User(id=OWNER_ID[slug], name=f'{slug} owner', username=f'owner@{slug}.test',
                     role='owner', active=True)
            u.set_password(f'{slug}-password-123')
            db.session.add(u)
            BusinessSetting.set('email', f'owner@{slug}.test')
            db.session.commit()
            if slug != C:
                problems = envoy.save_settings({
                    'enabled': '1', 'area': 'Orlando, FL', 'sender': f'{slug} sender',
                    'daily_limit': '10', 'ai_cap': '15', 'email_owner': '1',
                    **{f'day_{d}': 'realtor' for d in range(7)}})
                assert not problems, problems
            db.session.remove()


def host(slug):
    return f'https://{slug}.akye.test'


def owner(slug):
    from auth import _auth_fingerprint
    from models import User
    with app.app_context():
        with tenancy.use_tenant(slug):
            fp = _auth_fingerprint(User.query.get(OWNER_ID[slug]).password_hash)
            db.session.remove()
    c = app.test_client()
    with c.session_transaction(base_url=host(slug)) as s:
        s.update(logged_in=True, role='owner', user_id=OWNER_ID[slug],
                 user_name='Envoy Tester', auth_fingerprint=fp, tenant_slug=slug)
    return c


def counts(slug):
    from models import EnvoyDraft, EnvoyRun, Prospect
    with app.app_context():
        with tenancy.use_tenant(slug):
            out = (Prospect.query.filter_by(source='envoy').count(),
                   EnvoyDraft.query.count(), EnvoyRun.query.count(),
                   [p.business_name for p in Prospect.query.filter_by(source='envoy')])
            db.session.remove()
    return out


cron = app.test_client()
KEY = {'X-Api-Key': 'cron-key'}

print('\n1. Each company\'s morning run touches only its own schema')
# One company already has the listing the other's search will also return.
with app.app_context():
    from models import Prospect
    with tenancy.use_tenant(B):
        db.session.add(Prospect(business_name='Bravo had it first', place_id=SHARED_PLACE,
                                source='google_places'))
        db.session.commit(); db.session.remove()

r = cron.post('/api/envoy-daily', base_url=host(A), headers=KEY)
check(r.status_code == 200 and r.get_json().get('created') == 5, f'Dazzle & Shine: five new ({r.get_json()})')
r = cron.post('/api/envoy-daily', base_url=host(B), headers=KEY)
check(r.status_code == 200 and r.get_json().get('created') == 4,
      f'Other Co: four new -- the listing it already had is skipped ({r.get_json()})')
na, da, ra, names_a = counts(A)
nb, db_, rb, names_b = counts(B)
check(na == 5 and da == 5 and ra == 1, 'Dazzle & Shine has its own five prospects, drafts and run')
check(nb == 4 and db_ == 4 and rb == 1, 'Other Co has its own four')
check(all(CANARY[A] in n for n in names_a) and not any(CANARY[B] in n for n in names_a),
      'nothing of Other Co\'s is in Dazzle & Shine\'s schema')
check(all(CANARY[B] in n for n in names_b) and not any(CANARY[A] in n for n in names_b),
      'nothing of Dazzle & Shine\'s is in Other Co\'s')
check(any('Shared Listing' in n for n in names_a),
      'a business another company already has is still new to this one')
check(sorted(to for to, _s in MAIL) == [f'owner@{A}.test', f'owner@{B}.test'],
      f'each owner got their own morning email, and nobody else got any ({MAIL})')

print('\n2. One owner\'s page shows only their company')
a_html = owner(A).get('/envoy/', base_url=host(A))
b_html = owner(B).get('/envoy/', base_url=host(B))
check(a_html.status_code == 200 and b_html.status_code == 200, 'both owners see their page')
a_text, b_text = a_html.get_data(as_text=True), b_html.get_data(as_text=True)
check(CANARY[A] in a_text and CANARY[B] not in a_text, 'Dazzle & Shine\'s page has none of Other Co\'s')
check(CANARY[B] in b_text and CANARY[A] not in b_text, 'Other Co\'s page has none of Dazzle & Shine\'s')
wrong = owner(A).get('/envoy/', base_url=host(B))
check(wrong.status_code != 200 or CANARY[A] not in wrong.get_data(as_text=True)
      and CANARY[B] not in wrong.get_data(as_text=True),
      f'a Dazzle & Shine login on Other Co\'s address sees neither ({wrong.status_code})')
with app.app_context():
    from models import Prospect
    with tenancy.use_tenant(A):
        a_id = Prospect.query.filter_by(source='envoy').first().id
        db.session.remove()
    with tenancy.use_tenant(B):
        clash = Prospect.query.get(a_id)
        clash_is_b = clash is None or CANARY[A] not in (clash.business_name or '')
        db.session.remove()
r = owner(B).post(f'/envoy/draft/{a_id}', base_url=host(B))
check(clash_is_b and r.status_code in (302, 404), 'a prospect id from one company never reaches the other\'s record')

print('\n3. A company Envoy has not been released to has no Envoy')
c = owner(C)
check(c.get('/envoy/', base_url=host(C)).status_code == 404, 'the page is a 404')
check(c.post('/envoy/run', base_url=host(C)).status_code == 404, 'and so is "find now"')
r = cron.post('/api/envoy-daily', base_url=host(C), headers=KEY)
check(r.status_code == 200 and r.get_json().get('skipped'), 'the hourly call does nothing')
check(counts(C)[:3] == (0, 0, 0), 'and nothing is written')
# The Envoy tab sits beside Find leads, on that section's pages.
leads_c = c.get('/find-leads/', base_url=host(C))
check(leads_c.status_code == 200 and '/envoy/' not in leads_c.get_data(as_text=True),
      'and the Find Leads tabs do not offer it')
leads_a = owner(A).get('/find-leads/', base_url=host(A))
check(leads_a.status_code == 200 and '/envoy/' in leads_a.get_data(as_text=True),
      'where it is released, they do')
import scheduler
check(scheduler.released_to('envoy-daily', A) and scheduler.released_to('envoy-daily', B)
      and not scheduler.released_to('envoy-daily', C), 'the scheduler calls only the released companies')

print('\n4. The console\'s AI switch stops Claude for every company')
with app.app_context():
    from models import EnvoyDraft, EnvoyRun, Prospect
    for slug in (A, B):
        with tenancy.use_tenant(slug):
            EnvoyDraft.query.delete(); EnvoyRun.query.delete()
            Prospect.query.filter_by(source='envoy').delete()
            db.session.commit(); db.session.remove()
platform_switches.set_switch(engine, 'ai', False, by='test')
CLAUDE['calls'] = 0
r = cron.post('/api/envoy-daily', base_url=host(A), headers=KEY)
check(r.get_json().get('created') == 5 and r.get_json().get('drafted') == 5, f'the run still finds and drafts ({r.get_json()})')
check(CLAUDE['calls'] == 0, 'without a single call to Claude')
with app.app_context():
    from models import EnvoyDraft
    with tenancy.use_tenant(A):
        sources = {d.source for d in EnvoyDraft.query}
        db.session.remove()
check(sources == {'template'}, f'every draft is from the template ({sources})')
platform_switches.set_switch(engine, 'ai', True, by='test')
CLAUDE['calls'] = 0
cron.post('/api/envoy-daily', base_url=host(B), headers=KEY)
check(CLAUDE['calls'] == 4, f'switched back on, Claude writes them again ({CLAUDE["calls"]})')

print('\n4b. A draft goes with its prospect')
with app.app_context():
    from models import EnvoyDraft, Prospect
    with tenancy.use_tenant(B):
        gone = Prospect.query.filter_by(source='envoy').first()
        gid = gone.id
        db.session.delete(gone); db.session.commit()
        check(EnvoyDraft.query.filter_by(prospect_id=gid).count() == 0,
              'deleting a business deletes what Envoy wrote about it')
        db.session.remove()

print('\n4c. Send on hosted Akye: the company\'s own domain, and its own records')
with app.app_context():
    from models import BusinessSetting, EnvoyDraft, Prospect
    with tenancy.use_tenant(A):
        for k, v in {'address': '1 Main St', 'city': 'Springfield', 'state': 'IL'}.items():
            BusinessSetting.set(k, v)
        db.session.commit()
        sp = Prospect.query.filter_by(source='envoy').first()
        sid, sdraft = sp.id, EnvoyDraft.query.filter_by(prospect_id=sp.id).first()
        form = {'kind': 'intro', 'to': 'office@target.example.com',
                'subject': sdraft.email_subject, 'body': sdraft.email_body}
        db.session.remove()
MAIL.clear()
r = owner(A).post(f'/envoy/send/{sid}', base_url=host(A), data=form, follow_redirects=True)
check(not MAIL and 'own domain' in r.get_data(as_text=True),
      'without its own verified sending domain, a company cannot send cold email from Akye')
import email_domains
real_may = email_domains.may_send_as
email_domains.may_send_as = lambda addr: True
owner(A).post(f'/envoy/send/{sid}', base_url=host(A), data=form)
email_domains.may_send_as = real_may
check([to for to, _s in MAIL] == ['office@target.example.com'], 'with one, pressing Send sends that one email')
with app.app_context():
    from models import ProspectActivity
    with tenancy.use_tenant(A):
        a_logged = ProspectActivity.query.filter_by(prospect_id=sid, kind='email').count()
        db.session.remove()
    with tenancy.use_tenant(B):
        b_logged = ProspectActivity.query.filter_by(kind='email').count()
        db.session.remove()
check(a_logged == 1 and b_logged == 0, 'logged in that company\'s own history, and nowhere else')
r = owner(B).post(f'/envoy/send/{sid}', base_url=host(B), data=form)
check(r.status_code in (302, 404) and len(MAIL) == 1,
      'the same prospect id posted on another company\'s address sends nothing')

print('\n5. The console\'s Envoy switch stops it for every company')
platform_switches.set_switch(engine, 'envoy', False, by='test')
with app.app_context():
    from models import EnvoyRun
    with tenancy.use_tenant(A):
        EnvoyRun.query.delete(); db.session.commit(); db.session.remove()
r = cron.post('/api/envoy-daily', base_url=host(A), headers=KEY)
check(r.get_json().get('skipped') and counts(A)[2] == 0, f'paused: nothing searched, no run row ({r.get_json()})')
check(owner(A).get('/envoy/', base_url=host(A)).status_code == 200,
      'the page and what was already made stay readable')
platform_switches.set_switch(engine, 'envoy', True, by='test')

if failures:
    print(f'\n❌ {len(failures)} failed')
    sys.exit(1)
print('\n✅ Envoy stays inside each company, exists only where released, and obeys the console.')
