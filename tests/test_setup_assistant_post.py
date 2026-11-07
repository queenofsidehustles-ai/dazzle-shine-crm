"""The setup chat talks to Claude the way everything else does.

It used to make its own request, so unlike Ask Nana it did not retry when Claude
answered "busy" (429/529), and it did not share what llm.py knows about errors.
`_post` now goes through llm.post, and must keep two things the callers rely on:
an error answer comes back as an error-shaped dict (so "Claude answered with an
error" is told apart from "Claude could not be reached"), and an unreachable
Claude still raises.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
os.environ.pop('DATABASE_URL', None)

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


import llm
import setup_assistant

real = llm.post
sent = []

print('\n1. A good answer passes straight through')
llm.post = lambda body, timeout=30, budget=None: (sent.append((body, timeout)) or {'type': 'message', 'content': []})
out = setup_assistant._post({'model': 'm'}, timeout=7)
check(out == {'type': 'message', 'content': []}, 'the reply is returned as it came')
check(sent == [({'model': 'm'}, 7)], 'with the body and timeout the caller chose')

print('\n2. An error answer comes back in the shape the callers read')
def boom(body, timeout=30, budget=None):
    raise llm.ClaudeError('credit balance is too low')
llm.post = boom
out = setup_assistant._post({'model': 'm'})
check(out.get('type') == 'error' and 'credit balance' in out['error']['message'],
      'an API error is an error-shaped dict, not an exception')

print('\n3. Not being able to reach Claude still raises')
def down(body, timeout=30, budget=None):
    raise llm.ClaudeUnreachable('could not reach Claude: Timeout')
llm.post = down
try:
    setup_assistant._post({'model': 'm'})
    raised = False
except llm.ClaudeUnreachable:
    raised = True
check(raised, 'so the chat can say it could not reach her, which is a different sentence')

print('\n4. It goes through the shared request, which retries a busy answer once')
import inspect
check('requests.post' not in inspect.getsource(setup_assistant._post) and 'budget=' in inspect.getsource(setup_assistant._post),
      'no private request of its own any more')
llm.post = real
src = inspect.getsource(real)
check('429' in src and '529' in src, 'and the shared one is the one that retries 429 and 529')

print('\n5. A busy answer is retried only inside the time the step has left')
import time as _time
llm.post = real
class _Resp:
    status_code = 529
    def json(self):
        return {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'Overloaded'}}
calls, slept = [], []
import requests
_real_requests_post, _real_sleep = requests.post, _time.sleep
def fake_requests_post(url, timeout=None, **kw):
    calls.append(timeout)
    return _Resp()
requests.post = fake_requests_post
_time.sleep = lambda s: slept.append(s)
try:
    # 20s budget, first attempt "took" no time: the retry has ~18.5s left
    try:
        real({'model': 'm'}, timeout=20, budget=20)
    except llm.ClaudeError:
        pass
    check(len(calls) == 2 and calls[1] <= 20 - llm.RETRY_PAUSE + 0.01,
          f'with room, it retries once, within what is left ({calls})')
    calls.clear()
    # a budget too small for a retry: no second attempt at all
    try:
        real({'model': 'm'}, timeout=2, budget=2)
    except llm.ClaudeError as e:
        small_err = str(e)
    check(len(calls) == 1 and 'Overloaded' in small_err,
          'with no room, it does not retry, and says what Claude said')
    calls.clear()
    try:
        real({'model': 'm'}, timeout=20)
    except llm.ClaudeError:
        pass
    check(len(calls) == 2 and calls[1] == 20, 'callers with no budget behave exactly as before')
finally:
    requests.post, _time.sleep = _real_requests_post, _real_sleep

print()
if failures:
    print(f'❌ {len(failures)} failed')
    sys.exit(1)
print('✅ The setup chat shares Claude\'s request, retry and error handling.')
