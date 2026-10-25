"""Nana's "how do I..." answers: steps, Show me, the right model, nothing leaked.

From Monica, 2026-10-25, after a side-by-side test of 20 real questions.

What this holds:
- A "how do I" question is answered on the how-to model (Sonnet 5.5) at its
  lowest thinking level; a question about the business is not.
- The help lookup hands back a step-by-step guide, numbered, with a Show me
  button that opens the first step's page with the tour on.
- The guide behind Show me is served only to somebody signed in.
- When the figure check asks for a rewrite, nothing about the check reaches
  the owner -- the leak the test found ("That sentence doesn't contain a
  figure about your business...").
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/howto.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
import agent, llm, help_guide, howto

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


sent = []


def fake_post(body, timeout=30):
    """Claude, played back: answer straight away, no tools."""
    sent.append(body)
    return {'content': [{'type': 'text', 'text': 'Press New booking, then Save.'}],
            'stop_reason': 'end_turn', 'usage': {}}


llm.post = fake_post

with app.app_context(), app.test_request_context():
    db.create_all()

    print('\n1. "How do I" goes to the how-to model, at low effort')
    sent.clear()
    agent.run_claude('How do I book a job?')
    check(sent and all(b['model'] == llm.HOWTO_MODEL for b in sent),
          f'answered on {llm.HOWTO_MODEL}')
    check(llm.HOWTO_MODEL == 'claude-sonnet-5-5', 'which is Sonnet 5.5 by default')
    check(sent and all(b.get('output_config') == {'effort': 'low'} for b in sent),
          'at the lowest thinking level')
    check(all('thinking' not in b and 'temperature' not in b for b in sent),
          'with no setting Sonnet 5.5 refuses (thinking off, temperature)')

    print('\n2. A question about the business stays on the everyday model')
    sent.clear()
    agent.run_claude('What did I make this month?')
    check(sent and all(b['model'] == llm.SMART_MODEL for b in sent),
          f'answered on {llm.SMART_MODEL}')
    check(all('output_config' not in b for b in sent), 'with nothing extra sent')
    for q, want in [('how to send a quote', True), ('Show me how to pay my cleaners', True),
                    ('Where do I change my prices?', True), ('who is free tomorrow', False),
                    ('Write a Facebook post', False)]:
        check(agent.is_howto(q) is want, f'"{q}" is {"" if want else "not "}a how-to question')

    print('\n3. The help lookup gives steps and a Show me button')
    text, link = help_guide.answer('How do I book a job?')
    check('step by step' in text and '\n1. ' in text, 'numbered steps')
    check(link and link[0] == 'Show me', 'a Show me button')
    check(link and link[1].startswith('/') and 'tour=book-job' in link[1],
          f'that opens the first page with the tour on ({link and link[1]})')
    check(howto.validate() == [], f'the guides are well formed: {howto.validate()}')

print('\n3b. The answer carries the Show me button to the chat')
turns = iter([
    {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'how_to',
                  'input': {'question': 'How do I book a job?'}}], 'stop_reason': 'tool_use', 'usage': {}},
    {'content': [{'type': 'text', 'text': '1. Open Bookings and press New Booking.\n2. Press Book it.'}],
     'stop_reason': 'end_turn', 'usage': {}},
])
llm.post = lambda body, timeout=30: next(turns)
with app.app_context(), app.test_request_context():
    out = agent.run_claude('How do I book a job?')
btn = out.get('link') or (out.get('proposal') or {}).get('link')
check(btn and btn.get('label') == 'Show me' and 'tour=book-job' in btn.get('href', ''),
      f'a Show me button comes back with the answer ({btn})')
llm.post = fake_post

print('\n3c. Asked again, answered from the chat without a lookup: the button still comes')
llm.post = fake_post   # answers straight away, never calls how_to
with app.app_context(), app.test_request_context():
    again = agent.run_claude('How do I book a job?',
                             history=[{'role': 'user', 'content': 'How do I book a job?'},
                                      {'role': 'assistant', 'content': '1. Open Bookings...'}])
btn = again.get('link') or {}
check(btn.get('label') == 'Show me' and 'tour=book-job' in btn.get('href', ''),
      f'Show me is on the repeat answer too ({btn})')
with app.app_context(), app.test_request_context():
    other = agent.run_claude('What did I make this month?')
check(not other.get('link'), 'and a question about the business gets no Show me')

print('\n3d. A how-to with no guide says so, and is noted for the console')
import control_plane
noted = []
real_note = control_plane.record_howto_miss
control_plane.record_howto_miss = lambda engine, slug, q: noted.append(q)
llm.post = fake_post
with app.app_context(), app.test_request_context():
    none = agent.run_claude('How do I make a birthday card for a customer?')
    expl = agent.run_claude('What happens if it rains on the day?')
    biz = agent.run_claude('Who is free tomorrow?')
control_plane.record_howto_miss = real_note
check(agent.NO_WALKTHROUGH in none['say'] and not none.get('link'),
      'no guide: the answer says there is no walkthrough, and has no button')
check('no_walkthrough' not in none, 'the internal flag never reaches the page')
check(noted == ['How do I make a birthday card for a customer?'],
      f'and only that question was noted for the console ({noted})')
check(agent.NO_WALKTHROUGH not in expl['say'] and agent.NO_WALKTHROUGH not in biz['say'],
      '"what happens if" and business questions get no such note')

print('\n4. The guide behind Show me needs a login')
c = app.test_client()
r = c.get('/help/tour/book-job.json')
check(r.status_code in (302, 401, 403), f'signed out, it is not served ({r.status_code})')
with c.session_transaction() as s:
    s['logged_in'] = True
    s['role'] = 'owner'
r = c.get('/help/tour/book-job.json')
j = r.get_json() or {}
check(r.status_code == 200 and j.get('key') == 'book-job' and j.get('steps'),
      'signed in, it is')
check(set(j['steps'][0]) == {'say', 'page', 'start', 'target'}, 'and carries only what the page needs')
check(c.get('/help/tour/nope.json').status_code == 404, 'an unknown guide is a 404')

print('\n5. A rewrite never shows the owner the check')
leaked = ("That sentence doesn't contain a figure about your business. It comes from the "
          "Akye help guide and describes how the import works. Here is the answer again "
          "without it.\n\nUse the Migration Toolbox, which takes a CSV file.\n\n"
          "Give each cleaner a different name.")
clean = agent._strip_meta(leaked)
check('sentence' not in clean.lower() and 'figure' not in clean.lower(),
      'the paragraph about the check is gone')
check(clean.startswith('Use the Migration Toolbox') and 'different name' in clean,
      'and the answer itself is kept')
check(agent._strip_meta('Press New booking.\n\nThen press Save.') ==
      'Press New booking.\n\nThen press Save.', 'an ordinary answer is left alone')
check('Do not mention this request' in agent.RETRY_ONLY_ANSWER, 'and the rewrite request says so up front')

print()
if failures:
    print(f'❌ {len(failures)} how-to check(s) failed')
    sys.exit(1)
print('✅ how-to answers hold')
