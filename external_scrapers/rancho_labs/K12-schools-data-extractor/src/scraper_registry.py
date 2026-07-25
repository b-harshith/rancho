"""
src/scraper_registry.py — Module 1: Autonomous Seed Generator
─────────────────────────────────────────────────────────────
Scrapes official board portals (CBSE SARAS, ICSE CISCE, IB) to build
the master seed list of schools for a given city.

Outputs → ./data/cache/local_seed_cache.csv
State  → Upserts into SQLite with status=SEED_SCRAPED
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import aiohttp
import pandas as pd
from playwright.async_api import Page

from config.settings import CACHE_DIR, SEED_CACHE_FILE
from src.models import Board, SeedSchool
from src.state import StateManager
from src.utils.browser import BrowserPool

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Board-specific scrapers
# ──────────────────────────────────────────────────────────────


async def _fetch_cbse_pincode(session: aiohttp.ClientSession, aff_no: str, sem: asyncio.Semaphore) -> str:
    """Fetch the detailed page from CBSE SARAS and extract the Pin Code."""
    url = f"https://saras.cbse.gov.in/saras/AffiliatedList/AfflicationDetails/{aff_no}"
    async with sem:
        for attempt in range(3):
            try:
                async with session.get(url, ssl=False, timeout=10) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        pin_match = re.search(r"Pin Code.*?(\d{6})", html, re.DOTALL | re.IGNORECASE)
                        if pin_match:
                            return pin_match.group(1).strip()
                        return ""
            except Exception:
                await asyncio.sleep(0.5 * (attempt + 1))
    return ""


async def _scrape_cbse_saras(city: str, pool: BrowserPool, session: aiohttp.ClientSession) -> list[SeedSchool]:
    """
    Scrape the CBSE SARAS affiliation portal.

    Strategy:
        1. Navigate to the CBSE online affiliation status page.
        2. Select State and multiple Districts matching the target city.
        3. Parse the results table dynamically, handling multi-page pagination.
    """
    schools: list[SeedSchool] = []
    logger.info("Starting CBSE SARAS scrape for city=%s", city)

    # ── City → State/District mapping (comprehensive) ──
    city_map: dict[str, dict[str, str | list[str]]] = {
        "bangalore": {"state": "KARNATAKA", "districts": ["BENGALURU URBAN", "BENGALURU RURAL"]},
        "mumbai": {"state": "MAHARASHTRA", "districts": ["MUMBAI", "MUMBAI SUBURBAN"]},
        "delhi": {"state": "DELHI", "districts": ["NEW DELHI", "NORTH DELHI", "SOUTH DELHI", "EAST DELHI", "WEST DELHI"]},
        "hyderabad": {"state": "TELANGANA", "districts": ["HYDERABAD"]},
        "chennai": {"state": "TAMIL NADU", "districts": ["CHENNAI"]},
        "pune": {"state": "MAHARASHTRA", "districts": ["PUNE"]},
    }

    mapping = city_map.get(city.lower())
    if not mapping:
        logger.warning("No CBSE city mapping for '%s'. Skipping CBSE.", city)
        return schools

    districts = mapping["districts"]
    if isinstance(districts, str):
        districts = [districts]

    for district in districts:
        logger.info("Selecting district: %s", district)
        async with pool.new_page() as page:
            try:
                url = "https://saras.cbse.gov.in/saras/AffiliatedList/ListOfSchdirReport"
                logger.info("Navigating to CBSE SARAS portal for district %s: %s", district, url)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Click state-wise search radio button
                await page.click("#SearchMainRadioState_wise")
                await page.wait_for_timeout(1000)

                # Select state
                state_val = str(mapping["state"])
                await page.select_option("select#State", label=state_val)
                await page.wait_for_timeout(2000)  # Wait for districts to populate via AJAX

                await page.select_option("select#District", label=district)
                await page.wait_for_timeout(1000)

                # Click Search
                await page.click("input[type='submit'][value='Search']")
                
                # Robust wait for DataTables to fully initialize
                await page.wait_for_selector("#myTable", timeout=20000)
                await page.wait_for_selector("#myTable_info", timeout=20000)
                await page.wait_for_selector("#myTable_next", timeout=20000)
                await page.wait_for_timeout(2000)

                page_num = 1
                while True:
                    logger.info("Parsing page %d for district %s", page_num, district)
                    rows = await page.query_selector_all("#myTable tbody tr")
                    candidate_schools = []
                    for row in rows:
                        cols = await row.query_selector_all("td")
                        if len(cols) >= 6:
                            aff_text = (await cols[1].inner_text()).strip()
                            name_text = (await cols[4].inner_text()).strip()
                            addr_text = (await cols[5].inner_text()).strip()

                            # Regex matching
                            aff_match = re.search(r"Aff\.\s*No\.\s*:\s*(\w+)", aff_text)
                            aff_no = aff_match.group(1).strip() if aff_match else ""

                            name_match = re.search(r"Name\s*:\s*([^\n\r]+)", name_text)
                            name = name_match.group(1).strip() if name_match else ""

                            web_match = re.search(r"Website\s*:\s*([^\n\r]+)", addr_text)
                            website = web_match.group(1).strip() if web_match else ""

                            if name and aff_no:
                                candidate_schools.append({
                                    "aff_no": aff_no,
                                    "name": name,
                                    "website": website
                                })

                    if candidate_schools:
                        sem = asyncio.Semaphore(25)
                        tasks = [_fetch_cbse_pincode(session, c["aff_no"], sem) for c in candidate_schools]
                        pincodes = await asyncio.gather(*tasks)
                        for c, pincode in zip(candidate_schools, pincodes):
                            schools.append(SeedSchool(
                                school_id=f"CBSE_{c['aff_no']}",
                                name=c["name"],
                                board=Board.CBSE,
                                locality=district,
                                pincode=pincode,
                                website_url=c["website"],
                            ))

                    # Check for next button/pagination
                    next_btn = await page.query_selector("#myTable_next")
                    if next_btn:
                        classes = await next_btn.get_attribute("class") or ""
                        if "disabled" in classes:
                            break

                        # Get current page number before clicking
                        curr_page_el = await page.query_selector(".paginate_button.current")
                        curr_page_str = (await curr_page_el.inner_text()).strip() if curr_page_el else "1"

                        # Click next page
                        await next_btn.click()

                        # Wait for active page number to increment
                        target_page_str = str(int(curr_page_str) + 1)
                        try:
                            await page.wait_for_function(
                                f"() => {{ const el = document.querySelector('.paginate_button.current'); return el && el.innerText.trim() === '{target_page_str}'; }}",
                                timeout=10000
                            )
                        except Exception:
                            pass
                        
                        # Extra stable wait for AJAX transition
                        await page.wait_for_timeout(1000)
                        page_num += 1
                    else:
                        break
            except Exception as dist_err:
                logger.error("Failed to scrape district %s: %s", district, dist_err)

    logger.info("CBSE scrape finished — %d schools found", len(schools))
    return schools



async def _scrape_icse_cisce(city: str, session: aiohttp.ClientSession) -> list[SeedSchool]:
    """
    Query the CISCE 'Locate a School' portal.
    """
    schools: list[SeedSchool] = []
    logger.info("Starting ICSE CISCE scrape for city=%s", city)

    # 1. Attempt to load from cached local JSON first if it exists
    import os
    import json
    cache_path = os.path.join("data", "cache", f"cisce_schools_{city.lower()}.json")
    if os.path.exists(cache_path):
        logger.info("Loading ICSE CISCE seeds from local cache: %s", cache_path)
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            for item in data:
                # Extract pincode from address using regex
                address = item.get("address", "")
                pincode = ""
                if address:
                    pin_match = re.search(r"\b(\d{3}\s?\d{3})\b", address)
                    if pin_match:
                        pincode = pin_match.group(1).replace(" ", "")

                schools.append(SeedSchool(
                    school_id=f"ICSE_{item['code']}",
                    name=item['name'],
                    board=Board.ICSE,
                    locality=city.capitalize(),
                    pincode=pincode,
                    website_url=item['website'],
                ))
            logger.info("Loaded %d ICSE CISCE schools from cache", len(schools))
            return schools
        except Exception as e:
            logger.error("Failed to parse cached ICSE JSON: %s", e)

    # 2. If no cache, perform live scraping using Playwright with anti-bot evasion
    from playwright.async_api import async_playwright
    try:
        async with async_playwright() as p:
            logger.info("No cache found. Performing live CISCE locator scrape (headless=False + evasion)...")
            browser = await p.chromium.launch(
                headless=False,
                ignore_default_args=["--enable-automation"],
                args=["--disable-gpu", "--no-sandbox"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            
            url = "https://locate.cisce.org/"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1000)
            
            await page.evaluate("() => { $('#country-dropdown').val('India').trigger('change'); }")
            
            # Wait dynamically for states dropdown to load
            await page.wait_for_function("""() => {
                const select = document.querySelector('select#state-dropdown');
                return select && select.options.length > 1;
            }""", timeout=15000)
            
            await page.evaluate("() => { $('#state-dropdown').val('Karnataka').trigger('change'); }")
            await page.wait_for_timeout(1000)
            
            await page.click("input[type='submit'][value='Search']")
            await page.wait_for_timeout(5000)
            
            body_text = await page.inner_text("body")
            if "Performing security verification" in body_text:
                logger.error("CISCE live scrape blocked by Cloudflare")
                await browser.close()
                return schools
                
            page_num = 1
            while True:
                cards = await page.query_selector_all("div.school-card")
                for card in cards:
                    text = (await card.inner_text()).strip()
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    
                    website_url = ""
                    web_link = await card.query_selector("a:has-text('Visit Website')")
                    if web_link:
                        website_url = await web_link.get_attribute("href") or ""
                        
                    school_code = ""
                    school_name = ""
                    name_line = None
                    for line in lines:
                        match = re.match(r"^([A-Z]{2}\d{3})\s*-\s*(.+)$", line)
                        if match:
                            school_code = match.group(1).strip()
                            school_name = match.group(2).strip()
                            name_line = line
                            break
                            
                    if not school_name and len(lines) > 2:
                        school_name = lines[2]
                    if not school_code:
                        school_code = f"KA_GEN_{school_name.replace(' ', '_')[:20]}"
                        
                    # Filter for target city
                    is_in_city = any(city.lower() in line.lower() for line in lines)
                    if is_in_city:
                        card_text = (await card.inner_text()).strip()
                        pin_match = re.search(r"\b(\d{3}\s?\d{3})\b", card_text)
                        pincode = pin_match.group(1).replace(" ", "") if pin_match else ""

                        schools.append(SeedSchool(
                            school_id=f"ICSE_{school_code}",
                            name=school_name,
                            board=Board.ICSE,
                            locality=city.capitalize(),
                            pincode=pincode,
                            website_url=website_url,
                        ))
                        
                next_btn = await page.query_selector("li.page-item.next:not(.disabled) a, a:has-text('›')")
                if not next_btn:
                    break
                parent = await next_btn.evaluate_handle("el => el.parentElement")
                parent_class = await parent.get_attribute("class") or ""
                if "disabled" in parent_class:
                    break
                    
                await next_btn.click()
                await page.wait_for_timeout(2000)
                page_num += 1
                if page_num > 60:
                    break
                    
            await browser.close()
            logger.info("Live CISCE scrape finished — %d schools found for city %s", len(schools), city)
            
            # Save to cache file for next time
            try:
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                cached_data = [
                    {
                        "code": s.school_id.replace("ICSE_", ""),
                        "name": s.name,
                        "address": s.locality,
                        "website": s.website_url,
                        "raw_text": s.name
                    } for s in schools
                ]
                with open(cache_path, "w") as f:
                    json.dump(cached_data, f, indent=2)
            except Exception as e:
                logger.error("Failed to write scraped schools to cache: %s", e)
                
    except Exception as exc:
        logger.error("ICSE CISCE scrape failed: %s", exc)

    return schools


async def _scrape_ib_directory(city: str, pool: BrowserPool) -> list[SeedSchool]:
    """
    Scrape the IBO regional school directory.
    """
    schools: list[SeedSchool] = []
    logger.info("Starting IB directory scrape for city=%s", city)

    async with pool.new_page() as page:
        try:
            url = "https://www.ibo.org/programmes/find-an-ib-school/"
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            # Check for Cookie consent and accept
            try:
                allow_cookies_btn = page.locator("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll")
                if await allow_cookies_btn.is_visible():
                    await allow_cookies_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            # Check if keywords input is visible
            keywords_input = page.locator("input#SearchFields_Keywords")
            if await keywords_input.is_visible():
                await page.select_option("select#SearchFields_Country", label="India")
                await page.fill("input#SearchFields_Keywords", city)
                await page.click("button.Button--widest")
                await page.wait_for_timeout(4000)

                # Locate school card links on the page if any
                anchors = await page.query_selector_all("a")
                for a in anchors:
                    href = await a.get_attribute("href") or ""
                    text = (await a.inner_text()).strip()
                    if "/find-an-ib-school/find-a-school/" in href and text:
                        schools.append(SeedSchool(
                            school_id=f"IB_{text.replace(' ', '_')[:30]}",
                            name=text,
                            board=Board.IB,
                            locality=city.capitalize(),
                            pincode="",
                            website_url="",
                        ))
            
            logger.info("IB directory scrape finished — %d schools found", len(schools))

        except Exception as exc:
            logger.error("IB directory scrape failed/blocked: %s", exc)

    return schools


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────


async def generate_seed_list(
    city: str,
    pool: BrowserPool,
    state_mgr: StateManager,
    force_rescrape: bool = False,
) -> pd.DataFrame:
    """
    Orchestrates all board scrapers and produces a unified seed DataFrame.

    Args:
        city:           Target city name (lowercase).
        pool:           Shared BrowserPool instance.
        state_mgr:      Async SQLite state manager.
        force_rescrape: If True, ignore cached CSV and re-scrape.

    Returns:
        pd.DataFrame with columns:
            [School_ID, Name, Board, Locality, Pincode, Website_URL]
    """
    # ── Check cache ──
    if SEED_CACHE_FILE.exists() and not force_rescrape:
        logger.info("Using cached seed list from %s", SEED_CACHE_FILE)
        df = pd.read_csv(str(SEED_CACHE_FILE))
        # Still upsert into DB for idempotency
        seeds = [
            SeedSchool(
                school_id=row["School_ID"],
                name=row["Name"],
                board=Board(row["Board"]),
                locality=row.get("Locality", ""),
                pincode=str(row.get("Pincode", "")),
                website_url=row.get("Website_URL", ""),
            )
            for _, row in df.iterrows()
        ]
        await state_mgr.bulk_upsert_seeds(seeds)
        return df

    # ── Run all scrapers concurrently ──
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        cbse_task = _scrape_cbse_saras(city, pool, session)
        icse_task = _scrape_icse_cisce(city, session)
        ib_task = _scrape_ib_directory(city, pool)

        results = await asyncio.gather(cbse_task, icse_task, ib_task, return_exceptions=True)

    all_schools: list[SeedSchool] = []
    for result in results:
        if isinstance(result, Exception):
            logger.error("Scraper failed: %s", result)
        elif isinstance(result, list):
            all_schools.extend(result)

    # ── Normalize into DataFrame ──
    if not all_schools:
        logger.warning("No schools found for city=%s. Seed list is empty.", city)
        return pd.DataFrame(columns=["School_ID", "Name", "Board", "Locality", "Pincode", "Website_URL"])

    records = [
        {
            "School_ID": s.school_id,
            "Name": s.name,
            "Board": s.board.value,
            "Locality": s.locality,
            "Pincode": s.pincode,
            "Website_URL": s.website_url,
        }
        for s in all_schools
    ]
    df = pd.DataFrame(records)

    # Drop schools without a website
    before = len(df)
    df = df[df["Website_URL"].str.strip().astype(bool)].reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        logger.info("Dropped %d schools with empty Website_URL", dropped)

    # ── Persist ──
    df.to_csv(str(SEED_CACHE_FILE), index=False)
    logger.info("Saved seed cache to %s (%d schools)", SEED_CACHE_FILE, len(df))

    # Upsert into DB
    seeds = [
        SeedSchool(
            school_id=row["School_ID"],
            name=row["Name"],
            board=Board(row["Board"]),
            locality=row.get("Locality", ""),
            pincode=str(row.get("Pincode", "")),
            website_url=row.get("Website_URL", ""),
        )
        for _, row in df.iterrows()
    ]
    count = await state_mgr.bulk_upsert_seeds(seeds)
    logger.info("Upserted %d seed records into DB", count)

    return df
