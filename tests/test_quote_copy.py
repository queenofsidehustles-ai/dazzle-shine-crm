"""Sending the same quote to somebody who is not the lead.

On a post-construction job the person who rings is the builder and the person
who pays is often the homeowner. Both need the number in writing, and before
this the only way to reach the second one was to re-send the quote form against
their address -- which moved the lead's email, and with it the lead's own quote
link, onto a person who had never asked for a quote.

A copy must therefore change nothing: not the address on the lead, not the
price, and not the sent-at stamp the follow-up drip hangs off. Chasing the
homeowner with "still thinking about your quote?" emails is exactly the failure
this has to avoid.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/qc.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SENT = []
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to_email=None, to_name=None, subject='', html='', **k: (
    SENT.append({'to': to_email, 'name': to_name, 'subject': subject, 'html': html}),
    (True, 'stub'))[1]

from app import create_app
from extensions import db
from models import Lead, BusinessSetting
import quoting
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Dazzle & Shine Maids')
    BusinessSetting.set('crm_base', 'https://crm.example.com')
    db.session.commit()

    print('\n1. A builder rings and is quoted for a post-construction clean')
    lead = quoting.quote_lead(
        name='Jessica Hale', email='jessica@buildco.example',
        phone='4075551234', service_type='postcon_full',
        bedrooms='4', bathrooms='3', price=1850.00)
    db.session.commit()
    ok, err = quoting.send_quote(lead)
    check(ok, f'the quote goes out to her{"" if ok else " -- " + err}')
    check(SENT[-1]['to'] == 'jessica@buildco.example', 'addressed to the builder')
    quoted_at = lead.quote_sent_at
    check(quoted_at is not None, 'and the moment she was quoted is stamped')
    link = quoting.quote_url(lead)
    check(lead.quote_token in link, 'she has her own quote link')

    print('\n2. The homeowner behind her gets a copy')
    before = len(SENT)
    ok, err = quoting.send_quote_copy(
        lead, 'owner@example.com', 'Marcus Webb')
    check(ok, f'the copy sends{"" if ok else " -- " + err}')
    check(len(SENT) == before + 1, 'exactly one more email went out')
    copy = SENT[-1]
    check(copy['to'] == 'owner@example.com', 'to the homeowner')
    check(copy['name'] == 'Marcus Webb', 'opening with his name, not hers')
    check('1850.00' in copy['html'], 'at the same price she was quoted')
    check(lead.quote_token in copy['html'],
          'carrying the same quote link, not a fresh calculator')

    print('\n3. The lead is left exactly as it was')
    lead = Lead.query.get(lead.id)
    check(lead.email == 'jessica@buildco.example',
          "the builder's address is still the one on the lead")
    check(lead.name == 'Jessica Hale', 'and so is her name')
    check(lead.quoted_price == 1850.00, 'the price did not move')
    check(lead.quote_sent_at == quoted_at,
          'and the sent-at stamp was not touched, so the drip still '
          'counts from when SHE was quoted')
    check(Lead.query.filter_by(email='owner@example.com').first() is None,
          'copying somebody in does not make them a lead of their own')

    print('\n4. A typo is caught before it is sent')
    before = len(SENT)
    ok, err = quoting.send_quote_copy(lead, 'owner@example', '')
    check(not ok, 'an address with no domain suffix is refused')
    check('does not look right' in err, 'and says so in words she can act on')
    check(len(SENT) == before, 'nothing was sent')
    ok, err = quoting.send_quote_copy(lead, '   ', '')
    check(not ok, 'so is an empty box')

    print('\n5. There has to be a quote to copy')
    unquoted = Lead(name='Ray Oakes', email='ray@example.com',
                    service_type='standard', status='new')
    db.session.add(unquoted); db.session.commit()
    before = len(SENT)
    ok, err = quoting.send_quote_copy(unquoted, 'someone@example.com', '')
    check(not ok, 'a lead that was never quoted has nothing to copy')
    check('no quote on this lead' in err, 'and the message says that, not a crash')
    check(len(SENT) == before, 'and nothing went out')

    print('\n6. The button on the lead page does the same thing')
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    page = c.get(f'/leads/{lead.id}')
    check(page.status_code == 200, 'the lead page opens')
    body = page.get_data(as_text=True)
    check('Send a Copy' in body, 'with a Send a Copy button on it')
    check(link in body, 'and the quote link shown for copying by hand')

    before = len(SENT)
    r = c.post(f'/leads/{lead.id}/send-copy',
               data={'copy_email': 'second@example.com', 'copy_name': 'Dana'},
               follow_redirects=True)
    check(r.status_code == 200, 'posting the form works')
    check(len(SENT) == before + 1, 'one copy went out')
    check(SENT[-1]['to'] == 'second@example.com', 'to the address typed in')
    lead = Lead.query.get(lead.id)
    check(lead.email == 'jessica@buildco.example',
          'and the lead still belongs to the builder')
    check(lead.quote_sent_at == quoted_at, 'with her drip still untouched')

    print('\n7. A lead with no quote shows no share card')
    body = c.get(f'/leads/{unquoted.id}').get_data(as_text=True)
    check('Send a Copy' not in body,
          'nothing to share, so nothing offered -- the generic booking link '
          'is not this lead\'s quote')

print('\n🎉 A quote can reach the person paying without moving the lead.')
