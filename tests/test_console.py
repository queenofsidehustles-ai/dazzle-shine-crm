"""The room behind the product, and who is allowed in it.

Everything that spanned companies used to be a command-line tool run by
somebody holding the production database URL. That works while the somebody is
the founder; it does not work for an assistant, and it means beta feedback
lives in one inbox, which is where feedback goes to be forgotten.

The interesting half is not the pages. It is that this login can see every
company in the product, so it must never be reachable from a cleaning
company's own session, and a helper must not be able to grant access.
"""
import os, re, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/con.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


print('\n1. A console session is not a CRM session')
src = open(os.path.join(ROOT, 'blueprints', 'console.py')).read()
# The whole risk in one line: an owner of one cleaning company must not be
# able to read every other company because both used the same session key.
check("SESSION_KEY = 'console_email'" in src,
      'the console has its own session key')
check(src.count("session.get('logged_in')") == 0,
      'and never treats a CRM login as access here')
check('control_plane.console_user(_engine(), email)' in src,
      'every request re-checks the account against the list')
check("session.pop(SESSION_KEY, None)" in src,
      'so access removed mid-session ends the session')

print('\n2. A helper cannot let somebody else in')
check('def owner_only' in src, 'there is an owner-only gate')
for route in ('add_person', 'turn_off'):
    seg = src[src.index(f'def {route}') - 260:src.index(f'def {route}')]
    check('@owner_only' in seg, f'{route} is behind it')
# And the check is on the request, not on what the page chose to draw.
check("(getattr(request, 'console_user', {}) or {}).get('role') != 'owner'" in src,
      'the gate reads the account, not the form')

print('\n3. A wrong password says nothing useful')
cp = open(os.path.join(ROOT, 'control_plane.py')).read()
check('LOCK_AFTER' in cp and 'locked_until' in cp,
      'guesses are counted and the account stops answering')
check('That email and password do not match.' in src,
      'and one message covers both halves')
# The first version of this matched the comment explaining the design and
# passed for the wrong reason. What matters is the branch: the failure
# message must depend only on whether the account is locked, never on
# whether the email exists -- telling those apart is how somebody learns
# which addresses are real.
login_src = src[src.index('def login('):src.index('def logout(')]
messages = re.findall(r"flash\(\s*'([^']+)'|'([^']*)'\s+if why == 'locked'"
                      r"|else '([^']+)'", login_src)
flat = [m for group in messages for m in group if m]
check(len(set(flat)) == 2,
      f'exactly two things it can say: locked, or no match ({sorted(set(flat))})')
check(all('account' not in m.lower() and 'email' != m.lower() for m in flat),
      'and neither of them says whether the account exists')
check("why == 'locked'" in login_src,
      'the only thing the message depends on is being locked out')

print('\n4. A password is never emailed')
people = open(os.path.join(ROOT, 'templates', 'console', 'people.html')).read()
check('Tell them the password yourself' in people,
      'the page says to hand it over in person')
check('send_email' not in src.split('def add_person')[1][:900],
      'and adding somebody sends no mail')

print('\n5. The public question box')
ask = open(os.path.join(ROOT, 'templates', 'marketing', '_ask.html')).read()
check('one business day' in ask, 'it promises one business day')
check('one business day' in src, 'and the reply says the same thing')
check('ask-trap' in ask and "data.get('company')" in src,
      'a field only a robot fills is checked before anything is stored')
check('reply_to=email' in src,
      'replying to the notification goes to them, not to us')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ The console is reachable only by the people on the list.')
