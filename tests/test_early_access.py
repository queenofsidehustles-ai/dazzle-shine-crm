"""Regression checks for the disabled-registration fallback.

The fallback is a waitlist, never a fake signup. When registration opens,
/early-access must immediately yield to the real self-service /signup flow.
"""
import os, sys, tempfile
TMP=tempfile.mkdtemp()
os.environ['DATABASE_URL']=f'sqlite:///{TMP}/ea.db'
os.environ['SECRET_KEY']='test'
os.environ['BASE_DOMAIN']='akye.test'
os.environ['SIGNUPS_OPEN']='0'
os.environ['FLASK_ENV']='development'
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
SENT=[]
notifications.send_sms=lambda *a,**k:(True,'stub')
notifications.send_email=lambda to_email,to_name,subject,html,**k:(SENT.append({'to':to_email,'subject':subject,'body':html}),(True,'stub'))[1]
from app import create_app
app=create_app(); c=app.test_client(); PRODUCT={'Host':'akye.test'}; TENANT={'Host':'acme.akye.test'}
failures=[]
def check(cond,msg):
 print(('  ✅ ' if cond else '  ❌ ')+msg)
 if not cond: failures.append(msg)

print('\n1. Disabled registration is described truthfully')
home=c.get('/',headers=PRODUCT).data.decode()
check('/early-access' in home,'homepage exposes fallback')
check('Join waitlist' in home,'fallback is labelled waitlist')
check('href="/signup"' not in home,'disabled signup is not advertised')
page=c.get('/early-access',headers=PRODUCT).data.decode()
check('Join the waitlist' in page,'waitlist page identifies itself')
check('does not create an account' in page,'page says no account is created')

print('\n2. Waitlist submission cannot imply account creation')
r=c.post('/early-access',headers=PRODUCT,data={'name':'Dana','email':'dana@example.com'})
body=r.data.decode()
check("You're on the waitlist" in body,'confirmation says waitlist')
check('not an account' in body,'confirmation explicitly denies account creation')
check('couple of days' not in body,'obsolete manual-onboarding promise is gone')
check('When we set you up' not in body,'obsolete operator-provisioning copy is gone')

print('\n3. Validation and durable fallback remain')
r=c.post('/early-access',headers=PRODUCT,data={'name':'','email':''}); body=r.data.decode()
check('Please tell us your name' in body,'name required')
check('We need an email' in body,'email required')
SENT.clear(); c.post('/early-access',headers=PRODUCT,data={'name':'Marcus','company':'Feld Cleaning','email':'m@example.com'})
check(len(SENT)==1,'lead still reaches support if storage is unavailable')

print('\n4. Open registration has one authoritative path')
import blueprints.signup as signup
orig=signup.signups_open
try:
 signup.signups_open=lambda:True
 r=c.get('/early-access',headers=PRODUCT)
 check(r.status_code in (301,302),'legacy fallback redirects')
 check('/signup' in (r.headers.get('Location') or ''),'redirect target is /signup')
finally: signup.signups_open=orig

print('\n5. Fallback never leaks onto tenant CRM')
check(c.get('/early-access',headers=TENANT).status_code==404,'tenant host returns 404')
if failures:
 print(f'\n❌ {len(failures)} waitlist regression(s) failed'); sys.exit(1)
print('\n✅ Signup/waitlist semantics are unambiguous.')
