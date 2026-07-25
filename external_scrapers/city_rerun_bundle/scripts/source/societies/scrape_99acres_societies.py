#!/usr/bin/env python3
"""
99acres Societies Scraper
======================================
Injects the user's real session cookies into Playwright so the page loads
as an authenticated user and generates valid apitoken + authorizationtoken.
Then uses curl_cffi to scrape societies across pages.

Usage:
    python3 scrape_99acres_societies.py

Output:
    data/raw/99acres_<city_slug>_societies.jsonl
"""

import json
import os
import time
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from playwright.sync_api import sync_playwright
from curl_cffi import requests as cf_requests

# ─── Config ────────────────────────────────────────────────────────────────────

CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
TARGET_URL = os.environ.get(
    "TARGET_URL",
    "https://www.99acres.com/bangalore-reviews-and-ratings-wrffid",
)
API_BASE   = "https://www.99acres.com/api-aggregator/content/locations/rei/cityPageData"
API_MATCH  = "api-aggregator/content/locations/rei/cityPageData"
API_CITY_ID = os.environ.get("API_CITY_ID", "").strip()

API_PARAMS = {
    "cityId":      API_CITY_ID,
    "entityType":  "PROJECT",
    "budgetFilter":"ANY",
    "sortFilter":  "TOP_RATED",
    "platform":    "MSITE",
    "pageType":    "RNR",
    "limit":       30,
}

OUTPUT_DIR  = Path(__file__).parent / "data" / "raw"
OUTPUT_FILE = OUTPUT_DIR / f"99acres_{CITY_SLUG}_societies.jsonl"

MAX_PAGES   = 100
SLEEP_SEC   = 0.8

# ── User's real session cookies (long-lived; update PROPLOGIN if it expires) ──
RAW_COOKIE_STRING = os.environ.get("ACRES99_SESSION", os.environ.get("COOKIE_HEADER", "")).strip()

DEVICE_ID = "0167470337cce70ecb09adfcbb99597a"

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
    "text=/show\\s+more/i",
    "text=/load\\s+more/i",
    "text=/view\\s+more/i",
]

# ─── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_cookies(raw: str) -> list:
    """Parse a raw cookie header string into a list of Playwright cookie dicts."""
    cookies = []
    for part in raw.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies.append({
            "name":   name.strip(),
            "value":  value.strip(),
            "domain": ".99acres.com",
            "path":   "/",
        })
    return cookies


def capture_tokens_from_browser() -> dict:
    """
    Opens Playwright with real session cookies pre-injected.
    Navigates to page (now as logged-in user), scrolls, clicks Show More,
    and captures fresh apitoken + authorizationtoken from the API request.
    """
    captured = {}
    event    = threading.Event()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=80,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Mobile Safari/537.36"
            ),
        )

        # ── Inject real session cookies BEFORE navigating ───────────────────
        playwright_cookies = parse_cookies(RAW_COOKIE_STRING)
        context.add_cookies(playwright_cookies)
        log(f"Browser: injected {len(playwright_cookies)} cookies (incl. PROPLOGIN)")

        page = context.new_page()

        def on_request(request):
            if API_MATCH in request.url and not event.is_set():
                hdrs = dict(request.all_headers())
                city_ids = parse_qs(urlparse(request.url).query).get("cityId", [])
                if city_ids:
                    hdrs["_city_id"] = city_ids[0]
                captured.update(hdrs)
                log(f"  ✓ Tokens captured from browser!")
                log(f"    cityId:                   {hdrs.get('_city_id', 'not found')}")
                log(f"    apitoken present:          {'apitoken' in hdrs}")
                log(f"    authorizationtoken present: {'authorizationtoken' in hdrs}")
                event.set()

        page.on("request", on_request)

        log("Browser: navigating to page (as logged-in user)...")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
        log("Browser: DOM ready. Waiting 6s for JS to settle...")
        page.wait_for_timeout(6000)

        log(f"Browser: captured so far: {bool(captured)}")

        # Scroll gradually to activate lazy loading before looking for Show More.
        for attempt in range(30):
            if event.is_set():
                break

            before = page.evaluate("window.scrollY")
            page.mouse.wheel(0, 650)
            page.evaluate("window.scrollBy({top: Math.floor(window.innerHeight * 0.8), behavior: 'smooth'})")
            page.evaluate("""() => {
                const el = document.querySelector('.r-150rngu');
                if (el) el.scrollTop += Math.floor(el.clientHeight * 0.8);
            }""")
            page.wait_for_timeout(900)
            after = page.evaluate("window.scrollY")
            at_bottom = page.evaluate(
                "window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 80"
            )
            if at_bottom or after == before:
                page.wait_for_timeout(1800)
                page.evaluate("window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'smooth'})")
                page.wait_for_timeout(1200)

            button = None
            for sel in SHOW_MORE_SELECTORS:
                try:
                    loc = page.locator(sel).last
                    if loc.is_visible(timeout=500):
                        button = loc
                        break
                except Exception:
                    continue

            if button:
                log(f"Browser: clicking 'Show More' (attempt {attempt+1})...")
                try:
                    button.scroll_into_view_if_needed()
                    page.wait_for_timeout(200)
                    button.click()
                    page.wait_for_timeout(3500)
                except Exception as e:
                    log(f"  Click error: {e}")
            else:
                log(f"Browser: scrolling for 'Show More' (attempt {attempt+1}/30, y={after})...")

        if not event.is_set():
            # Last resort: try to trigger API call directly from page context
            log("Browser: triggering API via page.evaluate as fallback...")
            try:
                fallback_params = {**API_PARAMS, "page": 1}
                if not fallback_params["cityId"]:
                    raise RuntimeError("No API_CITY_ID supplied for fallback request")
                fallback_url = urlunparse(
                    urlparse(API_BASE)._replace(query=urlencode(fallback_params))
                )
                page.evaluate("url => fetch(url)", fallback_url)
                page.wait_for_timeout(3000)
            except Exception:
                pass

        if not captured:
            log("WARNING: Could not capture tokens.")

        page.wait_for_timeout(1500)
        browser.close()

    return captured


def scrape_all_pages(api_headers: dict, city_id: str) -> tuple:
    """Scrape pages 0..MAX_PAGES with curl_cffi. Returns (last_page, total, expired)."""
    session = cf_requests.Session()
    total   = 0

    for pg in range(0, MAX_PAGES):
        params = {**API_PARAMS, "cityId": city_id, "page": pg}
        try:
            resp = session.get(
                API_BASE, params=params, headers=api_headers,
                impersonate="chrome", timeout=20,
            )
        except Exception as e:
            log(f"  Network error on page {pg}: {e}")
            time.sleep(2)
            continue

        if resp.status_code == 401:
            log(f"  page={pg}: 401 — tokens expired. Refreshing...")
            return pg, total, True

        if resp.status_code != 200:
            log(f"  page={pg}: HTTP {resp.status_code} — skipping.")
            continue

        try:
            raw = resp.json()
        except Exception:
            log(f"  page={pg}: JSON parse error")
            continue

        # Response can be a list directly, or a dict with data/tuples/localities
        if isinstance(raw, list):
            items = raw
            body  = {"data": raw}   # wrap for consistent JSONL output
        elif isinstance(raw, dict):
            body      = raw
            data_field = body.get("data")
            items = (
                (data_field.get("tuples") if isinstance(data_field, dict) else None) or
                body.get("tuples") or
                body.get("localities") or
                body.get("projects") or
                (data_field if isinstance(data_field, list) else None) or
                []
            )
        else:
            log(f"  page={pg}: unexpected response type {type(raw)}")
            continue

        count = len(items)

        if count == 0:
            log(f"  page={pg}: 0 items → end of data.")
            return pg, total, False

        total += count
        body["_scraped_page"] = pg
        body["_scraped_at"]   = datetime.now().isoformat()
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(body, ensure_ascii=False) + "\n")

        log(f"  ✓ page={pg} | +{count} societies | total={total}")
        time.sleep(SLEEP_SEC)

    return MAX_PAGES - 1, total, False


# ─── Main ──────────────────────────────────────────────────────────────────────

def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as _:
        pass  # clear file

    grand_total = 0

    while True:
        log(f"\n{'='*55}")
        log("Phase 1: Capturing fresh tokens via browser...")
        log(f"{'='*55}")

        headers = capture_tokens_from_browser()

        if not headers.get("apitoken"):
            log("ERROR: apitoken not captured. Cannot proceed.")
            break

        city_id = headers.pop("_city_id", "") or API_CITY_ID
        if not city_id:
            log("ERROR: cityId was not captured. Set API_CITY_ID and retry.")
            break
        log(f"Using detected API cityId: {city_id}")

        api_headers = {
            "accept":             "application/json, text/plain, */*",
            "accept-language":    "en-GB,en-US;q=0.9,en;q=0.8",
            "apitoken":           headers.get("apitoken", ""),
            "authorizationtoken": headers.get("authorizationtoken", ""),
            "cookie":             headers.get("cookie", RAW_COOKIE_STRING),
            "deviceid":           headers.get("deviceid", DEVICE_ID),
            "pagename":           "RLP_RNR_CITY_PAGE",
            "platform":           "mobile",
            "referer":            TARGET_URL,
            "user-agent": (
                "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Mobile Safari/537.36"
            ),
            "sec-fetch-dest":  "empty",
            "sec-fetch-mode":  "cors",
            "sec-fetch-site":  "same-origin",
        }

        log(f"\nPhase 2: Scraping all pages with curl_cffi...")
        last_pg, count, expired = scrape_all_pages(api_headers, city_id)
        grand_total += count

        if not expired:
            log(f"\n{'='*55}")
            log(f"ALL DONE!  Total societies scraped: {grand_total}")
            log(f"Output → {OUTPUT_FILE}")
            log(f"{'='*55}")
            break
        else:
            log(f"Tokens expired at page {last_pg}. Re-running Phase 1...")
            time.sleep(2)


if __name__ == "__main__":
    run()
