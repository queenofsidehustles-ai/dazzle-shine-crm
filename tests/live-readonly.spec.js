// @ts-check
/**
 * READ-ONLY check against the live CRM.
 *
 * Every assertion here is a GET. Nothing submits a form, assigns a cleaner,
 * broadcasts a job, logs an expense, or touches money — so it can be run against
 * production safely, any time, without texting anyone or polluting the books.
 *
 * Credentials come from the environment, never from source:
 *   ADMIN_USER / ADMIN_PASS  (put them in .env — it's gitignored)
 *
 * Run:  npx playwright test tests/live-readonly.spec.js
 *
 * The ONE exception is the Stripe fee sync, which is opt-in and skipped unless
 * you pass STRIPE_FEE_SYNC=1. It moves no money — it reads Stripe's balance
 * transactions and stores the real fee total — but it does write that figure to
 * the database, so it stays behind a flag rather than running by default.
 */
const { test, expect } = require('@playwright/test');

const CRM = process.env.LIVE_CRM || 'https://dazzle-shine-crm-production.up.railway.app';
const USER = process.env.ADMIN_USER || '';
const PASS = process.env.ADMIN_PASS || '';

test.skip(!USER || !PASS,
  'Set ADMIN_USER and ADMIN_PASS in .env to run the live read-only checks.');

async function login(page) {
  await page.goto(CRM + '/login');
  await page.fill('input[name="username"]', USER);
  await page.fill('input[name="password"]', PASS);
  await page.click('button[type="submit"]');
  await expect(page.locator('.sidebar'),
    'login should land on the dashboard — check ADMIN_USER / ADMIN_PASS').toBeVisible();
}

test.describe.configure({ mode: 'serial' });

test.describe('Live CRM — read only', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('1. the deployed login works', async ({ page }) => {
    await expect(page).toHaveURL(CRM + '/');
  });

  test('2. the Money section shipped', async ({ page }) => {
    const sidebar = page.locator('.sidebar');
    await expect(sidebar).toContainText('Money');
    await expect(sidebar).toContainText('Profit & Loss');
    await expect(sidebar).toContainText('Expenses');
  });

  test('3. the dashboard shows the money tiles', async ({ page }) => {
    const text = await page.locator('body').innerText();
    expect(text).toMatch(/money in/i);
    expect(text).toMatch(/net profit/i);
    expect(text).toMatch(/still owed to you/i);
  });

  test('4. the P&L loads and its arithmetic balances on real data', async ({ page }) => {
    await page.goto(CRM + '/money/pnl');
    await expect(page.locator('body')).toContainText('Is your advertising paying for itself');

    const tile = async (label) => {
      const v = page.locator('.stat-card', { hasText: label }).first().locator('.value');
      return parseFloat((await v.innerText()).replace(/[$,\s]/g, ''));
    };
    const moneyIn = await tile('Money in');
    const moneyOut = await tile('Money out');
    const net = await tile('Net profit');
    expect(Number.isNaN(moneyIn)).toBe(false);
    // The books must reconcile against whatever real data is in there.
    expect(Math.abs((moneyIn - moneyOut) - net)).toBeLessThan(0.02);
    console.log(`   live P&L this month → in $${moneyIn}, out $${moneyOut}, net $${net}`);
  });

  test('5. the expenses ledger loads with the cleaner picker categories', async ({ page }) => {
    await page.goto(CRM + '/money/expenses');
    const options = await page.locator('select[name="category"] option').allInnerTexts();
    expect(options.join('|')).toContain('Google leads');
    expect(options.join('|')).toContain('Promotional items');
    expect(options.join('|')).toContain('Vehicle mileage');
    // The auto-only categories must never be selectable.
    expect(options.join('|')).not.toContain('Cleaner pay');
    expect(options.join('|')).not.toContain('Card processing fees');
  });

  test('6. a real booking page shows the crew / pay card', async ({ page }) => {
    await page.goto(CRM + '/bookings/');
    const firstBooking = page.locator('table a[href*="/bookings/"]').first();
    if (!(await firstBooking.count())) {
      test.skip(true, 'No bookings on the live CRM to open.');
      return;
    }
    await firstBooking.click();
    const body = page.locator('body');
    await expect(body).toContainText("Who's Paid For This Job");
    await expect(body).toContainText('How many cleaners are you paying?');
    // The picker must be present whenever a spot is open — the bug we fixed.
    const spotsOpen = await page.locator('select[name="add_staff_id"]').count();
    const alreadyFull = (await body.innerText()).includes('Already assigned to');
    expect(spotsOpen > 0 || alreadyFull,
      'either the cleaner picker shows, or the job is already fully assigned').toBe(true);
  });

  test('7. payroll and commissions load', async ({ page }) => {
    for (const path of ['/contractors/payroll', '/commissions/']) {
      const res = await page.goto(CRM + path);
      expect(res.status(), `${path}`).toBeLessThan(400);
      await expect(page.locator('body')).not.toContainText('Traceback (most recent call last)');
    }
  });

  test('8. the P&L CSV export downloads', async ({ page }) => {
    const res = await page.request.get(CRM + '/money/pnl/export');
    expect(res.status()).toBe(200);
    const csv = await res.text();
    expect(csv).toContain('NET PROFIT');
    expect(csv).toContain('Cash — income counted when payment was received');
  });

  test('9. every page in the sidebar loads on the live deploy', async ({ page }) => {
    await page.goto(CRM + '/');
    const hrefs = await page.locator('.sidebar nav a').evaluateAll(
      (as) => as.map((a) => a.getAttribute('href')).filter(Boolean));
    const links = [...new Set(hrefs)].filter((h) => h && !h.includes('logout'));
    const broken = [];
    for (const href of links) {
      const res = await page.goto(new URL(href, CRM).toString());
      const body = await page.locator('body').innerText();
      if (!res || res.status() >= 400) broken.push(`${href} → HTTP ${res && res.status()}`);
      else if (body.includes('Traceback (most recent call last)')) broken.push(`${href} → stack trace`);
    }
    expect(broken, `broken pages on live: ${broken.join(', ')}`).toEqual([]);
  });

  // ── Stripe: reads real fee data. Opt-in only. ─────────────────────────────
  test('10. Stripe fee sync pulls real fees (opt-in)', async ({ page }) => {
    test.skip(process.env.STRIPE_FEE_SYNC !== '1',
      'Set STRIPE_FEE_SYNC=1 to let this write the real fee total to the database.');

    await page.goto(CRM + '/money/pnl');
    const syncButton = page.locator('button:has-text("Pull fees from Stripe")');
    if (!(await syncButton.count())) {
      console.log('   No sync button — fees for this period are already synced.');
      return;
    }
    await syncButton.click();
    const body = await page.locator('body').innerText();
    // Either it worked, or it told us exactly why not — silence would be the bug.
    const worked = /Pulled card fees for \d+ month/i.test(body);
    const explained = /could not sync/i.test(body);
    console.log('   Stripe sync result: ' + (worked ? 'success' : explained ? 'reported an error' : 'no message'));
    expect(worked || explained,
      'the sync should either succeed or say why it failed').toBe(true);
    expect(worked, 'Stripe fee sync should succeed with a live key').toBe(true);
  });
});
