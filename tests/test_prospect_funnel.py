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
    # This used to assert the opposite — that a no went to 'lost' with nothing
    # scheduled. In commercial cleaning "not interested" nearly always means
    # "we are under contract", which is a date rather than a rejection, and
    # closing the file threw away the most winnable prospect there is: one who
    # has already told you they buy this service. It rests and comes back.
    check(nope.stage == 'nurture' and nope.next_action_date == plus(90),
          'a no rests in nurture and returns in a quarter, not closed forever')

    print('\n3b. Only an explicit "do not contact" actually closes the file')
    stop = Prospect(business_name='Leave Us Alone LLC', category='property_manager',
                    status='new', stage='new')
    db.session.add(stop); db.session.commit()
    c.post(f'/find-leads/{stop.id}/status', follow_redirects=True,
           data={'mode': 'log', 'status': 'do_not_contact'})
    stop = Prospect.query.get(stop.id)
    check(stop.stage == 'lost' and not stop.next_action_date,
          'asked not to be contacted: nothing scheduled, ever')
    check(not stop.is_due(),
          'and it never comes back onto the call list')

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

    print('\n13. Nurture is a queue, not a hole')
    # The bug this replaces: nurture was in neither LIVE_STAGES nor anything
    # else the Today view looked at, so every prospect that rested — whether
    # sent there by a no, by a "keep in touch", or simply by running out of
    # call attempts — was given a next action and a date and then never shown
    # again on any screen.
    resting = Prospect(business_name='Back In March Ltd', category='property_manager',
                       status='not_interested', stage='nurture',
                       next_action='Quarterly check-in', next_action_date=plus(90))
    ripe = Prospect(business_name='Due Today Group', category='property_manager',
                    status='not_interested', stage='nurture',
                    next_action='Quarterly check-in', next_action_date=TODAY)
    db.session.add_all([resting, ripe]); db.session.commit()
    check(not resting.is_due(), 'a nurturing prospect stays off the list until its date')
    check(ripe.is_due(), 'and comes back onto it the day it is due')
    html = c.get('/find-leads/').get_data(as_text=True)
    check('Due Today Group' in html, 'the one that is due appears in Today')
    check('Back In March Ltd' not in html, 'the one that is resting does not')

    print('\n14. The dashboard count and the list it links to agree')
    # These were two different queries: the count had no stage filter at all,
    # so it counted won, lost and resting prospects the page would never show.
    # A dashboard that promises seven callbacks and delivers four is worse than
    # one that says nothing, because you stop believing the number.
    import daily_plan
    rows = Prospect.query.all()
    shown = [p for p in rows if p.is_due(TODAY)]
    counted = sum(1 for p in Prospect.query.filter(Prospect.maybe_due(TODAY)).all()
                  if p.is_due(TODAY))
    check(counted == len(shown),
          f'dashboard counts exactly what Today shows ({counted})')
    check(any('/find-leads/' in link for _u, _t, link in daily_plan.items())
          or not shown,
          'and the dashboard links there when there is anything to do')

    print('\n15. A contract renewal wakes the prospect that was resting on it')
    import prospecting
    from datetime import date, timedelta as _td
    soon = (date.today() + _td(days=prospecting.RENEWAL_LEAD_DAYS - 5)).isoformat()
    far = (date.today() + _td(days=200)).isoformat()
    renewing = Prospect(business_name='Contract Ends Soon Co', category='property_manager',
                        status='not_interested', stage='nurture',
                        next_action='Quarterly check-in', next_action_date=plus(60),
                        renewal_date=soon)
    later = Prospect(business_name='Locked In For Ages Co', category='property_manager',
                     status='not_interested', stage='nurture',
                     next_action='Quarterly check-in', next_action_date=plus(60),
                     renewal_date=far)
    db.session.add_all([renewing, later]); db.session.commit()

    woken = prospecting.wake_renewals()
    renewing = Prospect.query.get(renewing.id)
    later = Prospect.query.get(later.id)
    check(woken == 1, f'exactly the one inside the window woke ({woken})')
    check(renewing.stage == 'working' and renewing.next_action_date == TODAY,
          'it is back on the call list today, not in three months')
    check(soon in (renewing.next_action or ''),
          'and the action says when the contract actually ends')
    check(later.stage == 'nurture' and later.next_action_date == plus(60),
          'a renewal still months out is left alone')

    # Firing once matters: this runs nightly, and a prospect that re-woke every
    # night for thirty nights would rewrite a real next action each time.
    again = prospecting.wake_renewals()
    check(again == 0, 'and it does not wake the same prospect again tomorrow')

    print('\n16. "Send your information" starts the sequence that chases it')
    import lifecycle
    from datetime import datetime as _dt
    sent_to = []
    real_send = lifecycle._send_prospect_drip
    lifecycle._send_prospect_drip = lambda p, seq, n: (
        sent_to.append((p.business_name, seq, n)) or True)

    info = Prospect(business_name='Wants The Packet Ltd', category='property_manager',
                    status='new', stage='new', contact_name='Dana Reid',
                    email='dana@wantsthepacket.test')
    db.session.add(info); db.session.commit()
    c.post(f'/find-leads/{info.id}/status', follow_redirects=True,
           data={'mode': 'log', 'status': 'send_info'})
    info = Prospect.query.get(info.id)
    check(info.sequence == 'send_info' and info.drip_step == 0,
          'the call puts them into the send_info sequence')

    # Nothing is due on the day of the call.
    check(lifecycle.run_prospect_sequences(now=_dt.utcnow()) == 0,
          'and nothing is mailed the same day')

    # Day 2.
    n = lifecycle.run_prospect_sequences(now=_dt.utcnow() + _td(days=2))
    info = Prospect.query.get(info.id)
    check(n == 1 and info.drip_step == 1, 'step 1 goes out on day 2')

    # Day 7 -- and only one step per run, even though both are now overdue.
    n = lifecycle.run_prospect_sequences(now=_dt.utcnow() + _td(days=30))
    info = Prospect.query.get(info.id)
    check(n == 1 and info.drip_step == 2,
          'a backdated run sends one step, not the whole sequence at once')

    print('\n17. Answering stops the chase without anybody stopping it')
    c.post(f'/find-leads/{info.id}/status', follow_redirects=True,
           data={'mode': 'log', 'status': 'interested'})
    info = Prospect.query.get(info.id)
    before = len(sent_to)
    lifecycle.run_prospect_sequences(now=_dt.utcnow() + _td(days=60))
    info = Prospect.query.get(info.id)
    check(info.sequence is None, 'moving them out of the stage ends the sequence')
    check(len(sent_to) == before, 'and no further email is sent')

    print('\n18. The sequence stops rather than running forever')
    done = Prospect(business_name='Ran Its Course Co', category='property_manager',
                    status='not_interested', stage='nurture',
                    contact_name='Sam Okafor', email='sam@ranitscourse.test',
                    sequence='nurture', drip_step=3,
                    last_drip_at=_dt.utcnow() - _td(days=400))
    db.session.add(done); db.session.commit()
    lifecycle.run_prospect_sequences(now=_dt.utcnow())
    done = Prospect.query.get(done.id)
    check(done.drip_step == 4, 'the last quarterly note goes out')
    check(done.sequence is None,
          'and then it stops mailing rather than becoming noise forever')
    check(done.stage == 'nurture' and done.business_name == 'Ran Its Course Co',
          'while the prospect itself stays on the books, still in nurture')

    print('\n19. A real no is never mailed')
    quiet = Prospect(business_name='Leave Us Be Ltd', category='property_manager',
                     status='new', stage='new', contact_name='Pat Lyle',
                     email='pat@leaveusbe.test')
    db.session.add(quiet); db.session.commit()
    c.post(f'/find-leads/{quiet.id}/status', follow_redirects=True,
           data={'mode': 'log', 'status': 'keep_in_touch'})
    quiet = Prospect.query.get(quiet.id)
    check(quiet.sequence == 'nurture', 'keep-in-touch starts the quarterly sequence')
    c.post(f'/find-leads/{quiet.id}/status', follow_redirects=True,
           data={'mode': 'log', 'status': 'do_not_contact'})
    quiet = Prospect.query.get(quiet.id)
    check(quiet.sequence is None,
          'and asking not to be contacted clears it immediately')
    before = len(sent_to)
    lifecycle.run_prospect_sequences(now=_dt.utcnow() + _td(days=365))
    check(len(sent_to) == before, 'they are never mailed again')

    lifecycle._send_prospect_drip = real_send

print('\n🎉 Funnel checks passed.')
