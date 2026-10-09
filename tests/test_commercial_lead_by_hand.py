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
    full = commercial_pricing.quote(4000, 'restaurant', 'weekly', ['restrooms', 'breakroom'])['monthly']
    med_bare = commercial_pricing.quote(4000, 'medical_office', 'weekly', [])['monthly']
    med_full = commercial_pricing.quote(4000, 'medical_office', 'weekly', ['disinfection'])['monthly']
    db.session.remove()
check(ticked == {'restrooms', 'breakroom'}, 'the kitchen and restrooms start ticked on the calculator')
check(bare < full, f'but unticking them takes them off the price ({bare} < {full})')
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

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Add a lead by hand, quote it from the lead, and talk to it — the call list keeps up.')
