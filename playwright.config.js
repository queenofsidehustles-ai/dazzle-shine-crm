// @ts-check
const { defineConfig } = require('@playwright/test');

/**
 * Two suites, deliberately separated:
 *
 *   tests/local-e2e.spec.js   full write flows against a LOCAL CRM with its own
 *                             empty database. Creates bookings, assigns cleaners,
 *                             logs expenses, checks the P&L. Safe — no Twilio or
 *                             Resend keys locally, so nothing is sent to anyone.
 *
 *   tests/live-readonly.spec.js  READ-ONLY against production. Logs in, loads every
 *                             page, asserts nothing is broken on the real deploy.
 *                             Never submits a form that changes data.
 *
 * Run:  npx playwright test tests/local-e2e.spec.js
 *       npx playwright test tests/live-readonly.spec.js
 */
module.exports = defineConfig({
  testDir: './tests',
  timeout: 45000,
  expect: { timeout: 10000 },
  fullyParallel: false,        // these share one database; keep them ordered
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    actionTimeout: 15000,
    ignoreHTTPSErrors: true,
    screenshot: 'only-on-failure',
  },
});
