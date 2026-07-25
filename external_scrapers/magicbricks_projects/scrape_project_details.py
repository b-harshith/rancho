#!/usr/bin/env python3
import json
import os
import re
import time
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

try:
    from curl_cffi import requests as cf_requests
except ImportError:
    raise ImportError("[ERROR] Missing curl_cffi: Please run `pip install curl_cffi`")

INPUT_FILE = "data/raw/bangalore_projects.jsonl"
OUTPUT_FILE = "data/raw/bangalore_projects_enriched.jsonl"
CONCURRENCY_LIMIT = 40  # Adjust concurrency to avoid overloading Magicbricks

def parse_html_details(html):
    min_price = None
    max_price = None
    lat = None
    lon = None
    
    # Extract all JSON-LD script blocks
    json_lds = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    for jld in json_lds:
        try:
            data = json.loads(jld.strip())
            # Handle list of items or single item
            items = data if isinstance(data, list) else [data]
            for item in items:
                # 1. Look for Pricing details
                if item.get("@type") == "Product" and "offers" in item:
                    offers = item["offers"]
                    if isinstance(offers, dict):
                        if "lowPrice" in offers and offers["lowPrice"]:
                            min_price = float(offers["lowPrice"])
                        if "highPrice" in offers and offers["highPrice"]:
                            max_price = float(offers["highPrice"])
                            
                # 2. Look for Coordinates details
                if item.get("@type") in ["ApartmentComplex", "Place"] and "geo" in item:
                    geo = item["geo"]
                    if isinstance(geo, dict):
                        if "latitude" in geo and geo["latitude"]:
                            lat = float(geo["latitude"])
                        if "longitude" in geo and geo["longitude"]:
                            lon = float(geo["longitude"])
        except Exception:
            continue
            
    return min_price, max_price, lat, lon

def fetch_details_sync(session, pdp_url):
    url = f"https://www.magicbricks.com/{pdp_url}"
    try:
        resp = session.get(url, impersonate="chrome", timeout=20)
        if resp.status_code == 200:
            return parse_html_details(resp.text)
        elif resp.status_code == 404:
            return "404", None, None, None
    except Exception:
        pass
    return None, None, None, None

async def worker(queue, session, write_queue, executor):
    loop = asyncio.get_event_loop()
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
        
        idx, card = item
        pdp_url = card.get("pdpUrl")
        
        if not pdp_url:
            await write_queue.put((idx, card, False))
            queue.task_done()
            continue
            
        # Run synchronous network request in the thread pool
        min_p, max_p, lat, lon = await loop.run_in_executor(
            executor, fetch_details_sync, session, pdp_url
        )
        
        # Check if 404
        if min_p == "404":
            await write_queue.put((idx, card, False))
            queue.task_done()
            continue
            
        # Update project data if successfully extracted
        updated = False
        if min_p is not None:
            card["minPrice"] = min_p
            card["minPriceF"] = min_p
            updated = True
        if max_p is not None:
            card["maxPrice"] = max_p
            card["maxPriceF"] = max_p
            updated = True
        if lat is not None:
            card["latitude"] = lat
            updated = True
        if lon is not None:
            card["longitude"] = lon
            updated = True
            
        await write_queue.put((idx, card, updated))
        queue.task_done()
        # Random sleep to avoid rapid hits
        await asyncio.sleep(random.uniform(0.5, 1.5))

async def writer(write_queue, total_lines):
    processed = 0
    updated_count = 0
    start_time = time.time()
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        while True:
            item = await write_queue.get()
            if item is None:
                write_queue.task_done()
                break
            idx, card, was_updated = item
            f.write(json.dumps(card, ensure_ascii=False) + "\n")
            f.flush()
            
            processed += 1
            if was_updated:
                updated_count += 1
                
            elapsed = time.time() - start_time
            qps = processed / elapsed if elapsed > 0 else 0
            eta = (total_lines - processed) / qps if qps > 0 else 0
            
            progress_pct = (processed / total_lines) * 100
            print(
                f"\rProgress: {processed}/{total_lines} ({progress_pct:.1f}%) | "
                f"Enriched: {updated_count} | QPS: {qps:.1f} | "
                f"Elapsed: {int(elapsed)}s | ETA: {int(eta//3600):02d}:{int((eta%3600)//60):02d}:{int(eta%60):02d}",
                end="",
                flush=True
            )
            write_queue.task_done()
    print()

async def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} does not exist.")
        return
        
    # Resume check: load what is already processed in output file
    existing_psmids = set()
    if os.path.exists(OUTPUT_FILE):
        print("Reading existing output file for resumption...")
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            record = json.loads(line)
                            psmid = record.get("psmid")
                            if psmid:
                                existing_psmids.add(str(psmid))
                        except:
                            pass
            print(f"Resuming: {len(existing_psmids)} projects already processed.")
        except Exception as e:
            print(f"Could not load resumption file: {e}")

    # Read remaining input cards
    cards = []
    skipped_cards = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    card = json.loads(line)
                    psmid = str(card.get("psmid"))
                    if psmid in existing_psmids:
                        skipped_cards.append(card)
                    else:
                        cards.append(card)
                except:
                    pass
                    
    total_to_process = len(cards)
    print(f"Total projects to fetch: {total_to_process} (Already cached: {len(skipped_cards)})")
    
    # Write existing (skipped) cards into enriched output file first to maintain them
    if skipped_cards and os.path.exists(OUTPUT_FILE):
        # We rewrite the output file at the end, but for safety, write queue handles new ones
        pass

    queue = asyncio.Queue()
    write_queue = asyncio.Queue()
    
    # Enqueue tasks
    for idx, card in enumerate(cards):
        await queue.put((idx, card))
        
    for _ in range(CONCURRENCY_LIMIT):
        await queue.put(None)

    # If we are resuming, we write skipped ones to write queue first so they are saved
    for idx, card in enumerate(skipped_cards):
        await write_queue.put((idx, card, False))

    total_lines = total_to_process + len(skipped_cards)

    session = cf_requests.Session()
    executor = ThreadPoolExecutor(max_workers=CONCURRENCY_LIMIT)
    
    workers = []
    for _ in range(CONCURRENCY_LIMIT):
        workers.append(asyncio.create_task(worker(queue, session, write_queue, executor)))
        
    writer_task = asyncio.create_task(writer(write_queue, total_lines))
    
    await asyncio.gather(*workers)
    await write_queue.put(None)
    await writer_task
    
    executor.shutdown()
    print(f"Enrichment complete! Dataset saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScraper interrupted. Progress saved.")
