"""A quote can show a discount, instead of just quietly being a smaller number.

Giving somebody a friends-and-family price meant typing the discounted figure
into the price box. The customer was then told "$232" with nothing to say it had
ever been $290 — so the discount bought no goodwill, because they could not see
they had been given anything, and left no record, because nothing said one had
been given. It never reached the booking either, so Job Economics reported no
discounting on jobs that were plainly discounted.

The rule protected here: `quoted_price` still means what they pay. Everything
that already read it — the email, the drips, the booking it becomes — is
untouched. The new columns say what it would have been and why it isn't.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/qd.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Lead, Booking, DiscountCode
import quoting
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


class Form(dict):
    """Stands in for a submitted form — getlist included."""
    def getlist(self, k):
        v = self.get(k, [])
        return v if isinstance(v, list) else [v]


def quote(**over):
    f = Form({'name': 'Aunt May', 'email': 'may@example.com', 'phone': '4075550199',
              'service_type': 'deep', 'bedrooms': '3', 'bathrooms': '2',
              'frequency': 'one_time', 'price': '290'})
    f.update(over)
    return quoting.handle_quote_form(f)


with app.app_context():
    db.create_all()
    db.session.add_all([
        DiscountCode(code='FAMILY20', discount_type='percent', discount_value=20,
                     is_active=True),
        DiscountCode(code='TWENTYOFF', discount_type='fixed', discount_value=20,
                     is_active=True),
        DiscountCode(code='DEAD', discount_type='percent', discount_value=50,
                     is_active=False),
        DiscountCode(code='USEDUP', discount_type='percent', discount_value=50,
                     is_active=True, max_uses=1, times_used=1),
    ])
    db.session.commit()

    print('\n1. No discount behaves exactly as before')
    lead, err = quote()
    check(err is None, 'the quote goes through')
    check(float(lead.quoted_price) == 290.0, 'they pay the price she typed')
    check(lead.quote_full_price is None, 'no full price recorded — there is nothing to show')
    check(lead.has_discount is False, 'and the quote says it has no discount')

    print('\n2. A percent code comes off, and the full price is kept')
    lead, err = quote(discount_code='FAMILY20', discount_label='Friends & Family')
    check(err is None, 'accepted')
    check(float(lead.quote_full_price) == 290.0, 'the $290 is remembered')
    check(float(lead.discount_amount) == 58.0, '20% of $290 is $58 off')
    check(float(lead.quoted_price) == 232.0, 'they pay $232')
    check(lead.discount_display == 'Friends & Family', 'and it is called what she called it')

    print('\n3. A fixed code, and a lower-case code, both work')
    lead, err = quote(discount_code='twentyoff')
    check(err is None and float(lead.quoted_price) == 270.0, '$20 off $290 = $270')
    check(lead.discount_display == 'TWENTYOFF', 'unnamed, it falls back to the code')

    print('\n4. A code that cannot be honoured is refused, not silently ignored')
    _, err = quote(discount_code='DEAD')
    check(err and 'inactive' in err.lower(), 'an inactive code is refused with a reason')
    _, err = quote(discount_code='USEDUP')
    check(err and 'limit' in err.lower(), 'a used-up code is refused')
    _, err = quote(discount_code='NOPE')
    check(err and 'NOPE' in err, 'an unknown code names itself')
    check(float(Lead.query.filter_by(email='may@example.com').first().quoted_price) == 270.0,
          'and none of those changed the price on the existing quote')

    print('\n5. A one-off amount with a reason, for the ones that were never a code')
    lead, err = quote(discount_amount='40', discount_label='Neighbour')
    check(err is None and float(lead.quoted_price) == 250.0, '$40 off $290 = $250')
    check(lead.discount_code is None, 'no code involved')
    check(lead.discount_display == 'Neighbour', 'named on the quote')

    print('\n6. A discount can never exceed the price')
    lead, err = quote(discount_amount='500', discount_label='Oops')
    check(float(lead.quoted_price) == 0.0, 'the price floors at $0')
    check(float(lead.discount_amount) == 290.0, 'and the discount is capped at the price')

    print('\n7. Re-quoting replaces the old discount rather than keeping it')
    lead, err = quote(discount_code='FAMILY20', discount_label='Friends & Family')
    check(float(lead.quoted_price) == 232.0, 'discounted again')
    lead, err = quote()
    check(lead.quote_full_price is None and float(lead.quoted_price) == 290.0,
          "last week's reason is gone from this week's price")

    print('\n8. The customer sees the working on their quote page')
    lead, err = quote(discount_code='FAMILY20', discount_label='Friends & Family')
    c = app.test_client()
    page = c.get(f'/quote/{lead.quote_token}').get_data(as_text=True)
    check('$290.00' in page, 'the full price is on the page')
    check('line-through' in page, 'struck through')
    check('Friends &amp; Family' in page or 'Friends & Family' in page, 'the reason is named')
    check('$58.00' in page, 'the saving is stated')
    check('$232.00' in page, 'and what they actually pay')

    print('\n9. Booking through it carries the discount onto the job')
    before = DiscountCode.query.filter_by(code='FAMILY20').first().times_used or 0
    booking = quoting.accept_quote(lead, preferred_date='2026-09-20')
    check(float(booking.price) == 232.0, 'the job is priced at what they were quoted')
    check(booking.discount_code == 'FAMILY20', 'the code is on the booking')
    check(float(booking.discount_amount) == 58.0,
          'and the $58 given away is recorded, so the books can see it')
    after = DiscountCode.query.filter_by(code='FAMILY20').first().times_used or 0
    check(after == before + 1, 'the code counts as used now they have booked, not when quoted')

    print('\n10. Quoting alone never spends a limited code')
    lead2, _ = quote(email='other@example.com', discount_code='FAMILY20')
    check((DiscountCode.query.filter_by(code='FAMILY20').first().times_used or 0) == after,
          'a quote that has not been accepted leaves the count alone')

print('\n🎉 Discounts are visible to the customer and recorded in the books.')
