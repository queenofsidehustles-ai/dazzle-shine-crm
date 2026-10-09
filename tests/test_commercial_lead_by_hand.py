"""A lead you found yourself: on the call list, quoted the right way, and talked to.

Search was the only way onto the call list, so the leads a cleaning company
values most -- the office manager met at a networking breakfast, the property
manager a customer passed on -- had nowhere to go. And a quote never knew which
lead it was for, so what would go wrong without each of these:
  * a referral kept on somebody's phone instead of the list, and never called;
  * the same business typed in twice, and rung by two people;
  * a quote copied out by hand from the lead's details;
  * a proposal sent while the call list still said "book the walkthrough";
  * a business that accepted still due a follow-up call -- ringing a customer
    who has just signed;
  * a lead texting back and showing in the inbox as an Unknown number, with
    Thursday's follow-up still set for somebody who answered on Tuesday;
  * the Send button on a quote quietly saving instead of sending, because it
    sat in a form nested inside another;
  * a property manager buying unit turnovers quoted as an office contract --
    or an office quoted per bedroom -- because the call list could not say
    which kind of work a lead was.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_commercial_lead_by_hand')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append((a, k)) or (True, 'stub'))
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import CommercialAccount, CommercialQuote, Message, Prospect
from scheduling import local_today
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SLUG = 'gleam'
HOST = f'http://{SLUG}.akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Gleam Cleaning', quiet=True)
    db.session.remove()
# The starter templates a real signup gets -- the residential quote email is one.
provisioning.seed(app, SLUG)
fresh_postgres.set_company_plan(SLUG, 'scale')
c = fresh_postgres.owner_client(app, SLUG, 'akye.test')
TODAY = local_today().isoformat()


def lead(name):
    with app.app_context(), tenancy.use_tenant(SLUG):
        p = Prospect.query.filter_by(business_name=name).first()
        out = None if p is None else {k: getattr(p, k) for k in (
            'id', 'stage', 'status', 'source', 'next_action', 'next_action_date',
            'notes', 'contact_name', 'email', 'brand', 'phone', 'website')}
        db.session.remove()
        return out


print('\n1. A business you met goes onto the call list by hand')
page = c.get('/find-leads/?view=add', base_url=HOST).get_data(as_text=True)
check('Add a business yourself' in page and 'action="/find-leads/add"' in page,
      'there is an "Add one" form on Find leads')
r = c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'Sunrise Pediatrics', 'category': 'medical_office',
    'contact_name': 'Dana Ruiz', 'phone': '(301) 555-0142',
    'email': 'dana@sunrisepeds.example', 'website': 'sunrisepeds.example',
    'address': '12 Elm St', 'city': 'Rockville', 'brand': 'all',
    'notes': 'Met at the chamber breakfast — nightly cleaning, 3 restrooms'})
p = lead('Sunrise Pediatrics')
check(r.status_code == 302 and p is not None, 'it is saved')
check(p and p['source'] == 'manual' and p['stage'] == 'new'
      and p['next_action'] == 'First call' and p['next_action_date'] == TODAY,
      'as a first call due today, like anything search found')
check(p and p['brand'] == 'commercial', 'a medical office is worked as the commercial brand')
check(p and p['website'] == 'https://sunrisepeds.example', 'a bare website gets its https://')
check(p and 'chamber breakfast' in (p['notes'] or '') and 'Added by hand' in p['notes'],
      'and what you knew about them is on its notes')
today = c.get('/find-leads/?view=today', base_url=HOST).get_data(as_text=True)
check('Sunrise Pediatrics' in today, 'it is on Today\'s calls straight away')

print('\n2. The same business is not added twice')
c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'Sunrise Peds (Dana)', 'phone': '301.555.0142', 'city': 'Bethesda'})
c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'sunrise pediatrics', 'city': 'ROCKVILLE'})
with app.app_context(), tenancy.use_tenant(SLUG):
    n = Prospect.query.count()
    db.session.remove()
check(n == 1, f'not by the same number, nor the same name in the same town ({n} on the list)')
r = c.post('/find-leads/add', base_url=HOST, data={'business_name': '  '})
with app.app_context(), tenancy.use_tenant(SLUG):
    n = Prospect.query.count()
    db.session.remove()
check(n == 1, 'and a blank name adds nothing')

c.post('/find-leads/add', base_url=HOST, data={'business_name': 'Bright Smiles Dental'})
c.post('/find-leads/add', base_url=HOST, data={'business_name': 'Bright Smiles Dental'})
with app.app_context(), tenancy.use_tenant(SLUG):
    n = Prospect.query.filter_by(business_name='Bright Smiles Dental').count()
    db.session.remove()
check(n == 2, 'but a name alone, with no town, is not a duplicate — franchises share names')

print('\n3. From the lead: text them and quote them')
everyone = c.get('/find-leads/?view=everyone', base_url=HOST).get_data(as_text=True)
check('id="cdText"' in everyone and 'id="cdQuote"' in everyone,
      'the lead\'s drawer has Text and Quote next to Call')
check('/messages/thread/0000000000' in everyone and 'prospect_id=0' in everyone,
      'pointing at the inbox and a new quote for that lead')
sheet = c.get(f'/find-leads/call/{p["id"]}', base_url=HOST).get_data(as_text=True)
check('/messages/thread/3015550142' in sheet and f'/quotes/new?prospect_id={p["id"]}' in sheet,
      'and so does the one-at-a-time call sheet')

form = c.get(f'/quotes/new?prospect_id={p["id"]}', base_url=HOST).get_data(as_text=True)
check('value="Sunrise Pediatrics"' in form and 'value="Dana Ruiz"' in form
      and 'value="dana@sunrisepeds.example"' in form and 'value="(301) 555-0142"' in form,
      'the quote opens already filled in with what the lead knows')
check('value="12 Elm St, Rockville"' in form and re.search(
          r'<option value="Office Building"\s+selected', form),
      'address and property type too')
check(f'name="prospect_id" value="{p["id"]}"' in form and 'on your call list' in form,
      'and it says which lead it is for')

r = c.post('/quotes/new', base_url=HOST, data={
    'prospect_id': p['id'], 'company': 'Sunrise Pediatrics', 'contact_name': 'Dana Ruiz',
    'email': 'dana@sunrisepeds.example', 'phone': '(301) 555-0142',
    'property_type': 'Office Building', 'frequency': 'daily', 'contract_term': 'annual',
    'monthly_price': '1850', 'services': ['Office Cleaning', 'Restroom Sanitation']})
with app.app_context(), tenancy.use_tenant(SLUG):
    q = CommercialQuote.query.filter_by(company='Sunrise Pediatrics').first()
    qid, token, linked = q.id, q.token, q.prospect_id
    db.session.remove()
check(linked == p['id'], 'the saved quote remembers its lead')

detail = c.get(f'/quotes/{qid}', base_url=HOST).get_data(as_text=True)
check(f'formaction="/quotes/{qid}/send"' in detail
      and f'action="/quotes/{qid}/send"' not in detail.replace('formaction', ''),
      'Send is a button of the edit form, not a form nested inside it '
      '(which a browser ignores, so Send used to save and send nothing)')

print('\n4. Sending moves the lead to Proposal')
SENT.clear()
r = c.post(f'/quotes/{qid}/send', base_url=HOST)
p = lead('Sunrise Pediatrics')
check(any(k.get('to_email') == 'dana@sunrisepeds.example' for _, k in SENT),
      'the proposal is emailed to them')
check(p['stage'] == 'proposal' and p['next_action'] == 'Follow up on the quote'
      and p['next_action_date'] > TODAY,
      f'the lead is in Proposal with a follow-up a few days out ({p["stage"]}, {p["next_action_date"]})')
check('Quote emailed' in (p['notes'] or ''), 'and the notes say a quote went')

print('\n5. Accepting wins it; declining rests it')
anon = app.test_client()
anon.post(f'/quotes/view/{token}/accept', base_url=HOST)
p = lead('Sunrise Pediatrics')
with app.app_context(), tenancy.use_tenant(SLUG):
    acc = CommercialAccount.query.filter_by(business_name='Sunrise Pediatrics').first()
    acc_lead = acc.prospect_id if acc else None
    db.session.remove()
check(p['stage'] == 'won' and p['status'] == 'won' and not p['next_action_date'],
      'an accepted quote marks the lead won, with no call left due')
check(acc_lead == p['id'], 'and the new account knows which lead it came from')
today = c.get('/find-leads/?view=today', base_url=HOST).get_data(as_text=True)
check('Sunrise Pediatrics' not in today.split('Today\'s calls', 1)[-1].split('callDrawer')[0],
      'so nobody rings a business that has just signed')
c.post(f'/quotes/{qid}/send', base_url=HOST)
check(lead('Sunrise Pediatrics')['stage'] == 'won',
      'resending the accepted quote leaves them won, not back in Proposal')

c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'Maple Office Park', 'category': 'office', 'phone': '3015550199'})
m = lead('Maple Office Park')
c.post('/quotes/new', base_url=HOST, data={
    'prospect_id': m['id'], 'company': 'Maple Office Park', 'contact_name': 'Lee',
    'email': 'lee@maple.example', 'property_type': 'Office Building', 'monthly_price': '900'})
with app.app_context(), tenancy.use_tenant(SLUG):
    q2 = CommercialQuote.query.filter_by(company='Maple Office Park').first()
    t2 = q2.token
    db.session.remove()
check(lead('Maple Office Park')['email'] == 'lee@maple.example'
      and lead('Maple Office Park')['contact_name'] == 'Lee',
      'who the quote went to is kept on the lead for the next call')
c.post('/find-leads/add', base_url=HOST, data={'business_name': 'Quiet Office Co', 'city': 'Laurel'})
qo = lead('Quiet Office Co')
c.post('/quotes/new', base_url=HOST, data={
    'prospect_id': qo['id'], 'company': 'Quiet Office Co', 'contact_name': 'Sam',
    'email': 'sam@quiet.example', 'phone': '(301) 555-0400', 'property_type': 'Office Building'})
check(lead('Quiet Office Co')['phone'] == '(301) 555-0400',
      'a phone number first given on the quote is kept on the lead too')
c.post(f'/quotes/{q2.id}/send', base_url=HOST)
anon.post(f'/quotes/view/{t2}/decline', base_url=HOST)
m = lead('Maple Office Park')
check(m['stage'] == 'nurture' and m['next_action'] == 'Quarterly check-in'
      and m['next_action_date'] > TODAY,
      'a declined quote rests the lead in nurture for a quarter, not lost')

print('\n6. When a lead texts back, the inbox and the call list both know')
import blueprints.messages as M
c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'Harbor Daycare', 'category': 'daycare',
    'contact_name': 'Pat', 'phone': '+1 (240) 555-0177'})
with app.app_context(), tenancy.use_tenant(SLUG):
    who = M.resolve_contact('2405550177')
    check(M.contact_kind(who) == 'prospect' and who['name'] == 'Pat (Harbor Daycare)',
          f'the number reads as the business lead, not Unknown ({who["name"]})')
    with app.test_request_context('/messages/incoming', method='POST',
                                  data={'From': '+12405550177',
                                        'Body': 'Yes — can you come Tuesday to look?'}):
        M.incoming()
    db.session.remove()
# Leaving a request clears the current company, so look again from inside it.
with app.app_context(), tenancy.use_tenant(SLUG):
    msg = Message.query.filter_by(phone='2405550177', direction='in').first()
    check(msg is not None and msg.contact_name == 'Pat (Harbor Daycare)',
          'the reply is in the inbox under their name')
    db.session.remove()
h = lead('Harbor Daycare')
check('Texted back' in (h['notes'] or '') and 'come Tuesday' in h['notes'],
      'and on the lead\'s notes')
check(h['next_action'] == 'They texted back — reply' and h['next_action_date'] == TODAY
      and h['stage'] == 'interested',
      'replying is what is due today, and the lead is now Interested')
inbox = c.get('/messages/', base_url=HOST).get_data(as_text=True)
check('Business lead' in inbox, 'the inbox can filter to business leads')

with app.app_context(), tenancy.use_tenant(SLUG):
    with app.test_request_context('/messages/incoming', method='POST',
                                  data={'From': '+12405550177', 'Body': 'STOP'}):
        M.incoming()
    db.session.remove()
check('Texted STOP' in (lead('Harbor Daycare')['notes'] or ''),
      'a STOP is written on the lead, so nobody texts them again by hand')

# Twilio refuses a STOPped number anyway, but the CRM must not offer or try.
everyone = c.get('/find-leads/?view=everyone', base_url=HOST).get_data(as_text=True)
harbor_row = everyone.split('data-name="Harbor Daycare"', 1)[1].split('>', 1)[0]
check('data-smsstop="1"' in harbor_row, 'after STOP the drawer stops offering Text')
sheet = c.get(f'/find-leads/call/{h["id"]}', base_url=HOST).get_data(as_text=True)
check('/messages/thread/2405550177' not in sheet, 'and so does the call sheet')
with app.app_context(), tenancy.use_tenant(SLUG):
    before = Message.query.filter_by(phone='2405550177', direction='out').count()
    db.session.remove()
c.post('/messages/thread/2405550177/send', base_url=HOST, data={'body': 'Just checking in!'})
with app.app_context(), tenancy.use_tenant(SLUG):
    after = Message.query.filter_by(phone='2405550177', direction='out').count()
    db.session.remove()
check(after == before, 'and a text typed into their conversation is refused, not sent')

print('\n7. Only the owner is offered a quote')
from blueprints import places_finder as PF
with app.test_request_context('/', base_url=HOST):
    from flask import session
    session['role'] = 'team'
    check(PF._can_quote() is False, 'a team member\'s drawer has no Quote button')

print('\n8. Residential or commercial: a toggle, and the quote follows it')
page = c.get('/find-leads/?view=add', base_url=HOST).get_data(as_text=True)
check('name="kind" value="residential"' in page and 'name="kind" value="commercial"' in page,
      'the add form asks what they are buying')
c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'Oakline Property Management', 'category': 'property_manager',
    'contact_name': 'Jo Park', 'phone': '3015550311', 'email': 'jo@oakline.example',
    'address': '9 Main St', 'city': 'Gaithersburg'})
c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'Ridge Realty Offices', 'category': 'realtor', 'kind': 'commercial'})
oak, ridge = lead('Oakline Property Management'), lead('Ridge Realty Offices')
check(oak['brand'] == 'primary', 'left alone, a property manager is residential — turnovers are home cleaning')
check(ridge['brand'] == 'commercial', 'but picking Commercial overrides the guess')
everyone = c.get('/find-leads/?view=everyone', base_url=HOST).get_data(as_text=True)
check('🏠 Residential' in everyone and '🏢 Commercial' in everyone,
      'every lead shows which it is')
check('data-kind="residential"' in everyone and '/leads/quote/new?prospect_id=0' in everyone,
      'and the drawer knows, with the home quote to hand')

sheet = c.get(f'/find-leads/call/{oak["id"]}', base_url=HOST).get_data(as_text=True)
check(f'/leads/quote/new?prospect_id={oak["id"]}' in sheet and 'Home quote' in sheet
      and f'/quotes/new?prospect_id={oak["id"]}' not in sheet,
      'a residential lead\'s call sheet offers the per-home quote, not a contract')

form = c.get(f'/leads/quote/new?prospect_id={oak["id"]}', base_url=HOST).get_data(as_text=True)
check('value="Jo Park"' in form and 'value="jo@oakline.example"' in form
      and 'value="3015550311"' in form and 'value="9 Main St"' in form,
      'the home quote opens filled in from the lead')
check(re.search(r'<option value="moveout"\s+selected', form)
      and f'name="prospect_id" value="{oak["id"]}"' in form
      and 'Residential quote for' in form,
      'as a move-out/turnover, saying which lead it is for')
SENT.clear()
c.post('/leads/quote/new', base_url=HOST, data={
    'prospect_id': oak['id'], 'name': 'Jo Park', 'email': 'jo@oakline.example',
    'phone': '3015550311', 'service_type': 'moveout', 'bedrooms': '2', 'bathrooms': '1',
    'frequency': 'one_time', 'address': '9 Main St', 'city': 'Gaithersburg'})
oak = lead('Oakline Property Management')
from models import Lead
with app.app_context(), tenancy.use_tenant(SLUG):
    res = Lead.query.filter_by(email='jo@oakline.example').first()
    res_link, res_id = (res.prospect_id, res.id) if res else (None, None)
    db.session.remove()
check(res_link == oak['id'], 'the residential quote remembers its lead')
check(any(k.get('to_email') == 'jo@oakline.example' or (a and a[0] == 'jo@oakline.example')
          for a, k in SENT), 'and is emailed to them')
check(oak['stage'] == 'proposal' and oak['next_action'] == 'Follow up on the quote'
      and 'Residential quote' in (oak['notes'] or ''),
      'sending it moves the lead to Proposal, like a contract quote')

import quoting
with app.app_context(), tenancy.use_tenant(SLUG):
    quoting.accept_quote(db.session.get(Lead, res_id), '2026-11-02')
    db.session.remove()
oak = lead('Oakline Property Management')
check(oak['stage'] == 'won' and not oak['next_action_date'],
      'and when they book from it, the lead is won')

r = c.post(f'/find-leads/{ridge["id"]}/kind', base_url=HOST,
           data={'kind': 'residential', 'next': 'https://evil.example/'})
check(lead('Ridge Realty Offices')['brand'] == 'primary', 'one tap flips a lead to residential')
check(r.headers.get('Location', '').startswith('/find-leads'),
      'and sends you back to the call list, never off-site')
c.post(f'/find-leads/{ridge["id"]}/kind', base_url=HOST, data={'kind': 'nonsense'})
check(lead('Ridge Realty Offices')['brand'] == 'primary', 'anything else changes nothing')
form = c.get(f'/quotes/new?prospect_id={ridge["id"]}', base_url=HOST).get_data(as_text=True)
check(f'/leads/quote/new?prospect_id={ridge["id"]}' in form,
      'and a contract quote started by mistake links across to the home quote')

print('\n9. Restaurants are a kind of business of their own')
import brands
import commercial_pricing
import places_finder as finder
page = c.get('/find-leads/?view=add', base_url=HOST).get_data(as_text=True)
check('<option value="restaurant"' in page and 'Restaurant / Café' in page,
      'Restaurant is in the list when adding one by hand')
find = c.get('/find-leads/?view=find', base_url=HOST).get_data(as_text=True)
check('<option value="restaurant"' in find and finder.CATEGORY_QUERIES.get('restaurant'),
      'and can be searched for under Find new')
c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'Sunshine Grill', 'category': 'restaurant', 'city': 'Silver Spring'})
grill = lead('Sunshine Grill')
check(grill['brand'] == 'commercial', 'a restaurant is commercial work unless you say otherwise')
form = c.get(f'/quotes/new?prospect_id={grill["id"]}', base_url=HOST).get_data(as_text=True)
check(re.search(r'<option value="Restaurant / Food Service"\s+selected', form),
      'its contract quote opens as a restaurant')
check(brands.brand_for_property('Restaurant / Food Service') == brands.COMMERCIAL,
      'and goes out under the commercial name')
with app.app_context(), tenancy.use_tenant(SLUG):
    check(commercial_pricing.prod_rate('restaurant') < commercial_pricing.prod_rate('office'),
          'kitchens are priced as slower work than an office')
    db.session.remove()
with app.app_context(), tenancy.use_tenant(SLUG):
    ticked = set(commercial_pricing.get_config()['default_extras']['restaurant'])
    bare = commercial_pricing.quote(4000, 'restaurant', 'weekly', [])['monthly']
    full = commercial_pricing.quote(4000, 'restaurant', 'weekly', sorted(ticked))['monthly']
    no_line = commercial_pricing.quote(4000, 'restaurant', 'weekly',
                                       sorted(ticked - {'floor_degrease', 'kitchen_equipment'}))['monthly']
    med_bare = commercial_pricing.quote(4000, 'medical_office', 'weekly', [])['monthly']
    med_full = commercial_pricing.quote(4000, 'medical_office', 'weekly', ['disinfection'])['monthly']
    db.session.remove()
check(ticked == {'restrooms', 'breakroom', 'floor_degrease', 'kitchen_equipment'},
      'the kitchen, restrooms, floor degreasing and the line (fryers, grills, cooktops) start ticked')
check(bare < no_line < full, f'but unticking them takes them off the price ({bare} < {no_line} < {full})')
check(med_bare == med_full, 'while a medical office still always carries its disinfection')

# Find new under "All brands" used to file every search as residential.
find = c.get('/find-leads/?view=find', base_url=HOST).get_data(as_text=True)
check(re.search(r'<option value="all"\s+selected>Work it out', find),
      'Find new files results by their kind of business unless you pick a brand')
import json as _json
c.post('/find-leads/import', base_url=HOST, data={
    'brand': 'all', 'selected': ['demo-restaurant-1'],
    'payload_demo-restaurant-1': _json.dumps({
        'business_name': 'Lakeside Bistro', 'category': 'restaurant',
        'place_id': 'demo-restaurant-1', 'city': 'Rockville', 'phone': '(407) 555-0413'})})
check(lead('Lakeside Bistro')['brand'] == 'commercial',
      'so a restaurant found by search lands as commercial')

# The call sheet's script follows the toggle, like its quote button does.
with app.app_context(), tenancy.use_tenant(SLUG):
    from models import BusinessSetting
    BusinessSetting.set('commercial_name', 'Gleam Commercial Co')
    db.session.commit()
    db.session.remove()
sheet_com = c.get(f'/find-leads/call/{grill["id"]}', base_url=HOST).get_data(as_text=True)
c.post(f'/find-leads/{grill["id"]}/kind', base_url=HOST, data={'kind': 'residential'})
sheet_res = c.get(f'/find-leads/call/{grill["id"]}', base_url=HOST).get_data(as_text=True)
# The brand switcher at the top of every page names both companies once, so
# compare against that: the commercial name only shows in the script itself.
check(sheet_com.count('Gleam Commercial Co') > 1 and sheet_res.count('Gleam Commercial Co') == 1
      and 'Home quote' in sheet_res,
      'flipped to residential, the call sheet reads the residential company, not the commercial one')

print('\n10. Gyms and churches too')
page = c.get('/find-leads/?view=add', base_url=HOST).get_data(as_text=True)
find = c.get('/find-leads/?view=find', base_url=HOST).get_data(as_text=True)
for key, name, ptype, extras in (
        ('gym', 'Harbor Point CrossFit', 'Gym / Fitness Center', {'restrooms', 'disinfection'}),
        ('church', 'Lakeside Baptist Church', 'Church / House of Worship', {'restrooms'})):
    check(f'<option value="{key}"' in page and f'<option value="{key}"' in find
          and finder.CATEGORY_QUERIES.get(key),
          f'{key}: in the add list, and searchable under Find new')
    c.post('/find-leads/add', base_url=HOST, data={
        'business_name': name, 'category': key, 'city': 'Bowie'})
    row = lead(name)
    check(row['brand'] == 'commercial', f'{key}: commercial work by default')
    form = c.get(f'/quotes/new?prospect_id={row["id"]}', base_url=HOST).get_data(as_text=True)
    check(re.search(rf'<option value="{re.escape(ptype)}"\s+selected', form)
          and brands.brand_for_property(ptype) == brands.COMMERCIAL,
          f'{key}: its contract quote opens as "{ptype}", under the commercial name')
    with app.app_context(), tenancy.use_tenant(SLUG):
        cfg = commercial_pricing.get_config()
        rate = commercial_pricing.prod_rate(key)
        # Big enough to be past the minimum-visit floor, which would hide an add-on.
        bare = commercial_pricing.quote(12000, key, 'weekly', [])['monthly']
        full = commercial_pricing.quote(12000, key, 'weekly', sorted(extras))['monthly']
        db.session.remove()
    check(key in commercial_pricing.PROD_RATES and rate == commercial_pricing.PROD_RATES[key]
          and set(cfg['default_extras'][key]) == extras and bare < full,
          f'{key}: its own cleaning rate, with {sorted(extras)} pre-ticked and removable')
check(commercial_pricing.prod_rate('gym') < commercial_pricing.prod_rate('office')
      < commercial_pricing.prod_rate('church'),
      'a gym is slower work than an office, a church faster')

print('\n11. One page per lead: correct it, qualify it, talk to it, quote it, sign it')
r = c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'Chang Chang', 'category': 'office', 'phone': '2025700946', 'city': 'Washington'})
chang = lead('Chang Chang')
check(r.headers.get('Location', '').endswith(f'/find-leads/{chang["id"]}'),
      'adding a lead by hand lands on its own page')
page = c.get(f'/find-leads/{chang["id"]}', base_url=HOST).get_data(as_text=True)
check(page.count('Log a call') and 'name="category"' in page and 'Contract quote' in page
      and 'Make them an account' in page and '2025700946' in page,
      'the page has the details, the call log, the quote and the account step in one place')

c.post(f'/find-leads/{chang["id"]}/edit', base_url=HOST, data={
    'business_name': 'Chang Chang', 'category': 'restaurant', 'contact_name': 'Mei Chang',
    'phone': '2025700946', 'email': 'mei@changchang.example', 'city': 'Washington'})
chang = lead('Chang Chang')
check(chang['brand'] == 'commercial' and chang['contact_name'] == 'Mei Chang'
      and chang['email'] == 'mei@changchang.example',
      'an office typed in by mistake is corrected to a restaurant, with who to ask for')
with app.app_context(), tenancy.use_tenant(SLUG):
    check(db.session.get(Prospect, chang['id']).category == 'restaurant', 'and saved as one')
    db.session.remove()
c.post(f'/find-leads/{oak["id"]}/edit', base_url=HOST, data={'category': 'office'})
check(lead('Oakline Property Management')['brand'] == 'commercial',
      'changing the kind of business, without picking a side, follows the new kind')
c.post(f'/find-leads/{oak["id"]}/edit', base_url=HOST, data={'category': 'office', 'kind': 'residential'})
check(lead('Oakline Property Management')['brand'] == 'primary', 'but a side picked by hand wins')

r = c.post(f'/find-leads/{chang["id"]}/status', base_url=HOST, data={
    'mode': 'log', 'status': 'interested', 'log_note': 'Wants nightly cleaning, 3,200 sq ft, kitchen too',
    'next': f'/find-leads/{chang["id"]}'})
chang = lead('Chang Chang')
check(r.headers.get('Location', '').endswith(f'/find-leads/{chang["id"]}')
      and chang['stage'] == 'interested' and 'nightly cleaning' in (chang['notes'] or ''),
      'a call logged from the page qualifies the lead and comes back to the page')
r = c.post(f'/find-leads/{chang["id"]}/snooze', base_url=HOST,
           data={'days': '3', 'next': 'https://evil.example/'})
check('evil.example' not in r.headers.get('Location', ''), 'and never sends anybody off-site')

with app.app_context(), tenancy.use_tenant(SLUG):
    import blueprints.places_finder as PF2
    with app.test_request_context('/', base_url=HOST):
        openers = PF2._openers()
    db.session.remove()
check(all(openers[b].get(cat) for b in openers for cat in ('office', 'restaurant', 'gym')),
      'the drawer has an opening script for every kind of business (it said "No script loaded yet")')

conv = c.get(f'/commercial/convert/{chang["id"]}', base_url=HOST).get_data(as_text=True)
check('value="Mei Chang"' in conv and 'value="mei@changchang.example"' in conv,
      'making them an account starts filled in from the lead')
c.post(f'/commercial/convert/{chang["id"]}', base_url=HOST, data={
    'contact_name': 'Mei Chang', 'email': 'mei@changchang.example', 'phone': '2025700946',
    'frequency': 'nightly', 'billing_type': 'monthly', 'billing_amount': '2400'})
chang = lead('Chang Chang')
with app.app_context(), tenancy.use_tenant(SLUG):
    acct = CommercialAccount.query.filter_by(prospect_id=chang['id']).first()
    acct_cat = acct.category if acct else None
    db.session.remove()
check(acct is not None and acct_cat == 'restaurant', 'they become a restaurant account')
check(chang['stage'] == 'won' and not chang['next_action_date'],
      'and the lead is won, with no call left due')
page = c.get(f'/find-leads/{chang["id"]}', base_url=HOST).get_data(as_text=True)
check('Their account' in page and 'Make them an account' not in page,
      'the page now points at their account instead')

print('\n12. The lead page is a lead surface, and gets the details right')
import rbac
check(all(rbac.required_permission(ep, m) == 'prospect.work' for ep, m in (
          ('places_finder.lead_page', 'GET'), ('places_finder.edit_lead', 'POST'),
          ('places_finder.set_kind', 'POST'), ('places_finder.add_by_hand', 'POST'))),
      'the lead page and its forms are the prospecting module (prospect.work)')
def role_client(role):
    """Signed in as a real user with this role, bound like a real login --
    a role changed inside the session alone is (rightly) signed out."""
    from auth import _auth_fingerprint
    from models import User
    with app.app_context(), tenancy.use_tenant(SLUG):
        u = User(name=role.title(), username=f'{role}@{SLUG}.test', role=role, active=True)
        u.set_password('a-perfectly-fine-password')
        db.session.add(u)
        db.session.commit()
        uid, fp = u.id, _auth_fingerprint(u.password_hash)
        db.session.remove()
    client = app.test_client()
    with client.session_transaction(base_url=HOST) as sess:
        sess.update(logged_in=True, role=role, user_id=uid, user_name=role.title(),
                    auth_fingerprint=fp, tenant_slug=SLUG)
    return client


cl = role_client('cleaner')
r1 = cl.get(f'/find-leads/{chang["id"]}', base_url=HOST)
r2 = cl.post(f'/find-leads/{chang["id"]}/edit', base_url=HOST, data={'business_name': 'Hijacked'})
check(r1.status_code == 403 and r2.status_code == 403 and lead('Chang Chang') is not None,
      f'a cleaner can neither open a lead page nor rename the lead ({r1.status_code}, {r2.status_code})')
dc = role_client('dispatcher')
check(dc.get(f'/find-leads/{chang["id"]}', base_url=HOST).status_code == 403,
      'nor can a dispatcher -- prospecting is the owner\'s and the Sales role\'s')

c.post(f'/find-leads/{oak["id"]}/edit', base_url=HOST, data={'category': 'property_manager'})
c.post(f'/find-leads/{oak["id"]}/edit', base_url=HOST, data={'category': 'property_manager', 'kind': 'commercial'})
check(lead('Oakline Property Management')['brand'] == 'commercial', '(set up: flipped to commercial by hand)')
c.post(f'/find-leads/{oak["id"]}/edit', base_url=HOST, data={
    'category': 'apartment', 'kind': 'commercial', 'kind_was': 'commercial'})
check(lead('Oakline Property Management')['brand'] == 'primary',
      'changing only the kind of business moves the side, though the form sends the side it showed')

with app.app_context(), tenancy.use_tenant(SLUG):
    from models import Script
    db.session.add(Script(category='call_office', title='Opening — offices (starter pack)',
                          content='Hi, quick question about your office cleaning', sort_order=1))
    old_lead = Prospect(business_name='Old Won Bakery', category='restaurant', status='won',
                        stage=None, phone='3015550999')
    db.session.add(old_lead)
    db.session.commit()
    old_id = old_lead.id
    # What a lead from before stages existed looks like: no stage, nothing due.
    db.session.execute(db.text('UPDATE prospect SET stage = NULL, next_action = NULL, '
                               'next_action_date = NULL, attempts = NULL WHERE id = :i'), {'i': old_id})
    db.session.commit()
    with app.test_request_context('/', base_url=HOST):
        office = PF2._openers()['commercial']['office']
    db.session.remove()
check(office and office[0]['title'].startswith('Opening — offices (starter pack)'),
      'loaded starter-pack openings for a kind of business are the ones the drawer reads')
c.get(f'/find-leads/{old_id}', base_url=HOST)
check(lead('Old Won Bakery')['stage'] == 'won',
      'an old lead opened straight from a link is brought up to date, not shown as New')

print('\n13. The walkthrough: booked, filled in on site, and written into the quote')
import commercial_pricing as cp
c.post('/find-leads/add', base_url=HOST, data={
    'business_name': 'Golden Wok', 'category': 'restaurant', 'phone': '2025550101', 'city': 'Washington'})
wok = lead('Golden Wok')
page = c.get(f'/find-leads/{wok["id"]}', base_url=HOST).get_data(as_text=True)
check('Book walkthrough' in page and 'Fill in the checklist on site' in page,
      'a lead can have its walkthrough booked, and the checklist filled in')
c.post(f'/find-leads/{wok["id"]}/walkthrough/book', base_url=HOST,
       data={'date': '2026-11-03', 'time': '10:30am'})
wok = lead('Golden Wok')
check(wok['next_action'] == 'Walkthrough at 10:30am' and wok['next_action_date'] == '2026-11-03'
      and wok['stage'] == 'interested',
      'booking it makes it the next step, on the day, so it shows on the calendar')
c.post(f'/find-leads/{wok["id"]}/walkthrough', base_url=HOST, data={
    'sqft': '3,200', 'restrooms': '2', 'frequency': 'weekly', 'hours': '',
    'services': ['floors', 'restrooms', 'nonsense'], 'days': 'Mondays after close',
    'access': 'Back door, code 4412', 'notes': 'Tile in the dining room'})
wok = lead('Golden Wok')
with app.app_context(), tenancy.use_tenant(SLUG):
    w = prospecting_walk = __import__('prospecting').walkthrough(db.session.get(Prospect, wok['id']))
    db.session.remove()
check(w.get('sqft') == 3200 and w.get('services') == ['floors', 'restrooms'] and w.get('frequency') == 'weekly',
      'the checklist is saved: 3,200 sq ft, weekly, floors and restrooms (unknown boxes ignored)')
check(wok['next_action'] == 'Write and send the quote' and wok['next_action_date'] == TODAY
      and 'Walkthrough done — 3,200 sq ft · 2 restrooms · weekly' in (wok['notes'] or ''),
      'and the next step is writing the quote, today, with the walkthrough in the history')
page = c.get(f'/find-leads/{wok["id"]}', base_url=HOST).get_data(as_text=True)
check('Write the quote from this walkthrough' in page and 'Starting price' in page,
      'the page shows what was found, a starting price, and the way to the quote')

form = c.get(f'/quotes/new?prospect_id={wok["id"]}', base_url=HOST).get_data(as_text=True)
check('value="3200"' in form and re.search(r'<option value="weekly"\s+selected', form)
      and re.search(r'value="Floor Care \(Sweep &amp; Mop\)"[^>]*checked', form)
      and re.search(r'value="Restroom Sanitation"[^>]*checked', form)
      and not re.search(r'value="Window Cleaning"[^>]*checked', form)
      and 'Mondays after close' in form and 'Filled in from the walkthrough' in form,
      'the contract quote opens with the size, how often, the services ticked and the scope')
with app.app_context(), tenancy.use_tenant(SLUG):
    full = cp.quote(3200, 'restaurant', 'weekly', ['restrooms'])
    db.session.remove()
check(f'value="{full["per_visit"]}"' in form and f'value="{full["monthly"]}"' in form,
      f'with a starting price from the calculator (${full["per_visit"]} a visit, ${full["monthly"]}/mo)')

# Floors only, an hour and a half: priced from the hours judged on site, not
# as a full clean of every square foot.
c.post(f'/find-leads/{wok["id"]}/walkthrough', base_url=HOST, data={
    'sqft': '3200', 'frequency': 'weekly', 'hours': '1.5', 'services': ['floors']})
with app.app_context(), tenancy.use_tenant(SLUG):
    by_hours = cp.quote(3200, 'restaurant', 'weekly', [], hours=1.5)
    db.session.remove()
form = c.get(f'/quotes/new?prospect_id={wok["id"]}', base_url=HOST).get_data(as_text=True)
check(by_hours['per_visit'] < full['per_visit'] and f'value="{by_hours["per_visit"]}"' in form,
      f'floors only, 1.5 hours a visit, starts at ${by_hours["per_visit"]} -- not the full-clean ${full["per_visit"]}')
with app.app_context(), tenancy.use_tenant(SLUG):
    check(cp.quote(3200, 'restaurant', 'weekly', []) == cp.quote(3200, 'restaurant', 'weekly', [], hours=None),
          'and without judged hours the calculator prices exactly as before')
    db.session.remove()

# A restaurant's kitchen: the floor degreased and the line cleaned, on the
# checklist, in the price and on the quote.
c.post(f'/find-leads/{wok["id"]}/walkthrough', base_url=HOST, data={
    'sqft': '3200', 'frequency': 'weekly',
    'services': ['floors', 'floor_degrease', 'kitchen_equipment']})
page = c.get(f'/find-leads/{wok["id"]}', base_url=HOST).get_data(as_text=True)
check('Kitchen floor — degrease' in page and 'fryers, grills, cooktops' in page,
      'the checklist offers kitchen floor degreasing and the fryers, grills and cooktops')
with app.app_context(), tenancy.use_tenant(SLUG):
    kitchen = cp.quote(3200, 'restaurant', 'weekly', ['floor_degrease', 'kitchen_equipment'])
    plain = cp.quote(3200, 'restaurant', 'weekly', [])
    db.session.remove()
form = c.get(f'/quotes/new?prospect_id={wok["id"]}', base_url=HOST).get_data(as_text=True)
check(kitchen['per_visit'] > plain['per_visit'] and f'value="{kitchen["per_visit"]}"' in form,
      f'and are priced: ${kitchen["per_visit"]} a visit against ${plain["per_visit"]} for the floors alone')
check(re.search(r'value="Kitchen Floor Degreasing"[^>]*checked', form)
      and re.search(r'value="Kitchen Equipment Degreasing \(Fryers, Grills, Cooktops\)"[^>]*checked', form),
      'the quote lists them ticked')
import html as _html
svc = [_html.unescape(v) for v in re.findall(r'name="services" value="([^"]+)"', form)]
check(svc[:3] == ['Floor Care (Sweep & Mop)', 'Kitchen Floor Degreasing',
                  'Kitchen Equipment Degreasing (Fryers, Grills, Cooktops)'],
      f'and a restaurant quote shows kitchen services first, not apartment lines ({svc[:3]})')

print('\n14. A Sales login: the call list and nothing else')
check(('sales', 'Sales — finding and working leads only') in rbac.ROLE_OPTIONS
      and rbac.has_permission('sales', 'prospect.work')
      and not any(rbac.has_permission('sales', perm) for perm in (
          'booking.read', 'lead.read', 'messages.read', 'messages.send', 'finance.manage', 'settings.manage')),
      'Sales holds prospecting and nothing else: no bookings, website leads, inbox or money')
team_page = c.get('/logins/', base_url=HOST).get_data(as_text=True)
check('value="sales"' in team_page, 'the owner can give a login the Sales role')
sc = role_client('sales')
r = sc.get('/', base_url=HOST)
check(r.status_code == 302 and r.headers.get('Location', '').endswith('/find-leads/'),
      f'signing in lands on Find leads, not a refusal ({r.status_code} {r.headers.get("Location")})')
calls = sc.get('/find-leads/', base_url=HOST)
body = calls.get_data(as_text=True)
check(calls.status_code == 200 and '📞 Calls' in body and 'Add one' in body, 'Find leads opens')
check('href="/bookings' not in body and 'href="/messages' not in body and 'href="/money' not in body
      and 'href="/settings/business' not in body,
      'and the menu offers nothing else: no bookings, messages, money or settings')
for path in ('/bookings/', '/messages/', '/quotes/', '/commercial/', '/leads/', '/money/pnl'):
    st = sc.get(path, base_url=HOST).status_code
    check(st in (302, 403), f'{path} is closed to Sales ({st})')
r = sc.post('/find-leads/add', base_url=HOST, data={'business_name': 'Sales Found Deli', 'category': 'restaurant'})
deli = lead('Sales Found Deli')
check(deli is not None, 'Sales adds a lead by hand')
page = sc.get(f'/find-leads/{deli["id"]}', base_url=HOST).get_data(as_text=True)
check('Book walkthrough' in page and 'Log a call' in page and 'Email them' in page,
      'works it: logs calls, emails, books and records the walkthrough')
check('Contract quote' not in page and 'Home quote' not in page and '/messages/thread' not in page,
      'and is not offered the quote or the inbox, which are the owner\'s')
sc.post(f'/find-leads/{deli["id"]}/walkthrough', base_url=HOST, data={'sqft': '1800', 'frequency': 'weekly', 'services': ['floors']})
check(lead('Sales Found Deli')['next_action'] == 'Write and send the quote', 'the walkthrough Sales did is ready for the owner to quote')
check(sc.post(f'/find-leads/{deli["id"]}/delete', base_url=HOST).status_code == 403
      and lead('Sales Found Deli') is not None, 'but cannot delete leads')
with app.app_context(), tenancy.use_tenant(SLUG):
    agent = db.session.get(Prospect, deli['id']).agent
    db.session.remove()
check(agent == 'Sales', 'and a lead Sales adds is credited to them, for commission')

print('\n15. Sales is held to the module, and the work it does stays credited to it')
# Not in the permission matrix used to mean "let the route decide" -- and many
# older routes only ask whether somebody is signed in.
for path in ('/bookings/999999/delete', '/contractors/applications/999999/hire',
             '/bookings/clients/999999/delete'):
    st = sc.post(path, base_url=HOST).status_code
    check(st == 403, f'an unclassified back-office form is closed to Sales: {path} ({st})')
check(sc.get('/account', base_url=HOST).status_code in (200, 302)
      and sc.get('/account', base_url=HOST).status_code != 403,
      'while Sales can still manage its own login')
body = sc.get('/find-leads/?view=everyone', base_url=HOST).get_data(as_text=True)
check('/delete' not in body and '/delete' in c.get('/find-leads/?view=everyone', base_url=HOST).get_data(as_text=True),
      'and is not shown the delete button the owner gets')

with app.app_context(), tenancy.use_tenant(SLUG):
    p = db.session.get(Prospect, deli['id'])
    p.walkthrough = None
    db.session.commit()
    db.session.remove()
sc.post(f'/find-leads/{deli["id"]}/walkthrough', base_url=HOST,
        data={'sqft': '1800', 'frequency': '', 'services': ['floors']})
form = c.get(f'/quotes/new?prospect_id={deli["id"]}', base_url=HOST).get_data(as_text=True)
check(re.search(r'<option value="weekly"\s+selected', form),
      'a walkthrough with no frequency quotes weekly, the way it was priced -- not daily')

payload = '{"business_name": "Imported Taqueria", "category": "restaurant", "city": "Washington", "place_id": "pid-taq-1"}'
sc.post('/find-leads/import', base_url=HOST, data={'selected': ['pid-taq-1'], 'payload_pid-taq-1': payload})
with app.app_context(), tenancy.use_tenant(SLUG):
    taq = Prospect.query.filter_by(business_name='Imported Taqueria').first()
    taq_agent = taq.agent if taq else None
    db.session.remove()
check(taq is not None and taq_agent == 'Sales', f'a lead Sales imports from search is credited to them ({taq_agent})')

c.post(f'/commercial/convert/{deli["id"]}', base_url=HOST, data={
    'contact_name': 'Deli Owner', 'email': 'owner@deli.example', 'phone': '2025550188',
    'frequency': 'weekly', 'billing_type': 'monthly', 'billing_amount': '600'})
with app.app_context(), tenancy.use_tenant(SLUG):
    acct = CommercialAccount.query.filter_by(prospect_id=deli['id']).first()
    deli_agent = acct.agent if acct else None
    db.session.remove()
check(deli_agent == 'Sales', f'the owner making their lead an account keeps it credited to Sales ({deli_agent})')

with app.app_context(), tenancy.use_tenant(SLUG):
    tp = Prospect(business_name='Quoted Cafe', category='restaurant', status='interested',
                  stage='proposal', agent='Sales', phone='2025550177')
    db.session.add(tp)
    db.session.commit()
    q = CommercialQuote(company='Quoted Cafe', contact_name='Cafe Owner', email='cafe@quoted.example',
                        property_type='Restaurant / Food Service', frequency='weekly',
                        monthly_price=500, status='sent', token='tok-quoted-cafe', prospect_id=tp.id)
    db.session.add(q)
    db.session.commit()
    db.session.remove()
app.test_client().post('/quotes/view/tok-quoted-cafe/accept', base_url=HOST)
with app.app_context(), tenancy.use_tenant(SLUG):
    acct = CommercialAccount.query.filter_by(business_name='Quoted Cafe').first()
    cafe_agent = acct.agent if acct else None
    db.session.remove()
check(acct is not None and cafe_agent == 'Sales', f'and so does the quote being accepted ({cafe_agent})')

with app.app_context(), tenancy.use_tenant(SLUG):
    from models import Lead
    db.session.add(Lead(name='Deli Owner', email='owner@deli.example', quoted_price=987.65,
                        status='contacted', prospect_id=deli['id']))
    db.session.commit()
    db.session.remove()
page = sc.get(f'/find-leads/{deli["id"]}', base_url=HOST).get_data(as_text=True)
check('987.65' not in page and '1 home quote' in page,
      'Sales sees that a home quote exists, not what it was priced at')
check('987.65' in c.get(f'/find-leads/{deli["id"]}', base_url=HOST).get_data(as_text=True),
      'the owner still sees the price')
comm = c.get('/commissions/', base_url=HOST).get_data(as_text=True)
check('<option value="Sales"' in comm,
      'the commissions page offers Sales logins, not only the old "team" role')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Add a lead by hand, quote it from the lead, and talk to it — the call list keeps up.')
