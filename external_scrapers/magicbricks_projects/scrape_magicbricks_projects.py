#!/usr/bin/env python3
import json
import os
import time
import random
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from curl_cffi import requests as cf_requests
except ImportError:
    raise ImportError("[ERROR] Missing curl_cffi: Please run `pip install curl_cffi`")

# Output Configuration
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FILE = os.environ.get(
    "MAGICBRICKS_PROJECTS_OUTPUT",
    str(PROJECT_ROOT / "DATA" / "raw" / "bangalore_projects.jsonl"),
)
CITY_ID = 3327  # Bangalore
PAGE_LIMIT = 1500  # Safety limit for total pages
MAX_WORKERS = 8  # Number of parallel scraper threads

# Only extract and save these useful fields to avoid bloated records
FIELDS_TO_KEEP = {
    "psmid", "psmName", "devName", "pdpUrl", 
    "minPrice", "maxPrice", "minPriceF", "maxPriceF", 
    "sqFtPrice", "sqFtPrMx", "totalUnits", "prjPossYear", "oc", 
    "pincode", "lmtDName", "ctname", "visBd"
}

# Thread Synchronization
file_lock = threading.Lock()
seen_lock = threading.Lock()
print_lock = threading.Lock()
counter_lock = threading.Lock()

current_page = 1
stop_event = threading.Event()
seen_ids = set()

def load_seen_ids(filename):
    seen = set()
    if not os.path.exists(filename):
        return seen
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            try:
                card = json.loads(line)
                psmid = card.get("psmid")
                if psmid:
                    seen.add(str(psmid))
            except:
                pass
    return seen

def safe_print(message):
    with print_lock:
        print(message)

def worker_session():
    global current_page
    session = cf_requests.Session()
    
    while not stop_event.is_set():
        # Get next page number atomically
        with counter_lock:
            page = current_page
            current_page += 1
            
        if page > PAGE_LIMIT:
            break
            
        url = f"https://www.magicbricks.com/mbproject/newProjectCards?&pageNo={page}&city={CITY_ID}&possessionCheck=N"
        
        response_text = None
        for attempt in range(3):
            if stop_event.is_set():
                return
            try:
                resp = session.get(url, impersonate="chrome", timeout=30)
                if resp.status_code == 200:
                    response_text = resp.text
                    break
                safe_print(f"  [Warning] Page {page}: HTTP {resp.status_code}, attempt {attempt+1}")
            except Exception as e:
                safe_print(f"  [Warning] Page {page}: Request error: {e}, attempt {attempt+1}")
            time.sleep((2 ** attempt) + random.uniform(1, 3))
            
        if not response_text:
            safe_print(f"[Error] Failed to fetch page {page}. Skipping.")
            continue
            
        try:
            data = json.loads(response_text)
        except Exception as e:
            safe_print(f"[Error] Failed to parse JSON on page {page}.")
            continue
            
        cards = data.get("projectsCards", [])
        if not cards:
            safe_print(f"[Info] No more project cards on page {page}. Stopping scraper.")
            stop_event.set()
            break
            
        new_cards = []
        page_dupes = 0
        
        with seen_lock:
            for card in cards:
                psmid = card.get("psmid")
                if psmid:
                    psmid_str = str(psmid)
                    if psmid_str not in seen_ids:
                        seen_ids.add(psmid_str)
                        
                        filtered_card = {k: card[k] for k in FIELDS_TO_KEEP if k in card}
                        filtered_card["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if "mhDesc" in card:
                            filtered_card["mhDesc"] = card["mhDesc"]
                        new_cards.append(filtered_card)
                    else:
                        page_dupes += 1
                else:
                    filtered_card = {k: card[k] for k in FIELDS_TO_KEEP if k in card}
                    filtered_card["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if "mhDesc" in card:
                        filtered_card["mhDesc"] = card["mhDesc"]
                    new_cards.append(filtered_card)

        if new_cards:
            with file_lock:
                with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                    for card in new_cards:
                        f.write(json.dumps(card, ensure_ascii=False) + "\n")
            safe_print(f"Page {page}: Saved {len(new_cards)} new projects. (Dupes: {page_dupes})")
        else:
            safe_print(f"Page {page}: No new projects. (Dupes: {page_dupes})")
            if page_dupes >= len(cards) and page > 50:
                # If we're deep in the pages and hit only duplicates, stop early
                safe_print(f"[Info] Page {page} has only duplicates. Stopping early.")
                stop_event.set()
                break
                
        time.sleep(random.uniform(1.0, 2.5))

def main():
    global seen_ids
    print("[Magicbricks Projects Scraper] Starting multi-threaded scraper...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    seen_ids = load_seen_ids(OUTPUT_FILE)
    print(f"[Magicbricks Projects Scraper] Loaded {len(seen_ids):,} existing project IDs.")
    
    # Run threads in ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(worker_session) for _ in range(MAX_WORKERS)]
        for f in futures:
            f.result()
            
    print(f"[Magicbricks Projects Scraper] Completed! Total unique projects scraped: {len(seen_ids)}.")

if __name__ == "__main__":
    main()
