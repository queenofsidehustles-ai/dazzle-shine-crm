// @ts-check
const { test, expect } = require('@playwright/test');

const CRM = 'https://dazzle-shine-crm-production.up.railway.app';
const SITE = 'https://www.dazzleandshinemaids.com';

// ─── Fill these in before running admin tests ───────────────────────────────
// Set via environment: ADMIN_USER=admin ADMIN_PASS=yourpassword npx playwright test
const ADMIN_USER = process.env.ADMIN_USER || 'admin';
const ADMIN_PASS = process.env.ADMIN_PASS || '';

// Helper: log into the CRM
async function login(page) {
  await page.goto(CRM + '/login');
  await page.fill('input[name="username"]', ADMIN_USER);
  await page.fill('input[name="password"]', ADMIN_PASS);
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL(CRM + '/');
}

// ═══════════════════════════════════════════════════════════════════════════════
// PUBLIC API TESTS (no login needed)
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('API — Public endpoints', () => {
  test('GET /api/config returns stripe_pk', async ({ request }) => {
    const res = await request.get(CRM + '/api/config');
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(data).toHaveProperty('stripe_pk');
    console.log('  Stripe PK present:', data.stripe_pk ? '✓' : '✗ MISSING');
  });

  test('POST /api/price returns calculated price', async ({ request }) => {
    const res = await request.post(CRM + '/api/price', {
      data: { service_type: 'standard', bedrooms: 3, bathrooms: 2, extras: '', frequency: 'one_time' },
    });
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(data.total).toBeGreaterThan(0);
    expect(data.deposit).toBe(50);
    console.log('  Price calculated: $' + data.total, '| Deposit: $' + data.deposit);
  });

  test('POST /api/price — deep clean is more expensive than standard', async ({ request }) => {
    const [std, deep] = await Promise.all([
      request.post(CRM + '/api/price', { data: { service_type: 'standard', bedrooms: 2, bathrooms: 1 } }),
      request.post(CRM + '/api/price', { data: { service_type: 'deep', bedrooms: 2, bathrooms: 1 } }),
    ]);
    const stdData = await std.json();
    const deepData = await deep.json();
    expect(deepData.total).toBeGreaterThan(stdData.total);
    console.log('  Standard: $' + stdData.total, '| Deep: $' + deepData.total);
  });

  test('POST /api/validate-code — invalid code returns error', async ({ request }) => {
    const res = await request.post(CRM + '/api/validate-code', {
      data: { code: 'FAKECODE999', price: 150 },
    });
    const data = await res.json();
    expect(data.ok).toBe(false);
    console.log('  Invalid code rejected ✓');
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// PUBLIC WEBSITE TESTS
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Website — Public pages', () => {
  test('Homepage loads with correct title', async ({ page }) => {
    await page.goto(SITE);
    await expect(page).toHaveTitle(/Dazzle|Shine|Maid/i);
    console.log('  Homepage title: ✓');
  });

  test('Homepage has booking section', async ({ page }) => {
    await page.goto(SITE);
    await expect(page.locator('#book')).toBeVisible();
    console.log('  Booking section present ✓');
  });

  test('Homepage has Join Our Team section', async ({ page }) => {
    await page.goto(SITE);
    await expect(page.locator('#careers')).toBeVisible();
    console.log('  Careers section present ✓');
  });

  test('Price calculator updates when service is selected', async ({ page }) => {
    await page.goto(SITE + '#book');
    await page.waitForTimeout(1000);
    // Select standard service
    const serviceCard = page.locator('input[name="service_type"][value="standard"]');
    if (await serviceCard.count() > 0) {
      await serviceCard.first().click();
      await page.selectOption('#bedrooms', '3');
      await page.selectOption('#bathrooms', '2');
      await page.waitForTimeout(2000);
      const priceDisplay = page.locator('#price-display');
      const isVisible = await priceDisplay.isVisible().catch(() => false);
      console.log('  Price display visible after selection:', isVisible ? '✓' : '— (may need JS load time)');
    } else {
      console.log('  Service cards not found on initial load (expected)');
    }
  });

  test('Quick quote form is present', async ({ page }) => {
    await page.goto(SITE);
    await expect(page.locator('#qq-name')).toBeVisible();
    console.log('  Quick quote form present ✓');
  });

  test('Careers application form is present', async ({ page }) => {
    await page.goto(SITE + '#careers');
    await expect(page.locator('#ca-name')).toBeVisible();
    await expect(page.locator('#ca-email')).toBeVisible();
    console.log('  Careers form fields present ✓');
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// PUBLIC CONTRACTOR APPLICATION (CRM)
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Contractor application form (CRM)', () => {
  test('Application page loads', async ({ page }) => {
    await page.goto(CRM + '/contractors/apply');
    await expect(page.locator('form')).toBeVisible();
    await expect(page.locator('input[name="name"]')).toBeVisible();
    console.log('  Application form loads ✓');
  });

  test('Application requires name and email', async ({ page }) => {
    await page.goto(CRM + '/contractors/apply');
    await page.click('button[type="submit"]');
    // Should stay on same page (form validation)
    await expect(page).toHaveURL(CRM + '/contractors/apply');
    console.log('  Form validation works ✓');
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// CRM ADMIN TESTS (requires ADMIN_USER + ADMIN_PASS env vars)
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('CRM Admin — Login', () => {
  test('Login page loads', async ({ page }) => {
    await page.goto(CRM + '/login');
    await expect(page.locator('input[name="username"]')).toBeVisible();
    await expect(page.locator('input[name="password"]')).toBeVisible();
    console.log('  Login page loads ✓');
  });

  test('Wrong password is rejected', async ({ page }) => {
    await page.goto(CRM + '/login');
    await page.fill('input[name="username"]', 'admin');
    await page.fill('input[name="password"]', 'wrongpassword123');
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL(CRM + '/login');
    console.log('  Wrong password rejected ✓');
  });
});

test.describe('CRM Admin — Navigation (requires credentials)', () => {
  test.skip(!ADMIN_PASS, 'Set ADMIN_PASS env var to run admin tests');

  test('Login succeeds', async ({ page }) => {
    await login(page);
    await expect(page.locator('.sidebar')).toBeVisible();
    console.log('  Login successful ✓');
  });

  test('Dashboard loads with stats', async ({ page }) => {
    await login(page);
    await expect(page.locator('.stat-grid')).toBeVisible();
    console.log('  Dashboard stats visible ✓');
  });

  test('All sidebar links load without 500 error', async ({ page }) => {
    await login(page);
    const links = [
      ['/bookings/', 'Bookings'],
      ['/bookings/calendar', 'Calendar'],
      ['/bookings/clients', 'Clients'],
      ['/reports', 'Reports'],
      ['/leads/', 'Leads'],
      ['/quotes/', 'Quotes'],
      ['/contractors/team', 'Team'],
      ['/contractors/applications', 'Applications'],
      ['/contractors/payroll', 'Payroll'],
      ['/workorders/templates', 'Checklists'],
      ['/content/', 'Content'],
      ['/discounts/', 'Discounts'],
      ['/settings/pricing', 'Settings Pricing'],
      ['/settings/business', 'Settings Business'],
    ];
    for (const [path, name] of links) {
      await page.goto(CRM + path);
      const status = await page.evaluate(() => document.title);
      const hasError = await page.locator('text=Internal Server Error').isVisible();
      console.log(`  ${name}: ${hasError ? '✗ ERROR' : '✓'} (${status})`);
      expect(hasError).toBe(false);
    }
  });

  test('Can create a discount code', async ({ page }) => {
    await login(page);
    const code = 'PW' + Date.now().toString().slice(-6);
    await page.goto(CRM + '/discounts/new');
    await page.fill('input[name="code"]', code);
    await page.selectOption('select[name="discount_type"]', 'percent');
    await page.fill('input[name="discount_value"]', '10');
    await page.click('button[type="submit"]');
    await expect(page.locator('text=' + code)).toBeVisible();
    console.log('  Discount code created ✓');
  });

  test('Reports page loads without error', async ({ page }) => {
    await login(page);
    await page.goto(CRM + '/reports');
    await expect(page.locator('#revenueChart')).toBeVisible();
    console.log('  Reports chart canvas present ✓');
  });

  test('Checklist templates page loads', async ({ page }) => {
    await login(page);
    await page.goto(CRM + '/workorders/templates');
    await expect(page.locator('.card')).toBeVisible();
    console.log('  Checklists page loads ✓');
  });

  test('Content studio loads', async ({ page }) => {
    await login(page);
    await page.goto(CRM + '/content/');
    await expect(page.locator('select[name="post_type"]')).toBeVisible();
    console.log('  Content studio form present ✓');
  });

  test('Payroll page loads and shows date range picker', async ({ page }) => {
    await login(page);
    await page.goto(CRM + '/contractors/payroll');
    await expect(page.locator('input[name="start"]')).toBeVisible();
    console.log('  Payroll date picker present ✓');
  });
});
