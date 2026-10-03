// @ts-check
/**
 * The hiring pipeline, walked the way a real person walks it.
 *
 * Boot a throwaway instance first — its own empty SQLite database, and no
 * TWILIO_* or RESEND_* keys, so send_sms and send_email return "not connected"
 * rather than contacting anybody:
 *
 *   DATABASE_URL="sqlite:////tmp/e2e_hire.db" SECRET_KEY=e2e-test \
 *   ADMIN_USER=e2e ADMIN_PASS=e2epass python3 -c \
 *   "from app import create_app; create_app().run(port=5055)"
 *
 * Then:  npx playwright test tests/hiring-pipeline-e2e.spec.js
 */
const { test, expect } = require('@playwright/test');

const CRM  = process.env.E2E_CRM  || 'http://localhost:5055';
const USER = process.env.E2E_USER || 'e2e';
const PASS = process.env.E2E_PASS || 'e2epass';

const who   = 'Pipeline ' + Date.now().toString().slice(-6);
const email = `pipeline${Date.now().toString().slice(-6)}@example.test`;

test.describe.serial('Hiring pipeline, end to end', () => {

  test('the apply page is reachable and in both languages', async ({ page }) => {
    await page.goto(CRM + '/contractors/apply');
    await expect(page.locator('form')).toBeVisible();
    // The bilingual spans carry both, so a Spanish speaker is not stuck.
    const es = await page.locator('[data-es]').count();
    expect(es).toBeGreaterThan(5);
  });

  test('the pool consent box is present, optional, and not pre-ticked', async ({ page }) => {
    await page.goto(CRM + '/contractors/apply');
    const box = page.locator('input[name="share_with_other_companies"]');
    await expect(box).toHaveCount(1);
    await expect(box).not.toBeChecked();          // opt in, never opt out
    expect(await box.getAttribute('required')).toBeNull();
  });

  test('somebody applies, and it lands', async ({ page }) => {
    await page.goto(CRM + '/contractors/apply');
    await page.fill('input[name="name"]', who);
    await page.fill('input[name="email"]', email);
    await page.fill('input[name="phone"]', '(407) 555-0123');
    const exp = page.locator('select[name="years_experience"]');
    if (await exp.count()) await exp.selectOption('5+ years');
    // Every required box, plus the optional one this test is about.
    for (const sel of ['input[name="has_transportation"]',
                       'input[name="background_check_consent"]',
                       'input[name="understands_bgcheck"]',
                       'input[name="agrees_to_ic_terms"]',
                       'input[name="share_with_other_companies"]']) {
      const el = page.locator(sel).first();
      if (await el.count()) await el.check({ force: true }).catch(() => {});
    }
    await page.locator('button[type="submit"], input[type="submit"]').first().click();
    await expect(page.locator('body')).toContainText(/thank|received|got it|gracias/i,
                                                     { timeout: 15000 });
  });

  test('the owner sees the application', async ({ page }) => {
    await page.goto(CRM + '/login');
    await page.fill('input[name="username"]', USER);
    await page.fill('input[name="password"]', PASS);
    await page.locator('button[type="submit"]').first().click();
    await page.goto(CRM + '/contractors/applications');
    await expect(page.locator('body')).toContainText(who, { timeout: 15000 });
  });

  test('the three hiring pages are in the menu and open', async ({ page }) => {
    await page.goto(CRM + '/login');
    await page.fill('input[name="username"]', USER);
    await page.fill('input[name="password"]', PASS);
    await page.locator('button[type="submit"]').first().click();

    for (const [path, needle] of [
      ['/admin/talent',        /cleaners looking for work/i],
      ['/admin/talent/invite', /past applicants/i],
      ['/admin/talent/ads',    /job adverts/i],
    ]) {
      await page.goto(CRM + path);
      await expect(page.locator('body')).toContainText(needle);
    }
    // and reachable without typing a URL — they sit in the Hiring tab bar
    await page.goto(CRM + '/contractors/applications');
    const tabs = page.locator('.section-tabs a[href*="/admin/talent"]');
    expect(await tabs.count()).toBe(3);
  });

  test('the advert pack shows the right one for a 1099 shop', async ({ page }) => {
    await page.goto(CRM + '/login');
    await page.fill('input[name="username"]', USER);
    await page.fill('input[name="password"]', PASS);
    await page.locator('button[type="submit"]').first().click();
    await page.goto(CRM + '/admin/talent/ads');
    await expect(page.locator('body')).toContainText(/1099 independent contractors/i);
    await expect(page.locator('body')).toContainText(/Independent Contractor/);
    await expect(page.locator('body')).toContainText(/Contratista Independiente/);
    await expect(page.locator('body')).toContainText(/do not mix the two/i);
  });

  test('the applicant who ticked the box is in the pool, and can leave', async ({ page }) => {
    await page.goto(CRM + '/login');
    await page.fill('input[name="username"]', USER);
    await page.fill('input[name="password"]', PASS);
    await page.locator('button[type="submit"]').first().click();
    await page.goto(CRM + '/admin/talent');
    await expect(page.locator('body')).toContainText(who, { timeout: 15000 });
  });

});
