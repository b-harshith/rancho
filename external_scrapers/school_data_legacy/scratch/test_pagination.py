import asyncio
import json
import re
from playwright.async_api import async_playwright

async def get_page_data(p, url):
    browser = await p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"]
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800}
    )
    page = await context.new_page()
    
    print(f"Navigating to {url}...")
    await page.goto(url, timeout=60000)
    
    # Wait for the challenge to complete
    for i in range(15):
        title = await page.title()
        print(f"[{i}] Title: {title}")
        if "challenge" not in title.lower():
            break
        await page.wait_for_timeout(2000)
        
    await page.wait_for_timeout(5000)
    
    html = await page.content()
    # Save to debug html
    with open("scratch/page2_debug.html", "w") as f:
        f.write(html)
        
    await browser.close()
    
    # Extract redux state
    match = re.search(r'window\.__REDUX_STATE__\s*=\s*(\{[\s\S]*?\});\s*(?:</script>|window\.)', html)
    if match:
        try:
            state_json = json.loads(match.group(1))
            hospitals = state_json.get("establishments", {}).get("hospitalListing", {}).get("hospitals", {})
            entities = hospitals.get("entities", {})
            return list(entities.values())
        except Exception as e:
            print("Error parsing state JSON:", e)
    return []

async def main():
    async with async_playwright() as p:
        url_p2 = 'https://www.practo.com/search/hospitals?results_type=hospital&q=%5B%7B%22word%22%3A%22hospital%22%2C%22autocompleted%22%3Atrue%2C%22category%22%3A%22type%22%7D%5D&city=bangalore&page=2'
        hospitals_p2 = await get_page_data(p, url_p2)
        print(f"Found {len(hospitals_p2)} hospitals on Page 2")

asyncio.run(main())
