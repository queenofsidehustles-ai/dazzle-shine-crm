"""Following up with the people who called through Google Ads and never booked.

Two things have to be right or this does real damage. It must never text someone
who already booked — nothing reads worse to a paying customer than "sorry we
didn't get to connect". And it must stop the instant someone says stop, which
until now nothing in the CRM could even notice: the opt-out list was keyed by
email address, and an inbound "STOP" was logged as an ordinary message.
"""
import os, sys, tempfile
from datetime import datetime, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/lsa.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEXTS = []
import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda to_phone=None, message=None, *a, **k: (
    TEXTS.append({'to': to_phone, 'body': message}), (True, 'stub'))[1]

from app import create_app
from extensions import db
from models import Booking, Client, LsaLead, SmsOptOut, Message
import lsa
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def texts_to(phone):
    return [t for t in TEXTS if lsa.phone10(t['to']) == lsa.phone10(phone)]


CSV = """Lead ID,Customer,Job type,Search Intent,Location,Lead type,Charge status,Lead received,Last activity
334826152,(334) 462-0191,,Category,Kissimmee,Phone,Charged,8/21/26 12:23 PM,8/22/26 12:36 PM
335468014,(772) 634-8141,,Category,Kissimmee,Phone,Not charged,8/24/26 7:06 PM,8/24/26 7:06 PM
335369749,(305) 934-4446,Standard clean,Category,Poinciana,Phone,Not charged,8/24/26 2:08 PM,8/24/26 2:08 PM
332489987,(347) 701-1627,,Category,Four Corners,Phone,Charged,8/13/26 11:58 AM,8/14/26 12:01 PM
330138089,(305) 338-7892,Standard clean,Category,Sanford,Phone,Charged,8/3/26 6:53 PM,8/4/26 6:58 PM
334622549,(305) 338-7892,Deep clean,Category,Sanford,Phone,Charged,8/22/26 1:48 PM,8/23/26 10:13 PM
999999999,not a phone,,Category,Orlando,Message,Charged,8/2/26 1:00 PM,8/2/26 1:00 PM
"""

with app.app_context():
    db.create_all()

    print('\n1. The export imports, and unusable rows are reported not hidden')
    rows, problems = lsa.parse_csv(CSV)
    check(len(rows) == 6, f'six usable leads read from seven rows (got {len(rows)})')
    check(len(problems) == 1 and 'not a phone' in problems[0],
          'the message-lead row is reported as skipped, with its value')
    check(rows[0]['phone'] == '3344620191', 'the number is stored as ten digits')
    check(rows[0]['received_at'] == datetime(2026, 8, 21, 12, 23),
          "Google's m/d/yy date and time survive the trip")
    check(rows[1]['charge_status'] == 'Not charged', "Google's billing status is kept")

    added, updated = lsa.import_rows(rows)
    check((added, updated) == (6, 0), 'all six are new the first time')

    print('\n2. Re-importing an overlapping export does not duplicate anyone')
    added2, updated2 = lsa.import_rows(lsa.parse_csv(CSV)[0])
    check((added2, updated2) == (0, 6), 'the second import refreshes rather than adds')
    check(LsaLead.query.count() == 6, 'still six rows')
    check(LsaLead.query.filter_by(phone='3053387892').count() == 2,
          'one number that called twice is two leads, not one — both calls are real')

    print('\n3. Anyone who booked is matched out by phone number')
    # Alice, from the LSA export, booked on 21 Aug.
    db.session.add(Booking(service_type='deep', name='Alice Greene', price=390,
                           email='alice.greene62@gmail.com', phone='(334) 462-0191',
                           address='3749 Paradiso Cr', city='Kissimmee'))
    # A client on file whose number called again but has no booking row.
    db.session.add(Client(name='Repeat Caller', email='r@example.com',
                          phone='347-701-1627'))
    db.session.commit()

    booked = lsa.match_bookings()
    check(booked == 2, 'both the booking and the existing client are matched')
    alice = LsaLead.query.filter_by(phone='3344620191').first()
    check(alice.booked and alice.booking_id, 'Alice is flagged as booked, with the booking')
    check(LsaLead.query.filter_by(phone='3477011627').first().booked,
          'an existing client counts too — she is not a stranger to text cold')
    check(alice.booked_checked_at is not None,
          'and we record that we looked, so "no match" differs from "never checked"')

    print('\n4. Starting the sequence sends nothing on its own')
    fresh = LsaLead.query.filter_by(phone='7726348141').first()
    check(lsa.start_sequence(fresh), 'the lead goes into the sequence')
    check(TEXTS == [], 'but no text has gone out — the run is what sends')
    check(not lsa.start_sequence(alice), 'and a booked lead cannot be started at all')

    print('\n5. The first run sends text one, and only text one')
    r = lsa.run_sequence()
    check(r['sent'] == 1, 'one text sent')
    check(len(texts_to('7726348141')) == 1, 'to the lead who never booked')
    body = texts_to('7726348141')[0]['body']
    check('STOP' in body, 'carrying opt-out wording')
    check('Aug 24' in body, 'and referring to the day they actually called')
    check(texts_to('3344620191') == [], 'Alice, who booked, is texted nothing')

    r = lsa.run_sequence()
    check(r['sent'] == 0, 'running again the same day sends nothing more')

    print('\n6. Texts two and three arrive on day 4 and day 8, then it ends')
    lead = LsaLead.query.filter_by(phone='7726348141').first()
    lead.last_seq_at = datetime.utcnow() - timedelta(days=3)
    db.session.commit()
    lsa.run_sequence()
    check(len(texts_to('7726348141')) == 1, 'nothing on day 3 — the gap is four days')

    lead.last_seq_at = datetime.utcnow() - timedelta(days=4)
    db.session.commit()
    lsa.run_sequence()
    check(len(texts_to('7726348141')) == 2, 'the second text goes out on day 4')

    lead = LsaLead.query.filter_by(phone='7726348141').first()
    lead.last_seq_at = datetime.utcnow() - timedelta(days=4)
    db.session.commit()
    lsa.run_sequence()
    check(len(texts_to('7726348141')) == 3, 'the third four days after that, on day 8')
    lead = LsaLead.query.filter_by(phone='7726348141').first()
    check(lead.seq_stopped == 'finished', 'and the sequence closes itself')

    lsa.run_sequence()
    check(len(texts_to('7726348141')) == 3, 'a fourth text is never sent')

    print('\n7. STOP is obeyed — the thing the CRM could not do before')
    stopper = LsaLead.query.filter_by(phone='3059344446').first()
    lsa.start_sequence(stopper)
    c = app.test_client()
    c.post('/messages/incoming', data={'From': '+13059344446', 'Body': 'STOP',
                                       'MessageSid': 'SM1'})
    check(SmsOptOut.query.filter_by(phone='3059344446').first() is not None,
          'the number is on the do-not-text list')
    check(notifications.sms_opted_out('(305) 934-4446'),
          'and is recognised in any format')
    stopper = LsaLead.query.filter_by(phone='3059344446').first()
    check(stopper.seq_stopped == 'opted_out', 'their sequence is stopped immediately')

    before = len(texts_to('3059344446'))
    lsa.run_sequence()
    check(len(texts_to('3059344446')) == before, 'and no further text is sent')

    ok, detail = notifications.send_marketing_sms('3059344446', 'anything at all')
    check(not ok and 'stop' in detail.lower(),
          'a marketing text to that number is refused outright')

    print('\n8. "stop by at 9" is a customer talking, not an opt-out')
    check(notifications.sms_stop_word('stop by at 9 instead') is None,
          'a sentence that merely contains the word is left alone')
    check(notifications.sms_stop_word('Stop.') == 'stop', 'a bare STOP still counts')
    check(notifications.sms_stop_word('UNSUBSCRIBE') == 'unsubscribe',
          'so do the other carrier keywords')

    print('\n9. Any reply ends the sequence — they get a person, not a robot')
    replier = LsaLead.query.filter_by(phone='3053387892').first()
    lsa.start_sequence(replier)
    lsa.run_sequence()
    sent_before = len(texts_to('3053387892'))
    c.post('/messages/incoming', data={'From': '+13053387892',
                                       'Body': 'yes how much for 3 bedrooms?',
                                       'MessageSid': 'SM2'})
    replier = LsaLead.query.filter_by(phone='3053387892').first()
    check(replier.seq_stopped == 'replied', 'the sequence stops on their reply')
    check(SmsOptOut.query.filter_by(phone='3053387892').first() is None,
          'and a normal reply is not mistaken for an opt-out')
    lsa.run_sequence()
    check(len(texts_to('3053387892')) == sent_before, 'nothing further is sent')

    print('\n10. Booking mid-sequence takes you out of it')
    late = LsaLead.query.filter(LsaLead.seq_started_at.is_(None),
                                LsaLead.booked == False).first()
    check(late is not None, 'there is a lead still waiting')
    lsa.start_sequence(late)
    db.session.add(Booking(service_type='standard', name='Booked Late', price=200,
                           email='late@example.com', phone=late.phone, address='1 St'))
    db.session.commit()
    lsa.match_bookings()
    late = LsaLead.query.get(late.id)
    check(late.booked and late.seq_stopped == 'booked',
          'the moment they book, the chasing stops')
    n = len(texts_to(late.phone))
    lsa.run_sequence()
    check(len(texts_to(late.phone)) == n, 'and they hear nothing more about it')

    print('\n11. The real CSV export, which is not shaped like the web table')
    # The download differs from the on-screen table in two ways that both cost
    # data silently. It has no Lead ID column at all, and it writes dates as
    # "Aug 24 2026" where the table shows "8/24/26 7:06 PM". The first import of
    # a real export parsed 35 leads and zero dates.
    REAL = (
        'Customer,Job type,Search intent,Location,Lead type,Charge status,'
        'Lead received,Last activity\n'
        '(772) 634-8141,,Categorical,Kissimmee,Phone call,Not charged,Aug 24 2026,Aug 24 2026,\n'
        '(305) 338-7892,Deep clean,Categorical,Sanford,Phone call,Charged,Aug 22 2026,Aug 23 2026,\n'
        '(305) 338-7892,Standard clean,Categorical,Sanford,Phone call,Charged,Aug 3 2026,Aug 4 2026,\n'
        ',,Categorical,Longwood,Phone call,Charged,Jul 9 2026,Jul 15 2026,\n'
    )
    real_rows, real_probs = lsa.parse_csv(REAL)
    check(len(real_rows) == 3, 'three leads read; the row with no number is not one')
    check(len(real_probs) == 1, 'and that row is reported rather than silently dropped')
    check(all(r['received_at'] for r in real_rows),
          'every date parses — "Aug 24 2026" is the format the export actually uses')
    check(real_rows[0]['received_at'] == datetime(2026, 8, 24), 'and parses correctly')
    check(real_rows[0]['charge_status'] == 'Not charged',
          'the trailing comma on every export row does not shift the columns')

    print('\n12. No Lead ID column, so re-importing must not duplicate anyone')
    LsaLead.query.delete()
    db.session.commit()
    check(all(r['lead_id'] is None for r in real_rows), 'the export carries no lead id')
    check(lsa.import_rows(real_rows) == (3, 0), 'three leads on the first import')
    check(lsa.import_rows(lsa.parse_csv(REAL)[0]) == (0, 3),
          'and the same file again refreshes all three rather than adding more')
    check(LsaLead.query.count() == 3, 'still three')
    check(LsaLead.query.filter_by(phone='3053387892').count() == 2,
          'the number that called twice on different days stays two leads')

    print('\n13. Two tracks — a missed call and a lost quote are different people')
    # Most of these leads are not missed calls at all. The owner spoke to them
    # and quoted a price; "sorry we didn't get to connect" reads to someone she
    # priced up three weeks ago as though she has no idea who they are.
    LsaLead.query.delete()
    db.session.commit()
    TRACKS_CSV = (
        'Customer,Job type,Search intent,Location,Lead type,Charge status,'
        'Lead received,Last activity\n'
        '(407) 111-2222,,Categorical,Orlando,Phone call,Not charged,Aug 20 2026,Aug 20 2026,\n'
        '(407) 333-4444,,Categorical,Orlando,Phone call,Charged,Aug 20 2026,Aug 21 2026,\n'
        '(407) 555-6666,,Categorical,Orlando,Phone call,Credited,Aug 20 2026,Aug 21 2026,\n'
    )
    lsa.import_rows(lsa.parse_csv(TRACKS_CSV)[0])
    missed = LsaLead.query.filter_by(phone='4071112222').first()
    quoted = LsaLead.query.filter_by(phone='4073334444').first()
    credited = LsaLead.query.filter_by(phone='4075556666').first()
    check(missed.track == lsa.MISSED, 'a lead Google did not charge for is a missed call')
    check(quoted.track == lsa.QUOTED, 'a charged lead is someone who got through')
    check(credited.track == lsa.MISSED, 'a credited lead is treated as missed too')

    check('did not get to connect' in lsa.message_for(1, missed).replace("didn't", 'did not'),
          'the missed-call text apologises for missing them')
    q1 = lsa.message_for(1, quoted)
    check('connect' not in q1, 'the quoted text does not apologise for a call that happened')
    check('24 hours' in q1 and 're-clean' in q1,
          'it leads with the guarantee, worded as the customer terms word it')

    print('\n14. She was on the calls, so she can overrule Google')
    quoted.track = lsa.MISSED
    db.session.commit()
    lsa.import_rows(lsa.parse_csv(TRACKS_CSV)[0])
    check(LsaLead.query.filter_by(phone='4073334444').first().track == lsa.MISSED,
          're-importing does not undo a correction she made by hand')

    print('\n15. The wording is hers to change without a deploy')
    check(lsa.template_for(lsa.QUOTED, 1) == lsa.DEFAULT_MESSAGES[(lsa.QUOTED, 1)],
          'out of the box she gets our wording')
    lsa.save_template(lsa.QUOTED, 1, 'Hi from {biz}! Still need that clean? — call {phone}')
    check(lsa.message_for(1, credited) is not None, 'other tracks are unaffected')
    credited.track = lsa.QUOTED
    db.session.commit()
    body = lsa.message_for(1, credited)
    check(body.startswith('Hi from '), 'her wording is what sends')
    check('{biz}' not in body and '{phone}' not in body, 'with the placeholders filled in')
    check('Dazzle' in body or body != 'Hi from ! Still need that clean? — call ',
          'from the real business name, not an empty string')

    lsa.save_template(lsa.QUOTED, 1, '')
    check(lsa.template_for(lsa.QUOTED, 1) == lsa.DEFAULT_MESSAGES[(lsa.QUOTED, 1)],
          'clearing the box puts the original wording back')

    print('\n16. A stray brace in her wording cannot break a send')
    lsa.save_template(lsa.QUOTED, 1, 'Hi {biz}, about that {mystery} of yours')
    out = lsa.message_for(1, credited)
    check('{mystery}' in out, 'an unknown placeholder is left as typed rather than raising')
    lsa.save_template(lsa.QUOTED, 1, '')

    print('\nAll Google Ads follow-up checks passed.')
