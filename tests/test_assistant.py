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
import os, re, sys, tempfile
from datetime import datetime, date, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/kye.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (SENT.append('sms'), (True, 'stub'))[1]
notifications.send_email = lambda *a, **k: (SENT.append('email'), (True, 'stub'))[1]

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
    picks, problem = assistant.choose('anything', api_key='')
    check(not picks, 'with no key it declines rather than guessing')
    for made_up in ('delete_everything', 'charge_all_cards', '', None):
        check(made_up not in assistant.TOOLS,
              f'{made_up!r} is not a tool it could pick')

    print('\n4. It will not send anything')
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
    check('do not send' in out['say'], 'and says plainly that it does not send')
    check('facts' in out['draft'],
          'showing what it was working from, so the words can be checked')
    check(SENT == [], 'nothing left the building')

    print('\n5. Finishing a job is offered, not done')
    out = assistant.finish_job(customer='Owes Money')
    check('confirm' in out, 'it comes back as something to confirm')
    check(out['confirm']['action'] == 'complete_booking', 'naming the action')
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
    check(ar.ACTIONS == ('complete_booking',), f'one allowed action: {ar.ACTIONS}')
    r = c.post('/ask/confirm', data={'action': 'charge_everything'},
               follow_redirects=True)
    check(r.status_code == 200, 'an action not on the list is refused, not run')

    b = Booking.query.filter_by(name='Owes Money').first()
    check(b.status == 'confirmed', 'and nothing happened to the job')
    c.post('/ask/confirm', data={'action': 'complete_booking', 'booking_id': b.id},
           follow_redirects=True)
    db.session.expire_all()
    b = Booking.query.get(b.id)
    check(b.status == 'completed', 'the real one, pressed by a person, does work')

    # Pressing it twice should say so rather than pretend.
    r = c.post('/ask/confirm', data={'action': 'complete_booking', 'booking_id': b.id},
               follow_redirects=True)
    check(b'already completed' in r.data, 'and a second press says it is already done')

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
    check('never sends one' in page, 'and that she does not send email')
    check('Nothing leaves without you' in page, 'and that nothing leaves without you')

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
        picks, problem = assistant.choose('any new enquiries?')
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

    print('\n13. Nana writes the answer; the books still write the numbers')
    # The router may now pull several lookups, because "what is my game plan
    # this week" is not one lookup and pretending it was is what made her dull.
    import json as _json

    class _Reply:
        def __init__(self, payload): self._p = payload; self.status_code = 200
        def json(self): return self._p

    def _fake(route_json, written):
        """Stand in for OpenRouter: first call routes, second call writes."""
        calls = {'n': 0}
        def post(url, **kw):
            calls['n'] += 1
            body = route_json if calls['n'] == 1 else written
            return _Reply({'choices': [{'message': {'content': body}}]})
        return post, calls

    import requests as _rq
    _real_post = _rq.post
    os.environ['OPENROUTER_API_KEY'] = 'sk-or-v1-test'
    try:
        # --- routing ---------------------------------------------------------
        _rq.post, _ = _fake('{"tools":[{"tool":"money_owed","args":{}},'
                            '{"tool":"unassigned_jobs","args":{}}]}', 'x')
        picks, problem = assistant.choose('how are we doing?')
        check(problem is None and [p[0] for p in picks]
              == ['money_owed', 'unassigned_jobs'],
              'one question can pull several lookups')

        _rq.post, _ = _fake('{"tool":"money_owed","args":{}}', 'x')
        picks, _ = assistant.choose('what is owed?')
        check([p[0] for p in picks] == ['money_owed'],
              'the old single-tool shape still works')

        # An action changes something or produces something to send. It is
        # never blended into a summary with three lookups.
        _rq.post, _ = _fake('{"tools":[{"tool":"money_owed","args":{}},'
                            '{"tool":"finish_job","args":{"customer":"Ama"}}]}', 'x')
        picks, _ = assistant.choose('mark Ama done')
        check([p[0] for p in picks] == ['finish_job'], 'an action travels alone')

        _rq.post, _ = _fake('{"tools":[' + ','.join(
            '{"tool":"%s","args":{}}' % t for t in
            ['money_owed', 'team', 'unassigned_jobs', 'jobs_this_week',
             'leads_waiting', 'money_made']) + ']}', 'x')
        picks, _ = assistant.choose('everything')
        check(len(picks) <= assistant.MAX_TOOLS,
              f'no more than {assistant.MAX_TOOLS} lookups in one answer')

        # --- the guardrail, through the front door ---------------------------
        # A figure it worked out itself never reaches the page. The owner still
        # gets an answer -- the computed lines -- rather than an error.
        _rq.post, calls = _fake('{"tools":[{"tool":"money_owed","args":{}}]}',
                                'You are owed $99,999.00, so chase it today.')
        owed_now = assistant.money_owed()
        out = assistant.ask('what is owed?')
        check('99,999' not in out['say'] and '99999' not in out['say'],
              'an invented figure is dropped, not shown')
        check(out['say'] == owed_now,
              'and the computed line from the books is shown instead')

        # Her wording, built only from figures that are really in the books.
        real = re.search(r'\$[\d,]+\.\d\d', owed_now).group(0)
        _rq.post, _ = _fake('{"tools":[{"tool":"money_owed","args":{}}]}',
                            f'Chase the {real} — it is money you have earned.')
        out = assistant.ask('what is owed?')
        check(out['say'] == f'Chase the {real} — it is money you have earned.',
              'an answer whose figures check out is shown in her words')
        check(out.get('facts'), 'and the computed lines come back with it')
    finally:
        _rq.post = _real_post
        os.environ.pop('OPENROUTER_API_KEY', None)
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
        url, model, key = speech.provider()
        check('openrouter.ai' in url and key == 'sk-or-test',
              'the OpenRouter key already in the deployment can speak')
        check('/' in model,
              f'using its own name for the model ({model})')

        # A direct OpenAI key, if one is ever added, is one hop fewer and wins.
        os.environ['OPENAI_API_KEY'] = 'sk-test'
        url, model, key = speech.provider()
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
print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ It reads the books, says what it found, and presses nothing.')
