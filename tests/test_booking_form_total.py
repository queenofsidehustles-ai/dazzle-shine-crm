"""The New Booking form's running total stopped working, silently.

The script found its form with document.querySelector('form') — the FIRST form
in the document. That was fine until a brand switcher appeared in the sidebar,
which sits above the content block. From then on every field lookup returned
null, reading .value off null threw before the fetch could happen, and the whole
running total died: the box read $0.00 whatever was typed, and typing a price
changed nothing because the listeners were bound to the wrong form.

Nothing caught it. The price maths is server-side and correct — this was a
client-side wiring failure, invisible to every test that only exercises routes.
"""
import os, sys, tempfile, re
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/bf.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. The page still has more than one form, so the bug is still possible')
    html = c.get('/bookings/new').get_data(as_text=True)
    check(html.count('<form') > 1,
          'there is more than one form on the page — the sidebar has its own')
    first = html.index('<form')
    booking = html.index('id="booking-form"')
    check(first < booking,
          'and one of them still comes BEFORE the booking form in the document')

    print('\n2. The total targets the booking form by id, not by position')
    script = html[html.index('rt-total'):]
    check("getElementById('booking-form')" in html,
          'the script looks the form up by id')
    check("querySelector('form')" not in html,
          "and never takes whichever form happens to be first")

    print('\n3. A missing field costs that field, not the whole total')
    check('|| {}).value' in html,
          'field reads are guarded, so one absent input cannot kill the running total')

    print('\n4. The prefill script actually renders')
    # It used to sit after {% endblock %}, which in a child template puts it
    # outside every block, so Jinja threw it away and the remembered service
    # type was never applied.
    check('data-prefill' in html, 'the prefill code is present in the rendered page')
    check(html.index('data-prefill]') < html.index("getElementById('booking-form')"),
          'and runs before the first total, so that total reflects the real choices')

    print('\n5. The server side was never the problem — prove it still adds up')
    r = c.get('/bookings/price-preview?service_type=deep&bedrooms=3&bathrooms=2'
              '&extras=Laundry&frequency=one_time&cleaning_price=390&lead_fee=')
    d = r.get_json()
    check(r.status_code == 200, 'the preview endpoint answers')
    check(d['cleaning'] == 390.0, 'a typed price is used exactly as typed')
    check(d['total'] == 390.0, 'and with no lead fee the customer pays that')

    r2 = c.get('/bookings/price-preview?service_type=deep&bedrooms=3&bathrooms=2'
               '&extras=Laundry&frequency=one_time&cleaning_price=390&lead_fee=25')
    check(r2.get_json()['total'] == 415.0, 'a lead fee is added on top for the customer')

    r3 = c.get('/bookings/price-preview?service_type=deep&bedrooms=3&bathrooms=2'
               '&frequency=one_time&cleaning_price=&lead_fee=')
    check(r3.get_json()['cleaning'] > 0,
          'leaving the price blank falls back to the calculated price')

    print('\nAll booking-form total checks passed.')
