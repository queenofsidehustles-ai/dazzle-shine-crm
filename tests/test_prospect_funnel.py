"""The call list, turned into a funnel.

It used to hold a status and free-text notes: nothing said what to do next or
when, and the list sorted by the day a business was imported. So a prospect
called on Monday and told "try me next week" was indistinguishable from one
nobody had ever rung, and both sat below whatever was imported most recently.
"""
import os, sys, tempfile
from datetime import date, datetime, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/pf.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
sent = []
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to, name, subject, html, **k: (
    sent.append({'to': to, 'subject': subject, 'html': html}) or (True, 'stub'))
from app import create_app
from extensions import db
from models import Prospect, BusinessSetting
import prospecting
app = create_app()

# PLAN FOR THIS TEST. A fresh database starts on the free plan, which allows two
# cleaners and sends no texts -- correct for a brand-new signup, and not what
# this file is about. Say which plan is being exercised rather than leaving it
# to a default that will change again.
with app.app_context():
    from models import BusinessSetting as _BS
    from extensions import db as _db
    _BS.set('plan', 'scale')
    _BS.set('plan_status', 'active')
    _db.session.commit()
import entitlements as _ent
_ent._clear_cache()

TODAY = date.today().isoformat()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def plus(n):
    return (date.today() + timedelta(days=n)).isoformat()


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. A no-answer schedules its own callback')
    p = Prospect(business_name='Mila Realty', category='property_manager',
                 phone='4075698899', status='new', stage='new')
    db.session.add(p); db.session.commit()
    c.post(f'/find-leads/{p.id}/status', follow_redirects=True, data={
        'mode': 'log', 'status': 'no_answer', 'log_note': 'left voicemail'})
    p = Prospect.query.get(p.id)
    check(p.next_action_date == plus(2), f'called back in 2 days (got {p.next_action_date})')
    check(p.stage == 'working', 'and it moved from New into Working')
    check(p.attempts == 1, 'the attempt was counted')
    check('left voicemail' in (p.notes or ''), 'and what happened is in the notes')

    print('\n2. Five unanswered attempts stops the calling instead of looping')
    for _ in range(4):
        c.post(f'/find-leads/{p.id}/status', follow_redirects=True,
               data={'mode': 'log', 'status': 'no_answer'})
    p = Prospect.query.get(p.id)
    check(p.attempts == 5, 'five attempts logged')
    check(p.stage == 'nurture', 'it moved itself to Nurture rather than calling forever')
    check('email' in (p.next_action or '').lower(), f'and suggests the last email ({p.next_action})')

    print('\n3. Interested books the walkthrough; a no closes the file')
    keen = Prospect(business_name='Parkside Management', category='property_manager',
                    status='new', stage='new')
    nope = Prospect(business_name='Nope Property', category='property_manager',
                    status='new', stage='new')
    db.session.add_all([keen, nope]); db.session.commit()
    c.post(f'/find-leads/{keen.id}/status', follow_redirects=True,
           data={'mode': 'log', 'status': 'interested'})
    c.post(f'/find-leads/{nope.id}/status', follow_redirects=True,
           data={'mode': 'log', 'status': 'not_interested'})
    keen, nope = Prospect.query.get(keen.id), Prospect.query.get(nope.id)
    check(keen.stage == 'interested' and keen.next_action_date == plus(2),
          'a yes gets a walkthrough in 2 days')
    check(nope.stage == 'lost' and not nope.next_action_date,
          'a no is closed with nothing scheduled — it stops taking up room')

    print('\n4. What the caller actually agreed beats the suggestion')
    c.post(f'/find-leads/{keen.id}/status', follow_redirects=True, data={
        'mode': 'log', 'status': 'called',
        'next_action': 'Walk the building with Dana',
        'next_action_date': plus(9)})
    keen = Prospect.query.get(keen.id)
    check(keen.next_action == 'Walk the building with Dana' and keen.next_action_date == plus(9),
          'the typed-in step and date are kept, not overwritten by the rule')

    print('\n5. Today shows what is due and hides what is not')
    html = c.get('/find-leads/').get_data(as_text=True)
    check('Parkside Management' not in html, 'a prospect due in 9 days is not in the way')
    check('Nope Property' not in html, 'and neither is a dead one')
    soon = Prospect(business_name='Due Today Co', status='called', stage='working',
                    next_action='Follow-up call', next_action_date=TODAY)
    late = Prospect(business_name='Overdue Co', status='called', stage='working',
                    next_action='Follow-up call', next_action_date=plus(-6))
    db.session.add_all([soon, late]); db.session.commit()
    html = c.get('/find-leads/').get_data(as_text=True)
    check('Due Today Co' in html and 'Overdue Co' in html, 'due and overdue both show')
    check(html.index('Overdue Co') < html.index('Due Today Co'), 'oldest first — overdue at the top')
    check('overdue' in html, 'and overdue is called out as such')

    print('\n6. Details from the call become fields, not just prose')
    c.post(f'/find-leads/{soon.id}/status', follow_redirects=True, data={
        'mode': 'log', 'status': 'called', 'contact': 'Dana Reyes, Facilities',
        'email': 'dana@duetoday.com', 'renewal': 'March 2027'})
    soon = Prospect.query.get(soon.id)
    check(soon.contact_name == 'Dana Reyes, Facilities', 'the contact is a field now')
    check(soon.email == 'dana@duetoday.com', 'so is the email — Places never has one')
    check(soon.renewal_note == 'March 2027', 'and the renewal date, which is why a no is worth keeping')

    print('\n7. Snoozing does not fake a phone call')
    before = soon.attempts
    c.post(f'/find-leads/{soon.id}/snooze', data={'days': 30}, follow_redirects=True)
    soon = Prospect.query.get(soon.id)
    check(soon.next_action_date == plus(30), 'pushed out a month')
    check(soon.attempts == before, 'without inventing an attempt that never happened')

    print('\n8. An outreach email sends, logs itself and sets the follow-up')
    sent.clear()
    r = c.post(f'/find-leads/{soon.id}/email', data={
        'email': 'dana@duetoday.com', 'subject': 'cleaning your property',
        'body': 'Hi Dana,\n\nTwenty minutes to walk the building?'}, follow_redirects=True)
    check(len(sent) == 1, 'one email went out')
    check(sent[0]['to'] == 'dana@duetoday.com', 'to the address on the record')
    check('Twenty minutes' in sent[0]['html'], 'carrying what was typed')
    soon = Prospect.query.get(soon.id)
    check(soon.last_emailed_at is not None, 'the send is stamped on the prospect')
    check(soon.next_action_date == plus(4), 'and it earns a follow-up four days out')
    check('Emailed' in (soon.notes or ''), 'with a line in the notes saying so')

    print('\n9. Nothing can be emailed into a void')
    blank = Prospect(business_name='No Email Co', status='new', stage='new')
    db.session.add(blank); db.session.commit()
    sent.clear()
    c.post(f'/find-leads/{blank.id}/email', data={'subject': 'x', 'body': 'y'},
           follow_redirects=True)
    check(not sent, 'a prospect with no address does not silently send nowhere')

    print('\n10. Contacts and CSV hold everything collected')
    html = c.get('/find-leads/?view=contacts').get_data(as_text=True)
    check('dana@duetoday.com' in html and 'Overdue Co' in html, 'the contacts view lists them all')
    r = c.get('/find-leads/export.csv')
    body = r.get_data(as_text=True)
    check(r.headers['Content-Type'].startswith('text/csv'), 'the export is a CSV')
    check('call-list-' in r.headers.get('Content-Disposition', ''), 'and downloads with a dated name')
    check('dana@duetoday.com' in body and 'March 2027' in body,
          'carrying the email and the renewal date')
    # Parsed rather than split on newlines: a call note spans several lines and
    # CSV quotes it, which is exactly what a spreadsheet expects.
    import csv as _csv, io as _io
    rows = list(_csv.reader(_io.StringIO(body)))
    check(len(rows) == Prospect.query.count() + 1,
          f'one row per business plus the header (got {len(rows)})')
    check(rows[0][:3] == ['Business', 'Category', 'Stage'], 'with named columns')
    multiline = [r for r in rows[1:] if '\n' in r[-1]]
    check(multiline, 'and a multi-line call history survives inside one cell')

    print('\n11. Prospects from before the funnel are not left behind')
    # A row as the migration leaves it: the new columns exist and are empty,
    # while status and notes carry everything that was known before.
    old = Prospect(business_name='Legacy Co', status='called')
    db.session.add(old); db.session.commit()
    db.session.execute(db.text(
        'UPDATE prospect SET stage=NULL, attempts=NULL, next_action=NULL, '
        'next_action_date=NULL WHERE id=:i'), {'i': old.id})
    db.session.commit()
    db.session.expire_all()
    html = c.get('/find-leads/').get_data(as_text=True)
    old = Prospect.query.get(old.id)
    check(old.stage == 'working', 'an already-called prospect lands in Working')
    check(old.next_action_date == TODAY, 'due today rather than backdated into a red list')
    check('Legacy Co' in html, 'and it shows up instead of sitting invisible')

    print('\n12. The pipeline board counts every stage')
    html = c.get('/find-leads/?view=pipeline').get_data(as_text=True)
    for label in ('New', 'Working', 'Interested', 'Won', 'Nurture', 'Lost'):
        check(label in html, f'{label} is on the board')

print('\n🎉 Funnel checks passed.')
