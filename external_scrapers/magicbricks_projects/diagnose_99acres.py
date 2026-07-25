#!/usr/bin/env python3
"""
Diagnostic: capture the EXACT request headers sent when 'Show More' is clicked.
This will reveal the client_id / auth header the page's JS injects.
"""
import json
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

TARGET_URL = "https://www.99acres.com/bangalore-reviews-and-ratings-wrffid"
API_MATCH  = "api-aggregator/content/locations/rei/cityPageData"
OUT        = Path(__file__).parent / "data" / "raw" / "99acres_request_headers.json"

SHOW_MORE_SELECTORS = [
    "button:has-text('Show More')",
    "button:has-text('Show more')",
    "a:has-text('Show More')",
    "a:has-text('Show more')",
    "span:has-text('Show More')",
    "div:has-text('Show More')",
    "[class*='showMore']",
    "[class*='show-more']",
    "[class*='loadMore']",
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def run():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    captured = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # Intercept ALL requests to log their headers
        def on_request(request):
            if API_MATCH in request.url:
                log(f">>> API REQUEST INTERCEPTED!")
                log(f"    Method : {request.method}")
                log(f"    URL    : {request.url}")
                hdrs = dict(request.all_headers())
                log(f"    Headers: {json.dumps(hdrs, indent=6)}")
                captured["url"]     = request.url
                captured["method"]  = request.method
                captured["headers"] = hdrs

        def on_response(response):
            if API_MATCH in response.url:
                log(f">>> API RESPONSE: HTTP {response.status}")
                try:
                    body = response.text()
                    log(f"    Body (first 300): {body[:300]}")
                    captured["response_status"] = response.status
                    captured["response_body_preview"] = body[:500]
                except Exception as e:
                    log(f"    Body read error: {e}")
                with open(OUT, "w") as f:
                    json.dump(captured, f, indent=2)
                log(f"    Saved to {OUT}")

        page.on("request",  on_request)
        page.on("response", on_response)

        log("Opening page...")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
        log("Waiting 6s for JS to settle...")
        page.wait_for_timeout(6000)

        # Scroll and click Show More to trigger the API call
        log("Scrolling to bottom...")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)

        button = None
        for sel in SHOW_MORE_SELECTORS:
            try:
                loc = page.locator(sel).last
                if loc.is_visible(timeout=2000):
                    button = loc
                    log(f"Found button with selector: {sel}")
                    break
            except Exception:
                continue

        if button:
            log("Clicking 'Show More'...")
            button.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            button.click()
            page.wait_for_timeout(4000)
        else:
            log("No 'Show More' button found! Checking page structure...")
            # Print all visible text that might be button-like
            visible_buttons = page.evaluate("""
                () => Array.from(document.querySelectorAll('button,a,[role=button]'))
                    .filter(el => el.offsetParent !== null)
                    .map(el => el.textContent.trim())
                    .filter(t => t.length > 0 && t.length < 50)
            """)
            log(f"Visible buttons/links: {visible_buttons[:20]}")

        if captured:
            log(f"\n=== SUMMARY ===")
            log(f"Found client_id / key headers: {[k for k in captured.get('headers', {}).keys()]}")
        else:
            log("No API call was captured.")

        page.wait_for_timeout(3000)
        browser.close()

if __name__ == "__main__":
    run()
