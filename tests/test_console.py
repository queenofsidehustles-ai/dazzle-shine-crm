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
check('def can_manage' in src, 'there is a gate on changing who has access')
for route in ('add_person', 'turn_off', 'turn_on'):
    seg = src[src.index(f'def {route}') - 260:src.index(f'def {route}')]
    check('@can_manage' in seg, f'{route} is behind it')
# The gate reads the signed-in account, never the form -- a hidden button is
# a courtesy, and the route is asked again by anybody who posts straight at it.
check("(getattr(request, 'console_user', {}) or {}).get('role')" in src,
      'the gate reads the account, not the form')
check('control_plane.may_act_on(me[\'role\'], target[\'role\'])' in src,
      'and each target is checked by rank as well as by the gate')

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

print('\n6. You can act on somebody below you, never beside you or above you')
import control_plane as _cp

# The rule the owner asked for, stated once and applied everywhere: a second
# pair of hands doing eighty per cent of the work must not be able to remove
# the person who granted them the access.
check(not _cp.may_act_on('manager', 'owner'),
      'a manager cannot touch the owner')
check(not _cp.may_act_on('manager', 'manager'),
      'nor another manager — beside you counts as not below you')
check(_cp.may_act_on('manager', 'helper'),
      'but can bring in and remove helpers, which is the work')
check(not _cp.may_act_on('helper', 'helper') and not _cp.may_act_on('helper', 'owner'),
      'a helper acts on nobody at all')
check(_cp.may_act_on('owner', 'manager') and _cp.may_act_on('owner', 'helper'),
      'the owner can act on everybody below')
check(not _cp.may_act_on('owner', 'owner'),
      'and not on another owner, so nobody switches an owner off from here')

# You cannot hand out your own level. Only the owner appoints a manager.
check(not _cp.may_grant('manager', 'manager'), 'a manager cannot appoint a manager')
check(not _cp.may_grant('manager', 'owner'), 'and certainly not an owner')
check(_cp.may_grant('manager', 'helper'), 'a manager can appoint a helper')
check(_cp.may_grant('owner', 'manager'), 'only the owner appoints a manager')
check(not _cp.may_grant('owner', 'owner'), 'and even an owner cannot mint an owner here')

# Somebody with no role at all is below everybody, not above.
check(_cp.rank('') == 0 and not _cp.may_act_on('', 'helper'),
      'an unknown role can do nothing')
# The first version of this called a helper "staff". Those rows still exist.
check(_cp.rank('staff') == _cp.rank('helper'),
      'accounts made under the old name still rank as helpers')

print('\n7. Every action is written down')
check('def log_console' in cp, 'there is a record')
for what in ("'signed in'", "'added'", "'switched off'", "'refused'",
             "'marked done'"):
    check(what in src, f'it records {what}')
# A refused attempt is the most interesting line in it: it is the only way to
# see somebody trying something they were not allowed to do.
check("'refused'" in src, 'including attempts that were turned down')
log_page = open(os.path.join(ROOT, 'templates', 'console', 'log.html')).read()
check('Everybody with access can read this' in log_page,
      'and everybody can read it, not only the owner')
print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ The console is reachable only by the people on the list.')
