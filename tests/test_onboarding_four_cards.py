"""Three cards and two go-live checks, one tap each, and the software does the rest.

Setup used to be six steps, 217 words of prompts before a single answer, a
1,339-word terms document presented as required reading, and two steps that
sent the owner off to another page. Somebody would leave, and be right to.

The thing that made it unnecessary: everything already has a working default.
The price matrix ships with numbers, the terms ship as a draft that is already
in force, the timezone falls back to New York. A business that never finishes
setup is not an unconfigured system -- it is one quoting real customers with
somebody else's prices under a contract nobody read, in the wrong timezone.

So setup is not filling in blanks. It is confirming the handful of defaults
that are wrong for this particular business, and the software fills in
everything it can work out by itself.

Since 2026-10-24 the required three are details, prices and payments -- the
owner is already the first cleaner, so there is no team step to do first. Terms
and balances keep their one-tap cards, straight after, as go-live checks.

What this holds:
- Three required steps, and the timezone is not one of them: the ZIP decides.
- Every required step arrives with its card already built, with no model call
  -- except payments, which is a link to Connections: bank details are never
  typed into the chat.
- Payments is required but skippable -- amber, then red on a clock that
  starts when the other two are done, never blocking the rest.
- A business too new for a Google listing gets the same card, not a failure.
"""
import os, sys, tempfile
from datetime import datetime, timedelta
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/four.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting
import onboarding, setup_assistant, zip_zones, business_lookup, automations

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


with app.app_context():
    db.create_all()
    # What signup now leaves behind: a name, an email, a ZIP, and the
    # timezone it worked out from the ZIP.
    BusinessSetting.set('business_name', 'Sparkle Cleaning')
    BusinessSetting.set('email', 'dana@sparkle.test')
    BusinessSetting.set('zip_code', '78751')
    BusinessSetting.set('timezone', zip_zones.zone_for_zip('78751'))
    db.session.commit()

print('\n1. The timezone was never a question')
check(zip_zones.zone_for_zip('78751') == 'America/Chicago',
      'an Austin ZIP is Central, worked out rather than asked')
with app.app_context():
    keys = [s['key'] for s in onboarding.journey() if s.get('required')]
check(keys == ['business', 'pricing', 'payments'],
      f'three required steps, and timezone is not one of them: {keys}')
with app.app_context():
    check(BusinessSetting.get('timezone') == 'America/Chicago',
          'and it is already set before the owner sees anything')

print('\n2. Every step arrives with its card, built without the model')
with app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    # The required steps, the optional team and the two go-live checks. Payments'
    # prompt is longer -- it carries the "skip it for tonight" way out -- so it
    # is held to two short sentences' worth rather than one line.
    for key in ('business', 'team', 'pricing', 'terms', 'balance'):
        text = setup_assistant.STEP_PROMPTS[key]
        # The business question depends on whether the boxes came prefilled,
        # so it is a callable. Both forms have to be short.
        forms = [text(True), text(False)] if callable(text) else [text]
        for form in forms:
            check(len(form.split()) <= 25,
                  f'{key}: the question is one line ({len(form.split())} words)')
        # The business step always arrives with an editable card, so both the
        # prefilled and the blank wording point at the Save button on screen.
        check(not callable(text) or 'Save' in text(False),
              f'{key}: the prompt points at the card rather than a dead end')
    pay_q = setup_assistant.STEP_PROMPTS['payments']
    check(len(pay_q.split()) <= 50, f'payments: the question is short ({len(pay_q.split())} words)')
    check('bank details stay with you' in pay_q and 'skip' in pay_q.lower(),
          'payments: it reassures about bank details and says it can wait')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    session['user_name'] = 'Dana Owner'
    team = setup_assistant.team_card()
    check(len(team) == 1 and team[0]['kind'] == 'team' and team[0]['step'] == 'team',
          'the team comes up as one card, not one per cleaner')
    check('me' not in team[0],
          'with no row for the owner: she is already the first cleaner')
    check('already on the team' in team[0]['note'],
          'and the card says so')
    check('emailed' in team[0]['note'],
          'and it says nobody is emailed until the owner chooses')
    pay_link = setup_assistant.STEP_LINKS.get('payments')
    check(pay_link and pay_link[1] == '/settings/connections',
          'payments is a link to Connections, never a card asking for bank details')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    _l, price = setup_assistant.price_card()
    check(price is not None and price['kind'] == 'form',
          'the prices come up as an editable card, already filled in')
    check(price['fields'][0]['name'] == 'two_bed_two_bath'
          and price['fields'][0]['value'],
          'with the 2/2 price in a box the owner can type over')
    check('$' in price['lines'][0], f"and show the number: {price['lines'][0]}")
    _l, terms = setup_assistant.terms_card()
    check(terms is not None and len(terms['lines']) == 4,
          'the terms are four lines, not thirteen hundred words')
    # Accepting the card marks the terms reviewed without showing them, so its
    # summary must promise what the terms do: 24 hours to report a problem
    # (it said 48, against the terms' and every confirmation's 24).
    import customer_terms
    window = [l for l in terms['lines'] if 'Tell us within' in l]
    check(window and '24 hours' in window[0] and 'within 24 hours' in customer_terms.DEFAULT_TERMS,
          f'the summary gives the same window as the terms ({window[0] if window else "-"})')
    both = setup_assistant.balance_cards()
    check(len(both) == 1 and both[0]['kind'] == 'choice'
          and len(both[0]['options']) == 2,
          'balances are one card with two answers, because it is one question')

print('\n3. A business too new to be listed is not a failure')
check(business_lookup.find('Brand New Cleaning', '') == {},
      'no ZIP, nothing found, nothing raised')
check(business_lookup._score('Sparkle Cleaning', {'business_name': 'Mighty Mops'}) == 0,
      'and somebody else’s listing never matches')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    lines, card = setup_assistant.prefilled_business_card()
    check(card is not None and card['kind'] == 'form',
          'the details arrive as an editable card, never a blank dead end')
    check({f['name'] for f in card['fields']} >= {'business_name', 'phone', 'address'},
          'with boxes for the details customers see')
    check(any('Sparkle Cleaning' in l for l in lines) if lines else True,
          'the card shows what we do know')
    check(any('Central' in l for l in lines) if lines else True,
          'including the timezone, as a word rather than a zone name')

print('\n4. Payments is required but skippable, and gets louder')
with app.app_context():
    p = onboarding.progress()
    pay = next(s for s in onboarding.journey() if s['key'] == 'payments')
check(pay.get('required') is True and pay.get('urgent') is True,
      'payments is required now, and still flagged urgent')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    setup_assistant.skip('payments')
    still = next(s for s in onboarding.progress()['steps'] if s['key'] == 'payments')
    skipped = 'payments' in setup_assistant.skipped()
    BusinessSetting.set(setup_assistant.SKIPPED_KEY, '')
    db.session.commit()
check(skipped and still['done'] is False,
      'it can be skipped for tonight, and skipping it is "not now", never "done"')
check(p['payments'] == 'amber', 'it is amber before setup is even finished')
with app.app_context():
    BusinessSetting.set('ready_at',
                        (datetime.utcnow() - timedelta(days=4)).isoformat(timespec='seconds'))
    db.session.commit()
    check(onboarding.payments_state() == 'red',
          'and red once it has been put off for three days')

print('\n5. Finishing the three is being able to trade')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    # Start the payments clock afresh: it is stamped by the other three.
    BusinessSetting.set('ready_at', '')
    BusinessSetting.set('phone', '(512) 555-0133')
    BusinessSetting.set('pricing_reviewed', '1')
    db.session.commit()
    p = onboarding.progress()
    check(p['done'] == 2 and p['complete'] is False
          and p['next_required']['key'] == 'payments',
          f"two of three, and payments is what is left ({p['done']}/{p['total']})")
    check((BusinessSetting.get('ready_at') or '').strip() != '',
          'the payments clock starts once the other two are done')
    check(p['payments'] in ('amber', 'red'),
          'with payments being asked for, because it is not done')
    ok, _said = setup_assistant.accept_terms({'accepted': '1'})
    check(ok, 'the terms card still accepts them, as a go-live check')
    ok, _said = setup_assistant.set_balance_mode({'mode': 'auto'})
    check(ok and automations.is_enabled('charge-balances'),
          'and the balance card really switches charging on')
    check(onboarding.progress()['complete'] is False,
          'terms and balances do not finish setup while payments is outstanding')
    import integrations
    integrations.set('stripe_secret_key', 'sk_live_fourcards')
    db.session.commit()
    p = onboarding.progress()
check(p['complete'] is True and p['done'] == p['total'] == 3,
      f"three of three, and able to trade ({p['done']}/{p['total']})")
check(p['payments'] == '', 'and the payments bar goes quiet once it is connected')
check(p['next'] is not None, 'and something left to offer, one at a time')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Four cards, one tap each, and the ZIP did the rest.')
