"""Envoy: a short list of new businesses to call each morning, with the words ready.

What would go wrong without each of these:
  * Envoy showing up for a company it was never released to -- or turning on
    by itself the moment the release-control switch could not be read;
  * a company seeing, or redrafting, another company's prospects;
  * the same business added to the call list twice, or a business that said
    "do not contact" (or is already a customer) found again;
  * two searches billed on one day because the scheduler called twice;
  * a draft that quotes a price, greets a made-up person, or invents an
    email address reaching the owner as if it were ready to send;
  * Claude still being called with the console's AI switch off, or past the
    company's daily cap;
  * anything at all sent to a prospect -- Envoy writes, a person sends;
  * a scoreboard counting rows Envoy did not earn.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import json
import os
import pathlib
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_envoy')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
os.environ['REMINDER_API_KEY'] = 'cron-key'
os.environ['ANTHROPIC_API_KEY'] = 'test-claude-key'

import notifications
MAIL, TEXTS = [], []
notifications.send_email = lambda to, *a, **k: (MAIL.append((to, a, k)) or (True, 'stub'))
notifications.send_sms = lambda *a, **k: (TEXTS.append(a) or (True, 'stub'))

from flask import g
from app import create_app
from extensions import db
from models import (BusinessSetting, CommercialAccount, CommercialQuote, EnvoyDraft,
                    Prospect, ProspectActivity, User)
from scheduling import local_today
import automations
import envoy
import llm
import places_finder
import platform_switches
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


BASE = 'akye.test'
A, B, C, D = 'sparkle', 'gleam', 'plainco', 'proplan'   # D is released but on Pro
OWNER = {A: 'owner@sparkle.test', B: 'owner@gleam.test'}
for slug, name in [(A, 'Sparkle Pros'), (B, 'Gleam Cleaning'), (C, 'Plain Co'), (D, 'Pro Plan Co')]:
    with app.app_context():
        provisioning.provision(slug, name, quiet=True)
        db.session.remove()
for slug in (A, B, C):
    fresh_postgres.set_company_plan(slug, 'scale')
fresh_postgres.set_company_plan(D, 'pro')
ENGINE = provisioning._engine()


def host(slug):
    return f'http://{slug}.{BASE}'


@contextmanager
def company(slug):
    """This company's data, with the plan read the way a request reads it."""
    with app.app_context(), tenancy.use_tenant(slug):
        g.tenant_slug = slug
        try:
            yield
        finally:
            db.session.remove()


# ── Doubles for the two outside services. Nothing leaves this process. ──────
SEARCHES = []
LISTINGS = {}


def fake_search(category, location, api_key=None, bias=None):
    SEARCHES.append((tenancy.current_schema(), category, location, bias))
    return True, [dict(r) for r in LISTINGS.get(tenancy.current_schema(), [])], ''


places_finder.search_businesses = fake_search
places_finder.api_key_present = lambda: True
places_finder.allowance = lambda: (False, False)
places_finder.locate = lambda text, api_key=None: (True, (28.54, -81.38, f'{text} (centre)'), '')

CLAUDE = []
CLAUDE_REPLY = {}


def fake_complete(system, user, max_tokens=600, model=None, timeout=30):
    CLAUDE.append((system, json.loads(user)))
    return json.dumps(CLAUDE_REPLY)


llm.complete = fake_complete


def good_reply(name):
    return {
        'first_line': f'Your team at {name} keeps a busy front desk.',
        'intro_subject': f'A cleaner for {name}',
        'intro_body': (f'Hi {name} team,\n\nWe are a local cleaning company and would be glad '
                       f'to come by for a free walkthrough and send a written quote.\n\nThanks,\nSam'),
        'call_script': 'Hi, this is Sam. We clean offices nearby. Could we do a free walkthrough?',
        'followup_3_subject': 'Following up', 'followup_3_body': 'Just checking in about a walkthrough.',
        'followup_7_subject': 'Last note', 'followup_7_body': 'One last note about a free walkthrough.',
    }


def listing(pid, name, phone='(555) 010-1000', website='https://x.example', rating=4.5,
            lat=28.55, lng=-81.37):
    return {'place_id': pid, 'business_name': name, 'phone': phone, 'website': website,
            'address': f'1 {name} Way', 'city': 'Somewhere', 'rating': rating,
            'lat': lat, 'lng': lng}


def owner_client(slug):
    return fresh_postgres.owner_client(app, slug, BASE)


def sales_client(slug):
    from auth import _auth_fingerprint
    with company(slug):
        u = User(name='Riley Rep', username=f'rep@{slug}.test', role='sales', active=True)
        u.set_password('a-perfectly-fine-password')
        db.session.add(u)
        db.session.commit()
        uid, fp = u.id, _auth_fingerprint(u.password_hash)
    c = app.test_client()
    with c.session_transaction(base_url=host(slug)) as s:
        s.update(logged_in=True, role='sales', user_id=uid, user_name='Riley Rep',
                 auth_fingerprint=fp, tenant_slug=slug)
    return c


def settings_form(**over):
    form = {'enabled': '1', 'area': 'Winter Park, FL', 'radius_miles': '10',
            'daily_limit': '3', 'sender_name': 'Sam', 'voice': 'Friendly and short.',
            'ai_daily_cap': '20'}
    form.update({f'day_{d}': 'office' for d in range(7)})
    form.update(over)
    return form


TODAY = local_today()
ISO = TODAY.isoformat()

# ─────────────────────────────────────────────────────────────────────────────
print('\n1. Released to nobody until an operator says so')
for slug in (A, B, C):
    with company(slug):
        check(not envoy.admitted(), f'{slug}: not released by default')
        BusinessSetting.set('email', OWNER.get(slug, f'owner@{slug}.test'))
        db.session.commit()
c_plain = owner_client(C)
r = c_plain.get('/envoy/', base_url=host(C))
check(r.status_code == 404, f'an unreleased company gets a 404, not a padlock ({r.status_code})')
r = c_plain.post('/api/envoy', base_url=host(C), headers={'X-Api-Key': 'cron-key'})
check(r.status_code == 200 and r.get_json().get('skipped'), 'and the scheduled run skips it')
with company(C):
    check(not any(row['key'] == 'envoy' for row in automations.overview()),
          'and its Automations page has no Envoy row (so its health is not "never ran")')
html = c_plain.get('/find-leads/', base_url=host(C)).get_data(as_text=True)
check('/envoy/' not in html, 'and Find Leads shows no link to it')

envoy.admit(ENGINE, A, True, by='test')
envoy.admit(ENGINE, B, True, by='test')
envoy.admit(ENGINE, D, True, by='test')
check(envoy.admitted_slugs(ENGINE) == sorted([A, B, D]), 'admit() releases exactly the named companies')
with company(A):
    check(envoy.admitted(), 'sparkle is released once admitted')
    check(not envoy.is_on(), 'but still off until the company itself switches it on')
with company(C):
    check(not envoy.admitted(), 'and releasing two companies released nobody else')

import control_plane
real_switches = control_plane.switches_checked
control_plane.switches_checked = lambda engine: (_ for _ in ()).throw(RuntimeError('db blinked'))
with company(A):
    check(not envoy.admitted(), 'an unreadable control plane reads as NOT released (fails closed)')
control_plane.switches_checked = real_switches

c_pro = owner_client(D)
r = c_pro.get('/envoy/', base_url=host(D), follow_redirects=False)
check(r.status_code in (302, 303) and '/upgrade' in (r.headers.get('Location') or ''),
      'released but not on the plan: the ordinary upgrade page')

# ─────────────────────────────────────────────────────────────────────────────
print('\n2. Settings: per company, off by default, saved by the owner only')
cA, cB = owner_client(A), owner_client(B)
r = cA.get('/envoy/', base_url=host(A))
body = r.get_data(as_text=True)
check(r.status_code == 200 and 'switched off' in body, 'the page opens, saying Envoy is off')
r = sales_client(A).get('/envoy/', base_url=host(A))
check(r.status_code in (302, 403), f'a Sales login cannot open it ({r.status_code})')
r = cA.post('/envoy/settings', base_url=host(A), data=settings_form())
check(r.status_code in (302, 303), 'the owner saves the settings')
with company(A):
    s = envoy.settings()
    check(s['enabled'] and s['area'] == 'Winter Park, FL' and s['daily_limit'] == 3,
          'enabled flag, service area and daily limit are kept')
    check(s['lat'] == 28.54 and s['lng'] == -81.38, 'the area was pinned to a centre once, on save')
    check(s['rotation'][TODAY.weekday()] == 'office', "today's category comes from the weekday rotation")
    check(s['sender_name'] == 'Sam' and s['voice'] == 'Friendly and short.', 'sender name and voice too')
    check(envoy.is_on(), 'and now all three locks are open')
with company(B):
    check(not envoy.settings()['enabled'] and envoy.settings()['area'] == '',
          "gleam's settings are its own: still off and empty")
r = cB.post('/envoy/settings', base_url=host(B),
            data=settings_form(area='Kissimmee, FL', daily_limit='10'))
with company(A):
    check(envoy.settings()['area'] == 'Winter Park, FL', "and gleam saving did not touch sparkle's")
with company(A):
    BusinessSetting.set('envoy_daily_limit', '')
    db.session.commit()
    check(envoy.settings()['daily_limit'] == 10, 'an unset daily limit falls back to 10')
    BusinessSetting.set('envoy_daily_limit', '3')
    db.session.commit()

# ─────────────────────────────────────────────────────────────────────────────
print('\n3. The daily run finds, de-duplicates, ranks and adds')
sA, sB = tenancy.schema_for(A), tenancy.schema_for(B)
LISTINGS[sA] = [
    listing('p-known', 'Already Listed Ltd'),
    listing('p-customer', 'Paying Customer Inc'),
    listing('p-far', 'Far Away Offices', lat=29.9, lng=-81.37),          # ~94 miles out
    listing('p-best', 'Best Offices', rating=4.9),
    listing('p-good', 'Good Offices', rating=4.0),
    listing('p-nophone', 'Quiet Offices', phone='', website='', rating=3.0),
    listing('p-best', 'Best Offices', rating=4.9),                        # Google repeating itself
]
LISTINGS[sB] = [listing('p-best', 'Gleam Side Offices'), listing('b-2', 'Bravo Tower')]
CLAUDE_REPLY.update(good_reply('Best Offices'))
with company(A):
    db.session.add(Prospect(business_name='Already Listed Ltd', place_id='p-known',
                            stage='lost', status='do_not_contact', source='google_places'))
    db.session.add(CommercialAccount(business_name='Paying Customer Inc', status='active'))
    db.session.commit()
    out = envoy.run_daily(force=True)
    mine = Prospect.query.filter_by(source='envoy').order_by(Prospect.id).all()
    names = [p.business_name for p in mine]
    check(out['found'] == 3 and len(mine) == 3, f'three added, the daily limit ({names})')
    check('Already Listed Ltd' not in names, 'a business already on the list (even do-not-contact) is not found again')
    check('Paying Customer Inc' not in names, 'an existing customer is not pitched')
    check('Far Away Offices' not in names, 'a listing outside the radius is dropped')
    check(names.count('Best Offices') == 1, 'a listing Google repeats is added once')
    check(names[0] == 'Best Offices' and 'Quiet Offices' in names,
          'ranked: the close, callable, well-rated one first')
    p = mine[0]
    check((p.source, p.stage, p.status, p.next_action, p.next_action_date) ==
          ('envoy', 'new', 'new', 'First call', ISO),
          "each is an ordinary prospect: source envoy, stage new, 'First call' due today")
    check(SEARCHES[-1][3] is not None and SEARCHES[-1][3][0] == 28.54,
          'the search was biased to the service-area circle')
    n_search = len(SEARCHES)
    again = envoy.run_daily(force=True)
    check(len(SEARCHES) == n_search and again['found'] == 0
          and Prospect.query.filter_by(source='envoy').count() == 3,
          'a second run the same day searches nothing and adds nothing')

# ─────────────────────────────────────────────────────────────────────────────
print('\n4. Drafts: personal, short, priced at nothing, invented nowhere')
with company(A):
    best = Prospect.query.filter_by(business_name='Best Offices').first()
    rows = {d.kind: d for d in EnvoyDraft.query.filter_by(prospect_id=best.id).all()}
    check(set(rows) == set(envoy.DRAFT_KINDS), 'all five drafts stored for the prospect')
    check(all(d.source == 'ai' for d in rows.values()), 'written by Claude when AI is on')
    sys_prompt, brief = CLAUDE[0]
    check('Never mention a price' in sys_prompt and 'free walkthrough and a written quote' in sys_prompt,
          'Claude is told: no prices, offer a free walkthrough and written quote')
    check('Do not invent' in sys_prompt, 'and told not to invent names, emails or facts')
    check(set(brief['business']) <= {'business_name', 'kind_of_business', 'area', 'address',
                                     'website', 'google_rating'},
          'and is given only what the listing showed')
    check(brief['voice'] == 'Friendly and short.' and brief['sender_name'] == 'Sam',
          "in the company's own voice, signed by its sender name")
    check(llm.FAST_MODEL, 'on the FAST model')

    f, cfg = envoy.facts(best), envoy.settings()
    bad = [
        ('intro_email', 'Our rate', 'Hi Best Offices team, only $99 per visit. Free walkthrough and quote.'),
        ('intro_email', 'Hi', 'Hi Maria, we would love a free walkthrough and to send a quote.'),
        ('intro_email', 'Hi', 'Hello team, email jane@bestoffices.com for a free walkthrough and quote.'),
        ('intro_email', 'Hi', 'Hello team, call (407) 555-1234 for a free walkthrough and written quote.'),
        ('intro_email', 'Hi', 'Hello [Name], a free walkthrough and written quote.'),
        ('intro_email', 'Hi', 'Hello team, ' + 'word ' * 130 + 'walkthrough quote'),
        ('intro_email', 'Hi', 'Hello team, we clean offices. Talk soon.'),
        ('first_line', None, 'We offer 20% off your first clean.'),
    ]
    for kind, subj, body in bad:
        check(envoy.problems(kind, subj, body, f, cfg), f'rejected: {body[:60]}…')
    good = envoy.problems('intro_email', 'A cleaner for Best Offices',
                          good_reply('Best Offices')['intro_body'], f, cfg)
    check(not good, f'a clean intro passes ({good})')

    # Claude writes something that breaks the rules: that piece falls back to
    # the template, the rest of its work is kept.
    reply = good_reply('Good Offices')
    reply['intro_body'] = 'Hi Maria, our deep clean is $149. Free walkthrough and written quote.'
    CLAUDE_REPLY.clear(); CLAUDE_REPLY.update(reply)
    goodp = Prospect.query.filter_by(business_name='Good Offices').first()
    envoy.write_drafts(goodp)
    rows = {d.kind: d for d in EnvoyDraft.query.filter_by(prospect_id=goodp.id).all()}
    check(rows['intro_email'].source == 'template' and '$' not in rows['intro_email'].body
          and 'Maria' not in rows['intro_email'].body,
          'a priced draft greeting a made-up person is replaced by the template')
    check(rows['first_line'].source == 'ai', 'and the pieces that passed are kept')
    plain = envoy.templates(goodp)
    words = len(plain['intro_email'][1].split())
    check(words < envoy.INTRO_MAX_WORDS and 'free walkthrough' in plain['intro_email'][1]
          and 'written quote' in plain['intro_email'][1],
          f'the template intro is under 120 words ({words}) and makes the same offer')
    check(all(not envoy.problems(k, s, b, envoy.facts(goodp), cfg)
              for k, (s, b) in plain.items() if k == 'intro_email'),
          'and passes the same checks')

# ─────────────────────────────────────────────────────────────────────────────
print('\n5. The AI kill switch, and the daily cap')
platform_switches.set_switch(ENGINE, 'ai', False, by='test')
before = len(CLAUDE)
with company(A):
    p = Prospect.query.filter_by(business_name='Quiet Offices').first()
    ai = envoy.write_drafts(p)
    rows = EnvoyDraft.query.filter_by(prospect_id=p.id).all()
    check(len(CLAUDE) == before and ai == 0, 'with the AI switch off, Claude is never called')
    check(len(rows) == 5 and all(d.source == 'template' for d in rows),
          'and the drafts still arrive, from the template')
r = cA.get('/envoy/', base_url=host(A))
check('AI writing is off' in r.get_data(as_text=True), 'the page says AI is off')
platform_switches.set_switch(ENGINE, 'ai', True, by='test')

with company(A):
    BusinessSetting.set('envoy_ai_daily_cap', '1')
    BusinessSetting.set(envoy.ai_used_key(), '0')
    db.session.commit()
    CLAUDE_REPLY.clear(); CLAUDE_REPLY.update(good_reply('Quiet Offices'))
    before = len(CLAUDE)
    envoy.write_drafts(p)
    envoy.write_drafts(p)
    check(len(CLAUDE) == before + 1, 'the daily cap of 1 allows exactly one Claude call')
    check(envoy.ai_used() == 1 and envoy.ai_room() == 0, 'and the count is kept per day')
    BusinessSetting.set('envoy_ai_daily_cap', '20')
    db.session.commit()

# ─────────────────────────────────────────────────────────────────────────────
print('\n6. Tenant isolation: one company never sees another\'s Envoy data')
CLAUDE_REPLY.clear(); CLAUDE_REPLY.update(good_reply('Bravo Tower'))
with company(B):
    out = envoy.run_daily(force=True)
    gb = [p.business_name for p in Prospect.query.filter_by(source='envoy').all()]
    check(sorted(gb) == ['Bravo Tower', 'Gleam Side Offices'],
          f"gleam finds its own, including a place sparkle already has ({gb})")
    check(EnvoyDraft.query.count() == 10, "gleam's drafts table holds only gleam's ten drafts")
    b_ids = {p.id for p in Prospect.query.filter_by(source='envoy')}
with company(A):
    a_ids = {p.id for p in Prospect.query.filter_by(source='envoy')}
    check(Prospect.query.filter_by(business_name='Bravo Tower').count() == 0,
          "sparkle's call list has none of gleam's businesses")
check(a_ids & b_ids, 'the two companies share prospect ids, so only the schema keeps them apart')
pageA = cA.get('/envoy/', base_url=host(A)).get_data(as_text=True)
pageB = cB.get('/envoy/', base_url=host(B)).get_data(as_text=True)
check('Best Offices' in pageA and 'Bravo Tower' not in pageA and 'Gleam Side' not in pageA,
      "sparkle's page shows only sparkle's businesses and drafts")
check('Bravo Tower' in pageB and 'Best Offices' not in pageB and 'Quiet Offices' not in pageB,
      "gleam's page shows only gleam's")
shared = sorted(a_ids & b_ids)[0]
with company(A):
    a_before = {d.kind: d.body for d in EnvoyDraft.query.filter_by(prospect_id=shared)}
CLAUDE_REPLY.clear(); CLAUDE_REPLY.update(good_reply('Gleam redraft'))
cB.post(f'/envoy/{shared}/redraft', base_url=host(B))
with company(A):
    a_after = {d.kind: d.body for d in EnvoyDraft.query.filter_by(prospect_id=shared)}
check(a_before == a_after, "gleam redrafting its prospect #%d left sparkle's #%d alone" % (shared, shared))
r = cB.get('/envoy/', base_url=host(A))
check(r.status_code != 200 or 'Best Offices' not in r.get_data(as_text=True),
      "gleam's login cannot open sparkle's Envoy page")
with company(A):
    check(envoy.scoreboard()['week']['found'] == 3, "sparkle's scoreboard counts sparkle's three")
with company(B):
    check(envoy.scoreboard()['week']['found'] == 2, "and gleam's counts gleam's two")

# ─────────────────────────────────────────────────────────────────────────────
print('\n7. Follow-ups due today, from the dates the call list keeps')
with company(A):
    db.session.add(Prospect(business_name='Due Today Dental', stage='working', source='google_places',
                            next_action='Follow-up call', next_action_date=ISO))
    db.session.add(Prospect(business_name='Overdue Gym', stage='working', source='google_places',
                            next_action='Call back', next_action_date=(TODAY - timedelta(days=2)).isoformat()))
    db.session.add(Prospect(business_name='Tomorrow Daycare', stage='working', source='google_places',
                            next_action='Call back', next_action_date=(TODAY + timedelta(days=1)).isoformat()))
    old = Prospect(business_name='Emailed Last Week', stage='working', source='envoy',
                   next_action='Follow up on the email', next_action_date=ISO,
                   last_emailed_at=datetime.utcnow() - timedelta(days=8),
                   created_at=datetime.utcnow() - timedelta(days=40))
    recent = Prospect(business_name='Emailed Monday', stage='working', source='envoy',
                      next_action='Follow up on the email', next_action_date=ISO,
                      last_emailed_at=datetime.utcnow() - timedelta(days=4),
                      created_at=datetime.utcnow() - timedelta(days=40))
    db.session.add_all([old, recent])
    db.session.commit()
    envoy.write_drafts(old)
    envoy.write_drafts(recent)
    due = envoy.followups()
    names = [p.business_name for p in due]
    check('Due Today Dental' in names and 'Overdue Gym' in names, 'due today and overdue are listed')
    check('Tomorrow Daycare' not in names, 'tomorrow is not')
    check(not any(n in names for n in ('Best Offices', 'Good Offices', 'Quiet Offices')),
          "today's new finds are not repeated as follow-ups")
    drafts = envoy.drafts_for([p.id for p in due])
    pick = {p.business_name: envoy.followup_draft(p, drafts) for p in due}
    check(pick['Emailed Last Week'].kind == 'followup_7', 'a week after the email: the day-7 follow-up')
    check(pick['Emailed Monday'].kind == 'followup_3', 'four days after: the day-3 follow-up')
    check(pick['Due Today Dental'] is None, 'a prospect Envoy did not write for gets no draft')

# ─────────────────────────────────────────────────────────────────────────────
print('\n8. Scoreboard from real records only')
with company(A):
    best = Prospect.query.filter_by(business_name='Best Offices').first()
    other = Prospect.query.filter_by(business_name='Due Today Dental').first()
    for kind in ('call', 'email'):
        db.session.add(ProspectActivity(prospect_id=best.id, business_name=best.business_name, kind=kind))
    db.session.add(ProspectActivity(prospect_id=best.id, business_name=best.business_name,
                                    kind='walkthrough_booked'))
    db.session.add(ProspectActivity(prospect_id=other.id, business_name=other.business_name, kind='call'))
    db.session.add(CommercialQuote(company='Best Offices', contact_name='Front desk',
                                   email='desk@x.example', token='tok-envoy-1', status='sent',
                                   sent_at=datetime.utcnow(), prospect_id=best.id))
    db.session.add(CommercialAccount(business_name='Best Offices', status='active',
                                     billing_type='monthly', billing_amount=600,
                                     prospect_id=best.id))
    db.session.add(CommercialAccount(business_name='Not From Envoy', status='active',
                                     billing_type='monthly', billing_amount=900,
                                     prospect_id=other.id))
    db.session.commit()
    sc = envoy.scoreboard()
    w, mth = sc['week'], sc['month']
    check(w['contacted'] == 1, f'contacted counts the business once, not each touch ({w["contacted"]})')
    check(w['walkthroughs'] == 1 and w['quotes'] == 1, 'walkthroughs booked and quotes sent are counted')
    check(w['won'] == 1 and w['mrr'] == 600.0, f'one won, $600 a month new ({w["won"]}, {w["mrr"]})')
    check(mth['found'] >= w['found'] and mth['mrr'] >= w['mrr'], 'the month includes the week')
    check(w['found'] == 3, 'found is what Envoy created this week, not the two from weeks ago')
page = cA.get('/envoy/', base_url=host(A)).get_data(as_text=True)
check('$600' in page and 'Scoreboard' in page, 'the page shows the scoreboard')

# ─────────────────────────────────────────────────────────────────────────────
print('\n9. The page, and the morning email: to the owner, and to nobody else')
check('data-copy=' in page and 'Copy' in page, 'drafts come with copy buttons')
check('Open lead to call or email' in page and '/find-leads/' in page,
      'each draft links to the lead page, where the existing send and its rules live')
html = cA.get('/find-leads/', base_url=host(A)).get_data(as_text=True)
check('/envoy/' in html, "a released company's owner sees the link from Find Leads")
MAIL.clear(); TEXTS.clear()
with company(A):
    BusinessSetting.set('envoy_last_email', '')
    db.session.commit()
    subject, body = envoy.compose_email()
    check(subject and 'new business' in subject and 'follow-up' in subject,
          f'the subject says what is waiting ({subject})')
    check('Best Offices' in body and 'Nothing has been sent' in body, 'it lists the businesses and says nothing was sent')
real_hour = envoy.MORNING_HOUR
envoy.MORNING_HOUR = 0
r = cA.post('/api/envoy', base_url=host(A), headers={'X-Api-Key': 'cron-key'})
check(r.status_code == 200 and r.get_json().get('ok'), f'the scheduled call runs ({r.get_json()})')
check(len(MAIL) == 1 and MAIL[0][0] == OWNER[A], 'exactly one email, to the owner')
r = cA.post('/api/envoy', base_url=host(A), headers={'X-Api-Key': 'cron-key'})
check(len(MAIL) == 1, 'and not again on the next hourly call')
prospect_addresses = {'desk@x.example'}
with company(A):
    prospect_addresses |= {p.email for p in Prospect.query.filter(Prospect.email.isnot(None))}
check(not any(to in prospect_addresses for to, *_ in MAIL) and not TEXTS,
      'nothing was emailed or texted to any prospect')
with company(A):
    from models import CronRun
    check(CronRun.query.filter_by(job='envoy').count() >= 1, 'each scheduled run is recorded for the Automations page')
    check(any(row['key'] == 'envoy' for row in automations.overview()),
          'and the Automations page shows the Envoy row to a released company')
r = cA.post('/api/envoy', base_url=host(A), headers={'X-Api-Key': 'wrong'})
check(r.status_code == 403, 'a wrong key is refused')
r = cA.post('/api/envoy?api_key=cron-key', base_url=host(A))
check(r.status_code in (400, 403), f'and a key in the URL is refused ({r.status_code})')
envoy.MORNING_HOUR = real_hour

import scheduling
real_now = scheduling.local_now
scheduling.local_now = lambda: real_now().replace(hour=6, minute=5)
with company(B):
    BusinessSetting.set('envoy_last_find', '')
    db.session.commit()
    n = len(SEARCHES)
    out = envoy.run_daily()
    check(out.get('skipped', '').startswith('waiting') and len(SEARCHES) == n,
          'before 7am where the business is, the hourly call waits')
scheduling.local_now = real_now

# ─────────────────────────────────────────────────────────────────────────────
print('\n10. Withdrawing it stops it, and keeps the data')
envoy.admit(ENGINE, A, False, by='test')
r = cA.get('/envoy/', base_url=host(A))
check(r.status_code == 404, 'withdrawn: the page is gone')
r = cA.post('/api/envoy', base_url=host(A), headers={'X-Api-Key': 'cron-key'})
check(r.get_json().get('skipped'), 'and the scheduled run does nothing')
with company(A):
    check(Prospect.query.filter_by(source='envoy').count() == 5 and EnvoyDraft.query.count() > 0,
          'and every prospect and draft it made is still there on the call list')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Envoy finds, drafts and reports for the company it was released to, and nobody else.')
