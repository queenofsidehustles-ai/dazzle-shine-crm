"""Post-construction, sold in three sizes, priced without giving the dump away.

A builder's clean is not a big house clean. It is three phases — haul the debris
out, detail clean, come back once the dust settles — and which of them the
customer is buying is the thing that actually varies on the call. So there are
three services, and each is written as the one below it plus what that one
leaves out.

Two ways this loses money if it is got wrong, and both are what this file
guards. Debris removal is dump fees plus loads, which no bedroom multiplier can
predict, so it is a line she sets per job — and a discount must not come off it,
because that discount comes out of her pocket and goes to a landfill. And the
final phase is a second visit on a second day: uncapped, a builder's slipping
handover date turns one price into three trips.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/pc.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
import checklist_expand as ce
import pricing
import quoting
from app import create_app
from extensions import db
from models import Lead, Booking
from werkzeug.datastructures import MultiDict
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


print('\n1. Three rungs of one job, each dearer than the last')
mult = pricing.SERVICE_MULTIPLIERS_DEFAULTS
check(mult['postcon_clean'] < mult['postcon_final'] < mult['postcon_full'],
      'clean only < clean + final < full service')
check(mult['postcon_clean'] > mult['moveout'],
      'even the smallest rung prices above a move-out — drywall dust is not dirt')

print('\n2. A reference tells the three rungs apart')
check(ce.service_for('Post-Construction Detail Clean') == 'postcon_clean',
      '"Detail Clean" resolves to the bottom rung')
check(ce.service_for('Post-Construction Clean + Final Phase') == 'postcon_final',
      '"Clean + Final Phase" is not swallowed by the word "clean"')
check(ce.service_for('Post-Construction Full Service') == 'postcon_full',
      '"Full Service" resolves to the top rung')
check(ce.service_for('Post-Construction Cleaning') == 'postcon_clean',
      'and an unspecific one falls back to the base list rather than to nothing')
check(ce.service_for('Deep Cleaning') == 'deep',
      'the services that were here before still resolve')

print('\n3. The top rung spells out the whole job, down to standard')
from blueprints.workorders import DEFAULT_ITEMS
rows = ce.expand(DEFAULT_ITEMS['postcon_full'], DEFAULT_ITEMS.get)
texts = [r['text'] for r in rows]
check(not any(ce.reference_phrase(t) and ce.service_for(ce.reference_phrase(t))
              for t in texts),
      'no line is left as a pointer to another list')
check(any('debris' in t.lower() for t in texts), 'the haul-out is in it')
check(any('dust has settled' in t.lower() for t in texts), 'the return visit is in it')
check(any('drywall dust' in t.lower() for t in texts), 'the post-construction work is in it')
check(any('mop' in t.lower() for t in texts),
      f'and the standard work is spelled out too ({len(texts)} lines)')

print('\n4. Debris goes first, because doing it second is doing the room twice')
debris_at = min(i for i, t in enumerate(texts) if 'haul out' in t.lower())
clean_at = min(i for i, t in enumerate(texts) if 'drywall dust' in t.lower())
check(debris_at < clean_at, 'the site is cleared before it is detail cleaned')

with app.app_context():
    db.create_all()

    print('\n5. A discount comes off the cleaning, never off the dump fee')
    form = MultiDict({
        'name': 'Ray Okonkwo', 'email': 'ray@example.com', 'phone': '4075551212',
        'service_type': 'postcon_full', 'bedrooms': '3', 'bathrooms': '2',
        'price': '900', 'debris_fee': '350', 'debris_note': '2 loads + dump fee',
        'discount_amount': '100', 'discount_label': 'Repeat builder',
    })
    lead, err = quoting.handle_quote_form(form)
    check(err is None, f'the quote saved ({err})')
    check(float(lead.debris_fee) == 350.0, 'the haul-off is kept as its own figure')
    check(float(lead.quoted_price) == 1150.0,
          '$900 cleaning − $100 off + $350 debris = $1150, not $1125')
    check(float(lead.discount_amount) == 100.0, 'she gave away exactly the $100 she meant to')
    check(float(lead.quote_full_price) == 1250.0,
          'and the struck-through price differs from what they pay by the discount alone')

    print('\n6. The breakdown says which money is which')
    lines = quoting.price_breakdown(lead)
    check('Cleaning:  $900.00' in lines, 'cleaning named and priced')
    check('2 loads + dump fee:  $350.00' in lines, 'the haul-off named as she described it')
    check('Repeat builder:  −$100.00' in lines, 'the discount named')
    check(lines.strip().endswith('$1,150.00'.replace(',', '')), 'and it adds up to what they pay')

    print('\n7. A discount cannot eat more than the cleaning')
    form = MultiDict({
        'name': 'Over Discount', 'email': 'over@example.com',
        'service_type': 'postcon_full', 'bedrooms': '2', 'bathrooms': '1',
        'price': '400', 'debris_fee': '200',
        'discount_amount': '900', 'discount_label': 'Mistake',
    })
    over, err = quoting.handle_quote_form(form)
    check(err is None, 'it still saves')
    check(float(over.quoted_price) == 200.0,
          'the cleaning goes to zero and the $200 dump fee survives — she is never out of pocket')

    print('\n8. Square footage reaches the price it was always able to change')
    small = MultiDict({'name': 'Small', 'email': 'small@example.com',
                       'service_type': 'postcon_clean', 'bedrooms': '3',
                       'bathrooms': '2'})
    big = MultiDict({'name': 'Big', 'email': 'big@example.com',
                     'service_type': 'postcon_clean', 'bedrooms': '3',
                     'bathrooms': '2', 'sqft': '4000'})
    a, _ = quoting.handle_quote_form(small)
    b, _ = quoting.handle_quote_form(big)
    check(b.sqft == 4000, 'the number is recorded on the lead')
    check(float(b.quoted_price) > float(a.quoted_price),
          'and a 4,000 sq ft three-bed prices above a standard-size one')

    print('\n9. What the customer is told in writing')
    full = Lead.query.filter_by(email='ray@example.com').first()
    note = quoting.scope_note(full)
    check('within 7 days' in note, 'the return visit is capped, so a slipped handover is not three free trips')
    check('trades are off site' in note, 'and the price assumes the build is actually finished')

    clean_only = Lead(name='Just Clean', email='jc@example.com',
                      service_type='postcon_clean', quoted_price=400)
    db.session.add(clean_only); db.session.commit()
    note = quoting.scope_note(clean_only)
    check('no return visit' in note, 'the bottom rung says plainly there is no second visit')
    check('not included' in note,
          'and that clearing the site is the builder\'s job — the reason this rung is cheaper')
    check(quoting.scope_note(Lead(name='X', email='x@e.com', service_type='standard')) == '',
          'a standard clean says none of this')

    print('\n10. An accepted quote carries the whole price onto the job')
    booking = quoting.accept_quote(full, preferred_date='2026-09-25',
                                   address='9 Build Ln', city='Orlando')
    check(float(booking.price) == 1150.0, 'the booking is for the price they were quoted, debris included')
    check(booking.service_type == 'postcon_full', 'as the service they actually bought')
    check(booking.sqft == full.sqft, 'and the size it was priced against comes with it')

    print('\n11. A price that is not a number is refused, not guessed at')
    bad = MultiDict({'name': 'Bad', 'email': 'bad@example.com',
                     'service_type': 'postcon_full', 'bedrooms': '3',
                     'bathrooms': '2', 'debris_fee': 'two loads'})
    _, err = quoting.handle_quote_form(bad)
    check(err is not None and 'debris' in err.lower(),
          'and the message says which box she needs to look at')

print('\n🎉 Three rungs, priced apart, with the dump fee kept out of the discount.')
