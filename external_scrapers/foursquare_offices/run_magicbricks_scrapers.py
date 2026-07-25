#!/usr/bin/env python3
import os
import sys
import json
import time
import random
import threading
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from curl_cffi import requests as cf_requests
except ImportError:
    raise ImportError("[ERROR] Missing curl_cffi: Please run `pip install curl_cffi`")

# Configuration
WEB_PLATFORM_DIR = Path("/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest")
DATA_DIR = WEB_PLATFORM_DIR / "DATA"
RAW_OUT_DIR = DATA_DIR / "raw"
LOCALITIES_CONFIG_DIR = WEB_PLATFORM_DIR / "config" / "magicbricks_localities"

CITIES_CONFIG = {
    "delhi_ncr": {
        "name": "Delhi NCR",
        "components": [
            {"source_city_id": "2624", "source_city_name": "New Delhi", "verified_url": "https://www.magicbricks.com/localities-in-new-delhi"},
            {"source_city_id": "6403", "source_city_name": "Noida", "verified_url": "https://www.magicbricks.com/localities-in-noida"},
            {"source_city_id": "2951", "source_city_name": "Gurgaon", "verified_url": "https://www.magicbricks.com/localities-in-gurgaon"},
            {"source_city_id": "6146", "source_city_name": "Ghaziabad", "verified_url": "https://www.magicbricks.com/localities-in-ghaziabad"},
            {"source_city_id": "2944", "source_city_name": "Faridabad", "verified_url": "https://www.magicbricks.com/localities-in-faridabad"}
        ]
    },
    "mumbai": {
        "name": "Mumbai",
        "components": [
            {"source_city_id": "4320", "source_city_name": "Mumbai", "verified_url": "https://www.magicbricks.com/localities-in-Mumbai"}
        ]
    },
    "hyderabad": {
        "name": "Hyderabad",
        "components": [
            {"source_city_id": "2060", "source_city_name": "Hyderabad", "verified_url": "https://www.magicbricks.com/localities-in-Hyderabad"}
        ]
    },
    "chennai": {
        "name": "Chennai",
        "components": [
            {"source_city_id": "5196", "source_city_name": "Chennai", "verified_url": "https://www.magicbricks.com/localities-in-Chennai"}
        ]
    },
    "kolkata": {
        "name": "Kolkata",
        "components": [
            {"source_city_id": "6903", "source_city_name": "Kolkata", "verified_url": "https://www.magicbricks.com/localities-in-Kolkata"}
        ]
    },
    "pune": {
        "name": "Pune",
        "components": [
            {"source_city_id": "4378", "source_city_name": "Pune", "verified_url": "https://www.magicbricks.com/localities-in-Pune"}
        ]
    },
    "ahmedabad": {
        "name": "Ahmedabad",
        "components": [
            {"source_city_id": "2690", "source_city_name": "Ahmedabad", "verified_url": "https://www.magicbricks.com/localities-in-Ahmedabad"}
        ]
    }
}

# --- Project Scraper Rules ---
FIELDS_TO_KEEP = {
    "psmid", "psmName", "devName", "pdpUrl", 
    "minPrice", "maxPrice", "minPriceF", "maxPriceF", 
    "sqFtPrice", "sqFtPrMx", "totalUnits", "prjPossYear", "oc", 
    "pincode", "lmtDName", "ctname", "visBd"
}

# --- Setup Directories ---
RAW_OUT_DIR.mkdir(parents=True, exist_ok=True)
LOCALITIES_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Generate configuration files for magicbricks_localities
for city_id, info in CITIES_CONFIG.items():
    cfg_payload = {
        "cities": {
            city_id: {
                "components": [
                    {
                        "source_city_id": comp["source_city_id"],
                        "source_city_name": comp["source_city_name"],
                        "verified_url": comp["verified_url"],
                        "pagination_url": "https://www.magicbricks.com/mbutility/localitySearchPage?autoLoad=Y&page={page}&sortBy=&cityName={city_name}"
                    }
                    for comp in info["components"]
                ]
            }
        }
    }
    cfg_file = LOCALITIES_CONFIG_DIR / f"{city_id}.json"
    with open(cfg_file, "w") as f:
        json.dump(cfg_payload, f, indent=2)
    print(f"Generated localities config: {cfg_file}")


def load_seen_ids(filename):
    seen = set()
    if not os.path.exists(filename):
        return seen
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            try:
                card = json.loads(line)
                psmid = card.get("psmid") or card.get("psid")
                if psmid:
                    seen.add(str(psmid))
            except:
                pass
    return seen


def scrape_projects_for_city(city_id, info):
    print(f"\n[Projects Scraper] Starting projects scraper for {info['name']}...")
    output_file = RAW_OUT_DIR / f"{city_id}_projects.jsonl"
    seen_ids = load_seen_ids(output_file)
    print(f"[Projects Scraper] {info['name']}: Loaded {len(seen_ids)} existing project IDs.")

    file_lock = threading.Lock()
    seen_lock = threading.Lock()
    print_lock = threading.Lock()
    counter_lock = threading.Lock()

    # Set page limit to 1500 for all cities to ensure completeness
    page_limit = 1500
    max_workers = 4
    
    current_page = 1
    stop_event = threading.Event()

    def safe_print(msg):
        with print_lock:
            print(msg)

    def worker(city_num_id, comp_name):
        nonlocal current_page
        session = cf_requests.Session()
        while not stop_event.is_set():
            with counter_lock:
                page = current_page
                current_page += 1
            if page > page_limit:
                break

            url = f"https://www.magicbricks.com/mbproject/newProjectCards?&pageNo={page}&city={city_num_id}&possessionCheck=N"
            response_text = None
            for attempt in range(3):
                if stop_event.is_set():
                    return
                try:
                    resp = session.get(url, impersonate="chrome", timeout=30)
                    if resp.status_code == 200:
                        response_text = resp.text
                        break
                except Exception as e:
                    pass
                time.sleep((2 ** attempt) + random.uniform(1, 2))

            if not response_text:
                continue

            try:
                data = json.loads(response_text)
            except:
                continue

            cards = data.get("projectsCards", [])
            if not cards:
                stop_event.set()
                break

            new_cards = []
            page_dupes = 0

            with seen_lock:
                for card in cards:
                    psmid = card.get("psmid") or card.get("psid")
                    if psmid:
                        psmid_str = str(psmid)
                        if psmid_str not in seen_ids:
                            seen_ids.add(psmid_str)
                            filtered_card = {k: card[k] for k in FIELDS_TO_KEEP if k in card}
                            filtered_card["psmid"] = psmid
                            filtered_card["source_city_id"] = str(city_num_id)
                            filtered_card["source_city_name"] = comp_name
                            filtered_card["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            if "mhDesc" in card:
                                filtered_card["mhDesc"] = card["mhDesc"]
                            new_cards.append(filtered_card)
                        else:
                            page_dupes += 1

            if new_cards:
                with file_lock:
                    with open(output_file, "a", encoding="utf-8") as f:
                        for card in new_cards:
                            f.write(json.dumps(card, ensure_ascii=False) + "\n")
                safe_print(f"[{info['name']} - {comp_name}] Page {page}: Saved {len(new_cards)} new projects.")
            else:
                if page_dupes >= len(cards) and page > 50:
                    stop_event.set()
                    break

            time.sleep(random.uniform(0.5, 1.5))

    for comp in info["components"]:
        comp_id = comp["source_city_id"]
        comp_name = comp["source_city_name"]
        stop_event.clear()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker, comp_id, comp_name) for _ in range(max_workers)]
            for f in futures:
                f.result()

    print(f"[Projects Scraper] Completed projects for {info['name']}. Output: {output_file}")


def run_localities_for_city(city_id):
    print(f"\n[Localities Collector] Starting localities collector for {city_id}...")
    cfg_file = LOCALITIES_CONFIG_DIR / f"{city_id}.json"
    
    # We invoke the module collectors.magicbricks_localities
    # We output to WEB_PLATFORM_DIR / "DATA" / "multicity"
    cmd = [
        sys.executable,
        "-m",
        "collectors.magicbricks_localities",
        "--city", city_id,
        "--config", str(cfg_file),
        "--output-root", str(DATA_DIR / "multicity"),
        "--resume",
        "--workers", "1"
    ]
    try:
        subprocess.run(cmd, cwd=str(WEB_PLATFORM_DIR), check=True)
        print(f"[Localities Collector] Completed localities for {city_id} successfully.")
    except Exception as e:
        print(f"[Localities Collector] [ERROR] Localities collector failed for {city_id}: {e}")


def main():
    print("=== Launching Parallel Scrapers ===")
    
    # Run the projects and localities scrapers in parallel
    # We will use ThreadPoolExecutor to run them concurrently for all target cities
    cities_to_scrape = list(CITIES_CONFIG.keys())
    
    def scrape_everything_for_city(city_id):
        # 1. Projects Scraping
        scrape_projects_for_city(city_id, CITIES_CONFIG[city_id])
        # 2. Localities Scraping
        run_localities_for_city(city_id)

    with ThreadPoolExecutor(max_workers=len(cities_to_scrape)) as executor:
        executor.map(scrape_everything_for_city, cities_to_scrape)

    print("\n=== All Scrapers and Collectors Execution Finished ===")

if __name__ == "__main__":
    main()
