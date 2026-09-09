"""Nana answers from the books, and cannot be talked into anything else.

The design this suite exists to hold: the model picks which question was asked
and nothing else. Every figure, name and date is read from the database and
written by ordinary Python, so the worst a wrong guess can do is answer a
different question — visibly — rather than state a number that is not true.

The other half is what it will not do. It does not send email, does not text
anybody, does not charge a card, and marking a job finished is offered rather
than done. Anything that reaches a customer or moves money should be a button a
person pressed, not a sentence a model understood.
"""
import json, os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, date, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/kye.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (SENT.append('sms'), (True, 'stub'))[1]
notifications.send_email = lambda to=None, *a, **k: (
    SENT.append(('email', to)), (True, 'stub'))[1]

from app import create_app
from extensions import db
from models import Booking, Client, Staff
import assistant

app = create_app()
failures = []


def _dbcommit():
    db.session.commit()


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


with app.app_context():
    db.create_all()
    import scheduling
    today = scheduling.local_today()

    db.session.add(Staff(name='Laura Moreira', phone='4075550001',
                         email='l@x.com', is_active=True))
    db.session.add(Client(name='Rita Vance', email='rita@x.com',
                          phone='4079990000', address='1 Elm'))

    def job(name, when, price, paid=None, cleaner='Laura Moreira', status='confirmed'):
        b = Booking(service_type='standard', name=name, email=f'{name[:4]}@x.com',
                    phone='4079990000', address='1 Elm', city='Orlando',
                    bedrooms='3', bathrooms='2', price=price, status=status,
                    preferred_date=when.isoformat(), preferred_time='10:00 AM',
                    assigned_cleaner=cleaner, paid_at=paid,
                    amount_collected=(price if paid else 0))
        db.session.add(b)
        db.session.commit()
        return b

    job('Rita Vance', today, 260.0, paid=datetime.utcnow())
    job('Paid Earlier', today - timedelta(days=2), 190.0, paid=datetime.utcnow())
    job('Owes Money', today - timedelta(days=1), 300.0)
    job('Nobody On It', today + timedelta(days=2), 220.0, cleaner=None)

    print('\n1. The numbers come from the books, not the model')
    said = assistant.money_made('this month')
    check('450.00' in said, f'takes what was actually paid: {said!r}')
    check('2 paid' in said, 'and counts the jobs behind it')
    check('300' not in said, 'unpaid work is not counted as money made')

    said = assistant.money_owed()
    # 300 done-and-unpaid plus 220 booked-and-unpaid. "Booked or already done"
    # is what the figure means, and a job in two days' time is money owed even
    # though nobody has cleaned anything yet.
    check('520.00' in said, f'owed covers booked as well as done: {said!r}')

    print('\n2. It answers in the words somebody would use')
    said = assistant.jobs_on('today')
    check('today' in said and 'Rita Vance' in said, f'{said.splitlines()[0]!r}')
    check('Laura Moreira' in said, 'and says who is cleaning it')
    check(str(today) not in said, 'no ISO dates — a person would not say 2026-09-07')

    said = assistant.jobs_on('tomorrow')
    check('Nothing is booked tomorrow' in said, 'an empty day says so plainly')

    said = assistant.unassigned_jobs()
    check('Nobody On It' in said, 'a job with no cleaner is findable')

    print('\n3. A wrong guess answers a different question — it cannot invent one')
    # The model returns a tool name. Anything it makes up is dropped.
    picks, _kind, problem = assistant.choose('anything', api_key='')
    check(not picks, 'with no key it declines rather than guessing')
    for made_up in ('delete_everything', 'charge_all_cards', '', None):
        check(made_up not in assistant.TOOLS,
              f'{made_up!r} is not a tool it could pick')

    print('\n4. A draft for a customer is still only words')
    SENT.clear()
    # With a key it writes; without one it says so. Either way nothing leaves.
    class _Fake:
        @staticmethod
        def post(*a, **k):
            class R:
                @staticmethod
                def json():
                    return {'choices': [{'message': {
                        'content': 'Hello Rita, sorry we were late today.'}}]}
            return R()
    import assistant as _a
    _real_requests = __import__('requests')
    sys.modules['requests'] = _Fake
    try:
        out = _a.draft_email(about='say sorry we were late', to='Rita',
                             api_key='pretend')
    finally:
        sys.modules['requests'] = _real_requests
    check(out.get('draft', {}).get('body'), f'it writes a draft: {out.get("draft", {}).get("body")!r}')
    check('do not send' in out['say'],
          'and says plainly that this one does not send')
    check('facts' in out['draft'],
          'showing what it was working from, so the words can be checked')
    check(SENT == [], 'nothing left the building')

    print('\n5. Finishing a job is offered, not done')
    out = assistant.finish_job(customer='Owes Money')
    check('confirm' in out, 'it comes back as something to confirm')
    # The page is handed a token and nothing else. It does not learn the
    # action, or the job id, so it cannot post back a different one -- what
    # runs is read from what was written down when the offer was made.
    check(set(out['confirm']) <= {'token', 'label', 'reversible'},
          f'the page carries a token, not the deed ({sorted(out["confirm"])})')
    check(out['confirm']['token'], 'and the token is real')
    import proposals as _pr
    _act, _pay, _row = _pr.take(out['confirm']['token'])
    check(_act == 'complete_booking', 'which stands for finishing that job')
    b = Booking.query.filter_by(name='Owes Money').first()
    check(b.status == 'confirmed', 'and the job is untouched until somebody presses it')

    print('\n6. It asks rather than guessing between two people')
    job('Rita Vance', today - timedelta(days=3), 200.0)
    out = assistant.finish_job(customer='Rita')
    check('More than one' in out['say'], 'two matches is a question, not a coin toss')
    check('confirm' not in out, 'and nothing is offered to press')

    out = assistant.finish_job(customer='')
    check('Which job' in out['say'], 'no name at all is also a question')

    print('\n7. There is no tool that spends money or texts anybody')
    for bad in ('charge', 'refund', 'pay', 'text', 'sms', 'send_email', 'delete'):
        hits = [t for t in assistant.TOOLS if bad in t and t != 'draft_email']
        check(not hits, f'nothing named like {bad!r} ({hits})')
    # Only one tool changes anything at all, and it proposes.
    writers = [n for n, (_f, d, _a) in assistant.TOOLS.items()
               if 'mark' in d or 'finished' in d]
    check(writers == ['finish_job'], f'exactly one tool touches data: {writers}')

    print('\n7b. It knows about leads, not just jobs')
    from models import Lead, Prospect, CommercialAccount
    check('No new enquiries waiting' in assistant.leads_waiting(),
          'an empty inbox says so')
    db.session.add(Lead(name='Dana Ruiz', email='dana@x.com', phone='4071112222',
                        service_type='standard', city='Orlando', status='new',
                        quoted_price=210.0))
    db.session.add(Lead(name='Old One', email='old@x.com', phone='4073334444',
                        service_type='standard', status='contacted'))
    db.session.commit()
    said = assistant.leads_waiting()
    check('Dana Ruiz' in said, f'a new enquiry is surfaced: {said.splitlines()[0]!r}')
    check('210.00' in said, 'with what they were quoted')
    check('Old One' not in said, 'somebody already replied to is not still waiting')

    said = assistant.commercial_pipeline()
    check('Nothing commercial yet' in said, 'and an empty pipeline says so plainly')
    db.session.add(Prospect(business_name='Palm Ridge Lettings',
                            category='property_manager', stage='called'))
    db.session.add(CommercialAccount(business_name='Lakeview Offices',
                                     contact_name='Sam', email='sam@x.com',
                                     status='active'))
    db.session.commit()
    said = assistant.commercial_pipeline()
    check('1 account' in said, f'won accounts are counted: {said!r}')
    check('called' in said, 'and prospects are grouped by where they got to')

    print('\n7c. A draft is written from facts, and still is not sent')
    SENT.clear()
    out = assistant.draft_email(about='thank them for the enquiry', to='Dana',
                                api_key='')
    check('no writing key' in out['say'], 'with no key it says so rather than guessing')
    check(SENT == [], 'and nothing was sent')
    # The facts handed to it come from the database, not from the model's memory.
    who = assistant._who('Dana')
    check(who and who['kind'] == 'enquiry', 'it finds an enquiry by name')
    check(who['quoted'] == 210.0, 'and knows what they were actually quoted')
    check(assistant._who('Sam')['kind'] in ('commercial', 'customer'),
          'and finds a commercial contact too')
    check(assistant._who('nobody at all') is None, 'and does not invent a person')

    print('\n8. The page offers; the button acts')
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['logged_in'] = True
        sess['role'] = 'owner'
    check(c.get('/ask').status_code == 200, 'the page loads')

    # A confirmation only does what is on a fixed list -- not "whatever the
    # model named", which is how a new tool would quietly become a new power.
    import blueprints.assistant_routes as ar
    check(set(ar.ACTIONS) == {'complete_booking', 'send_prospect_email'},
          f'a short, fixed list of actions: {sorted(ar.ACTIONS)}')

    b = Booking.query.filter_by(name='Owes Money').first()
    check(b.status == 'confirmed', 'the job starts unfinished')

    # Naming the deed in the form does nothing at all. This is the property the
    # whole gate exists for: the route takes a token that stands for something
    # already written down, so a page cannot ask for work nobody offered.
    r = c.post('/ask/confirm',
               data={'action': 'complete_booking', 'booking_id': b.id},
               follow_redirects=True)
    check(r.status_code == 200, 'posting the deed itself is refused, not run')
    db.session.expire_all()
    check(db.session.get(Booking, b.id).status == 'confirmed',
          'and the job is untouched by it')
    r = c.post('/ask/confirm', data={'token': 'made-up'}, follow_redirects=True)
    check(db.session.get(Booking, b.id).status == 'confirmed',
          'an invented token does nothing either')

    # The real route: ask, get an offer, press it.
    offer = assistant.finish_job(customer='Owes Money')
    tok = offer['confirm']['token']
    c.post('/ask/confirm', data={'token': tok}, follow_redirects=True)
    db.session.expire_all()
    check(db.session.get(Booking, b.id).status == 'completed',
          'the real one, pressed by a person, does work')

    # Pressing it twice should say so rather than pretend.
    r = c.post('/ask/confirm', data={'token': tok}, follow_redirects=True)
    check(b'already done' in r.data, 'and a second press says it is already done')

    print('\n9. It cannot run away with somebody else\'s bill')
    import assistant as _a
    from models import BusinessSetting
    check(_a.remaining() == _a.MONTHLY_LIMIT - _a.used_this_month(),
          f'{_a.remaining()} of {_a.MONTHLY_LIMIT} left this month')
    BusinessSetting.set(_a._month_key(), str(_a.MONTHLY_LIMIT))
    db.session.commit()
    out = _a.ask('how much did I make')
    check('limit' in out['say'], 'at the limit it stops and says why')
    check('works as normal' in out['say'], 'and says the rest of the CRM is fine')
    BusinessSetting.set(_a._month_key(), '0')
    db.session.commit()

    print('\n9b. She is not free')
    # Every question costs real money to answer, every month, forever. That is
    # the same argument SMS is zero on Solo for, and the only two limits in
    # entitlements.py that are about cash rather than product design.
    import entitlements, navigation
    check('assistant' in entitlements.PLANS['pro']['features'],
          'Pro can ask')
    check('assistant' not in entitlements.PLANS['solo']['features'],
          'the free plan cannot')
    check(entitlements.PLANS['scale']['features'] is None,
          'and Scale gets everything, as ever')
    check(navigation.MIN_PLAN.get('assistant.page') == 'assistant',
          'the menu draws it as a paid page rather than hiding it')
    check(entitlements.FEATURE_LABELS.get('assistant'),
          'and the upsell has a name for it, not a code word')

    # Every way in, not just the page. A route left ungated is the way round.
    import blueprints.assistant_routes as _ar
    import inspect
    for fn in ('page', 'ask', 'confirm'):
        src = inspect.getsource(getattr(_ar, fn))
        check("requires_plan('assistant')" in src or '@requires_plan' in src,
              f'/{fn} is behind the plan too')

    print('\n10. It can be asked out loud, and answer out loud')
    page = c.get('/ask').get_data(as_text=True)
    check('SpeechRecognition' in page, 'the browser does the listening')
    check('webkitSpeechRecognition' in page, 'including on Safari and Chrome')
    check('speechSynthesis' in page, 'and reads the answer back')
    # No service, no key, no audio leaving this server -- the browser's own
    # engine does both halves. Anything that cannot gets the typing box.
    check('id="mic" hidden' in page,
          'the microphone starts hidden and is only shown if it will work')
    check('nana-speak' in page, 'and whether to read answers aloud is remembered')
    check('isFinal' in page,
          'it waits for the end of the sentence — half a question is not a question')
    check('not-allowed' in page,
          'a blocked microphone says so rather than looking broken')
    check('driving' in page.lower(),
          'and the page says not to do this while driving')

    print('\n11. She is described by what she will not do')
    # The customer here has been burned by software acting on its own, so the
    # reassuring half of the pitch is the half about restraint. It also has to
    # stay true: if she ever does send, this wording has to change first.
    check('cannot make a number up' in page,
          'the page says answers come from the records')
    # She can send now, to one prospect, after a press. The page has to say
    # exactly that -- the old copy promised she never sends at all, and a
    # promise the software no longer keeps is worse than no promise.
    check('Nothing leaves without you' in page,
          'the page still promises nothing leaves without you')
    # The copy wraps across lines in the template, so compare on the words
    # rather than on how the file happens to be formatted.
    flat = ' '.join(page.split())
    check('one outreach email to one commercial prospect' in flat,
          'and says precisely what she can send')
    check('read every word and pressed send' in flat,
          'and that it takes reading it and pressing send')
    check('never texts anybody and never charges a card' in page,
          'and what she still cannot do at all')

    print('\n12. A fault of ours is never dressed up as a fault of theirs')
    # This shipped broken. The model name in MODEL did not exist, so every
    # single call errored, the error was caught and dropped, and every question
    # -- including the suggestion chips on our own page -- came back "I did not
    # follow that". An owner reading that concludes the assistant is stupid and
    # stops using it. The fault was ours and it read as theirs.
    #
    # So: each way the round trip can fail says a different, true thing, and
    # none of them is the sentence that means "your wording confused me".
    saved = os.environ.pop('OPENROUTER_API_KEY', None)
    try:
        picks, _kind, problem = assistant.choose('any new enquiries?')
        check(problem == 'not-configured',
              'no key is reported as no key, not as a misunderstood question')
    finally:
        if saved is not None:
            os.environ['OPENROUTER_API_KEY'] = saved

    check(len(set(assistant.TROUBLE.values())) == len(assistant.TROUBLE),
          'no two failures give the owner the same sentence')
    for reason, sentence in assistant.TROUBLE.items():
        check('did not follow' not in sentence,
              f'{reason} does not blame the owner for asking badly')

    # And the model has to be one that exists. There is no way to check the
    # catalogue offline, but the name that broke it is known and must not return.
    check(assistant.MODEL != 'anthropic/claude-3.5-haiku',
          'the model name that never existed is not back')

    print('\n13. The routing shapes that came before the loop')
    # She used to pick tools in one pass and never see the results. That is
    # gone -- section 22 covers what replaced it -- but choose() is still how
    # a failure to reach the service is reported, and that must keep working.
    saved_key = os.environ.pop('OPENROUTER_API_KEY', None)
    try:
        picks, kind, problem = assistant.choose('anything')
        check(problem == 'not-configured' and not picks,
              'with no key it says so rather than guessing')
    finally:
        if saved_key is not None:
            os.environ['OPENROUTER_API_KEY'] = saved_key

    print('\n14. What the check on figures does and does not cover')
    books = ['$450.00 came in this month, across 2 paid jobs.',
             '1 job in the next seven days. 1 still has nobody assigned.',
             'Tuesday: Mrs Adjei, 10am.']
    asked = 'how am I doing this week?'

    def grounded(sentence):
        return assistant._grounded(sentence, books + [asked])

    # Reads back what is there, in whatever shape a person would say it.
    check(grounded('You took $450 this month.'),
          'the same money written a shorter way still passes')
    check(grounded('Two paid jobs so far.'),
          'a figure spelled as a word is checked, and passes when it is true')
    check(grounded('Chase it today — that money is already earned.'),
          'advice with no figures in it passes')
    check(grounded('Tuesday is Mrs Adjei at 10am.'),
          'a name and a day it was actually given pass')

    # Arithmetic is the whole risk. It is not allowed to do any.
    check(not grounded('You are averaging $225.00 a job.'),
          'a figure it divided out is blocked')
    check(not grounded('$450.00 in and $520.00 owed makes $970.00.'),
          'a figure it added up is blocked')
    check(not grounded('You made $4500.00 this month.'),
          'a misplaced decimal point is blocked')
    check(not grounded('3 jobs are booked next week.'),
          'a count that is not in the books is blocked')
    check(not grounded('You are up 15% on last month.'),
          'a percentage out of nowhere is blocked')

    # A true figure on the wrong month is still wrong, so days and months are
    # held to the same rule. Names are not -- see _grounded for why.
    check(not grounded('Revenue was $450.00 in July.'),
          'a real figure hung on a month nobody mentioned is blocked')
    check(not grounded('You are booked Friday.'),
          'a day that is not in the books is blocked')
    print('\n15. The voice cannot run up a bill, and never goes silent')
    import speech

    saved_key = os.environ.pop('OPENAI_API_KEY', None)
    try:
        # No key is the normal state, not a fault. It means "browser reads it".
        saved_router = os.environ.pop('OPENROUTER_API_KEY', None)
        check(speech.configured() is False, 'with no key at all the good voice is off')
        check(speech.say('anything') is None,
              'and asking for it returns nothing to play, not an error')

        # The key that already answers questions also reads them out. Nobody
        # has to sign up for a second account to be spoken to.
        os.environ['OPENROUTER_API_KEY'] = 'sk-or-test'
        url, models, key = speech.provider()
        check('openrouter.ai' in url and key == 'sk-or-test',
              'the OpenRouter key already in the deployment can speak')
        # More than one candidate, because the first name I picked was not
        # served and that took the whole feature down silently.
        check(len(models) > 1 and all('/' in m for m in models),
              f'with several models to try, by their own names ({models})')

        # A direct OpenAI key, if one is ever added, is one hop fewer and wins.
        os.environ['OPENAI_API_KEY'] = 'sk-test'
        url, models, key = speech.provider()
        check('api.openai.com' in url and key == 'sk-test',
              'a direct key takes precedence when there is one')
        check(speech.configured() is True, 'with a key it is on')
        if saved_router is None:
            os.environ.pop('OPENROUTER_API_KEY', None)

        # The allowance is spent before the call, so a request that times out
        # still costs its characters. A bill runs away the other way round.
        start = speech.used_this_month()
        speech._count(500)
        check(speech.used_this_month() == start + 500,
              'characters are counted against this month')

        # Past the cap it stops paying and falls back. It does not stop
        # speaking, and it does not tell anybody -- the browser picks it up.
        from models import BusinessSetting
        BusinessSetting.set(speech._month_key(), str(speech.CAP_CHARS))
        _dbcommit()
        check(speech.remaining() == 0, 'the month can be used up')
        before = speech.used_this_month()
        check(speech.say('hello there') is None,
              'and past it nothing is bought')
        check(speech.used_this_month() == before,
              'and nothing more is charged for either')

        # One answer can never be a large bill on its own.
        BusinessSetting.set(speech._month_key(), '0')
        _dbcommit()
        check(speech.MAX_ONE <= 1200,
              f'one answer is capped at {speech.MAX_ONE} characters')
        check(speech.CAP_CHARS <= 60000,
              f'and a company at {speech.CAP_CHARS} characters a month, '
              f'which is about 90 cents')
    finally:
        BusinessSetting.set(speech._month_key(), '0')
        _dbcommit()
        os.environ.pop('OPENAI_API_KEY', None)
        if saved_key is not None:
            os.environ['OPENAI_API_KEY'] = saved_key
    print('\n16. Nothing is done except what a person read and approved')
    import proposals, actions
    from models import AssistantProposal

    # An offer is written down before it is shown, and the page is handed a
    # token. Nothing about what to do travels through the browser.
    tok = proposals.offer('complete_booking', {'booking_id': 4321},
                          summary='Mark Ama on Tuesday as finished?',
                          label='Mark Ama finished', reversible=True)
    check(isinstance(tok, str) and len(tok) > 20, 'an offer returns a token')
    row = AssistantProposal.query.filter_by(token=tok).first()
    check(row is not None and row.action == 'complete_booking',
          'and the action is stored, not carried by the page')
    check('Mark Ama on Tuesday' in row.summary,
          'along with the exact sentence the person read')

    # Spent on use. A double-tap, a refresh or a replayed request does the
    # work once, which is the difference between an assistant and an accident.
    a, pay, r = proposals.take(tok)
    check(a == 'complete_booking' and pay == {'booking_id': 4321},
          'approving it gives back exactly what was offered')
    a2, _pay2, _r2 = proposals.take(tok)
    check(a2 is None, 'and the same token cannot be spent twice')
    check(proposals.why_not(tok) == 'already-done',
          'with a reason a person can act on, not just a refusal')

    # Offers go stale. An assistant that will still act on something you
    # glanced at yesterday is not one anybody should trust with a business.
    from datetime import datetime as _dt, timedelta as _td
    old_tok = proposals.offer('complete_booking', {'booking_id': 1})
    old_row = AssistantProposal.query.filter_by(token=old_tok).first()
    old_row.created_at = _dt.utcnow() - _td(minutes=proposals.TTL_MINUTES + 1)
    _dbcommit()
    check(proposals.take(old_tok)[0] is None, 'a stale offer will not run')
    check(proposals.why_not(old_tok) == 'stale',
          'and says it is stale rather than that it never existed')

    # A token nobody issued does nothing at all.
    check(proposals.take('not-a-real-token')[0] is None,
          'an invented token does nothing')
    check(proposals.take('')[0] is None, 'and neither does an empty one')

    # The model picks a name from a list. It cannot name its way into a
    # capability that does not exist, and every real one runs through one gate.
    check(actions.run('delete_everything', {})[0] is False,
          'an action that is not on the list does not run')
    check(actions.run('charge_all_cards', {})[0] is False,
          'however plausible the name sounds')
    for _name, _entry in actions.ACTIONS.items():
        check(callable(_entry[0]) and isinstance(_entry[2], bool),
              f'{_name} has a handler and says whether it can be undone')

    # A handler re-checks the world. The payload was true when it was written;
    # between the offer and the button the job can be finished by somebody else.
    ok, said = actions.run('complete_booking', {'booking_id': 999999})
    check(ok is False and 'not here' in said,
          'a job that has gone since it was offered is refused, not invented')
    print('\n17. She can write to a company she has not spoken to yet')
    from models import Prospect
    db.session.add(Prospect(business_name='Harbor Realty Group', city='Tampa',
                            status='new'))
    db.session.commit()

    # The commercial list somebody is actually working was the one table _who
    # did not search, so "draft an email to Harbor Realty Group" found nothing
    # to write from and came back asking for facts.
    found = assistant._who('Harbor Realty')
    check(found is not None, 'a prospect can be found by name')
    check(found and found['kind'] == 'prospect',
          'and is known to be a company nobody has called yet')

    # And she knows who *she* is. An introduction is written out of what the
    # business does, which was sitting in settings unread.
    from models import BusinessSetting
    BusinessSetting.set('business_name', 'Kojo Cleaning')
    BusinessSetting.set('city', 'Tampa')
    BusinessSetting.set('state', 'FL')
    db.session.commit()
    profile = assistant.business_profile()
    check(any('Kojo Cleaning' in f for f in profile),
          f'the profile says who the business is ({profile})')
    check(any('Tampa' in f for f in profile), 'and where it works')

    # The rule that broke it: "use only the facts, invent nothing" with no
    # facts meant refusing to write. It has to forbid inventing *specifics*,
    # not forbid writing sentences.
    src = open(os.path.join(ROOT, 'assistant.py')).read()
    draft_src = src[src.index('def draft_email'):src.index('def whats_next')]
    check('Never state a price' in draft_src,
          'prices, dates and promises still cannot be invented')
    check('an introduction is not made of database facts' in draft_src,
          'but writing an ordinary email is now the job, not a refusal')
    check('Use ONLY the facts below' not in draft_src,
          'the rule that produced "I have no facts to work with" is gone')
    print('\n19. A drafted email can be sent, and only by pressing send')
    import proposals as _pr2, actions as _ac2, prospecting as _psg
    from models import Prospect as _P

    pr = _P(business_name='Harborside Property Co', city='Tampa',
            email='dana@lakeview.test', contact_name='Dana', status='callback',
            category='property_manager',
            notes='[Sep 05] Spoke to Dana — wants a quote for 3 buildings.')
    db.session.add(pr)
    db.session.commit()

    # She now reads the call log, which is the difference between a follow-up
    # and a form letter.
    found = assistant._who('Harborside')
    check(found and found.get('prospect_id') == pr.id,
          'the prospect is found with its id')
    check(found and 'dana@lakeview.test' == found.get('email'),
          'and the address asked for on the call')
    check(found and 'three buildings' not in (found.get('notes') or '')
          and 'Dana' in (found.get('notes') or ''),
          'and the notes from the calls so far')

    # Nothing is sent by drafting. The offer is written down; the send only
    # happens when somebody presses the button.
    SENT.clear()
    token = _pr2.offer('send_prospect_email',
                       {'prospect_id': pr.id, 'to': pr.email,
                        'subject': 'Quote for your three buildings',
                        'body': 'Hello Dana, following up on our call.'},
                       summary='Send this to dana@lakeview.test?',
                       label='Send to dana@lakeview.test', reversible=False)
    check(SENT == [], 'writing the offer sends nothing')

    was_stage, was_next = pr.stage, pr.next_action
    act, pay, row = _pr2.take(token)
    ok, said = _ac2.run(act, pay)
    check(ok, f'pressing send does send it ({said})')
    check(len(SENT) == 1, 'exactly one email left the building')
    check(SENT[0] == ('email', 'dana@lakeview.test'),
          f'to the address that was on screen ({SENT[0]})')

    # The whole reason for sharing one implementation with the call screen: an
    # email is a touch, and a touch that schedules nothing is a thing sent
    # into a void.
    db.session.refresh(pr)
    check(pr.last_emailed_at is not None, 'the touch is recorded on the prospect')
    check('Emailed — Quote for your three buildings' in (pr.notes or ''),
          'the subject goes into the dated call log')
    check(pr.next_action == 'Follow up on the email' and pr.next_action_date,
          f'and a follow-up is scheduled ({pr.next_action_date})')

    # It cannot be sent twice, and the page is told it cannot be taken back.
    SENT.clear()
    act2, _p2, _r2 = _pr2.take(token)
    check(act2 is None and SENT == [], 'the same offer cannot be sent again')
    check(_ac2.ACTIONS['send_prospect_email'][2] is False,
          'sending is marked as something that cannot be undone')

    # Outreach goes out on the commercial identity, never the one a customer's
    # booking confirmation depends on.
    src = open(os.path.join(ROOT, 'prospecting.py')).read()
    check('brands.COMMERCIAL' in src,
          'outreach uses the commercial sender, not the residential one')
    print('\n20. The page shows it is working, and can be told to stop')
    page = open(os.path.join(ROOT, 'templates', 'admin', 'assistant.html')).read()
    css = open(os.path.join(ROOT, 'static', 'akye.css')).read()

    # A still ellipsis is indistinguishable from a page that did nothing, and
    # an advice question takes a few seconds to come back.
    check('class="thinking"' in page, 'a question shows something moving')
    check('@keyframes nana-think' in css, 'and it actually animates')
    check('prefers-reduced-motion' in css, 'unless the device asked it not to')

    # Stopping matters more than starting: a customer walks in while an answer
    # about their bill is being read aloud.
    check('function hush()' in page, 'speech can be stopped')
    check('speechSynthesis.cancel()' in page and 'player.pause()' in page,
          'and both kinds of voice are stopped, not just one')
    check('showHush(true)' in page, 'the stop button appears when speech starts')

    # Which voice, when the device has more than one worth choosing between.
    check("localStorage.setItem('nana-voice'" in page, 'a chosen voice is remembered')
    check('pool.length < 2' in page,
          'and no menu is offered when there is nothing to choose between')

    print('\n21. A model that thinks before it writes is given room to')
    src = open(os.path.join(ROOT, 'assistant.py')).read()
    # gpt-5-mini spends tokens reasoning out of the same budget. At 600 it
    # spent the lot and returned an empty message, so every piece of advice
    # fell back to the raw fact list -- the exact wall of numbers this mode
    # was built to replace.
    check('THINK_MODEL, 2000' in src, 'the thinking budget covers thinking')
    check("'reasoning': {'effort': 'low'}" in src,
          'and it is told to think briefly rather than at length')
    check('returned nothing to say' in src,
          'an empty answer is recorded rather than silently falling back')

    # And the voice tries more than one name, because being wrong about one
    # should cost a retry, not the feature.
    sp = open(os.path.join(ROOT, 'speech.py')).read()
    check('ROUTER_MODELS' in sp and sp.count(',') > 0,
          'the voice has more than one model to try')
    check('_remember(model)' in sp, 'and remembers the one that answers')
    check('no voice model answered' in sp,
          'and says so somewhere a person can read when none do')
    print('\n22. She thinks in more than one step now')
    import agent, requests as _rq3
    _real3 = _rq3.post
    os.environ['OPENROUTER_API_KEY'] = 'sk-or-v1-test'

    class _R3:
        def __init__(self, p): self._p = p; self.status_code = 200
        def json(self): return self._p

    def _tool_call(name, args=None):
        return {'choices': [{'message': {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {
                    'name': name, 'arguments': json.dumps(args or {})}}]},
                'finish_reason': 'tool_calls'}]}

    def _final(text):
        return {'choices': [{'message': {'role': 'assistant', 'content': text},
                             'finish_reason': 'stop'}]}

    try:
        # The whole point: look something up, see the answer, look up something
        # else, then reply. The old Nana got exactly one pass and could never
        # react to what she found.
        steps = {'n': 0}
        sent = []
        def post(url, **kw):
            steps['n'] += 1
            sent.append(kw.get('json') or {})
            if steps['n'] == 1:
                return _R3(_tool_call('money_owed'))
            if steps['n'] == 2:
                return _R3(_tool_call('unassigned_jobs'))
            return _R3(_final('Chase the money owed first — it is already earned.'))
        _rq3.post = post
        out = assistant.ask('what should I chase first?')
        check(steps['n'] == 3, f'she took several turns, not one ({steps["n"]})')
        check(out['say'].startswith('Chase the money owed'),
              'and answered in her own words at the end')
        # Each result went back to her before she decided again.
        roles = [m['role'] for m in sent[-1]['messages']]
        check('tool' in roles, 'the tool results were handed back to her')
        check(sent[0].get('tools'), 'and she was offered the tools to begin with')

        # General knowledge is allowed now. This was the gag.
        _rq3.post = lambda url, **kw: _R3(_final(
            'Most companies charge around $150 to $250 for a move-out clean, '
            'so you are not far off.'))
        out = assistant.ask('what should I charge for a move-out?')
        check('150' in out['say'],
              'she can answer a question her database cannot')

        # And the rule that did not change.
        _rq3.post = lambda url, **kw: _R3(_final('You made $9,900 this month.'))
        out = assistant.ask('how much did I make?')
        check('9,900' not in out['say'],
              'a figure about their books that no tool produced is still dropped')

        # An action still comes back as a button, not as something done.
        # A fresh job: earlier tests finished the other ones.
        job('Nadia Owusu', today - timedelta(days=1), 210.0)
        SENT.clear()
        _rq3.post = lambda url, **kw: _R3(_tool_call('finish_job', {'customer': 'Nadia'}))
        out = assistant.ask('mark Nadia finished')
        check('confirm' in out and out['confirm'].get('token'),
              'an action is still offered as a token to press')
    finally:
        _rq3.post = _real3
        os.environ.pop('OPENROUTER_API_KEY', None)

    print('\n23. A conversation, and a way to end it')
    check(agent.MEMORY_TURNS >= 4, 'she carries several turns of context')
    routes = open(os.path.join(ROOT, 'blueprints', 'assistant_routes.py')).read()
    check("session.get('nana_history')" in routes, 'the last turns are remembered')
    check('MEMORY_TURNS * 2' in routes, 'and trimmed, so a long session is not a long bill')
    check("session.pop('nana_history'" in routes,
          'and there is a way to make her forget')
    page = open(os.path.join(ROOT, 'templates', 'admin', 'assistant.html')).read()
    check('Start over' in page, 'which the page offers as Start over')
    check('function goodOnes' in page,
          'the voice list is trimmed to the few worth choosing between')
print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ It reads the books, says what it found, and presses nothing.')
