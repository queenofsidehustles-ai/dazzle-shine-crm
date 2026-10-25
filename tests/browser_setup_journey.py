"""The four setup steps, in a real browser, with screenshots.

P0-03 (25 Oct report) asked for more than a passing suite: a browser walking
the setup a new owner sees -- exactly four required steps, the owner's own
cleaner row confirmed and never duplicated, the count surviving a reload, and
payments still asked for while Stripe is not connected.

Runs a disposable local instance on its own SQLite file, with no API keys (so
the setup chat is off, the path that used to strand step 2), and drives it
with Playwright's Chromium. Screenshots go to $BROWSER_EVIDENCE_DIR (a temp
directory by default). Skips, saying so, where Playwright or Chromium is not
installed -- never in CI, where a skip would read as a pass.

    python3 tests/browser_setup_journey.py
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    if os.environ.get('CI'):
        sys.exit('Playwright is not installed in CI; this journey cannot run.')
    print('  ⚠️  SKIPPED: Playwright for Python is not installed.')
    sys.exit(0)

TMP = tempfile.mkdtemp()
DB = f'sqlite:///{TMP}/setup-journey.db'
OUT = os.environ.get('BROWSER_EVIDENCE_DIR') or os.path.join(TMP, 'shots')
os.makedirs(OUT, exist_ok=True)
ENV = dict(os.environ, DATABASE_URL=DB, SECRET_KEY='setup-journey', FLASK_ENV='development')
for k in ('ANTHROPIC_API_KEY', 'STRIPE_SECRET_KEY', 'BASE_DOMAIN'):
    ENV.pop(k, None)
PASSWORD = 'journey-password-1'

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


# A brand-new business: an owner login and her own cleaner row, as signup makes
# them, and nothing else filled in.
seed = f'''
import os, sys
sys.path.insert(0, {ROOT!r})
from app import create_app
from extensions import db
from models import BusinessSetting, User
import owner_cleaner
app = create_app()
with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Journey Cleaning')
    BusinessSetting.set('email', 'mo@journey.test')
    u = User(name='Mo Lewis', username='mo@journey.test', role='owner', active=True)
    u.set_password({PASSWORD!r})
    db.session.add(u); db.session.commit()
    owner_cleaner.ensure(u, 'mo@journey.test'); db.session.commit()
'''
r = subprocess.run([sys.executable, '-c', seed], env=ENV, cwd=ROOT, capture_output=True, text=True)
if r.returncode:
    sys.exit('could not seed the business:\n' + r.stderr[-2000:])

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    PORT = s.getsockname()[1]
BASE = f'http://127.0.0.1:{PORT}'
server = subprocess.Popen(
    [sys.executable, '-c', f'from app import create_app; create_app().run(host="127.0.0.1", port={PORT})'],
    env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def staff_rows():
    q = ('import sys; sys.path.insert(0, %r)\nfrom app import create_app\nfrom models import Staff\n'
         'app = create_app()\nwith app.app_context():\n'
         '    print(";".join(f"{s.name}|{int(bool(s.is_owner))}|{int(bool(s.is_active))}" for s in Staff.query.all()))') % ROOT
    out = subprocess.run([sys.executable, '-c', q], env=ENV, cwd=ROOT, capture_output=True, text=True)
    return [x for x in out.stdout.strip().splitlines()[-1].split(';') if x] if out.stdout.strip() else []


try:
    for _ in range(60):
        try:
            import urllib.request
            urllib.request.urlopen(BASE + '/login', timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            if os.environ.get('CI'):
                raise
            print(f'  ⚠️  SKIPPED: Chromium will not start ({type(e).__name__}).')
            sys.exit(0)
        page = browser.new_page(viewport={'width': 390, 'height': 844})   # a phone

        def shot(name):
            page.screenshot(path=os.path.join(OUT, name), full_page=True)

        def progress():
            page.goto(BASE + '/settings/getting-started')
            return page.inner_text('main') if page.locator('main').count() else page.inner_text('body')

        print('\n1. Sign in as a brand-new owner')
        page.goto(BASE + '/login')
        page.fill('input[name="username"]', 'mo@journey.test')
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')
        text = progress()
        shot('1-start.png')
        check('0 of 4 done' in text, 'nothing done yet: 0 of 4')
        check('Check your details' in text, 'and step 1 is the details')

        print('\n2. Step 1: the details')
        page.goto(BASE + '/settings/business')
        page.fill('input[name="phone"]', '(407) 555-0100')
        page.locator('button:has-text("Save Business Info")').click()
        page.wait_for_load_state('networkidle')
        text = progress()
        shot('2-details-done.png')
        check('1 of 4 done' in text and 'Set yourself up as a cleaner' in text,
              '1 of 4, and step 2 is setting herself up as a cleaner')
        check(page.locator('#teamStepForm').count() == 1,
              'with her card right there, no chat needed')

        print('\n3. Step 2: herself, as the first cleaner')
        check(page.input_value('input[name="me_name"]') == 'Mo Lewis', 'her name is filled in')
        page.locator('#teamStepForm button[type="submit"]').click()
        page.wait_for_load_state('networkidle')
        text = progress()
        shot('3-team-done.png')
        check('2 of 4 done' in text and 'Confirm your prices' in text, '2 of 4, and step 3 is prices')
        rows = staff_rows()
        check(rows == ['Mo Lewis|1|1'], f'exactly one staff row, hers, active ({rows})')

        print('\n4. Step 3: the prices')
        page.goto(BASE + '/settings/pricing')
        page.locator('button[data-tour="price-save"]').click()
        page.wait_for_load_state('networkidle')
        text = progress()
        shot('4-prices-done.png')
        check('3 of 4 done' in text and 'Connect payments' in text, '3 of 4, and step 4 is payments')

        print('\n5. Step 4 stays open until Stripe is really connected')
        page.reload()
        page.wait_for_load_state('networkidle')
        text = progress()
        shot('5-reload.png')
        check('3 of 4 done' in text, 'a reload keeps the count: nothing done twice, nothing lost')
        check('Connect payments' in text, 'and still asks for payments, with no Stripe key')
        page.goto(BASE + '/contractors/team')
        shot('6-team-page.png')
        check(page.inner_text('body').count('Mo Lewis') >= 1 and staff_rows() == ['Mo Lewis|1|1'],
              'the Team page shows her, and there is still one row')
        browser.close()
finally:
    server.terminate()
    try:
        server.wait(10)
    except Exception:
        server.kill()

print(f'\n  screenshots: {OUT}')
if failures:
    print(f'\n❌ {len(failures)} failed')
    sys.exit(1)
print('\n✅ The four setup steps, walked in a browser.')
