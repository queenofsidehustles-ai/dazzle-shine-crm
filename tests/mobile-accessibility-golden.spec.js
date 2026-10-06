// @ts-check
/**
 * Cohort launch evidence for critical owner journeys on narrow/mobile and desktop
 * viewports. This suite is intentionally local-only: it performs authenticated
 * navigation against the disposable CRM used by local-e2e.spec.js and never
 * contacts Production or external providers.
 *
 * Run after starting the disposable local CRM documented in local-e2e.spec.js:
 *   npx playwright test tests/mobile-accessibility-golden.spec.js
 */
const { test, expect } = require('@playwright/test');

const CRM = process.env.LOCAL_CRM || 'http://localhost:5001';
const USER = process.env.LOCAL_ADMIN_USER || 'e2e';
const PASS = process.env.LOCAL_ADMIN_PASS || 'e2epass';

const viewports = [
  { name: 'mobile-360', width: 360, height: 800 },
  { name: 'mobile-390', width: 390, height: 844 },
  { name: 'desktop-1280', width: 1280, height: 800 },
];

const criticalRoutes = [
  { name: 'dashboard', path: '/' },
  { name: 'bookings', path: '/bookings/' },
  { name: 'new-booking', path: '/bookings/new' },
  { name: 'money', path: '/money/pnl' },
];

async function login(page) {
  await page.goto(CRM + '/login');
  await page.locator('input[name="username"]').fill(USER);
  await page.locator('input[name="password"]').fill(PASS);
  await page.locator('button[type="submit"]').click();
  await expect(page.locator('body')).not.toContainText('Traceback (most recent call last)');
}

function interactiveLocator(page) {
  return page.locator('a[href], button, input:not([type="hidden"]), select, textarea');
}

for (const viewport of viewports) {
  test.describe(`Golden journey accessibility — ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test.beforeEach(async ({ page }) => { await login(page); });

    for (const route of criticalRoutes) {
      test(`${route.name} is usable without horizontal document overflow`, async ({ page }) => {
        const response = await page.goto(CRM + route.path);
        expect(response, `${route.path} should return a response`).not.toBeNull();
        expect(response.status(), `${route.path} should load`).toBeLessThan(400);
        await expect(page.locator('body')).not.toContainText('Traceback (most recent call last)');

        const dimensions = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        }));
        expect(
          dimensions.scrollWidth,
          `${route.path} horizontally overflows ${viewport.name}`,
        ).toBeLessThanOrEqual(dimensions.clientWidth + 2);
      });
    }

    test('critical controls expose accessible names and keyboard focus', async ({ page }) => {
      await page.goto(CRM + '/bookings/new');
      const controls = interactiveLocator(page);
      const count = await controls.count();
      expect(count, 'critical page should expose interactive controls').toBeGreaterThan(0);

      for (let i = 0; i < count; i += 1) {
        const control = controls.nth(i);
        if (!(await control.isVisible()) || !(await control.isEnabled())) continue;
        const tag = await control.evaluate((el) => el.tagName.toLowerCase());
        const type = ((await control.getAttribute('type')) || '').toLowerCase();
        if (tag === 'input' && ['hidden', 'submit', 'button'].includes(type)) continue;

        const name = await control.evaluate((el) => {
          const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby');
          if (aria && aria.trim()) return aria.trim();
          if (el.id) {
            const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (label && label.textContent && label.textContent.trim()) return label.textContent.trim();
          }
          if (el.closest('label') && el.closest('label').textContent) {
            return el.closest('label').textContent.trim();
          }
          if (el.getAttribute('placeholder')) return el.getAttribute('placeholder').trim();
          return (el.textContent || '').trim();
        });
        expect(name, `visible ${tag} control ${i} should have an accessible name`).not.toBe('');
      }

      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => document.activeElement && document.activeElement !== document.body);
      expect(focused, 'keyboard navigation should move focus into the page').toBe(true);
    });
  });
}
