"""Nana on the Claude API: same tools, same rules, different wire format.

With ANTHROPIC_API_KEY set, every question goes to Claude and nothing goes to
OpenRouter. The figure check still throws away a number no tool produced.
Writing helpers (email drafts, translation) use Claude too. Without the key,
nothing here changes -- test_assistant.py covers that path.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/nana.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
os.environ.pop('OPENROUTER_API_KEY', None)
sys.path.insert(0, ROOT)

import requests
OPENROUTER_CALLS = []
_real_post = requests.post
def _guard(url, *a, **k):
    OPENROUTER_CALLS.append(url)
    raise AssertionError(f'unexpected HTTP call to {url}')
requests.post = _guard

from app import create_app
from extensions import db
from models import Booking, Staff, BusinessSetting
import assistant, agent, llm

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SCRIPT, SENT = [], []


def fake_post(body, timeout=30):
    SENT.append(body)
    if not SCRIPT:
        raise llm.ClaudeError('script empty')
    nxt = SCRIPT.pop(0)
    if isinstance(nxt, Exception):
        raise nxt
    return nxt


llm.post = fake_post


def tool(name, inp=None, tid='t1', text=None):
    content = ([{'type': 'text', 'text': text}] if text else []) + [
        {'type': 'tool_use', 'id': tid, 'name': name, 'input': inp or {}}]
    return {'content': content, 'stop_reason': 'tool_use'}


def say(text):
    return {'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn'}


with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Sparkle Co')
    db.session.add(Staff(name='Ama Owusu', phone='4075550111', is_active=True))
    db.session.commit()

print('\n1. Switched on by the Claude key alone')
with app.app_context():
    check(assistant.configured(), 'Nana counts as configured with only ANTHROPIC_API_KEY')

print('\n2. A lookup: tool, then an answer built on what the tool said')
with app.app_context(), app.test_request_context():
    SCRIPT[:] = [tool('team', text='Let me check your team.'),
                 say('Your team right now is Ama Owusu.')]
    out = agent.run('who is on my team?')
check(out['say'] == 'Your team right now is Ama Owusu.', 'answer is the final reply, not the "let me check" line')
check(SENT[0]['model'] == llm.SMART_MODEL, 'uses the Nana model')
check(SENT[0]['system'][0].get('cache_control'), 'system prompt is cached')
check(SENT[0]['tools'][-1].get('cache_control'), 'tool list is cached')
check(SENT[1]['messages'][-1]['content'][0]['type'] == 'tool_result', 'tool result handed back')
days = [t for t in SENT[0]['tools'] if t['name'] == 'jobs_on'][0]
check(days['input_schema']['properties']['day'].get('enum') == ['today', 'tomorrow', 'yesterday'],
      'tools tell Claude what each argument accepts')
check(not OPENROUTER_CALLS, 'nothing went to OpenRouter')

print('\n3. An invented figure is caught and corrected')
SENT.clear()
with app.app_context(), app.test_request_context():
    SCRIPT[:] = [tool('team'),
                 say('Ama Owusu has cleaned 37 homes for you.'),
                 say('Ama Owusu is on your team.')]
    out = agent.run('tell me about my team')
check(out['say'] == 'Ama Owusu is on your team.', 'the corrected answer is shown')
check('37' in SENT[-1]['messages'][-1]['content'], 'Claude was told which sentence was wrong')
check(SENT[-1].get('tools') and SENT[-1].get('tool_choice') == {'type': 'none'},
      'the retry declares tools (required with tool history) but cannot call one')
check(SENT[-1]['messages'][-2]['content'] == 'Ama Owusu has cleaned 37 homes for you.',
      'the retry quotes only the rejected answer, not earlier preamble')

print('\n3b. Out of steps, she is asked for an answer rather than showing a preamble')
SENT.clear()
with app.app_context(), app.test_request_context():
    SCRIPT[:] = [tool('team', tid=f's{i}', text='Let me check.') for i in range(agent.MAX_STEPS)] + [
        say('Ama Owusu is on your team.')]
    out = agent.run('team please')
check(out['say'] == 'Ama Owusu is on your team.', 'final answer, not "Let me check."')
check(SENT[-1].get('tool_choice') == {'type': 'none'}, 'the last call forbids more lookups')

print('\n3c. Markdown bold is stripped, and today is known')
with app.app_context(), app.test_request_context():
    SCRIPT[:] = [say('**Ama Owusu** is on your team.')]
    out = agent.run('team')
check(out['say'] == 'Ama Owusu is on your team.', 'no asterisks on the page')
check('Today is ' in SENT[-1]['system'][0]['text'], 'the prompt tells her today\'s date')

with app.app_context(), app.test_request_context():
    SCRIPT[:] = [tool('team'), say('You made $9,999 from Ama Owusu.'),
                 say('Still $9,999 from Ama Owusu.')]
    out = agent.run('how is ama doing')
check('9,999' not in out['say'], 'a figure that survives the retry never reaches the screen')

print('\n4. Every tool call is answered, even past the limit')
SENT.clear()
with app.app_context(), app.test_request_context():
    SCRIPT[:] = [{'content': [{'type': 'tool_use', 'id': f'u{i}', 'name': 'team', 'input': {}}
                              for i in range(6)], 'stop_reason': 'tool_use'},
                 say('Ama Owusu.')]
    agent.run('team?')
res = SENT[1]['messages'][-1]['content']
check(len(res) == 6 and sum(1 for r in res if r.get('is_error')) == 2,
      'six calls, six answers, two marked not run')

print('\n5. History is turned into turns Claude accepts')
msgs = agent._alternate([{'role': 'assistant', 'content': 'hi'},
                         {'role': 'user', 'content': 'a'}, {'role': 'user', 'content': 'b'},
                         {'role': 'assistant', 'content': 'c'},
                         {'role': 'user', 'content': 'dangling'}])
check([m['role'] for m in msgs] == ['user', 'assistant'], 'starts with the owner, alternates, no dangling turn')

print('\n6. When Claude is down she says so plainly')
with app.app_context(), app.test_request_context():
    SCRIPT[:] = [llm.ClaudeError('overloaded')]
    out = agent.run('hello')
check(out['say'] == assistant.TROUBLE['service-error'], 'service error sentence')
with app.app_context(), app.test_request_context():
    SCRIPT[:] = [llm.ClaudeUnreachable('timeout')]
    out = agent.run('hello')
check(out['say'] == assistant.TROUBLE['unreachable'], 'a timeout says it could not reach her')

print('\n7. Email drafts and translation are written by Claude')
with app.app_context(), app.test_request_context():
    SCRIPT[:] = [say('Subject: Cleaning for your offices\n\nHi there, we clean offices.')]
    out = assistant.draft_email(about='introduce us', to='Harbor Realty')
check(out.get('draft', {}).get('subject') == 'Cleaning for your offices', 'draft subject split off')
check(SENT[-1]['model'] == llm.FAST_MODEL, 'drafts use the fast model')
import translate
SCRIPT[:] = [say('Hola, mañana a las 9.')]
check(translate.translate('Hi, tomorrow at 9.', 'es') == 'Hola, mañana a las 9.', 'translation via Claude')
SCRIPT[:] = [llm.ClaudeError('down')]
check(translate.translate('Hi there', 'es') == 'Hi there', 'and fails soft to the original')

print('\n8. The demo never spends credits')
import demo_guard
_orig = demo_guard.active
demo_guard.active = lambda: True
try:
    check(not llm.ready(), 'Claude is not ready in the demo')
finally:
    demo_guard.active = _orig

check(not OPENROUTER_CALLS, 'and nothing at all went to OpenRouter')
requests.post = _real_post

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ All Nana-on-Claude tests passed.')
