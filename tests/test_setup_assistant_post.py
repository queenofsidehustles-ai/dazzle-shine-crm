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
llm.post = lambda body, timeout=30: (sent.append((body, timeout)) or {'type': 'message', 'content': []})
out = setup_assistant._post({'model': 'm'}, timeout=7)
check(out == {'type': 'message', 'content': []}, 'the reply is returned as it came')
check(sent == [({'model': 'm'}, 7)], 'with the body and timeout the caller chose')

print('\n2. An error answer comes back in the shape the callers read')
def boom(body, timeout=30):
    raise llm.ClaudeError('credit balance is too low')
llm.post = boom
out = setup_assistant._post({'model': 'm'})
check(out.get('type') == 'error' and 'credit balance' in out['error']['message'],
      'an API error is an error-shaped dict, not an exception')

print('\n3. Not being able to reach Claude still raises')
def down(body, timeout=30):
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
check('requests.post' not in inspect.getsource(setup_assistant._post),
      'no private request of its own any more')
llm.post = real
src = inspect.getsource(real)
check('429' in src and '529' in src, 'and the shared one is the one that retries 429 and 529')

print()
if failures:
    print(f'❌ {len(failures)} failed')
    sys.exit(1)
print('✅ The setup chat shares Claude\'s request, retry and error handling.')
