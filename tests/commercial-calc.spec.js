// @ts-check
/**
 * The number on the screen is the number the server worked out.
 *
 * This is the test that would have caught the original fault. The commercial
 * price used to be calculated in JavaScript, in two separate copies, and the
 * copies had drifted: one ignored scope add-ons entirely, so a medical office
 * priced from the account form came out at office rates while the same
 * building priced on the calculator page came out higher. Meanwhile the Python
 * function the module called "the pricing brain" was called by nothing, so
 * every correction anybody made to it changed nothing anybody was quoted.
 *
 * Reading the source and checking the formulas match would not have found it —
 * they were different formulas in different files and both looked fine on
 * their own. So this loads the real page in a real browser, types real
 * numbers, and compares what is rendered against what /commercial/quote.json
 * returns. If the arithmetic ever moves back into the template, these disagree.
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

/** What the server says a job costs. The single source of truth. */
async function serverQuote(page, params) {
  const q = new URLSearchParams(params);
  const r = await page.request.get(CRM + '/commercial/quote.json?' + q.toString());
  expect(r.ok()).toBeTruthy();
  return r.json();
}

test.describe.configure({ mode: 'serial' });

test.describe('Commercial calculator — screen agrees with server', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  // Sizes, distances and facility types that exercise the parts that differ:
  // above and below the minimum, near and far, plain and mandatory-scope.
  const CASES = [
    { sqft: 5000, drive: 30, type: 'office', label: 'a mid-size office' },
    { sqft: 1200, drive: 60, type: 'office', label: 'a small job an hour away' },
    { sqft: 1200, drive: 5, type: 'office', label: 'the same job next door' },
    { sqft: 9000, drive: 45, type: 'daycare', label: 'a large daycare' },
  ];

  for (const c of CASES) {
    test(`calculator page: ${c.label}`, async ({ page }) => {
      await page.goto(CRM + '/commercial/calculator');
      await page.click(`#typePick .pick[data-val="${c.type}"]`);
      await page.fill('#f_sqft', String(c.sqft));
      await page.fill('#f_drive', String(c.drive));
      await page.waitForTimeout(600);   // debounce + fetch

      // The hidden field is what gets saved onto the account, so it is the
      // one that actually matters — a pretty number on screen and a different
      // number in the form would be the worst version of this bug.
      const saved = await page.locator('#f_amount').inputValue();

      const extras = await page.locator('.chk input:checked')
        .evaluateAll(els => els.map(e => e.value));
      const params = { sqft: c.sqft, category: c.type, frequency: 'weekly',
                       drive_minutes: c.drive };
      const q = await serverQuote(page, params);
      // Mandatory scope is ticked by the page; ask with the same set.
      const qs = new URLSearchParams(params);
      extras.forEach(e => qs.append('extras', e));
      const r = await page.request.get(CRM + '/commercial/quote.json?' + qs.toString());
      const want = (await r.json()).standard;

      expect(Number(saved), 'the price saved onto the account').toBe(want);
      await expect(page.locator('#result'),
        'and the price shown to the person quoting').toContainText(String(want));
    });
  }

  test('the drive is visible in the breakdown, not hidden in the total', async ({ page }) => {
    await page.goto(CRM + '/commercial/calculator');
    await page.fill('#f_sqft', '5000');
    await page.fill('#f_drive', '45');
    await page.waitForTimeout(600);
    const q = await serverQuote(page, { sqft: 5000, category: 'office',
                                        frequency: 'weekly', drive_minutes: 45 });
    const result = page.locator('#result');
    await expect(result).toContainText(String(q.drive_price));
    await expect(result).toContainText('45-minute');
    // And the parts add up, because they are shown side by side.
    expect(q.onsite_price + q.drive_price).toBe(q.standard);
  });

  test('distance changes the price of a job sitting on the minimum', async ({ page }) => {
    // The original bug, from the outside. Two identical small buildings.
    await page.goto(CRM + '/commercial/calculator');
    await page.fill('#f_sqft', '1200');
    await page.fill('#f_drive', '10');
    await page.waitForTimeout(600);
    const near = Number(await page.locator('#f_amount').inputValue());

    await page.fill('#f_drive', '90');
    await page.waitForTimeout(600);
    const far = Number(await page.locator('#f_amount').inputValue());

    expect(far, 'ninety minutes away must cost more than ten').toBeGreaterThan(near);
  });
});
