// @ts-check
const { defineConfig } = require('@playwright/test');

const CRM = 'https://dazzle-shine-crm-production.up.railway.app';
const SITE = 'https://www.dazzleandshinemaids.com';

module.exports = defineConfig({
  testDir: './tests',
  timeout: 30000,
  retries: 1,
  reporter: 'list',
  use: {
    headless: true,
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
  // Pass URLs as globals
  globalSetup: undefined,
  // Expose to tests via env
  define: {
    CRM_URL: JSON.stringify(CRM),
    SITE_URL: JSON.stringify(SITE),
  },
});
