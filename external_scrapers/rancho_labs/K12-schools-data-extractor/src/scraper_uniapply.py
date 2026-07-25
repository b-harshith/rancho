"""
src/scraper_uniapply.py — Module 1 (Alternative): UniApply Listings & Fees Scraper
─────────────────────────────────────────────────────────────────────────────
Scrapes school directories from UniApply to build a master seed list with initial fee data.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import Page

from config.settings import SEED_CACHE_FILE
from src.models import Board, SeedSchool, SchoolProcessingStatus
from src.state import StateManager
from src.utils.browser import BrowserPool

logger = logging.getLogger(__name__)


def parse_fee_text(fee_text: str) -> dict:
    """
    Parses UniApply fee text (e.g. "₹ 50,000 - 80,000 Annually", "₹ 4,000 Monthly")
    and returns calculated range metrics.
    """
    result = {
        "raw_text": fee_text,
        "avg_annual_fee": 0.0,
        "highest_annual_fee": 0,
        "period": "Annual",
    }
    
    if not fee_text:
        return result
        
    try:
        # Extract numerical digits
        numbers = [int(n.replace(",", "")) for n in re.findall(r"\b\d[\d,]*\b", fee_text)]
        if not numbers:
            return result
            
        # Determine period multiplier
        multiplier = 1
        low_text = fee_text.lower()
        if "month" in low_text:
            multiplier = 12
            result["period"] = "Monthly"
        elif "quarter" in low_text:
            multiplier = 4
            result["period"] = "Quarterly"
        elif "term" in low_text:
            multiplier = 2
            result["period"] = "Semi-Annual"
            
        if len(numbers) >= 2:
            avg_val = (numbers[0] + numbers[1]) / 2.0
            highest_val = max(numbers[0], numbers[1])
        else:
            avg_val = float(numbers[0])
            highest_val = numbers[0]
            
        result["avg_annual_fee"] = avg_val * multiplier
        result["highest_annual_fee"] = int(highest_val * multiplier)
        
    except Exception as e:
        logger.debug("Failed to parse fee text '%s': %s", fee_text, e)
        
    return result


async def scrape_uniapply_listings(
    city: str,
    pool: BrowserPool,
    state_mgr: StateManager,
    max_schools: int = 100,
) -> list[dict]:
    """
    Scrapes school listings and fee metadata from UniApply.
    """
    schools = []
    logger.info("Starting UniApply scraper for city=%s (limit=%d)", city, max_schools)

    async with pool.new_page() as page:
        # Target URLs to try
        target_urls = [
            f"https://www.uniapply.com/schools-in-{city.lower()}/",
            f"https://www.uniapply.com/schools/{city.lower()}/",
        ]
        
        success = False
        for url in target_urls:
            logger.info("Navigating to UniApply listing URL: %s", url)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                # Check if we got a 404 or bad page
                title = await page.title()
                if "404" not in title and "Not Found" not in title:
                    success = True
                    break
            except Exception as e:
                logger.warning("Failed to navigate to %s: %s", url, e)

        if not success:
            logger.error("Could not find a valid UniApply school listing page for %s", city)
            return schools

        # Log page diagnostic information
        page_title = await page.title()
        body_text = await page.inner_text("body")
        logger.info("Loaded Page Title: %s", page_title)
        logger.info("Page Body Snippet: %s", body_text[:1000].replace('\n', ' | '))

        if "cloudflare" in body_text.lower() or "captcha" in body_text.lower() or "verify you are human" in body_text.lower():
            logger.warning("Bot protection / Cloudflare challenge detected on UniApply page.")

        # Implement scroll loop to fetch dynamic listings
        logger.info("Scrolling page to load dynamic school cards...")
        previous_card_count = 0
        scroll_attempts = 0
        max_scroll_attempts = max(15, (max_schools // 20) + 15)
        
        while len(schools) < max_schools and scroll_attempts < max_scroll_attempts:
            # Dynamically count current unique school listing cards loaded by querying school profile links
            current_count = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href*="/school/"]'))
                    .filter(a => {
                        const href = a.href;
                        return !href.includes('/schools-in-') && !href.includes('/schools/') && !href.includes('/compare-') && !href.includes('/admission');
                    }).length
            """)
            
            logger.info("Found %d school links loaded on page (scroll attempt %d)", current_count, scroll_attempts)
            
            if current_count == previous_card_count and scroll_attempts > 2:
                # Check for "Load More" button
                load_more_btn = await page.query_selector("button:has-text('Load More'), a:has-text('Load More'), .load-more")
                if load_more_btn and await load_more_btn.is_visible():
                    logger.info("Clicking 'Load More' button...")
                    await load_more_btn.click()
                    await page.wait_for_timeout(2000)
                else:
                    break
                    
            previous_card_count = current_count
            
            # Scroll down
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            scroll_attempts += 1

        # Now parse the loaded school cards
        logger.info("Extracting data from school cards...")
        cards = []
        card_selectors = [
            "div.school-card", 
            "div.school-box", 
            "div[class*='school-box']", 
            "div[class*='school-card']",
            ".listing-school-card"
        ]
        
        for selector in card_selectors:
            elements = await page.query_selector_all(selector)
            if len(elements) > len(cards):
                cards = elements

        for card in cards[:max_schools]:
            try:
                card_text = (await card.inner_text()).strip()
                lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                
                if not lines:
                    continue

                # Extract school name
                name = ""
                name_el = await card.query_selector("h2, h3, a.school-name")
                if name_el:
                    name = (await name_el.inner_text()).strip()
                if not name and lines:
                    name = lines[0]

                # Extract board
                board = Board.UNKNOWN
                board_match = re.search(r"\b(CBSE|ICSE|IB|IGCSE|State Board|KSEEB)\b", card_text, re.IGNORECASE)
                if board_match:
                    board_str = board_match.group(1).upper()
                    if board_str == "KSEEB":
                        board = Board.STATE
                    else:
                        board = Board(board_str)

                # Extract locality
                locality = city.capitalize()
                addr_match = re.search(r"Location:?\s*([^\n\r,]+)", card_text, re.IGNORECASE)
                if addr_match:
                    locality = addr_match.group(1).strip()
                elif len(lines) > 1:
                    locality = lines[1]

                # Extract pincode
                pincode = ""
                pin_match = re.search(r"\b(560\d{3})\b", card_text)
                if pin_match:
                    pincode = pin_match.group(1)

                # Extract website / detail link
                detail_url = ""
                anchor = await card.query_selector("a[href]")
                if anchor:
                    detail_url = await anchor.get_attribute("href") or ""
                    if detail_url.startswith("/"):
                        detail_url = "https://www.uniapply.com" + detail_url

                # Extract fee details
                fee_text = ""
                fee_match = re.search(r"(?:fee|charges|cost).*?(₹\s*[\d,]+.*?)(?:\n|$)", card_text, re.IGNORECASE)
                if fee_match:
                    fee_text = fee_match.group(1).strip()
                else:
                    for line in lines:
                        if "₹" in line:
                            fee_text = line
                            break
                            
                parsed_fee = parse_fee_text(fee_text)

                if name:
                    school_id = f"UNI_{re.sub(r'[^a-zA-Z0-9]', '_', name.lower())[:30]}"
                    schools.append({
                        "school_id": school_id,
                        "name": name,
                        "board": board,
                        "locality": locality,
                        "pincode": pincode,
                        "website_url": detail_url,
                        "raw_fee_text": fee_text,
                        "avg_annual_fee": parsed_fee["avg_annual_fee"],
                        "highest_annual_fee": parsed_fee["highest_annual_fee"],
                        "fee_period": parsed_fee["period"]
                    })
                    
            except Exception as e:
                logger.warning("Error parsing individual school card: %s", e)

        # Fallback: Dynamic content-independent JS search
        if not schools:
            logger.info("No school cards matched selectors. Executing semantic JS list extraction...")
            js_script = """
            (city) => {
                const schoolLinks = Array.from(document.querySelectorAll('a[href*="/school/"]'));
                const results = [];
                const seenUrls = new Set();
                
                for (const a of schoolLinks) {
                    const href = a.href;
                    if (href.includes('/schools-in-') || href.includes('/schools/') || href.includes('/compare-') || href.includes('/admission')) {
                        continue;
                    }
                    if (seenUrls.has(href)) {
                        continue;
                    }
                    seenUrls.add(href);
                    
                    const name = (a.innerText || '').trim();
                    if (!name || name.length < 3) {
                        continue;
                    }
                    
                    let card = a.parentElement;
                    let cardText = '';
                    let foundFees = '';
                    let foundBoard = 'Unknown';
                    let foundLocality = city;
                    let depth = 0;
                    
                    while (card && depth < 10) {
                        const text = card.innerText || '';
                        if (text.includes('₹')) {
                            cardText = text;
                            const lines = text.split('\\n').map(l => l.trim()).filter(l => l.includes('₹'));
                            if (lines.length > 0) {
                                foundFees = lines[0];
                            }
                            
                            const boardMatch = text.match(/\\b(CBSE|ICSE|IB|IGCSE|State Board|KSEEB)\\b/i);
                            if (boardMatch) {
                                foundBoard = boardMatch[1];
                            }
                            
                            const locMatch = text.match(/(?:Location|Address|Area)\\s*:\\s*([^\\n,]+)/i);
                            if (locMatch) {
                                foundLocality = locMatch[1].trim();
                            }
                            break;
                        }
                        card = card.parentElement;
                        depth++;
                    }
                    
                    results.push({
                        name: name,
                        website_url: href,
                        raw_fee_text: foundFees,
                        board: foundBoard,
                        locality: foundLocality
                    });
                }
                return results;
            }
            """
            js_schools = await page.evaluate(js_script, city.capitalize())
            logger.info("Semantic JS extraction found %d potential schools on page", len(js_schools))
            
            for s in js_schools[:max_schools]:
                parsed_fee = parse_fee_text(s["raw_fee_text"])
                board = Board.UNKNOWN
                board_str = s["board"].upper()
                if "CBSE" in board_str:
                    board = Board.CBSE
                elif "ICSE" in board_str:
                    board = Board.ICSE
                elif "IB" in board_str:
                    board = Board.IB
                elif "IGCSE" in board_str:
                    board = Board.IB
                elif "STATE" in board_str or "KSEEB" in board_str:
                    board = Board.STATE
                    
                school_id = f"UNI_{re.sub(r'[^a-zA-Z0-9]', '_', s['name'].lower())[:30]}"
                schools.append({
                    "school_id": school_id,
                    "name": s["name"],
                    "board": board,
                    "locality": s["locality"],
                    "pincode": "",
                    "website_url": s["website_url"],
                    "raw_fee_text": s["raw_fee_text"],
                    "avg_annual_fee": parsed_fee["avg_annual_fee"],
                    "highest_annual_fee": parsed_fee["highest_annual_fee"],
                    "fee_period": parsed_fee["period"]
                })

        # Bulk upsert seeds into DB and save local cache
        if schools:
            seed_schools = []
            for s in schools:
                seed_schools.append(SeedSchool(
                    school_id=s["school_id"],
                    name=s["name"],
                    board=s["board"],
                    locality=s["locality"],
                    pincode=s["pincode"],
                    website_url=s["website_url"]
                ))
            
            # Upsert using state manager
            await state_mgr.bulk_upsert_seeds(seed_schools)
            
            # Write UniApply detailed fee metrics to SQLite
            for s in schools:
                # Custom temporary storage inside db for scraped listing fees
                # We will merge this in the final validation step
                await state_mgr._conn.execute(
                    """
                    UPDATE schools 
                    SET calculated_average_annual_fee_inr = ?, 
                        highest_annual_fee_inr = ?,
                        fee_data_found = 1
                    WHERE school_id = ?
                    """,
                    (s["avg_annual_fee"], s["highest_annual_fee"], s["school_id"])
                )
            await state_mgr._conn.commit()
            
            logger.info("Scraped %d schools from UniApply and saved to database", len(schools))

    return schools
