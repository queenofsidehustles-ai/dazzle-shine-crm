"""Two different faults are two rows, when there is no line to tell them apart.

assistant._record builds a RuntimeError and never raises it, so it arrives at
errors.capture with no traceback. The fingerprint was endpoint + type + line,
and with no line every Nana failure hashed the same: unreachable, a model that
does not exist, and an empty reply were one row, count incremented, message
overwritten by whichever happened last. Alerting is once per fingerprint per
day, so whichever failure came second that day was silent. That is how a model
name that did not exist ran in production for a day without an alert.

What this holds:
- Built exceptions are told apart by the shape of their message.
- The particulars still do not matter: two bad model names are one fault.
- Raised exceptions are unchanged -- still grouped by line, never by message.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import errors

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def built(msg, endpoint='setup_assistant.ask'):
    """What assistant._record produces: constructed, never raised."""
    return errors.fingerprint(endpoint, RuntimeError(msg))


def raised(msg, endpoint='bookings.client'):
    try:
        raise ValueError(msg)
    except ValueError as e:
        return errors.fingerprint(endpoint, e)


print('\n1. Nana failures with different causes are different rows')
unreachable = built('Nana: setup assistant could not reach Claude: ConnectTimeout')
no_model = built('Nana: setup assistant: model: claude-haiku-5-5')
silent = built('Nana: setup assistant said nothing (stop_reason=max_tokens)')
check(len({unreachable, no_model, silent}) == 3,
      'unreachable, a missing model and an empty reply are three faults')

print('\n2. The particulars still do not matter')
check(built('Nana: setup assistant: model: claude-haiku-5-5')
      == built('Nana: setup assistant: model: claude-haiku-9-9'),
      'the same wrong model guessed at two versions is one fault')
check(built('Nana: setup assistant: model: claude-haiku-5-5')
      != built('Nana: setup assistant: model: claude-sonnet-5-5'),
      'but a different model family is a different misconfiguration')
check(built('action failed: complete_booking 41')
      == built('action failed: complete_booking 87'),
      'the same action failing on two records is one fault')

print('\n3. The same fault twice is still one row')
check(unreachable == built('Nana: setup assistant could not reach Claude: ConnectTimeout'),
      'an identical failure keeps its fingerprint')

print('\n4. Where it happened still counts')
check(built('Nana: x', 'setup_assistant.ask') != built('Nana: x', 'assistant.ask'),
      'the same message from two endpoints is two faults')

print('\n5. Raised exceptions are unchanged')
check(raised('Client 41 not found') == raised('Client 87 not found'),
      'a real traceback still groups by line, not by message')

if failures:
    print(f'\n❌ {len(failures)} fingerprint check(s) failed')
    sys.exit(1)
print('\n✅ Faults are filed apart when nothing else can tell them apart.')
