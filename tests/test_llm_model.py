"""The model name is real, and a wrong one is loud.

A model name typed from memory once reached production as
'anthropic/claude-3.5-haiku', which does not exist, and nothing showed it,
because every caller turns an API error into an apology or into the
untranslated text. (#111 then took 'claude-haiku-5-5' for another such name.
It is a published model, Claude Haiku 5.5; the defaults stay on Haiku 4.5
until a switch is measured, and Console -> Health's check is what says whether
this account can use a given model.)

What this holds:
- Every model this deployment would send to Anthropic is a published name.
- llm.check() reports the failure instead of hiding it, and says which model.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import llm
import setup_assistant

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


# Anthropic's published model ids. Add to this from the model list
# (GET /v1/models), never from memory -- that is the bug this file exists for.
KNOWN = {
    'claude-fable-5-1', 'claude-fable-5',
    'claude-opus-5-5', 'claude-opus-5', 'claude-opus-4-8', 'claude-opus-4-7', 'claude-opus-4-6',
    'claude-sonnet-5-5', 'claude-sonnet-5', 'claude-sonnet-4-6',
    'claude-haiku-5-5', 'claude-haiku-4-5',
}

print('\n1. Every configured model is a real one')
for label, name in (('Nana (SMART_MODEL)', llm.SMART_MODEL),
                    ('short writing (FAST_MODEL)', llm.FAST_MODEL),
                    ('setup chat', setup_assistant.MODEL)):
    check(name in KNOWN, f'{label} is a published model name: {name}')

print('\n2. A model that does not exist is reported, not swallowed')
os.environ['ANTHROPIC_API_KEY'] = 'test-key'
real_post = llm.post


def refuses(body, timeout=30):
    raise llm.ClaudeError('model: claude-not-a-model')


llm.post = refuses
ok, detail = llm.check()
check(not ok, 'check() fails when the API refuses the model')
check('claude-not-a-model' in detail or llm.SMART_MODEL in detail,
      'the failure names the model that was refused')

print('\n3. Unreachable is a failure too, not a shrug')


def unreachable(body, timeout=30):
    raise llm.ClaudeUnreachable('could not reach Claude: ConnectTimeout')


llm.post = unreachable
ok, detail = llm.check()
check(not ok and 'reach' in detail, 'a network failure is reported')

print('\n4. A real answer passes')


def answers(body, timeout=30):
    check(body.get('max_tokens') == 1, 'the test question costs one token')
    check(body.get('model') == llm.SMART_MODEL, 'it asks on the configured model')
    return {'content': [{'type': 'text', 'text': 'hi'}], 'stop_reason': 'max_tokens'}


llm.post = answers
ok, detail = llm.check()
check(ok and llm.SMART_MODEL in detail, 'check() passes and says which model answered')

print('\n5. No key is a clear answer, not a crash')
llm.post = real_post
os.environ.pop('ANTHROPIC_API_KEY', None)
ok, detail = llm.check()
check(not ok and 'ANTHROPIC_API_KEY' in detail, 'a missing key says so')

if failures:
    print(f'\n❌ {len(failures)} model check(s) failed')
    sys.exit(1)
print('\n✅ All model name tests passed.')
