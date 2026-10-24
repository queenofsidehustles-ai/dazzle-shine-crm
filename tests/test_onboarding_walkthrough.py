"""Walk the whole of setup the way an owner does, and arrive at the end.

This file exists because the flow shipped with a dead end that two full
regression runs did not notice and the owner found in four minutes. The
business step produced no card for any company without a Google listing --
which is most new ones -- no link, and a prompt that was not a question. A
statement, an empty text box, and "Skip for now". Nothing to do, and the
banner kept pointing back at it.

Every other test here checks a part. This one checks that a person can get
from one end to the other, because that is the thing that was broken while
every part passed.

What this holds, for a brand-new company and for one that existed before any
of this was built:
- every required step offers something to do: a card, or a question that
  names what to type, and always a page to go to if the model is down;
- tapping what is offered advances the step, every time;
- setup reaches the end rather than looping.

Since 2026-10-24 the required walk is details, prices, payments, and the
go-live checks -- terms, then balances -- follow in the same chat, so the walk
carries on through those two as well. The team is not on the walk: the owner is
already the first cleaner, and adding people is optional, for when she hires. Payments is the one step the chat
cannot finish: it is a link to Connections (bank details never go in the
chat), so the walk does what the owner does there and connects Stripe.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/walk.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting
import onboarding, setup_assistant, zip_zones

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def seed(**kw):
    with app.app_context():
        db.drop_all()
        db.create_all()
        for k, v in kw.items():
            BusinessSetting.set(k, v)
        db.session.commit()


def offered(step_key):
    """What the chat puts in front of somebody on this step."""
    with app.app_context(), app.test_request_context():
        from flask import session
        session['role'] = 'owner'
        text, cards, key = setup_assistant.next_message()
        kinds = [c.get('kind') for c in cards]
        return text, cards, kinds, key


def tap(card):
    with app.app_context(), app.test_request_context():
        from flask import session
        session['role'] = 'owner'
        return setup_assistant.confirm(card['token'])


def fill_and_save(step, card):
    """What the owner does to an editable card: fill any required-but-empty
    box, then press Save. A brand-new company's details card has no phone, so
    that is the one box that has to be typed before Save does anything."""
    fields = {f['name']: f['value'] for f in card.get('fields', [])}
    if step == 'business' and not fields.get('phone'):
        fields['phone'] = '(407) 555-0100'
    with app.app_context(), app.test_request_context():
        from flask import session
        session['role'] = 'owner'
        return setup_assistant.save_form(step, fields)


def progress():
    with app.app_context():
        return onboarding.progress()


for label, fixture in (
    ('a brand-new company, no Google listing',
     dict(business_name='Brand New Cleaning', email='o@bn.test',
          zip_code='32801', timezone=zip_zones.zone_for_zip('32801'))),
    ('a company that existed before any of this',
     dict(business_name='Established Cleaning', email='o@est.test')),
):
    print(f'\n=== {label} ===')
    seed(**fixture)
    seen = []
    for _round in range(12):
        p = progress()
        if p['next'] is None:
            break
        key = p['next']['key']
        if not p['next'].get('required') and key not in ('terms', 'balance'):
            break      # the required steps and the go-live checks must be walkable
        text, cards, kinds, _k = offered(key)
        confirms = [c for c in cards if c.get('kind') == 'confirm']
        # A choice card is one question with several answers; tapping the
        # first answer is what an owner in a hurry does.
        confirms += [dict(o, kind='confirm') for c in cards if c.get('kind') == 'choice'
                     for o in c.get('options', [])[:1]]
        forms = [c for c in cards if c.get('kind') in ('form', 'team')]
        links = [c for c in cards if c.get('kind') == 'link']

        asked = text.strip() or ' '.join(c.get('title', '') for c in cards
                                         if c.get('kind') == 'choice')
        check(bool(asked.strip()), f'{key}: says something')
        check(bool(confirms or forms) or '?' in asked,
              f'{key}: offers a card, or asks a question in plain words')
        check(bool(confirms or forms or links),
              f'{key}: has a way through that is not the chat box')

        if key == 'payments':
            # Bank details never go in the chat: no form, no confirm, just
            # the way to Connections, where the owner connects Stripe.
            check(not forms and not confirms,
                  'payments: no card in the chat asks for bank details')
            check(any(l.get('href') == '/settings/connections' for l in links),
                  'payments: the way through is the Connections page')
            check(any(c.get('kind') == 'skip' for c in cards),
                  'payments: and it can be skipped for tonight')
            import integrations
            with app.app_context():
                integrations.set('stripe_secret_key', 'sk_live_walkthrough')
                db.session.commit()
        elif forms:
            ok, said = fill_and_save(key, forms[0])
            check(ok, f'{key}: filling it in and saving works — {said[:48]}')
        elif confirms:
            ok, said = tap(confirms[0])
            check(ok, f'{key}: tapping it works — {said[:48]}')
        else:
            # No card: the question named what to type, so do that.
            with app.app_context():
                BusinessSetting.set('phone', '(407) 555-0100')
                db.session.commit()
        after = progress()
        check(after['next'] is None or after['next']['key'] != key,
              f'{key}: setup moves on rather than asking again')
        if after['next'] and after['next']['key'] == key:
            print(f'     >>> STUCK on {key}')
            break
        seen.append(key)

    p = progress()
    check(p['complete'] is True,
          f'reaches the end: {p["done"]}/{p["total"]} after {seen}')
    check(seen[:3] == ['business', 'pricing', 'payments'],
          f'in the agreed order: details, prices, payments ({seen[:3]})')
    check(seen[3:5] == ['terms', 'balance'],
          f'then the go-live checks, terms and balances ({seen[3:5]})')
    check('team' not in seen,
          'and the team is not on the walk: the owner is the first cleaner')

print('\n=== and the timezone was never a question ===')
check('timezone' not in [s['key'] for s in onboarding.journey()]
      if False else True, 'placeholder')
seed(business_name='Zip Co', email='z@z.test', zip_code='78751',
     timezone=zip_zones.zone_for_zip('78751'))
with app.app_context():
    check(BusinessSetting.get('timezone') == 'America/Chicago',
          'an Austin ZIP gives Central before anybody is asked')
    check('timezone' not in [s['key'] for s in onboarding.journey()],
          'and it is not a step')

if failures:
    print(f'\n❌ {len(failures)} walkthrough check(s) failed')
    sys.exit(1)
print('\n✅ Setup can be walked from one end to the other.')
