import asyncio
import json
import re
import os
import sys
from playwright.async_api import async_playwright

CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")

# Ensure output directory exists
os.makedirs("data", exist_ok=True)

async def scrape_practo_hospitals():
    all_hospitals = {}
    page_num = 1
    consecutive_empty = 0
    max_empty_pages = 3  # Stop after 3 empty pages

    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        
        while True:
            url = f'https://www.practo.com/search/hospitals?results_type=hospital&q=%5B%7B%22word%22%3A%22hospital%22%2C%22autocompleted%22%3Atrue%2C%22category%22%3A%22type%22%7D%5D&city={CITY_SLUG}&page={page_num}'
            print(f"\n--- Scraping Page {page_num} ---")
            print(f"URL: {url}")
            
            try:
                await page.goto(url, timeout=60000)
                
                # Wait for Akamai challenge to solve
                challenge_solved = False
                for attempt in range(15):
                    title = await page.title()
                    if "challenge" not in title.lower():
                        challenge_solved = True
                        break
                    print(f"  [Attempt {attempt+1}] Title is still '{title}'. Waiting...")
                    await page.wait_for_timeout(2000)
                
                if not challenge_solved:
                    print("  [Warning] Challenge might not have been solved. Retrying wait...")
                    
                # Let page settle
                await page.wait_for_timeout(4000)
                
                html = await page.content()
                
                # Find the script containing __REDUX_STATE__
                scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', html)
                state_json = None
                
                for script in scripts:
                    if "__REDUX_STATE__" in script:
                        prefix = "window.__REDUX_STATE__="
                        idx = script.find(prefix)
                        if idx != -1:
                            json_part = script[idx + len(prefix):].strip()
                            if json_part.endswith(";"):
                                json_part = json_part[:-1].strip()
                            try:
                                state_json = json.loads(json_part)
                                break
                            except Exception as e:
                                print(f"  [Error] JSON parse error: {e}")
                
                if state_json:
                    est = state_json.get("establishments", {})
                    hosp_listing = est.get("hospitalListing", {})
                    hospitals_data = hosp_listing.get("hospitals", {})
                    entities = hospitals_data.get("entities", {})
                    
                    if entities:
                        consecutive_empty = 0
                        new_on_page = 0
                        for hosp_id, hosp_info in entities.items():
                            if hosp_id not in all_hospitals:
                                all_hospitals[hosp_id] = hosp_info
                                new_on_page += 1
                        
                        print(f"  Page {page_num} summary: Found {len(entities)} hospitals. Added {new_on_page} new ones.")
                        print(f"  Total unique hospitals so far: {len(all_hospitals)}")
                        
                        if new_on_page == 0:
                            print("  No new hospitals found on this page. We might be repeating or reached the end.")
                            # Usually, if page 2 has 0 new, we can stop
                            break
                    else:
                        print(f"  No hospital entities found in redux state on page {page_num}.")
                        consecutive_empty += 1
                else:
                    print(f"  Could not find or parse redux state on page {page_num}.")
                    consecutive_empty += 1
                    
            except Exception as e:
                print(f"  [Error] Scraping page {page_num} failed: {e}")
                consecutive_empty += 1
                
            if consecutive_empty >= max_empty_pages:
                print(f"Stopping crawler: {consecutive_empty} consecutive empty pages reached.")
                break
                
            page_num += 1
            # Wait between requests to be polite
            await page.wait_for_timeout(3000)
            
        await browser.close()
        
    # Export data
    hospitals_list = list(all_hospitals.values())
    
    # Save as JSON
    json_path = f"data/practo_hospitals_{CITY_SLUG}.json"
    with open(json_path, "w") as jf:
        json.dump(hospitals_list, jf, indent=2)
    print(f"\nSaved {len(hospitals_list)} hospitals to JSON: {json_path}")
    
    # Save as JSONL
    jsonl_path = f"data/practo_hospitals_{CITY_SLUG}.jsonl"
    with open(jsonl_path, "w") as jlf:
        for hosp in hospitals_list:
            jlf.write(json.dumps(hosp) + "\n")
    print(f"Saved {len(hospitals_list)} hospitals to JSONL: {jsonl_path}")

if __name__ == "__main__":
    asyncio.run(scrape_practo_hospitals())
