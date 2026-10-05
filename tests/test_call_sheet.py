"""Working a call list one business at a time.

The list view answers "who is there". It was also being asked "who am I
ringing now", which it did badly: the script in one drawer, the fields in
another, and nothing carrying you from one call to the next.

Most calls end without a conversation, so the sheet opens with three buttons
and no form. Two are one click and the next business loads.

What is worth protecting here:

  * every outcome the scheduler knows how to handle can actually be recorded
  * a call that nobody answered still counts as a call made
  * hanging up never leaves a prospect with nothing scheduled -- except the
    one outcome where that is the point
  * the caller can overrule the suggested date, and that wins
  * the free plan cannot reach any of it
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/callsheet.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from app import create_app
from extensions import db
from models import Prospect, BusinessSetting
from blueprints import places_finder as bp
import prospecting
from scheduling import local_today

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


class Form(dict):
    def get(self, k, d=''):
        return dict.get(self, k, d)


with app.app_context():
    db.create_all()
    BusinessSetting.set('plan', 'scale')
    BusinessSetting.set('plan_status', 'active')
    db.session.commit()

    print('1. Every outcome the scheduler knows can be written down')
    missing = [k for k in prospecting.RULES if k not in Prospect.STATUS_LABELS]
    check(not missing,
          f'no outcome drives a follow-up it cannot record (missing: {missing})')

    print('\n2. A call is recorded and the next one scheduled')
    today = local_today().isoformat()
    for name, outcome, expect_date in (
            ('Lakeside', 'no_answer', True),
            ('Harbour Point', 'voicemail', True),
            ('Civic Offices', 'send_info', True),
            ('Mercy Clinic', 'not_interested', True),
            ('Quiet Co', 'do_not_contact', False)):
        p = Prospect(business_name=name, category='property_manager',
                     phone='4075550000', status='new', stage='new')
        db.session.add(p)
        db.session.commit()
        before = p.attempts or 0
        bp._log_call(p, Form(log_note='said no'), outcome)
        p.called_at = datetime.utcnow()
        db.session.commit()
        if expect_date:
            check(bool(p.next_action and p.next_action_date),
                  f'{outcome}: hanging up left something scheduled')
            check(p.next_action_date >= today, f'{outcome}: and it is not in the past')
        else:
            check(not p.next_action_date,
                  f'{outcome}: the one outcome that schedules nothing')
        check((p.attempts or 0) == before + 1, f'{outcome}: counted as an attempt')
        check(p.notes and 'said no' in p.notes, f'{outcome}: what they said was kept')

    print('\n3. The caller overrules the suggestion')
    p = Prospect(business_name='Override Ltd', category='realtor', status='new', stage='new')
    db.session.add(p); db.session.commit()
    bp._log_call(p, Form(next_action='Ring the facilities manager',
                         next_action_date='2027-03-01'), 'callback')
    db.session.commit()
    check(p.next_action == 'Ring the facilities manager' and p.next_action_date == '2027-03-01',
          'what the person who made the call said beats the table')

    print('\n4. What was learned is kept as fields, not prose')
    p = Prospect(business_name='Fields Ltd', category='office', status='new', stage='new')
    db.session.add(p); db.session.commit()
    bp._log_call(p, Form(contact='Dana Reed', email='dana@fields.com',
                         renewal='March 2027'), 'send_info')
    db.session.commit()
    check(p.contact_name == 'Dana Reed', 'the person')
    check(p.email == 'dana@fields.com', 'the email you cannot post a note to')
    check(p.renewal_note == 'March 2027',
          'and when their contract ends — the reason a no is worth keeping')

    print('\n5. A booked walkthrough is the date they agreed, on the calendar')
    p = Prospect(business_name='Harbour Group', category='property_manager',
                 status='new', stage='new')
    db.session.add(p); db.session.commit()
    bp._log_call(p, Form(walkthrough_date='2026-11-12', contact='Ray'), 'interested')
    db.session.commit()
    check(p.next_action_date == '2026-11-12',
          'the date they agreed, not the table\'s "book it in two days"')
    check(p.next_action == 'Walkthrough', 'and it says what it is')

    # The jobs calendar draws walkthroughs and nothing else: a walkthrough is
    # somewhere she has to be, a callback is a four-minute task with no time.
    walk = (p.next_action or '').strip().lower().startswith('walkthrough')
    check(walk, 'so the jobs calendar will draw it, beside the cleans')

    cb = Prospect(business_name='Callback Co', category='office', status='new', stage='new')
    db.session.add(cb); db.session.commit()
    bp._log_call(cb, Form(), 'callback')
    db.session.commit()
    check(bool(cb.next_action_date), 'a callback is still scheduled')
    check(not (cb.next_action or '').lower().startswith('walkthrough'),
          'but it is not a walkthrough, so it stays off the jobs calendar')

    print('\n6. The free plan cannot reach it')
    BusinessSetting.set('plan', 'solo')
    db.session.commit()
    import entitlements as E
    E._clear_cache()
    check(E.can('lead_finder') is False, 'Solo has no lead finder')
    src = open('blueprints/places_finder.py', encoding='utf-8').read()
    for route in ("def call_sheet", "def log_call"):
        head = src[:src.index(route)]
        guard = head.rsplit('@places_finder_bp.route', 1)[-1]
        check("@requires_plan('lead_finder')" in guard, f'{route} is gated')

    print('\n7. The right script for the business being rung')
    from models import Script
    for cat, title in (
            ('outbound', '🏢 Cold Call Opening + Discovery — Commercial (offices · daycares · medical)'),
            ('outbound', '🏘️ Cold Call Opening + Discovery — [Your Company] (apartments · property managers)'),
            ('outbound', '🏘️ Cold Call Opening + Discovery — Bright Clean (apartments · property managers)'),
            ('outbound', '🔑 Cold Call Opening + Discovery — Realtors'),
            ('general', '🔑 Gatekeeper — Getting to the Decision-Maker'),
            ('general', '📵 Voicemail Scripts That Actually Get Callbacks'),
            ('objection', 'Objection — "I Already Have a Cleaner"'),
            ('closing', 'Closing — Pencil You In')):
        db.session.add(Script(category=cat, title=title, content='Say this.'))
    db.session.commit()

    office = Prospect(business_name='Civic Offices', category='office', status='new', stage='new')
    flats = Prospect(business_name='Harbour Flats', category='apartment', status='new', stage='new')
    db.session.add_all([office, flats]); db.session.commit()

    import brands
    sec = dict(bp._scripts_for(office, brands.COMMERCIAL))
    titles = [r['title'] for r in sec.get('What to say', [])]
    check(any('offices' in t for t in titles),
          'an office gets the offices opening, not every opening there is')
    check(not any('Realtors' in t for t in titles), 'and not the realtor one')

    sec = dict(bp._scripts_for(flats, brands.COMMERCIAL))
    titles = [r['title'] for r in sec.get('What to say', [])]
    check(any('apartments' in t for t in titles), 'a block of flats gets the apartments one')
    check(not any('[Your Company]' in t for t in titles),
          "and the version she has made her own, not the seeded placeholder")

    labels = [label for label, _ in bp._scripts_for(office, brands.COMMERCIAL)]
    check('If it goes to voicemail' in labels and 'If they push back' in labels,
          'with the moments a call goes sideways each behind their own heading')
    check(labels[0] == 'What to say',
          'and what to say when they pick up first, since that is the one that is open')

    none_known = Prospect(business_name='Odd Co', category='other', status='new', stage='new')
    db.session.add(none_known); db.session.commit()
    sec = dict(bp._scripts_for(none_known, brands.COMMERCIAL))
    check(len(sec.get('What to say', [])) > 0,
          'a business nothing matches gets every opening, not a blank panel')

    print('\n8. The page actually renders')
    # The gap that let a NameError reach production: every check above
    # exercised the helper that writes a call down, and none of them ever
    # asked the view to draw itself. A route that cannot render is not a
    # subtle failure -- it is the whole screen, and the tests were green.
    BusinessSetting.set('plan', 'scale')
    db.session.commit()
    E._clear_cache()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['logged_in'] = True
        sess['role'] = 'owner'

    r = c.get('/find-leads/call')
    check(r.status_code == 200, 'the call sheet renders with businesses waiting')

    r = c.get('/find-leads/?view=today')
    check(r.status_code == 200, 'and so does the list it is started from')
    r = c.get('/find-leads/?view=month')
    check(r.status_code == 200, 'and the month')
    r = c.get('/find-leads/?view=everyone')
    check(r.status_code == 200, 'and everyone')
    r = c.get('/find-leads/?view=pipeline')
    check(r.status_code in (200, 302), 'and an old bookmark still goes somewhere')

print('\n9. A morning that ends, and old links that still work')
import blueprints.places_finder as _bp
src = open('blueprints/places_finder.py', encoding='utf-8').read()
check(_bp.DAILY_STINT == 20, 'a sitting is twenty calls, not an endless queue')
check("request.args.get('more')" in src,
      'and "keep going" is one click — a finish line, not a cap')
check("{'pipeline': 'everyone', 'contacts': 'everyone'}" in src,
      'the two merged tabs still resolve, so old links and bookmarks work')
tpl = open('templates/admin/find_leads.html', encoding='utf-8').read()
check('overdue</strong>' not in tpl,
      'a backlog is not shouted at her in red every time she opens the page')
check(tpl.count("('today', '📞 Calls'") == 1 and "'pipeline', '📊" not in tpl,
      'three tabs, not five')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
