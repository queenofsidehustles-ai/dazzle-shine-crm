"""The legal pages exist, say the specific things, and appear in the right places.

A generic terms-of-service protects nobody. The value in these is in four
clauses that are specific to what this software actually does, and this file
exists so that none of them can be quietly edited away:

  * it records pay but does not file or withhold anything
  * it takes no view on whether somebody is a contractor or an employee
  * it stores background check results but does not obtain them
  * a business's cleaners and clients are that business's data, not ours

The third and fourth carry real exposure. The software computes contractor pay
and produces 1099 totals, so "the software told me to" must never be available
as a defence. And it holds background check results, which is a regulated area
where the obligations sit with the employer whoever ran the check.
"""
import os, sys, tempfile, pathlib
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/legal.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['SIGNUPS_OPEN'] = '1'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db

app = create_app()
with app.app_context():
    db.create_all()

PRODUCT = {'Host': 'akye.test'}
TENANT = {'Host': 'acme.akye.test'}
c = app.test_client()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def page(path, headers=PRODUCT):
    """The page with its whitespace flattened.

    A sentence wrapped across two lines in the template is the same sentence.
    Searching raw HTML makes these tests fail on reformatting, which teaches
    people to loosen the assertion rather than read it."""
    import re
    raw = c.get(path, headers=headers).data.decode('utf8', 'replace')
    return re.sub(r'\s+', ' ', raw)


print('\n1. The three documents exist and say they are drafts')
for path, title in [('/terms', 'Terms of Service'),
                    ('/privacy', 'Privacy Policy'),
                    ('/subprocessors', 'Who we share data with')]:
    body = page(path)
    check(title in body, f'{path} is the {title}')
    check('not yet been reviewed by a lawyer' in body,
          f'{path} says plainly that it is a draft')

print('\n2. Not a payroll provider — stated, not implied')
terms = page('/terms')
check('Not a payroll provider' in terms, 'it has its own heading')
for phrase in ('does not pay anybody', 'withhold', 'file anything', 'remit any tax'):
    check(phrase in terms, f'and says it does not {phrase!r}')
check('not a filed return' in terms, 'and that a 1099 total is not a filed return')

print('\n3. No view on contractor versus employee')
# The software is built around per-job pay. Somebody will eventually argue that
# using it implies a classification. It must not.
check('contractor or an employee' in terms, 'the question is named')
check('not us telling you anybody is an independent contractor' in terms,
      'and answered: the software is not saying it')
check('not evidence of anything' in terms,
      'using per-job pay is explicitly not evidence')

print('\n4. Background checks — held, not obtained')
check('Not a background check company' in terms, 'it has its own heading')
check('not a consumer reporting agency' in terms,
      'and disclaims being a consumer reporting agency')
check('Fair Credit Reporting Act' in terms,
      'and points at where the obligations actually sit')

print('\n5. The customer owns their data, and we say what we do not do with it')
check('belongs to you' in terms, 'the terms say the data is theirs')
priv = page('/privacy')
check('do not sell' in priv and 'do not use your business data to train' in priv.lower(),
      'and the privacy policy rules out selling it or training on it')
check('That is yours, not ours' in priv,
      'with the controller/processor split stated in words a person can read')

print('\n6. The uncomfortable truths are in there')
# The temptation in a privacy policy is to imply deletion is instant and
# security is perfect. Both would be untrue.
check('Backups take longer' in priv,
      'it admits deleted data survives in backups for up to a month')
check('72 hours' in priv, 'and commits to a breach notification window')
check('No system is perfect' in priv, 'rather than claiming otherwise')
check('access notes' in priv.lower(),
      'and names the most sensitive field in the software by name')
check('W-9' in priv, 'along with the documents that get uploaded')

print('\n7. Every outside company is listed')
subs = page('/subprocessors')
for who in ('Railway', 'Stripe', 'Twilio', 'Resend', 'Cloudinary', 'GitHub', 'Sentry'):
    check(who in subs, f'{who} is disclosed')
check('never customer records' in subs,
      'and the AI entry says customer records are not sent to it')

print('\n8. Agreement is asked for where somebody is actually agreeing')
signup = page('/signup')
check('/terms' in signup and '/privacy' in signup,
      'the signup form links both, rather than burying them in a footer')

print('\n9. Linked from every page of the product site')
for path in ('/', '/pricing', '/terms'):
    body = page(path)
    check('/privacy' in body and '/terms' in body,
          f'{path} carries the links in its footer')

print('\n10. And none of it appears on a cleaning company\'s CRM')
for path in ('/terms', '/privacy', '/subprocessors'):
    r = c.get(path, headers=TENANT)
    check(r.status_code == 404,
          f'{path} does not exist on a company subdomain — these are OUR terms, not theirs')

print('\n11. The payroll disclaimer is in the product, not only in a document')
# A clause in a document nobody reads protects nobody. It belongs on the screen
# where the number is being looked at.
# Payroll and 1099s are paid features, and a fresh hosted database starts free
# -- so without this the pages redirect to the upgrade screen and the assertion
# below would be checking an empty room.
with app.app_context():
    from models import BusinessSetting
    BusinessSetting.set('plan', 'scale')
    BusinessSetting.set('plan_status', 'active')
    db.session.commit()
import entitlements as _ent
_ent._clear_cache()

admin = app.test_client()
with admin.session_transaction() as sess:
    sess['logged_in'] = True
    sess['role'] = 'owner'
import re as _re
for path, what in [('/money/tax-forms', 'the 1099 page'),
                   ('/contractors/payroll', 'the payroll page')]:
    resp = admin.get(path)
    assert resp.status_code == 200, f'{what} did not render: HTTP {resp.status_code}'
    body = _re.sub(r'\s+', ' ', resp.data.decode('utf8', 'replace'))
    check('not a tax filing' in body, f'{what} says these are records, not a filing')
    check('contractor or an employee' in body,
          f'{what} says the software takes no view on classification')

print('\n12. Nothing is left blank, and we are named as the company')
# This started life as "every blank a lawyer must fill in is highlighted".
# The blanks are now filled, so the useful invariant flipped: no unfilled
# placeholder may ship, and the legal entity must actually appear -- a terms
# of service that does not say who it is with is not a contract with anybody.
import product
import re
whoever = product.legal_entity() or product.name()
for path in ('/terms', '/privacy'):
    body = page(path)
    blanks = re.findall(r'\[([A-Z][A-Z0-9 ,./&-]{3,})\]', body)
    check(not blanks, f'{path} has no unfilled placeholders left ({blanks[:3]})')
    check(whoever in body, f'{path} names {whoever!r} as the company')

# Who that is depends on where it is running, and the gate is the point: only
# the real product domain may claim to be our LLC. A self-hosted copy states
# its own name instead, because a stranger's deployment putting our company on
# its terms of service would make us party to a contract we never signed.
import importlib, os as _os
_saved = _os.environ.get('BASE_DOMAIN')
try:
    _os.environ['BASE_DOMAIN'] = 'akyehq.com'
    importlib.reload(product)
    check(product.legal_entity() == 'Yaa Mansa LLC',
          'on akyehq.com the entity is Yaa Mansa LLC')
    check(product.legal_address()[0].startswith('1317'),
          'and the registered address comes with it')

    _os.environ['BASE_DOMAIN'] = 'crm.somebodyelse.com'
    importlib.reload(product)
    check(product.legal_entity() == '',
          'on somebody else\'s deployment it is blank, not our company')
    check(product.legal_address() == [],
          'and so is the address')

    _os.environ['PRODUCT_LEGAL_ENTITY'] = 'Their Company Ltd'
    importlib.reload(product)
    check(product.legal_entity() == 'Their Company Ltd',
          'a self-hoster can state their own entity')
finally:
    _os.environ.pop('PRODUCT_LEGAL_ENTITY', None)
    if _saved is None:
        _os.environ.pop('BASE_DOMAIN', None)
    else:
        _os.environ['BASE_DOMAIN'] = _saved
    importlib.reload(product)

# And it comes from one place, so it cannot drift between the two documents.
check('LEGAL_ENTITY' in pathlib.Path('templates/marketing/legal_terms.html').read_text()
      and 'LEGAL_ENTITY' in pathlib.Path('templates/marketing/legal_privacy.html').read_text(),
      'both documents read the entity from product.py rather than hardcoding it')

print('\n\n✅ All legal-page tests passed.\n')
