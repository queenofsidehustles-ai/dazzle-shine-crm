"""The Meta Pixel for Akye's own ads: where it loads and what it records.

What would matter if it went wrong:

  * the pixel turning up on a single-business deployment, or on pages a
    company's customers see (it is only ever included on the signup form and
    the owner's first screen);
  * CompleteRegistration firing on an ordinary sign-in, or more than once;
  * no way to turn it off without a code change.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


import product
from jinja2 import Environment, FileSystemLoader

saved = {k: os.environ.get(k) for k in ('BASE_DOMAIN', 'META_PIXEL_ID')}


def setenv(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


print('\n1. Which deployments get a pixel')
setenv(BASE_DOMAIN=None, META_PIXEL_ID=None)
check(product.meta_pixel_id() == '', 'a single-business deployment gets none')
setenv(BASE_DOMAIN='akyehq.com')
check(product.meta_pixel_id() == product.DEFAULT_META_PIXEL_ID,
      'the product gets the Akye Pixel by default')
setenv(META_PIXEL_ID='123')
check(product.meta_pixel_id() == '123', 'META_PIXEL_ID overrides it')
setenv(META_PIXEL_ID='off')
check(product.meta_pixel_id() == '', 'META_PIXEL_ID=off turns it off')

print('\n2. What the snippet renders')
env = Environment(loader=FileSystemLoader(os.path.join(ROOT, 'templates')),
                  autoescape=True)
tpl = env.get_template('_meta_pixel.html')
out = tpl.render(META_PIXEL_ID='')
check('fbq' not in out, 'no pixel id, no script')
out = tpl.render(META_PIXEL_ID='1087100530584907')
check("fbq('init', \"1087100530584907\")" in out and "'PageView'" in out,
      'init and PageView with the id')
check('CompleteRegistration' not in out, 'no signup event unless asked for')
out = tpl.render(META_PIXEL_ID='1087100530584907', meta_event='CompleteRegistration')
check("fbq('track', \"CompleteRegistration\")" in out, 'records the signup when asked')

print('\n3. Where it is included')
read = lambda p: open(os.path.join(ROOT, p)).read()
check("_meta_pixel.html" in read('templates/admin/signup.html'), 'on the signup form')
gs = read('templates/admin/getting_started.html')
check("session.pop('meta_signup_complete'" in gs,
      'first screen records the signup once (the flag is popped)')
check("session['meta_signup_complete'] = True" in read('blueprints/signup.py'),
      'only the post-signup welcome sets the flag')
check("meta_signup_complete" not in read('auth.py'), 'a normal sign-in never sets it')
check("_meta_pixel.html" not in read('templates/base_admin.html'),
      'not in the back-office layout every page shares')

setenv(**saved)
print()
if failures:
    print(f'❌ {len(failures)} failed')
    sys.exit(1)
print('✅ all passed')
