"""Every "Show me" guide still points at something real.

howto.py's guides are read to paying customers and walked on the real screen:
each step names the page it happens on and the `data-tour` element to light
up. A template that drops or renames that attribute leaves the tour pointing
at nothing, and nothing else would notice -- so this opens every step's page,
as the owner, and looks for the attribute.
"""
import os, re, sys, secrets, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/howto_guides.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'ok')
notifications.send_sms = lambda *a, **k: (True, 'ok')

from app import create_app
from extensions import db
from models import Booking, Client, Staff
import howto

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'

    # What the record pages need in the normal case: an unpaid, one-off,
    # residential job with nobody on it yet, and a cleaner who has not set up
    # her sign-in.
    client = Client(name='Dana Whitfield', email='dana@example.com', phone='+12565550100')
    db.session.add(client)
    db.session.commit()
    booking = Booking(service_type='standard', name='Dana Whitfield', email='dana@example.com',
                      phone='+12565550100', status='confirmed', price=180.0,
                      preferred_date='2026-11-12', preferred_time='10:00 AM',
                      address='12 Elm St', city='Huntsville', bedrooms=3, bathrooms=2,
                      frequency='one_time', estimated_hours=3.0, client_id=client.id)
    cleaner = Staff(name='Maya Johnson', is_active=True, email='maya@example.com',
                    phone='+12565550111', agreement_token=secrets.token_urlsafe(32))
    db.session.add_all([booking, cleaner])
    db.session.commit()

    # The commercial pages: a business on the call list, due a first call
    # today, with no walkthrough or account yet (so Book walkthrough and
    # Make them an account are offered); an account to book a job for; and a
    # draft quote to review. Hiring: an applicant who has finished the video
    # interview and is not yet approved.
    import brands
    from scheduling import local_today
    from models import CommercialAccount, CommercialQuote, ContractorApplication, Prospect
    lead = Prospect(business_name='Riverside Dental', category='office', phone='2565550123',
                    email='office@riverside.example', city='Huntsville', status='new', stage='new',
                    source='manual', brand=brands.COMMERCIAL, next_action='First call',
                    next_action_date=local_today().isoformat())
    account = CommercialAccount(business_name='Oak Tower Offices', contact_name='Pat Lee',
                                email='pat@oaktower.example', category='office', frequency='weekly',
                                billing_type='monthly', billing_amount=800, status='active', source='manual')
    quote = CommercialQuote(company='Oak Tower Offices', contact_name='Pat Lee', email='pat@oaktower.example',
                            property_type='Office', frequency='weekly', price_per_visit=200,
                            token=secrets.token_urlsafe(32), status='draft')
    applicant = ContractorApplication(name='Rosa Diaz', email='rosa@example.com', phone='+12565550122',
                                      status='new', interview_status='completed')
    db.session.add_all([lead, account, quote, applicant])
    db.session.commit()

    RECORD = {r'^/bookings/\d+$': f'/bookings/{booking.id}',
              r'^/contractors/team/\d+$': f'/contractors/team/{cleaner.id}',
              r'^/find-leads/\d+$': f'/find-leads/{lead.id}',
              r'^/find-leads/call(/\d+)?$': '/find-leads/call',
              r'^/commercial/convert/\d+$': f'/commercial/convert/{lead.id}',
              r'^/commercial/\d+$': f'/commercial/{account.id}',
              r'^/commercial/\d+/book$': f'/commercial/{account.id}/book',
              r'^/quotes/\d+/review$': f'/quotes/{quote.id}/review',
              r'^/contractors/applications/\d+$': f'/contractors/applications/{applicant.id}',
              r'^/admin/interviews/\d+$': f'/admin/interviews/{applicant.id}'}

    print('\n1. The guides themselves are sound')
    problems = howto.validate()
    check(problems == [], f'howto.validate() finds nothing wrong {problems or ""}')
    keys = [g['key'] for g in howto.GUIDES]
    check(len(keys) == len(set(keys)), 'every guide key is used once')
    for g in howto.GUIDES:
        n = len(g['steps'])
        check(2 <= n <= 6, f'{g["key"]}: {n} steps (2 to 6)')

    def url_for_step(st):
        page = st.get('page') or ''
        if page in RECORD:
            return RECORD[page]
        # Kept whole: a view picked by query string (/find-leads/?view=find)
        # is a different screen on the same path.
        return st.get('start') or '/'

    pages = {}

    def get(url):
        if url not in pages:
            r = c.get(url)
            pages[url] = (r.status_code, r.get_data(as_text=True), r.headers.get('Location'))
        return pages[url]

    print('\n2. Every step\'s "Take me there" opens a page (no redirect)')
    for g in howto.GUIDES:
        for i, st in enumerate(g['steps'], 1):
            code, _body, loc = get(st['start'])
            check(code == 200, f'{g["key"]} step {i}: {st["start"]} -> {code}'
                               + (f' (to {loc})' if loc else ''))

    print('\n3. Every highlighted element is on its page')
    for g in howto.GUIDES:
        for i, st in enumerate(g['steps'], 1):
            if not st.get('target'):
                continue
            url = url_for_step(st)
            check(re.search(st['page'], url.split('?')[0]) is not None,
                  f'{g["key"]} step {i}: {url} is a page the step matches')
            code, body, _loc = get(url)
            check(code == 200 and f'data-tour="{st["target"]}"' in body,
                  f'{g["key"]} step {i}: data-tour="{st["target"]}" on {url}')

    print('\n4. The tour script can fetch each guide')
    for g in howto.GUIDES:
        r = c.get(f'/help/tour/{g["key"]}.json')
        check(r.status_code == 200 and r.get_json().get('key') == g['key'],
              f'/help/tour/{g["key"]}.json serves the guide')

if failures:
    print(f'\n❌ {len(failures)} failure(s)')
    sys.exit(1)
print('\n✅ All how-to guide checks passed')
