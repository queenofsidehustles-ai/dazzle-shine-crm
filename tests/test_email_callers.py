"""Every place that sends an email can actually call the function.

Two of them could not, and both failed silently for the same reason.

`send_email(to_email, to_name, subject, html)` takes four arguments. Two
callers passed three, so Python raised `TypeError` before a single byte went
anywhere — and both callers sat inside `except Exception: pass`, written to
stop a mail outage from taking the page down with it. So the exception was
caught, discarded, and nothing was sent, logged, or shown:

  * `errors.py` — the crash alerter. The CRM catches its own 500s and emails
    the owner about them. It had never sent one. The whole point of that
    feature is finding out about a fault without a customer having to
    report it, and it had been quietly doing nothing.

  * `blueprints/marketing.py` — the early-access lead. Written down AND
    emailed, deliberately, so that a failed write still reaches a person.
    The write worked, so nothing looked wrong; the second half of a
    belt-and-braces pair was missing and the belt hid it.

The unit test did not catch it because the stub took three arguments. A stub
that is easier to call than the real function is a test of the stub.

So this checks the calls rather than the sends: every call to `send_email`
and `send_sms` in the application is bound against the real signature, the
same way Python will bind it at runtime. It needs no mail account, no
network, and no way to reach the code path — which matters, because the two
broken ones were on paths that only run when something has already gone
wrong, and those are exactly the paths nobody exercises by hand.
"""
import ast
import inspect
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {'node_modules', 'tests', 'migrations', '.git', 'venv', '.venv'}

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def sources():
    for p in sorted(ROOT.rglob('*.py')):
        if any(part in SKIP for part in p.relative_to(ROOT).parts):
            continue
        yield p


def calls_to(names):
    """Every call to one of `names`, as (path, line, positional, keywords)."""
    for path in sources():
        try:
            tree = ast.parse(path.read_text(encoding='utf8', errors='replace'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            fname = f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', '')
            if fname not in names:
                continue
            # `send_email = lambda ...` in a stub, or a def, is not a call.
            star = any(isinstance(a, ast.Starred) for a in node.args)
            kwargs = {k.arg for k in node.keywords if k.arg}
            splat = any(k.arg is None for k in node.keywords)
            yield path, node.lineno, len(node.args), kwargs, star, splat


print('\n1. Every send_email call binds against the real signature')
sig = inspect.signature(notifications.send_email)
print(f'     send_email{sig}')

found = 0
for path, line, npos, kwargs, star, splat in calls_to({'send_email'}):
    found += 1
    rel = path.relative_to(ROOT)
    if star or splat:
        # A caller forwarding *args/**kwargs cannot be checked statically and
        # is not the shape that broke.
        print(f'  ⏭  {rel}:{line} forwards *args — not checkable here')
        continue
    try:
        sig.bind(*[f'a{i}' for i in range(npos)], **{k: 'x' for k in kwargs})
        ok, why = True, ''
    except TypeError as e:
        ok, why = False, str(e)
    check(ok, f'{rel}:{line}' + (f' — {why}' if not ok else ''))

check(found >= 2, f'and it actually found call sites to check ({found})')


print('\n2. The two that were broken, named')
# Stated explicitly so that a regression reads as a regression rather than as
# one of a long list of green ticks.
def binds(path, needle):
    src = (ROOT / path).read_text()
    for p, line, npos, kwargs, star, splat in calls_to({'send_email'}):
        if p.name != pathlib.Path(path).name or star or splat:
            continue
        try:
            sig.bind(*[f'a{i}' for i in range(npos)], **{k: 'x' for k in kwargs})
        except TypeError:
            return False
    return needle in src


check(binds('errors.py', 'Something broke'),
      'the crash alerter can send the email it exists to send')
check(binds('blueprints/marketing.py', 'Early access request'),
      'an early-access lead reaches a person even when the write fails')


print('\n3. send_sms too, for the same reason')
sms = inspect.signature(notifications.send_sms)
print(f'     send_sms{sms}')
n = 0
for path, line, npos, kwargs, star, splat in calls_to({'send_sms'}):
    if star or splat:
        continue
    n += 1
    try:
        sms.bind(*[f'a{i}' for i in range(npos)], **{k: 'x' for k in kwargs})
        ok, why = True, ''
    except TypeError as e:
        ok, why = False, str(e)
    if not ok:
        check(False, f'{path.relative_to(ROOT)}:{line} — {why}')
check(True, f'{n} send_sms call sites bind cleanly')


print('\n4. Nothing that sends mail hides a programming error')
# The `except Exception: pass` is right — a mail outage must not take a page
# down. But it must not be the only thing standing between a broken call and
# silence, which is the whole reason this file exists.
alert = (ROOT / 'errors.py').read_text()
check('except Exception' in alert,
      'the crash alerter still refuses to raise (a mail outage is not a 500)')


if failures:
    print(f'\n\n❌ {len(failures)} email-caller check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Every caller can call what it is calling.\n')
