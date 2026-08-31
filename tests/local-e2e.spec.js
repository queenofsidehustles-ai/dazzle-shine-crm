// @ts-check
/**
 * Full end-to-end write test against a LOCAL CRM with its own empty database.
 *
 * Start the server first:
 *   DATABASE_URL="sqlite:////tmp/e2e.db" SECRET_KEY=e2e-test \
 *   ADMIN_USER=e2e ADMIN_PASS=e2epass python3 -c \
 *   "from app import create_app; create_app().run(port=5001)"
 *
 * Then:  npx playwright test tests/local-e2e.spec.js
 *
 * Safe by construction: with no TWILIO_* or RESEND_* keys set, send_sms and
 * send_email return "not connected" instead of contacting anybody. Nothing here
 * touches the live CRM, real cleaners, or real money.
 */
const { test, expect } = require('@playwright/test');

const CRM = process.env.LOCAL_CRM || 'http://localhost:5001';
const USER = process.env.LOCAL_ADMIN_USER || 'e2e';
const PASS = process.env.LOCAL_ADMIN_PASS || 'e2epass';

async function login(page) {
  await page.goto(CRM + '/login');
  await page.fill('input[name="username"]', USER);
  await page.fill('input[name="password"]', PASS);
  await page.click('button[type="submit"]');
  await expect(page.locator('.sidebar')).toBeVisible();
}

// Today, and a date inside the current month, as YYYY-MM-DD.
const today = new Date();
const iso = (d) => d.toISOString().slice(0, 10);
const TODAY = iso(today);

test.describe.configure({ mode: 'serial' });

test.describe('CRM end-to-end — local', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('1. logs in and lands on the dashboard', async ({ page }) => {
    await expect(page).toHaveURL(CRM + '/');
    await expect(page.locator('.sidebar')).toContainText('Bookings');
  });

  // The money pages used to be five separate sidebar entries. They are one
  // entry with tabs now (see navigation.py), so the sidebar carries "Money"
  // and the pages themselves appear once you are inside the section. This
  // test still checks all five are reachable — just in the place they now live.
  test('2. the Money section is in the nav', async ({ page }) => {
    await expect(page.locator('.sidebar')).toContainText('Money');

    await page.goto(CRM + '/money/pnl');
    const tabs = page.locator('.section-tabs');
    await expect(tabs).toContainText('Profit & Loss');
    await expect(tabs).toContainText('Expenses');
    await expect(tabs).toContainText('Payroll');
    await expect(tabs).toContainText('VA commissions');
  });

  test('3. adds a cleaner to the team', async ({ page }) => {
    await page.goto(CRM + '/staff/new');
    await page.fill('input[name="name"]', 'Test Cleaner');
    await page.fill('input[name="email"]', 'testcleaner@example.com');
    await page.fill('input[name="phone"]', '5550001111');
    // Must be active, or she won't be offered on the booking page.
    const active = page.locator('input[name="is_active"]');
    if (await active.count() && !(await active.isChecked())) await active.check();
    await page.click('button[type="submit"]');
    await expect(page.locator('body')).toContainText('Test Cleaner');
  });

  test('4. creates a booking', async ({ page }) => {
    await page.goto(CRM + '/bookings/new');
    await page.fill('input[name="name"]', 'E2E Big House');
    await page.fill('input[name="address"]', '1 Mansion Way');
    await page.fill('input[name="email"]', 'client@example.com');
    await page.fill('input[name="phone"]', '5559998888');
    await page.fill('input[name="cleaning_price"]', '600');
    await page.fill('input[name="preferred_date"]', TODAY);
    // Don't email the (fake) customer.
    const notify = page.locator('input[name="notify_customer"]');
    if (await notify.count() && await notify.isChecked()) await notify.uncheck();
    await page.click('button[type="submit"]');
    await expect(page.locator('body')).toContainText('E2E Big House');
  });

  test('5. the booking page shows the "who\'s paid" card with a cleaner picker',
    async ({ page }) => {
      await page.goto(CRM + '/bookings/');
      await page.click('text=E2E Big House');
      await expect(page.locator('body')).toContainText("Who's Paid For This Job");
      await expect(page.locator('body')).toContainText('Give this job to a specific cleaner');
      await expect(page.locator('select[name="add_staff_id"]')).toBeVisible();
      await expect(page.locator('input[name="add_pay"]')).toBeVisible();
    });

  test('6. assigns the cleaner directly at a set amount', async ({ page }) => {
    await page.goto(CRM + '/bookings/');
    await page.click('text=E2E Big House');
    await page.selectOption('select[name="add_staff_id"]', { label: 'Test Cleaner' });
    await page.fill('input[name="add_pay"]', '250');
    await page.click('button[name="send_now"]');
    const body = page.locator('body');
    await expect(body).toContainText('Test Cleaner');
    // The pay lands in an input, and toContainText only reads visible text —
    // an input's value is an attribute and never appears in it. Test 7 checks
    // the same figure the right way.
    await expect(page.locator('input[name^="pay_"]')).toHaveValue('250.00');
    // Assigned directly means it must NOT be sitting open on the claim board.
    await expect(body).toContainText('Already assigned to Test Cleaner');
  });

  test('7. the set amount overrides the automatic percentage', async ({ page }) => {
    await page.goto(CRM + '/bookings/');
    await page.click('text=E2E Big House');
    // 50% of a $600 job would be $300; we set $250 by hand and that must win.
    await expect(page.locator('input[name^="pay_"]')).toHaveValue('250.00');
  });

  test('8. logs expenses, including mileage', async ({ page }) => {
    await page.goto(CRM + '/money/expenses');

    await page.selectOption('select[name="category"]', 'ads_google');
    await page.fill('input[name="amount"]', '180');
    await page.fill('input[name="vendor"]', 'Google Ads');
    await page.fill('input[name="date"]', TODAY);
    await page.click('button:has-text("Log this expense")');
    await expect(page.locator('body')).toContainText('Google Ads');

    // Mileage swaps the amount box for miles × rate.
    await page.selectOption('select[name="category"]', 'mileage');
    await expect(page.locator('input[name="miles"]')).toBeVisible();
    await page.fill('input[name="miles"]', '100');
    await page.fill('input[name="date"]', TODAY);
    await page.click('button:has-text("Log this expense")');
    // 100 mi × $0.70 = $70.00
    await expect(page.locator('body')).toContainText('70.00');
    await expect(page.locator('body')).toContainText('100 mi');
  });

  test('9. refuses to hand-enter cleaner pay (double-count guard)', async ({ page }) => {
    // The category must not even be offered in the dropdown.
    await page.goto(CRM + '/money/expenses');
    const options = await page.locator('select[name="category"] option').allInnerTexts();
    expect(options.join('|')).not.toContain('Cleaner pay');

    // Posting it straight to the server must be rejected too. Playwright follows
    // the redirect, so the refusal lands in THIS response body — checking a later
    // page load would miss it, because the flash is consumed on first render.
    const res = await page.request.post(CRM + '/money/expenses/add', {
      form: { category: 'contractor_pay', amount: '275', date: TODAY },
    });
    expect(res.status()).toBeLessThan(400);
    expect(await res.text()).toContain('would count it twice');

    // And no such row landed in the ledger. (Scope to the ledger table — the
    // page's footer note mentions "Cleaner pay" in prose on purpose.)
    await page.goto(CRM + '/money/expenses');
    const ledger = page.locator('table').first();
    await expect(ledger).not.toContainText('Cleaner pay');
    await expect(ledger).not.toContainText('275.00');
  });

  test('10. adds a recurring cost', async ({ page }) => {
    await page.goto(CRM + '/money/expenses');
    const form = page.locator('form[action*="/money/recurring/add"]');
    await form.locator('select[name="category"]').selectOption('insurance');
    await form.locator('input[name="vendor"]').fill('Test Insurance');
    await form.locator('input[name="amount"]').fill('145');
    await form.locator('input[name="day_of_month"]').fill('1');
    await form.locator('button[type="submit"]').click();
    await expect(page.locator('body')).toContainText('Test Insurance');
  });

  test('11. the P&L renders and the arithmetic balances', async ({ page }) => {
    await page.goto(CRM + '/money/pnl');
    const body = page.locator('body');
    await expect(body).toContainText('Money in');
    await expect(body).toContainText('Net profit');
    await expect(body).toContainText('Is your advertising paying for itself');

    // Read the three headline figures off the stat cards structurally, then
    // check they reconcile. Structure beats regex here — the same words appear
    // in the statement below and in the explanatory prose.
    const tile = async (label) => {
      const value = page.locator('.stat-card', { hasText: label }).first().locator('.value');
      const raw = (await value.innerText()).replace(/[$,\s]/g, '');
      return parseFloat(raw);
    };
    const moneyIn = await tile('Money in');
    const moneyOut = await tile('Money out');
    const net = await tile('Net profit');
    for (const [n, v] of [['in', moneyIn], ['out', moneyOut], ['net', net]]) {
      expect(Number.isNaN(v), `money ${n} should be a number`).toBe(false);
    }
    // revenue − everything out == net profit
    expect(Math.abs((moneyIn - moneyOut) - net)).toBeLessThan(0.02);
  });

  test('12. unpaid jobs are NOT counted as revenue', async ({ page }) => {
    await page.goto(CRM + '/money/pnl');
    // Labels are uppercased by CSS, so innerText comes back shouting — match
    // case-insensitively rather than against the source casing.
    const text = await page.locator('body').innerText();
    // The booking was never marked paid, so money in must be $0.00.
    expect(text).toMatch(/Money in[\s\S]{0,80}?\$0\.00/i);
    // ...but it must still be visible as money owed.
    expect(text).toMatch(/still owed to you/i);
    // And the unpaid work should show as booked pipeline, not income.
    expect(text).toMatch(/booked this period/i);
  });

  test('13. exports the P&L as CSV with Schedule C lines', async ({ page }) => {
    const res = await page.request.get(CRM + '/money/pnl/export');
    expect(res.status()).toBe(200);
    const csv = await res.text();
    expect(csv).toContain('Line 8 — Advertising');
    expect(csv).toContain('NET PROFIT');
    expect(csv).toContain('Line 9 — Car & truck');   // the mileage entry
  });

  test('14. white label — no hardcoded brand in the CSV export', async ({ page }) => {
    const res = await page.request.get(CRM + '/money/pnl/export');
    const csv = await res.text();
    // This local instance has no business_name set, so the real brand must not appear.
    expect(csv).not.toContain('Dazzle');
  });

  test('15. every page in the sidebar loads without error', async ({ page }) => {
    // Crawl the real nav rather than a hardcoded list — this tests exactly what
    // she can click, and stays correct when the nav changes.
    await page.goto(CRM + '/');
    const hrefs = await page.locator('.sidebar nav a').evaluateAll(
      (as) => as.map((a) => a.getAttribute('href')).filter(Boolean));
    const links = [...new Set(hrefs)].filter((h) => h && !h.includes('logout'));
    expect(links.length, 'sidebar should have links').toBeGreaterThan(8);

    const broken = [];
    for (const href of links) {
      const res = await page.goto(new URL(href, CRM).toString());
      const body = await page.locator('body').innerText();
      if (!res || res.status() >= 400) broken.push(`${href} → HTTP ${res && res.status()}`);
      else if (body.includes('Traceback (most recent call last)')) broken.push(`${href} → stack trace`);
    }
    expect(broken, `broken nav pages: ${broken.join(', ')}`).toEqual([]);
  });
});

test.describe('Calendar — drag to reschedule', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('dragging a job to another day moves it', async ({ page }) => {
    // Three things had to be fixed here, and all three were the test's fault
    // rather than the calendar's — the drag itself always worked.
    //
    // 1. The booking is named uniquely and deleted at the end. It used to be
    //    called "Drag Me" and left behind, so every run added another chip to
    //    the 5th. By the tenth the day cell was tall enough that the drop
    //    landed nowhere and the test failed with no job having moved.
    //
    // 2. The drop is dispatched rather than mimed. `dragTo` moves a mouse and
    //    hopes the browser synthesises HTML5 drag events from it, which it
    //    does most of the time. Dispatching dragstart/dragover/drop with one
    //    shared DataTransfer is what the page actually listens for.
    //
    // 3. The toast is read immediately. The calendar reloads itself 900ms
    //    after a drop to re-read the grid from the server, which wipes it.
    //    (Holding the reload is not an option — Chromium will not let you
    //    reassign `location.reload`, and the assignment fails silently, which
    //    is its own small trap.) The message lands about 20ms after the drop,
    //    so reading it straight away has a wide margin; sleeping first does
    //    not, which is what an earlier version of this did.
    const who = `Drag Me ${Math.random().toString(36).slice(2, 8)}`;
    await page.goto(CRM + '/bookings/new');
    await page.fill('input[name="name"]', who);
    await page.fill('input[name="address"]', '5 Drag St');
    await page.fill('input[name="cleaning_price"]', '260');
    await page.fill('input[name="preferred_date"]', '2026-08-05');
    const notify = page.locator('input[name="notify_customer"]');
    if (await notify.count() && await notify.isChecked()) await notify.uncheck();
    await page.click('button[type="submit"]');
    const bookingUrl = page.url();

    await page.goto(CRM + '/bookings/calendar?year=2026&month=8');
    // The chip shows only the first word of the name; the whole of it is in
    // the title attribute, which is what makes this run-unique locator work.
    const chip = page.locator(`.jobchip[title^="${who}"]`).first();
    await expect(chip, 'the job should be on the calendar and draggable').toBeVisible();
    await expect(chip).toHaveAttribute('draggable', 'true');

    const target = page.locator('.daycell[data-date="2026-08-19"]');
    await expect(target).toBeVisible();

    const dt = await page.evaluateHandle(() => new DataTransfer());
    await chip.dispatchEvent('dragstart', { dataTransfer: dt });
    await target.dispatchEvent('dragover', { dataTransfer: dt });
    await target.dispatchEvent('drop', { dataTransfer: dt });

    // Read straight away — see (3) above.
    await expect(page.locator('#dropMsg'),
      'the calendar should say what it just did').toContainText(`Moved ${who} to 2026-08-19`);

    // And it stuck. The server is the source of truth, so this re-reads the
    // grid rather than trusting the toast.
    await page.goto(CRM + '/bookings/calendar?year=2026&month=8');
    const moved = page.locator(`.daycell[data-date="2026-08-19"] .jobchip[title^="${who}"]`);
    await expect(moved, 'the job should now sit on the 19th').toBeVisible();
    await expect(page.locator(`.daycell[data-date="2026-08-05"] .jobchip[title^="${who}"]`),
      'and no longer on the 5th').toHaveCount(0);

    // Put the database back. Leaving this behind is what broke (1).
    page.on('dialog', d => d.accept());
    await page.goto(bookingUrl);
    const del = page.locator('button:has-text("Delete Booking")');
    if (await del.count()) {
      await del.first().click();
      await page.waitForLoadState('networkidle');
    }
  });
});
