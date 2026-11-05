"""Choosing a password: one rule everywhere, and signup asks twice.

A slip when a password is chosen means an account nobody can sign in to, on its
first day. So signup asks for it twice, like resetting one does, and the rules
for what is acceptable are written once (passwords.py) instead of in two places
that had drifted apart: the reset page refused "qwertyui" and signup did not.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/pw.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import passwords

print('1. The rule')
check(passwords.problem('goodenough1', 'goodenough1') is None, 'a good password, typed twice the same: fine')
check('at least 8' in passwords.problem('short', 'short'), 'too short')
check('do not match' in passwords.problem('goodenough1', 'goodenough2'), 'typed twice differently')
check('do not match' in passwords.problem('goodenough1', ''), 'the second box left empty')
check('too easy' in passwords.problem('password', 'password'), 'the obvious ones')
check('too easy' in passwords.problem('QWERTYUI', 'QWERTYUI'), 'in any case, and including the one signup used to let through')
check('at least 8' in passwords.problem('abc', 'xyz'), 'a short pair says short first, as the reset page always has')

print('\n2. Signup asks the same question')
import blueprints.signup as signup
form = {'business': 'B', 'name': 'A', 'email': 'a@b.test', 'phone': '4075550123', 'zip_code': '32801'}
check('do not match' in (signup._validate(form, 'ok-slug', 'goodenough1', True, 'goodenough2') or ''),
      'two different passwords are refused')
check('do not match' in (signup._validate(form, 'ok-slug', 'goodenough1', True) or ''),
      'and a second box that was not sent at all')
check('too easy' in (signup._validate(form, 'ok-slug', 'qwertyui', True, 'qwertyui') or ''),
      'signup refuses what the reset page refuses')

print('\n3. One copy of the rule')
src = {f: open(f'{ROOT}/{f}').read() for f in ('blueprints/signup.py', 'blueprints/account.py')}
check('passwords.problem(' in src['blueprints/signup.py'] and "'changeme'" not in src['blueprints/signup.py'],
      'signup calls it and no longer keeps a list of its own')
check(src['blueprints/account.py'].count('passwords.problem(') == 3 and "'changeme'" not in src['blueprints/account.py'],
      'so do reset, invite and change-password')

print('\n4. The form')
html = open(f'{ROOT}/templates/admin/signup.html').read()
check('name="confirm"' in html and 'id="confirm"' in html and html.count('autocomplete="new-password"') == 2,
      'a second box, and both are new-password so a password manager fills both')
check('id="show_password"' in html and "pw.type = t; cf.type = t" in html,
      'a Show password box that changes both')
check('setCustomValidity' in html and 'aria-live="polite"' in html,
      'the page says whether they match as they type, and tells screen readers')
shell = open(f'{ROOT}/templates/admin/login_shell.html').read()
check('.panel input[type="checkbox"]' in shell and 'width:auto' in shell.split('.panel input[type="checkbox"]')[1][:80],
      'a tick box is not stretched to the width of the form')

print()
if failures:
    print(f'❌ {len(failures)} password check(s) failed.')
    sys.exit(1)
print('🎉 Asked twice, judged once.')
