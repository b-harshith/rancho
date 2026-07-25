import asyncio
import json
import os
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        # Launch browser with some user agent / args to look more human
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
            ]
        )
        # Create context with standard viewport and user agent
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        page = await context.new_page()
        
        # We will save all JSON responses to a list
        responses_captured = []
        
        async def handle_response(response):
            try:
                url = response.url
                # Filter responses that might be the search data
                if "practo.com" in url:
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type or "javascript" in content_type or "search" in url or "api" in url:
                        # Only try to read if status is 200
                        if response.status == 200:
                            try:
                                text = await response.text()
                                # Try parsing as JSON to see if it contains hospital data
                                data = json.loads(text)
                                # Let's save this
                                responses_captured.append({
                                    "url": url,
                                    "data": data
                                })
                                print(f"Captured JSON response from: {url[:100]}... (keys: {list(data.keys()) if isinstance(data, dict) else 'list'})")
                            except Exception:
                                pass
            except Exception as e:
                pass

        page.on("response", handle_response)
        
        url = 'https://www.practo.com/search/hospitals?results_type=hospital&q=%5B%7B%22word%22%3A%22hospital%22%2C%22autocompleted%22%3Atrue%2C%22category%22%3A%22type%22%7D%5D&city=bangalore'
        print(f"Navigating to {url}...")
        
        try:
            # Go to the page and wait. The challenge might take 5-15 seconds to solve and redirect.
            await page.goto(url, timeout=60000)
            
            print("Page loaded. Waiting for title or redirect...")
            for i in range(15):
                title = await page.title()
                print(f"Current Page Title: {title}")
                if "challenge" not in title.lower():
                    break
                await page.wait_for_timeout(2000)
            
            # Wait for some selectors that indicate hospitals list
            # We can also scroll down to load more
            print("Waiting for any hospital list element or card...")
            # Let's inspect the page content to see if we see any hospital names
            await page.wait_for_timeout(10000)
            
            # Let's write the HTML again to see if it changed
            html = await page.content()
            with open("scratch/practo_search_loaded.html", "w") as f:
                f.write(html)
            print("Saved current HTML to scratch/practo_search_loaded.html")
            
        except Exception as e:
            print(f"Navigation/waiting failed: {e}")
            
        # Let's save all captured responses to a file for analysis
        with open("scratch/captured_responses.json", "w") as f:
            json.dump(responses_captured, f, indent=2)
        print(f"Saved {len(responses_captured)} captured responses to scratch/captured_responses.json")
        
        await browser.close()

asyncio.run(run())
