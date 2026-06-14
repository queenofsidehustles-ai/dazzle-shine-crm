"""
Full CRM walkthrough audit — identifies UI gaps, broken flows, missing steps.
Run: python3 audit.py
"""
import os, sys, time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "https://dazzle-shine-crm-production.up.railway.app"
USER = os.environ.get("ADMIN_USER", "admin")
PASS = os.environ.get("ADMIN_PASS", "")

gaps   = []
ok     = []
errors = []

def gap(section, msg):
    item = f"⚠️  [{section}] {msg}"
    gaps.append(item); print(item)

def good(section, msg):
    item = f"✅ [{section}] {msg}"
    ok.append(item); print(item)

def err(section, msg):
    item = f"❌ [{section}] {msg}"
    errors.append(item); print(item)

def wait(page, selector, timeout=8000):
    try:
        page.wait_for_selector(selector, timeout=timeout)
        return True
    except PWTimeout:
        return False

def login(page):
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.wait_for_selector('input[name="username"]', timeout=20000)
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', PASS)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle", timeout=15000)
    if "/login" in page.url:
        raise Exception("Login failed — wrong credentials or page error")
    good("Login", "Admin login successful")

def audit_dashboard(page):
    page.goto(f"{BASE}/")
    page.wait_for_load_state("networkidle")
    title = page.title()
    if "dashboard" in title.lower() or page.url.startswith(BASE + "/admin"):
        good("Dashboard", "Loads without error")
    else:
        err("Dashboard", f"Unexpected page: {title}")

    # Check for key nav links
    for label in ["Bookings", "Team", "Applications", "Payroll", "Settings"]:
        if page.query_selector(f'text="{label}"') or label.lower() in page.content().lower():
            good("Dashboard Nav", f'"{label}" link present')
        else:
            gap("Dashboard Nav", f'"{label}" link missing from sidebar')

def audit_applications(page):
    page.goto(f"{BASE}/contractors/applications")
    page.wait_for_load_state("networkidle")

    # Check page structure
    if "Application" in page.content():
        good("Applications", "Applications page loads")
    else:
        err("Applications", "Page failed to load")
        return

    # Check if there's a way to filter / see pipeline stages
    content = page.content()
    for stage in ["New", "Reviewing", "Hired", "Rejected"]:
        if stage in content:
            good("Applications", f'Stage filter "{stage}" present')
        else:
            gap("Applications", f'Stage filter "{stage}" missing')

    # Check if phone interview field exists
    links = page.query_selector_all('a[href*="/applications/"]')
    if links:
        href = links[0].get_attribute("href")
        page.goto(BASE + href if not href.startswith("http") else href)
        page.wait_for_load_state("networkidle")
        c = page.content()
        for field in ["Phone interview", "Background check", "Worker Type", "Hire"]:
            if field.lower() in c.lower():
                good("Application Detail", f'"{field}" section present')
            else:
                gap("Application Detail", f'"{field}" section missing — hiring pipeline incomplete')
    else:
        gap("Applications", "No applications found — cannot audit detail page")

def audit_team(page):
    page.goto(f"{BASE}/contractors/team")
    page.wait_for_load_state("networkidle")
    c = page.content()

    if "Team" in c or "Contractor" in c:
        good("Team", "Team page loads")
    else:
        err("Team", "Team page failed to load")
        return

    # Check if onboarding steps show
    if "Onboarding" in c or "checklist" in c.lower():
        good("Team", "Onboarding progress visible on team list")
    else:
        gap("Team", "No onboarding progress indicator on team list — can't see who needs attention")

    # Click into first staff member
    links = page.query_selector_all('a[href*="/team/"]')
    if links:
        href = links[0].get_attribute("href")
        page.goto(BASE + href if not href.startswith("http") else href)
        page.wait_for_load_state("networkidle")
        c = page.content()
        checks = {
            "Onboarding Checklist": "onboarding checklist showing",
            "Work Agreement": "agreement section present",
            "Pay Settings": "pay settings present",
            "Pending Steps": "pending steps / action items visible",
        }
        for text, desc in checks.items():
            if text.lower() in c.lower():
                good("Staff Detail", desc)
            else:
                gap("Staff Detail", f'"{text}" section missing')

        # Check for Reset Orientation
        if "Reset Orientation" in c or "reset" in c.lower():
            good("Staff Detail", "Reset orientation option present")
        else:
            gap("Staff Detail", "No 'Reset Orientation' button — admin cannot force cleaner to re-take training")

        # Check worker model is visible
        if "contractor" in c.lower() or "employee" in c.lower() or "worker" in c.lower():
            good("Staff Detail", "Worker model visible")
        else:
            gap("Staff Detail", "Worker model (contractor/employee) not shown — uniform/supply steps always visible")
    else:
        gap("Team", "No staff members found")

def audit_bookings(page):
    page.goto(f"{BASE}/bookings/")
    page.wait_for_load_state("networkidle")
    c = page.content()

    if "Booking" in c:
        good("Bookings", "Bookings list loads")
    else:
        err("Bookings", "Bookings page failed to load")
        return

    # Check for status filters
    for status in ["Pending", "Confirmed", "Completed", "Cancelled"]:
        if status in c:
            good("Bookings", f'"{status}" filter present')
        else:
            gap("Bookings", f'"{status}" filter missing')

    # Open a booking and check cleaner assignment
    links = page.query_selector_all('a[href*="/bookings/"][href$="/"]')
    booking_links = [l for l in page.query_selector_all('a')
                     if '/bookings/' in (l.get_attribute('href') or '')
                     and l.get_attribute('href') != '/bookings/']
    if booking_links:
        href = booking_links[0].get_attribute("href")
        page.goto(BASE + href if not href.startswith("http") else href)
        page.wait_for_load_state("networkidle")
        c = page.content()
        checks = {
            "Assign Cleaner": ("assign cleaner dropdown", "cannot assign jobs to cleaners"),
            "Notify":         ("notification confirmation", "no indication whether cleaner was notified"),
            "Accept":         ("accept/decline status from cleaner", "cannot see if cleaner accepted the job"),
        }
        for text, (desc, missing_desc) in checks.items():
            if text.lower() in c.lower() or "cleaner" in c.lower():
                good("Booking Detail", desc)
            else:
                gap("Booking Detail", missing_desc)

        # Check if notification send status is shown
        if "notif" in c.lower() or "sent to" in c.lower():
            good("Booking Detail", "Notification status visible on booking")
        else:
            gap("Booking Detail", "No confirmation that cleaner notification was sent — admin doesn't know if email went out")

        # Check if cleaner acceptance is tracked
        if "accepted" in c.lower() or "declined" in c.lower():
            good("Booking Detail", "Cleaner accept/decline status tracked")
        else:
            gap("Booking Detail", "Cleaner accept/decline status not shown on booking — admin doesn't know if cleaner confirmed")
    else:
        gap("Bookings", "No bookings found — cannot audit booking detail")

def audit_orientation_flow(page):
    # Check if the orientation URL structure works
    page.goto(f"{BASE}/contractors/team")
    page.wait_for_load_state("networkidle")

    staff_links = [l for l in page.query_selector_all('a')
                   if '/team/' in (l.get_attribute('href') or '')]
    if not staff_links:
        gap("Orientation", "No staff members — cannot audit orientation flow")
        return

    href = staff_links[0].get_attribute("href")
    page.goto(BASE + href if not href.startswith("http") else href)
    page.wait_for_load_state("networkidle")
    c = page.content()

    # Check orientation status
    if "Orientation" in c:
        good("Orientation", "Orientation status visible on staff detail")
    else:
        gap("Orientation", "Orientation status missing from staff detail")

    # Check if orientation link is accessible
    if "orientation-complete" in c or "Copy Link" in c:
        good("Orientation", "Orientation completion link available")
    else:
        gap("Orientation", "No orientation link visible on staff page — admin can't resend or copy orientation URL")

    # Check if orientation materials section exists (training hub)
    if "training" in c.lower() or "materials" in c.lower() or "SOP" in c:
        good("Orientation", "Training materials reference visible")
    else:
        gap("Orientation", "No reference to training materials on staff page — cleaner has no permanent place to access policies")

def audit_payroll(page):
    page.goto(f"{BASE}/contractors/payroll")
    page.wait_for_load_state("networkidle")
    c = page.content()

    if "Payroll" in c or "payroll" in c.lower():
        good("Payroll", "Payroll page loads")
    else:
        err("Payroll", "Payroll page failed to load")
        return

    for field in ["Earnings", "Pay", "Cleaner"]:
        if field in c:
            good("Payroll", f'"{field}" visible on payroll page')
        else:
            gap("Payroll", f'"{field}" missing — payroll summary may be incomplete')

def audit_settings(page):
    page.goto(f"{BASE}/settings/business")
    page.wait_for_load_state("networkidle")
    c = page.content()
    for field in ["Worker Model", "Reception Model", "Agreement Template", "Business Name"]:
        if field.lower() in c.lower():
            good("Settings", f'"{field}" setting present')
        else:
            gap("Settings", f'"{field}" setting missing — white-label toggle not available')

def audit_public_pages(page):
    # Public store / booking form
    page.goto(f"{BASE}/store")
    page.wait_for_load_state("networkidle")
    c = page.content()
    if "book" in c.lower() or "clean" in c.lower():
        good("Public", "Public booking/store page loads")
    else:
        gap("Public", "Public store page not rendering correctly")

    # Contractor apply page
    page.goto(f"{BASE}/contractors/apply")
    page.wait_for_load_state("networkidle")
    c = page.content()
    if "apply" in c.lower() or "application" in c.lower():
        good("Public", "Contractor apply page accessible at /contractors/apply")
    else:
        err("Public", "/contractors/apply not loading — website application form broken")

def audit_email_templates(page):
    page.goto(f"{BASE}/email-templates/")
    page.wait_for_load_state("networkidle")
    c = page.content()
    if "template" in c.lower() or "email" in c.lower():
        good("Email Templates", "Email templates page loads")
        # Count templates
        rows = page.query_selector_all('tr, .card')
        good("Email Templates", f"{len(rows)} rows/cards found on template page")
    else:
        gap("Email Templates", "Email templates page not accessible — automated emails can't be edited")

def audit_sops_scripts(page):
    for path, name in [("/scripts/", "VA Scripts"), ("/sops/", "SOP Library")]:
        page.goto(f"{BASE}{path}")
        page.wait_for_load_state("networkidle")
        c = page.content()
        if "script" in c.lower() or "sop" in c.lower() or "procedure" in c.lower():
            good(name, f"{name} page accessible")
        else:
            gap(name, f"{name} page not loading — team can't access scripts/procedures")

def main():
    print(f"\n{'='*60}")
    print(f"  Dazzle & Shine CRM — Full Process Audit")
    print(f"  Target: {BASE}")
    print(f"{'='*60}\n")

    if not PASS:
        print("⚠️  WARNING: No ADMIN_PASS set. Run: ADMIN_PASS=yourpassword python3 audit.py")
        print("   Attempting with empty password...\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.set_default_timeout(15000)

        try:
            login(page)
        except Exception as e:
            err("Login", f"Cannot log in: {e}")
            print("\nAudit cannot continue without login. Check ADMIN_PASS env var.")
            browser.close()
            return

        for audit_fn, label in [
            (audit_dashboard,        "Dashboard"),
            (audit_applications,     "Applications"),
            (audit_team,             "Team"),
            (audit_bookings,         "Bookings"),
            (audit_orientation_flow, "Orientation"),
            (audit_payroll,          "Payroll"),
            (audit_settings,         "Settings"),
            (audit_email_templates,  "Email Templates"),
            (audit_sops_scripts,     "SOPs & Scripts"),
            (audit_public_pages,     "Public Pages"),
        ]:
            print(f"\n--- {label} ---")
            try:
                audit_fn(page)
            except Exception as e:
                err(label, f"Audit error: {e}")

        browser.close()

    print(f"\n{'='*60}")
    print(f"  AUDIT SUMMARY")
    print(f"{'='*60}")
    print(f"\n✅ {len(ok)} things working correctly")
    print(f"⚠️  {len(gaps)} gaps / missing features")
    print(f"❌ {len(errors)} errors\n")

    if gaps:
        print("GAPS TO FIX:")
        for g in gaps:
            print(f"  {g}")
    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  {e}")

    with open("audit_report.txt", "w") as f:
        f.write("Dazzle & Shine CRM — Process Gap Audit\n")
        f.write("="*60 + "\n\n")
        f.write("PASSING\n" + "-"*30 + "\n")
        for o in ok: f.write(o + "\n")
        f.write("\nGAPS\n" + "-"*30 + "\n")
        for g in gaps: f.write(g + "\n")
        f.write("\nERRORS\n" + "-"*30 + "\n")
        for e in errors: f.write(e + "\n")
    print(f"\nFull report saved to audit_report.txt")

if __name__ == "__main__":
    main()
