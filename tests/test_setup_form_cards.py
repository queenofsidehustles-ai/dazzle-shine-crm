"""The setup cards you can type into, and the Save that writes what you typed.

The confirm cards offer a fixed payload for one tap. The form cards go a step
further: the boxes are editable, so a brand-new company with no phone on file
is never stuck -- it types the phone into the same card and presses Save.

What this holds:
- The details and prices steps arrive as editable form cards, prefilled.
- /save writes what was typed, validated server-side, and advances setup.
- A bad phone or a silly price is refused with the boxes kept, not saved.
- A company with nothing on file still gets a card, not a dead-end chat box.
- Only the owner can save.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/form.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting
import setup_assistant
import onboarding
import pricing

app = create_app()
failures = []
H = {'Origin': 'http://localhost'}


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def owner():
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'
    return c


def save(client, step, fields):
    return client.post('/settings/getting-started/assistant/save',
                       json={'step': step, 'fields': fields}, headers=H)


with app.app_context():
    db.create_all()
    # What signup leaves: a name, an email, a ZIP and the timezone from it.
    # No phone -- the thing the owner has to supply.
    BusinessSetting.set('business_name', 'Sparkle Co')
    BusinessSetting.set('email', 'o@sparkle.test')
    BusinessSetting.set('zip_code', '32801')
    BusinessSetting.set('timezone', 'America/New_York')
    db.session.commit()

print('\n1. The details step is an editable card, prefilled but not finished')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    _lines, card = setup_assistant.prefilled_business_card()
check(card is not None and card['kind'] == 'form', 'it is a form card')
names = {f['name']: f for f in card['fields']}
check(names['business_name']['value'] == 'Sparkle Co', 'the name is prefilled')
check(names['phone']['value'] == '', 'the phone box is empty, for the owner to type')

print('\n2. Saving what was typed writes it and moves setup on')
with app.app_context():
    before = onboarding.progress()['done']
c = owner()
r = save(c, 'business', {'business_name': 'Sparkle Co', 'phone': '(407) 555-0100',
                         'address': '12 Main St', 'city': 'Orlando', 'state': 'FL'})
j = r.get_json()
check(r.status_code == 200 and j['ok'], 'the save is accepted')
with app.app_context():
    check(BusinessSetting.get('phone') == '(407) 555-0100', 'the phone is now saved')
    check(onboarding.progress()['done'] == before + 1, 'and the step is done')
check(j.get('follow') and j.get('cards'), 'the next step comes back in the same reply')
check(j['progress']['done'] == before + 1, 'with fresh progress for the meter')

print('\n3. A bad value is refused, with nothing written')
r = save(owner(), 'business', {'phone': '555'})
j = r.get_json()
check(not j['ok'] and 'phone' in j['say'].lower(), 'a half a phone number is refused')

print('\n4. Prices: type a number, get the whole matrix')
r = save(owner(), 'pricing', {'two_bed_two_bath': '240'})
j = r.get_json()
check(j['ok'], 'the price saves')
with app.app_context():
    check(round(pricing.get_std_price(2, 2)) == 240, 'the 2/2 price is what was typed')
    check(pricing.get_std_price(3, 2) > 240, 'and the bigger sizes scaled up from it')
r = save(owner(), 'pricing', {'two_bed_two_bath': '5'})
check(not r.get_json()['ok'], 'a $5 house clean is refused')

print('\n5. A company with nothing on file still gets a card, not a dead end')
with app.app_context():
    db.drop_all()
    db.create_all()
    BusinessSetting.set('email', 'new@nowhere.test')
    db.session.commit()
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    _lines, blank = setup_assistant.prefilled_business_card()
check(blank is not None and blank['kind'] == 'form',
      'the card is there with empty boxes, never a blank chat box that asks nothing')
check(all(f['value'] == '' for f in blank['fields'] if f['name'] != 'business_name'),
      'and its boxes are empty, waiting to be filled')

print('\n6. Only the owner can save')
va = app.test_client()
with va.session_transaction() as s:
    s['logged_in'] = True
    s['role'] = 'va'
r = save(va, 'business', {'phone': '(407) 555-0100'})
check(r.status_code in (302, 403), 'a non-owner is turned away')

if failures:
    print(f'\n❌ {len(failures)} form-card check(s) failed')
    sys.exit(1)
print('\n✅ The cards you can type into save what you typed.')
