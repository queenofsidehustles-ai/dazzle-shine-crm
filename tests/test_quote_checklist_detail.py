"""A quote has to say what the money buys, not point at a list.

Checklists are written as one rung plus the next. A move-out template opens with
a single line — "All deep clean tasks" — which stands for the deep list, which
opens with "All standard clean tasks" and another twelve. Between cleaners that
is good shorthand. In a quote it means someone weighing four hundred dollars for
a move-out was shown eight lines, one of which was a cross-reference to a
document they have never seen and cannot open.

Work orders learned to spell the chain out when a cleaner's first deep clean
turned out to be twelve invisible basics. Quotes were still sending the
shorthand. Same module, same chain, so the list the customer is promised and the
list the cleaner works from cannot describe two different jobs.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/qc.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (True, 'stub')
def _capture(to_email=None, to_name=None, subject=None, html=None, *a, **k):
    SENT.append({'to': to_email, 'subject': subject, 'html': html or ''})
    return True, 'stub'
notifications.send_email = _capture
from app import create_app
from extensions import db
from models import Lead, ChecklistTemplate
import quoting

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. The chain is followed all the way down')
    moveout = quoting.service_checklist('moveout')
    deep = quoting.service_checklist('deep')
    standard = quoting.service_checklist('standard')
    check(len(moveout) > 25, f'a move-out quote lists {len(moveout)} tasks, not eight')
    check(not any('all deep clean' in i.lower() or 'everything in' in i.lower()
                  for i in moveout), 'with no line left pointing at another list')
    check(set(standard) <= set(deep) <= set(moveout),
          'each service contains the one below it, task for task')
    check(len(moveout) == len(set(moveout)), 'and nothing is listed twice')

    print('\n2. Order survives — the work reads in the order it happens')
    check(moveout[0] == standard[0], 'the standard basics come first')
    check('walkthrough' in moveout[-1].lower(),
          'and the final walkthrough is still last')

    print('\n3. The quote email spells it out')
    SENT.clear()
    c.post('/leads/quote/new', data={
        'name': 'Phone Lead', 'email': 'lead@example.com', 'phone': '4075551234',
        'service_type': 'moveout', 'bedrooms': '3', 'bathrooms': '2',
        'price': '425'}, follow_redirects=True)
    lead = Lead.query.filter_by(email='lead@example.com').first()
    body = SENT[-1]['html']
    missing = [i for i in moveout if i not in body]
    check(not missing, f'every one of the {len(moveout)} tasks is in the email ({missing[:2]})')
    check(f'{len(moveout)} tasks' in body,
          'headed with the count, so the price has something to sit against')
    check('All deep clean tasks' not in body, 'and the shorthand is not sent to a customer')

    print('\n4. And so does the page they land on')
    page = c.get(f'/quote/{lead.quote_token}').get_data(as_text=True)
    check(all(i in page for i in moveout), 'the booking page lists the same tasks')
    check(f'{len(moveout)} tasks' in page, 'with the same count')
    check('All deep clean tasks' not in page, 'and no shorthand here either')

    print('\n5. She can still take individual items off')
    # The point of expanding is that a promise can now be edited task by task.
    # Unticking used to mean dropping a whole rung of the service at once.
    keep = [i for i in moveout if 'oven' not in i.lower()]
    c.post('/leads/quote/new', data={
        'name': 'No Oven', 'email': 'nooven@example.com', 'phone': '4075559999',
        'service_type': 'moveout', 'bedrooms': '3', 'bathrooms': '2',
        'price': '400', 'checklist': keep}, follow_redirects=True)
    picky = Lead.query.filter_by(email='nooven@example.com').first()
    items = quoting.checklist_for(picky)
    check(not any('oven' in i.lower() for i in items),
          'the oven line is gone because she took it off')
    check(len(items) == len(moveout) - 1,
          'and everything else she agreed to is still promised')

    print('\n6. A quote saved before this still opens in full')
    # Every quote already on the system holds the shorthand it was saved with.
    old = Lead(name='Older Quote', email='old@example.com', service_type='moveout',
               quoted_price=400.0, quote_token='tok-old',
               quote_checklist='["All deep clean tasks", "Clean inside oven"]')
    db.session.add(old); db.session.commit()
    items = quoting.checklist_for(old)
    check(len(items) > 20, f'it expands on the way out too ({len(items)} tasks)')
    check('Clean inside oven' in items, 'keeping the line she typed herself')
    check(not any('all deep clean' in i.lower() for i in items),
          'and resolving the one she did not')

    print('\n7. A business with no templates still describes the work')
    # service_checklist read templates only, so an instance that had never
    # opened the Checklists page sent quotes with no "what's included" at all.
    ChecklistTemplate.query.delete()
    db.session.commit()
    fallback = quoting.service_checklist('moveout')
    check(len(fallback) > 15, f'the built-in list stands in ({len(fallback)} tasks)')
    check(not any('all deep clean' in i.lower() for i in fallback),
          'expanded the same way')

print('\n🎉 A quote describes the whole job, not a reference to it.\n')
