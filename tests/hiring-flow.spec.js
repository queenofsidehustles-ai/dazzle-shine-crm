// @ts-check
// End-to-end test of the contractor hiring flow:
//   apply (qualifying) → lands in CRM → interview link queued → clean up
//
// Run the PUBLIC part (no login):   npx playwright test hiring-flow -g "submits"
// Run the FULL flow (needs login):  ADMIN_PASS=yourpassword npx playwright test hiring-flow
const { test, expect } = require('@playwright/test');

const CRM = 'https://dazzle-shine-crm-production.up.railway.app';
const ADMIN_USER = process.env.ADMIN_USER || 'admin';
const ADMIN_PASS = process.env.ADMIN_PASS || '';
// Any email lands in Monica's inbox via the +pwtest tag; override with TEST_EMAIL.
const TEST_EMAIL = process.env.TEST_EMAIL || 'queenofsidehustles+pwtest@gmail.com';

// Unique name so we can find + delete exactly this test row.
const testName = 'PW Test ' + Date.now().toString().slice(-6);

async function login(page) {
  await page.goto(CRM + '/login');
  await page.fill('input[name="username"]', ADMIN_USER);
  await page.fill('input[name="password"]', ADMIN_PASS);
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL(CRM + '/');
}

test.describe.serial('Hiring flow — apply → interview queued → cleanup', () => {

  test('A qualifying application submits successfully', async ({ page }) => {
    await page.goto(CRM + '/contractors/apply');

    await page.fill('input[name="name"]', testName);
    await page.fill('input[name="email"]', TEST_EMAIL);
    await page.fill('input[name="phone"]', '(407) 555-0123');
    await page.selectOption('select[name="years_experience"]', '5+ years');   // qualifies (has experience)
    await page.check('input[name="services"][value="Standard Cleaning"]');
    await page.check('input[name="availability"][value="Monday"]');
    await page.check('input[name="availability"][value="Tuesday"]');
    await page.check('input[name="has_transportation"]');                     // qualifies (has a car)
    await page.check('input[name="background_check_consent"]');
    await page.check('input[name="understands_bgcheck"]');
    await page.check('input[name="agrees_to_ic_terms"]');
    await page.fill('textarea[name="why_interested"]', 'Playwright automated test — safe to delete.');

    await page.click('button[type="submit"]');

    // Success page
    await expect(page.locator('body')).toContainText(/Application Received|Thank you/i, { timeout: 15000 });
    console.log('  ✓ Application submitted for', testName, '(' + TEST_EMAIL + ')');
  });

  test('Applicant lands in the CRM with the interview link queued, then clean up', async ({ page }) => {
    test.skip(!ADMIN_PASS, 'Set ADMIN_PASS to verify in the CRM and auto-delete the test entry.');

    await login(page);
    await page.goto(CRM + '/contractors/applications');

    const row = page.locator('tr', { hasText: testName });
    await expect(row).toBeVisible({ timeout: 10000 });
    console.log('  ✓ Test applicant appears in the CRM');

    // A qualifying applicant is immediately marked "Interview Link Sent"
    await expect(row).toContainText(/Interview Link Sent/i);
    console.log('  ✓ Interview link was queued automatically');

    // Clean up: accept the confirm() dialog, then click this row's trash button
    page.on('dialog', (d) => d.accept());
    await row.locator('button[title="Delete application"]').click();
    await expect(page.locator('tr', { hasText: testName })).toHaveCount(0, { timeout: 10000 });
    console.log('  ✓ Test applicant deleted — CRM left clean');
  });
});
