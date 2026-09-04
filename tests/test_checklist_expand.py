"""A deep clean's checklist lists the standard items, not a reference to them.

The seeded deep-clean checklist opens with "Everything in Standard Cleaning",
and move-out with "Everything in Deep Cleaning". Fine shorthand for somebody who
has done a hundred standard cleans; useless to a cleaner whose first job is a
deep clean, who gets a pointer to a list she has never seen and cannot open —
and the twelve things it stands for are the twelve most basic parts of the job.

It fails silently: one line where twelve should be, and the way you find out is
a customer saying the floors were not mopped.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/cl.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
import checklist_expand as ce
from app import create_app
from extensions import db
from models import Booking, Staff, JobChecklist, ChecklistTemplate
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


FAKE = {
    'standard': ['Dust surfaces', 'Mop floors', 'Empty trash'],
    'deep': ['Everything in Standard Cleaning', 'Scrub baseboards', 'Clean blinds'],
    'moveout': ['Everything in Deep Cleaning', 'Inside oven', 'Inside fridge'],
}

print('\n1. A reference becomes the items it points at')
rows = ce.expand(FAKE['deep'], FAKE.get)
texts = [r['text'] for r in rows]
check('Everything in Standard Cleaning' not in texts, 'the pointer itself is gone')
check('Dust surfaces' in texts and 'Mop floors' in texts, 'the standard items are really there')
check('Scrub baseboards' in texts, "and the deep clean's own items too")
check(len(texts) == 5, f'3 standard + 2 deep = 5 lines (got {len(texts)})')

print('\n2. The inherited part is labelled so it can be folded')
groups = {r['group'] for r in rows}
check('Everything in Standard Cleaning' in groups, 'the block keeps the name it came from')
check(None in groups, "and the deep clean's own items are not inside it")

print('\n3. It follows the chain more than one level')
rows = ce.expand(FAKE['moveout'], FAKE.get)
texts = [r['text'] for r in rows]
check('Dust surfaces' in texts, 'move-out reaches all the way to standard')
check('Scrub baseboards' in texts, 'through deep')
check(len(texts) == 7, f'3 + 2 + 2 = 7 lines (got {len(texts)})')

print('\n4. A loop cannot hang the job')
loopy = {'deep': ['Everything in Move-Out'], 'moveout': ['Everything in Deep Cleaning']}
rows = ce.expand(loopy['deep'], loopy.get)
check(len(rows) >= 1, 'two templates pointing at each other still return')

print('\n5. A reference to nothing is left as written, not dropped')
rows = ce.expand(['Everything in Standard Cleaning', 'Real item'], lambda s: None)
check([r['text'] for r in rows] == ['Everything in Standard Cleaning', 'Real item'],
      'an odd line beats a silently shorter checklist')

print('\n6. Sections come out in order, ungrouped items standing alone')
secs = ce.grouped(ce.expand(FAKE['deep'], FAKE.get))
check(secs[0][0] == 'Everything in Standard Cleaning', 'the folded block is first')
check(len(secs[0][1]) == 3, 'holding its three items')
check(secs[1][0] is None and 'Scrub baseboards' in secs[1][1], 'then the loose items')

with app.app_context():
    db.create_all()
    for name, key, items in (('Standard Cleaning', 'standard', FAKE['standard']),
                             ('Deep Cleaning', 'deep', FAKE['deep'])):
        import json as _j
        db.session.add(ChecklistTemplate(name=name, service_type=key,
                                         items=_j.dumps(items)))
    ana = Staff(name='Ana Ruiz', is_active=True, email='ana@example.com')
    db.session.add(ana); db.session.commit()

    print('\n7. A real work order stores the expanded list')
    b = Booking(service_type='deep', name='Deep Job', address='1 St', price=300,
                status='confirmed', assigned_cleaner='Ana Ruiz',
                preferred_date='2026-09-20')
    db.session.add(b); db.session.commit()
    from blueprints.workorders import create_and_send_workorder
    # A request context: the work-order email builds an absolute checklist URL.
    with app.test_request_context('/', base_url='https://crm.example.com'):
        create_and_send_workorder(b)
    cl = JobChecklist.query.filter_by(booking_id=b.id).first()
    check(cl is not None, 'the work order was created')
    lines = cl.get_items()
    # create_app seeds the real templates, so the expansion resolves against
    # those rather than this test's stand-ins — which is the real behaviour.
    check(not any(ce.reference_phrase(l) and ce.service_for(ce.reference_phrase(l))
                  for l in lines),
          'no line is still a pointer to another list')
    check(any('mop' in l.lower() for l in lines),
          f'and the standard work is spelled out ({len(lines)} lines)')
    check(len(lines) > len(FAKE['deep']),
          'the list is longer than the deep template alone')

    print('\n8. The cleaner sees it, folded')
    c = app.test_client()
    page = c.get(f'/workorders/checklist/{cl.token}').get_data(as_text=True)
    check('cl-section' in page, 'rendered as a foldable section')
    check('items</span>' in page or 'items<' in page, 'the fold says how many it holds')

    print('\n9. Tick boxes keep unique numbers across the fold')
    import re
    idx = [int(n) for n in re.findall(r'toggleItem\((\d+),', page)]
    check(idx == list(range(len(cl.get_items()))),
          f'indexes run 0..{len(cl.get_items()) - 1} with no repeats')

    print('\n10. A checklist made before sections still works')
    import json as _j
    old = JobChecklist(booking_id=b.id, template_name='Old', token='old-tok',
                       items=_j.dumps(['Plain one', 'Plain two']))
    db.session.add(old); db.session.commit()
    check(old.get_items() == ['Plain one', 'Plain two'], 'plain strings still read')
    check(c.get('/workorders/checklist/old-tok').status_code == 200, 'and the page still serves')

print('\n🎉 A cleaner is handed the whole job, folded so it can be read.')
