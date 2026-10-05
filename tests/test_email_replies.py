"""A prospect's reply reaching the company that wrote to them.

An introduction goes out from the company's own domain; a reply to it used to
go to the owner's mailbox, where the CRM never saw it. So the chase still
fired on Thursday for somebody who answered on Tuesday, and the best prospect
on the list got nagged for replying.

Every outreach email now carries its own return address, and that address says
which company and which business. Unlike an inbound text -- where a phone
number carries nothing and the company has to be guessed from who wrote last
-- there is nothing here to work out.

What is worth protecting:

  * the address identifies exactly one prospect in exactly one company
  * it is signed, so it is not a way to write into somebody else's CRM by
    guessing a small integer
  * a reply stops the chase: somebody who answered should get a person
  * the owner is sent the reply, because a note in a CRM nobody opened today
    has not been read
  * unsigned POSTs are refused outright
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/replies.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
os.environ['REPLY_DOMAIN'] = 'reply.akyehq.com'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
import email_replies, security

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


with app.app_context():
    print('1. The address says who it belongs to')
    a = email_replies.address_for('final-touch-group-llc', 42)
    check(a.endswith('@reply.akyehq.com'), 'it is on the platform domain, not the company one')
    check(email_replies.parse(a) == ('final-touch-group-llc', 42),
          'and it reads back as that company and that business')
    check('final-touch-group-llc' in a,
          'a slug with hyphens survives — it is never reversed out of a schema name')

    print('\n2. It cannot be forged by guessing a number')
    check(email_replies.parse('final-touch-group-llc-43-' + a.split('-')[-1]) is None,
          'the same signature against a different business is refused')
    check(email_replies.parse('someoneelse-42-' + a.split('-')[-1].split('@')[0] + '@reply.akyehq.com') is None,
          'and against a different company')
    check(email_replies.parse('final-touch-group-llc-42-000000000000@reply.akyehq.com') is None,
          'a made-up signature is refused')
    check(email_replies.parse('anything@gmail.com') is None, 'another domain is not ours')
    check(email_replies.parse('') is None and email_replies.parse(None) is None,
          'and nothing is nothing')

    print('\n3. Found among everyone the reply was sent to')
    pick = email_replies.pick_address(
        {'to': ['Someone <colleague@lakeside.com>', f'<{a}>'], 'cc': 'boss@lakeside.com'})
    check(pick == ('final-touch-group-llc', 42),
          'a reply that also copies a colleague still lands')
    check(email_replies.pick_address({'to': ['a@b.com'], 'cc': None}) is None,
          'and mail that is nothing to do with us does not')

    print('\n4. A reply stops the chase and reaches a person')
    from models import Prospect, BusinessSetting
    db.create_all()
    BusinessSetting.set('email', 'owner@brightclean.com')
    p = Prospect(business_name='Lakeside PM', category='property_manager',
                 email='dana@lakeside.com', status='called', stage='working',
                 next_action='Did the information land?', next_action_date='2026-10-09',
                 sequence='intro')
    db.session.add(p); db.session.commit()

    import notifications
    forwarded = []
    real = notifications.send_email
    notifications.send_email = lambda *a, **k: (forwarded.append((a[0], k.get('reply_to'))), (True, 'stub'))[1]
    try:
        ok, said = email_replies.record('brightclean', p.id, 'dana@lakeside.com',
                                        'Re: cleaning', 'Yes — send pricing please.')
    finally:
        notifications.send_email = real
    check(ok is True, 'it is recorded')
    check(p.next_action == 'They replied — read it',
          'the scheduled chase becomes "a person should read this"')
    check(p.next_action_date <= '2026-10-09', 'and it is due now, not next week')
    check(p.sequence is None, 'the drip stops — they already answered')
    check('Yes — send pricing please.' in (p.notes or ''), 'what they said is kept')
    check(forwarded and forwarded[0][0] == 'owner@brightclean.com',
          'and the owner is sent it, because a CRM she has not opened has not been read')
    check(forwarded and forwarded[0][1] == 'dana@lakeside.com',
          'addressed so that hitting reply reaches the prospect, not us')

    print('\n5. Switched off is switched off')
    os.environ['REPLY_DOMAIN'] = ''
    check(email_replies.address_for('brightclean', 1) == '',
          'no reply domain configured means no return address, not a broken one')
    check(email_replies.parse(a) is None, 'and nothing routes')
    os.environ['REPLY_DOMAIN'] = 'reply.akyehq.com'

print('\n6. Unsigned mail does not get to write to anybody')
check('/api/email-reply' in security.CSRF_EXEMPT_PATHS,
      'the email service posts from elsewhere and is exempt from the origin check')
src = open('blueprints/api.py', encoding='utf-8').read()
body = src[src.index('def email_reply('):]
check('_resend_signature_ok' in body.split('payload =')[0],
      'but the signature is checked before anything is read or written')
check("g.tenant_slug, g._org = slug, None" in body,
      'and it becomes the company, not merely its schema')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
