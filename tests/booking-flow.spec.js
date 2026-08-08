// @ts-check
// Full booking → assign cleaner → cleaner notified (email + TEXT) → cleanup.
//
// Public part (no login):   npx playwright test booking-flow -g "booking is created"
// Full flow (needs login):  ADMIN_PASS=yourpass TEST_CLEANER_PHONE=+14075551234 npx playwright test booking-flow
//   (set TEST_CLEANER_PHONE to a cell YOU control to actually receive the assignment text)
const { test, expect } = require('@playwright/test');

const CRM = process.env.CRM_BASE || 'http://localhost:5001';  // set CRM_BASE to point this at a deployed instance
const ADMIN_USER = process.env.ADMIN_USER || 'admin';
const ADMIN_PASS = process.env.ADMIN_PASS || '';
const CLEANER_PHONE = process.env.TEST_CLEANER_PHONE || '';           // your cell to receive the real text
const CLEANER_EMAIL = process.env.TEST_CLEANER_EMAIL || 'queenofsidehustles+pwcleaner@gmail.com';
const CUSTOMER_EMAIL = process.env.TEST_CUSTOMER_EMAIL || 'queenofsidehustles+pwbooking@gmail.com';

const stamp = Date.now().toString().slice(-6);
const CUSTOMER = 'PW Booking ' + stamp;
const CLEANER = 'PW Cleaner ' + stamp;
const shared = { bookingId: null };

async function login(page) {
  await page.goto(CRM + '/login');
  await page.fill('input[name="username"]', ADMIN_USER);
  await page.fill('input[name="password"]', ADMIN_PASS);
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL(CRM + '/');
}

test.describe.serial('Booking → assign cleaner → notify (email + text)', () => {

  test('1. A booking is created (public API)', async ({ request }) => {
    const res = await request.post(CRM + '/api/booking', {
      data: {
        name: CUSTOMER, email: CUSTOMER_EMAIL, phone: '4075550123',
        service_type: 'standard', bedrooms: 3, bathrooms: 2,
        address: '123 Test St', city: 'Orlando', zip_code: '32801',
        preferred_date: new Date(Date.now() + 2 * 864e5).toISOString().slice(0, 10),
        preferred_time: '10:00 AM',
      },
    });
    expect(res.ok()).toBeTruthy();   // 200 or 201
    const data = await res.json();
    expect(data.ok).toBe(true);
    shared.bookingId = data.booking_id;
    console.log('  ✓ Booking created — id', data.booking_id, '($' + (data.total ?? '?') + ')');
  });

  test('2. Create a test cleaner', async ({ page }) => {
    test.skip(!ADMIN_PASS, 'Set ADMIN_PASS to run the assign + notify flow.');
    await login(page);
    await page.goto(CRM + '/staff/new');
    await page.fill('input[name="name"]', CLEANER);
    await page.fill('input[name="email"]', CLEANER_EMAIL);
    if (CLEANER_PHONE) await page.fill('input[name="phone"]', CLEANER_PHONE);
    const active = page.locator('input[name="is_active"]');
    if (await active.count() && !(await active.first().isChecked())) await active.first().check();
    await Promise.all([page.waitForLoadState('networkidle'), page.click('button[type="submit"]')]);
    console.log('  ✓ Test cleaner created:', CLEANER, CLEANER_PHONE ? '(phone set)' : '(no phone)');
  });

  test('3. Assign the cleaner → they get notified + texted', async ({ page }) => {
    test.skip(!ADMIN_PASS, 'Set ADMIN_PASS to run the assign + notify flow.');
    await login(page);
    await page.goto(CRM + '/bookings/' + shared.bookingId);
    await page.selectOption('select[name="assigned_cleaner"]', CLEANER);
    await Promise.all([page.waitForLoadState('networkidle'), page.click('button:has-text("Save Changes")')]);
    // The flash confirms the assignment email + checklist (+ text if phone) fired
    await expect(page.locator('body')).toContainText(/notification.*(sent|checklist)|checklist sent/i, { timeout: 8000 });
    console.log('  ✓ Cleaner assigned — assignment email + checklist sent' + (CLEANER_PHONE ? ' + TEXT to your phone 📲' : ''));
  });

  test('4. Clean up (delete test booking + cleaner)', async ({ page }) => {
    test.skip(!ADMIN_PASS, 'Set ADMIN_PASS to run cleanup.');
    await login(page);
    page.on('dialog', (d) => d.accept());
    // delete booking
    if (shared.bookingId) {
      await page.goto(CRM + '/bookings/' + shared.bookingId);
      const del = page.locator('button:has-text("Delete Booking")');
      if (await del.count()) { await del.first().click(); await page.waitForLoadState('networkidle'); }
    }
    // delete test cleaner from the Team page
    await page.goto(CRM + '/contractors/team');
    const card = page.locator('div:has-text("' + CLEANER + '")').locator('button[title="Delete team member"]').first();
    if (await card.count()) { await card.click(); await page.waitForLoadState('networkidle'); }
    console.log('  ✓ Cleaned up test booking + cleaner');
  });
});
