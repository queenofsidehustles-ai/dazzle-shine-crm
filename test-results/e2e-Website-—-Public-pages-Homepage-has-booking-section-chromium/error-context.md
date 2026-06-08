# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: e2e.spec.js >> Website — Public pages >> Homepage has booking section
- Location: tests/e2e.spec.js:77:3

# Error details

```
Error: page.goto: net::ERR_CONNECTION_CLOSED at https://www.dazzleandshinemaids.com/
Call log:
  - navigating to "https://www.dazzleandshinemaids.com/", waiting until "load"

```

# Test source

```ts
  1   | // @ts-check
  2   | const { test, expect } = require('@playwright/test');
  3   | 
  4   | const CRM = 'https://dazzle-shine-crm-production.up.railway.app';
  5   | const SITE = 'https://www.dazzleandshinemaids.com';
  6   | 
  7   | // ─── Fill these in before running admin tests ───────────────────────────────
  8   | // Set via environment: ADMIN_USER=admin ADMIN_PASS=yourpassword npx playwright test
  9   | const ADMIN_USER = process.env.ADMIN_USER || 'admin';
  10  | const ADMIN_PASS = process.env.ADMIN_PASS || '';
  11  | 
  12  | // Helper: log into the CRM
  13  | async function login(page) {
  14  |   await page.goto(CRM + '/login');
  15  |   await page.fill('input[name="username"]', ADMIN_USER);
  16  |   await page.fill('input[name="password"]', ADMIN_PASS);
  17  |   await page.click('button[type="submit"]');
  18  |   await expect(page).toHaveURL(CRM + '/');
  19  | }
  20  | 
  21  | // ═══════════════════════════════════════════════════════════════════════════════
  22  | // PUBLIC API TESTS (no login needed)
  23  | // ═══════════════════════════════════════════════════════════════════════════════
  24  | 
  25  | test.describe('API — Public endpoints', () => {
  26  |   test('GET /api/config returns stripe_pk', async ({ request }) => {
  27  |     const res = await request.get(CRM + '/api/config');
  28  |     expect(res.status()).toBe(200);
  29  |     const data = await res.json();
  30  |     expect(data).toHaveProperty('stripe_pk');
  31  |     console.log('  Stripe PK present:', data.stripe_pk ? '✓' : '✗ MISSING');
  32  |   });
  33  | 
  34  |   test('POST /api/price returns calculated price', async ({ request }) => {
  35  |     const res = await request.post(CRM + '/api/price', {
  36  |       data: { service_type: 'standard', bedrooms: 3, bathrooms: 2, extras: '', frequency: 'one_time' },
  37  |     });
  38  |     expect(res.status()).toBe(200);
  39  |     const data = await res.json();
  40  |     expect(data.total).toBeGreaterThan(0);
  41  |     expect(data.deposit).toBe(50);
  42  |     console.log('  Price calculated: $' + data.total, '| Deposit: $' + data.deposit);
  43  |   });
  44  | 
  45  |   test('POST /api/price — deep clean is more expensive than standard', async ({ request }) => {
  46  |     const [std, deep] = await Promise.all([
  47  |       request.post(CRM + '/api/price', { data: { service_type: 'standard', bedrooms: 2, bathrooms: 1 } }),
  48  |       request.post(CRM + '/api/price', { data: { service_type: 'deep', bedrooms: 2, bathrooms: 1 } }),
  49  |     ]);
  50  |     const stdData = await std.json();
  51  |     const deepData = await deep.json();
  52  |     expect(deepData.total).toBeGreaterThan(stdData.total);
  53  |     console.log('  Standard: $' + stdData.total, '| Deep: $' + deepData.total);
  54  |   });
  55  | 
  56  |   test('POST /api/validate-code — invalid code returns error', async ({ request }) => {
  57  |     const res = await request.post(CRM + '/api/validate-code', {
  58  |       data: { code: 'FAKECODE999', price: 150 },
  59  |     });
  60  |     const data = await res.json();
  61  |     expect(data.ok).toBe(false);
  62  |     console.log('  Invalid code rejected ✓');
  63  |   });
  64  | });
  65  | 
  66  | // ═══════════════════════════════════════════════════════════════════════════════
  67  | // PUBLIC WEBSITE TESTS
  68  | // ═══════════════════════════════════════════════════════════════════════════════
  69  | 
  70  | test.describe('Website — Public pages', () => {
  71  |   test('Homepage loads with correct title', async ({ page }) => {
  72  |     await page.goto(SITE);
  73  |     await expect(page).toHaveTitle(/Dazzle|Shine|Maid/i);
  74  |     console.log('  Homepage title: ✓');
  75  |   });
  76  | 
  77  |   test('Homepage has booking section', async ({ page }) => {
> 78  |     await page.goto(SITE);
      |                ^ Error: page.goto: net::ERR_CONNECTION_CLOSED at https://www.dazzleandshinemaids.com/
  79  |     await expect(page.locator('#book')).toBeVisible();
  80  |     console.log('  Booking section present ✓');
  81  |   });
  82  | 
  83  |   test('Homepage has Join Our Team section', async ({ page }) => {
  84  |     await page.goto(SITE);
  85  |     await expect(page.locator('#careers')).toBeVisible();
  86  |     console.log('  Careers section present ✓');
  87  |   });
  88  | 
  89  |   test('Price calculator updates when service is selected', async ({ page }) => {
  90  |     await page.goto(SITE + '#book');
  91  |     await page.waitForTimeout(1000);
  92  |     // Select standard service
  93  |     const serviceCard = page.locator('input[name="service_type"][value="standard"]');
  94  |     if (await serviceCard.count() > 0) {
  95  |       await serviceCard.first().click();
  96  |       await page.selectOption('#bedrooms', '3');
  97  |       await page.selectOption('#bathrooms', '2');
  98  |       await page.waitForTimeout(2000);
  99  |       const priceDisplay = page.locator('#price-display');
  100 |       const isVisible = await priceDisplay.isVisible().catch(() => false);
  101 |       console.log('  Price display visible after selection:', isVisible ? '✓' : '— (may need JS load time)');
  102 |     } else {
  103 |       console.log('  Service cards not found on initial load (expected)');
  104 |     }
  105 |   });
  106 | 
  107 |   test('Quick quote form is present', async ({ page }) => {
  108 |     await page.goto(SITE);
  109 |     await expect(page.locator('#qq-name')).toBeVisible();
  110 |     console.log('  Quick quote form present ✓');
  111 |   });
  112 | 
  113 |   test('Careers application form is present', async ({ page }) => {
  114 |     await page.goto(SITE + '#careers');
  115 |     await expect(page.locator('#ca-name')).toBeVisible();
  116 |     await expect(page.locator('#ca-email')).toBeVisible();
  117 |     console.log('  Careers form fields present ✓');
  118 |   });
  119 | });
  120 | 
  121 | // ═══════════════════════════════════════════════════════════════════════════════
  122 | // PUBLIC CONTRACTOR APPLICATION (CRM)
  123 | // ═══════════════════════════════════════════════════════════════════════════════
  124 | 
  125 | test.describe('Contractor application form (CRM)', () => {
  126 |   test('Application page loads', async ({ page }) => {
  127 |     await page.goto(CRM + '/contractors/apply');
  128 |     await expect(page.locator('form')).toBeVisible();
  129 |     await expect(page.locator('input[name="name"]')).toBeVisible();
  130 |     console.log('  Application form loads ✓');
  131 |   });
  132 | 
  133 |   test('Application requires name and email', async ({ page }) => {
  134 |     await page.goto(CRM + '/contractors/apply');
  135 |     await page.click('button[type="submit"]');
  136 |     // Should stay on same page (form validation)
  137 |     await expect(page).toHaveURL(CRM + '/contractors/apply');
  138 |     console.log('  Form validation works ✓');
  139 |   });
  140 | });
  141 | 
  142 | // ═══════════════════════════════════════════════════════════════════════════════
  143 | // CRM ADMIN TESTS (requires ADMIN_USER + ADMIN_PASS env vars)
  144 | // ═══════════════════════════════════════════════════════════════════════════════
  145 | 
  146 | test.describe('CRM Admin — Login', () => {
  147 |   test('Login page loads', async ({ page }) => {
  148 |     await page.goto(CRM + '/login');
  149 |     await expect(page.locator('input[name="username"]')).toBeVisible();
  150 |     await expect(page.locator('input[name="password"]')).toBeVisible();
  151 |     console.log('  Login page loads ✓');
  152 |   });
  153 | 
  154 |   test('Wrong password is rejected', async ({ page }) => {
  155 |     await page.goto(CRM + '/login');
  156 |     await page.fill('input[name="username"]', 'admin');
  157 |     await page.fill('input[name="password"]', 'wrongpassword123');
  158 |     await page.click('button[type="submit"]');
  159 |     await expect(page).toHaveURL(CRM + '/login');
  160 |     console.log('  Wrong password rejected ✓');
  161 |   });
  162 | });
  163 | 
  164 | test.describe('CRM Admin — Navigation (requires credentials)', () => {
  165 |   test.skip(!ADMIN_PASS, 'Set ADMIN_PASS env var to run admin tests');
  166 | 
  167 |   test('Login succeeds', async ({ page }) => {
  168 |     await login(page);
  169 |     await expect(page.locator('.sidebar')).toBeVisible();
  170 |     console.log('  Login successful ✓');
  171 |   });
  172 | 
  173 |   test('Dashboard loads with stats', async ({ page }) => {
  174 |     await login(page);
  175 |     await expect(page.locator('.stat-grid')).toBeVisible();
  176 |     console.log('  Dashboard stats visible ✓');
  177 |   });
  178 | 
```