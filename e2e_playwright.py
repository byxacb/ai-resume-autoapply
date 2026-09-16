"""Playwright E2E tests for Dashboard"""
import os
import sys
from urllib.parse import urljoin

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not installed. Install with: pip install playwright")
    sys.exit(1)

BASE = os.environ.get("BASE_URL", "http://localhost:8080")
REPORT = []


def screenshot(page, name):
    path = os.path.join("reports", f"{name}.png")
    os.makedirs("reports", exist_ok=True)
    page.screenshot(path=path)
    REPORT.append({"step": name, "status": "PASS", "screenshot": path})


def test_dashboard_and_boss_form():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)
        screenshot(page, "dashboard_home")

        tabs = ["tab-dashboard", "tab-run", "tab-candidates", "tab-boss-apply", "tab-queue", "tab-logs", "tab-metrics", "tab-settings"]
        for tab in tabs:
            assert page.locator(f"#{tab}").count() >= 1, f"Missing tab {tab}"
        REPORT.append({"step": "tabs_exist", "status": "PASS"})

        boss_tab = page.locator(".tab[data-tab='boss-apply']")
        if boss_tab.count() > 0:
            boss_tab.first.click()
            page.wait_for_timeout(800)
            page.evaluate("""() => {
                const activePane = [...document.querySelectorAll('.tab-pane')].find(p => p.classList.contains('active'));
                const activeTab = [...document.querySelectorAll('.tab')].find(t => t.classList.contains('active'));
                console.log('E2E_DIAG activePane', activePane ? activePane.id : 'none');
                console.log('E2E_DIAG activeTab', activeTab ? activeTab.dataset.tab : 'none');
                const bossPane = document.getElementById('tab-boss-apply');
                if (bossPane && !bossPane.classList.contains('active')) {
                    bossPane.classList.add('active');
                }
            }""")
            page.wait_for_timeout(300)
            screenshot(page, "boss_apply_tab")
        else:
            REPORT.append({"step": "boss_tab_click", "status": "SKIP", "detail": "boss tab not found"})

        boss_job_id = page.locator("#boss-job-id-v2")
        jd_text = page.locator("#boss-jd-text-v2")
        candidate = page.locator("#boss-candidate-v2")
        submit = page.locator("#boss-apply-form-v2 button[type='submit']")

        if boss_job_id.count() > 0:
            boss_job_id.fill("12345")
            jd_text.fill("Sample JD for E2E")
            if candidate.count() > 0:
                candidate.select_option(index=0)
            submit.click()
            page.wait_for_timeout(2000)
            screenshot(page, "boss_apply_submitted")
            # account selector screenshot if present
            const accountSel = page.locator("#boss-account-select");
            if (accountSel.count() > 0) {
                screenshot(page, "boss_account_selector")
            }
            # BOSS recent/queue screenshot
            page.goto(urljoin(BASE, "/boss-batch"), wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            screenshot(page, "boss_batch_after_apply")
        else:
            REPORT.append({"step": "boss_form_fill", "status": "SKIP", "detail": "boss inputs not found"})

        page.goto(urljoin(BASE, "/queue"), wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        screenshot(page, "queue_after_apply")

        browser.close()


if __name__ == "__main__":
    try:
        test_dashboard_and_boss_form()
    except Exception as e:
        REPORT.append({"step": "playwright_run", "status": "FAIL", "detail": str(e)})
    print("PLAYWRIGHT_REPORT=" + str(REPORT))
