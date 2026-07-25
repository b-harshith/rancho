#!/usr/bin/env python3
import os
import re
import json
import asyncio
import urllib.parse
import time
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

try:
    from curl_cffi import requests as cf_requests
except ImportError:
    raise ImportError("[ERROR] Missing curl_cffi: Please run `pip install curl_cffi`")

# Configuration
RAW_DIR = Path("/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/DATA/raw")
API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
CONCURRENCY_LIMIT = 40  # Max concurrent detail requests / geocoding

CITIES_METADATA = {
    "delhi_ncr": {"address_suffix": "Delhi NCR, India"},
    "mumbai": {"address_suffix": "Mumbai, Maharashtra, India"},
    "hyderabad": {"address_suffix": "Hyderabad, Telangana, India"},
    "chennai": {"address_suffix": "Chennai, Tamil Nadu, India"},
    "kolkata": {"address_suffix": "Kolkata, West Bengal, India"},
    "pune": {"address_suffix": "Pune, Maharashtra, India"},
}


# --- Stage 1: Parse details from PDP HTML ---
def parse_html_details(html):
    min_price = None
    max_price = None
    lat = None
    lon = None
    
    json_lds = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    for jld in json_lds:
        try:
            data = json.loads(jld.strip())
            items = data if isinstance(data, list) else [data]
            for item in items:
                # Price extraction
                if item.get("@type") == "Product" and "offers" in item:
                    offers = item["offers"]
                    if isinstance(offers, dict):
                        if "lowPrice" in offers and offers["lowPrice"]:
                            min_price = float(offers["lowPrice"])
                        if "highPrice" in offers and offers["highPrice"]:
                            max_price = float(offers["highPrice"])
                            
                # Coordinate extraction
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


# --- Stage 2: Google Geocoding Fallback ---
async def geocode_address(session, address):
    if not API_KEY:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY before running this scraper.")
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={API_KEY}"
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("status") == "OK" and data.get("results"):
                    loc = data["results"][0]["geometry"]["location"]
                    return loc["lat"], loc["lng"]
                elif data.get("status") == "OVER_QUERY_LIMIT":
                    return "OVER_LIMIT", None
            return None, None
    except Exception:
        return None, None


# --- Core Enrichment & Geocoding Worker for Async loop ---
async def process_card(session, card, executor, city_suffix, stats):
    pdp_url = card.get("pdpUrl")
    lat, lon = None, None

    # Step 1: Attempt HTML Detail extraction first
    if pdp_url:
        loop = asyncio.get_event_loop()
        min_p, max_p, detail_lat, detail_lon = await loop.run_in_executor(
            executor, fetch_details_sync, session, pdp_url
        )
        if detail_lat is not None and detail_lon is not None:
            lat, lon = detail_lat, detail_lon
            stats["html_success"] += 1
            if min_p and min_p != "404":
                card["minPrice"] = min_p
                card["minPriceF"] = min_p
            if max_p:
                card["maxPrice"] = max_p
                card["maxPriceF"] = max_p

    # Step 2: Fallback to Google Geocoding if coordinates are still missing
    if lat is None or lon is None:
        name = card.get("psmName") or card.get("devName") or ""
        sublocality = card.get("lmtDName") or ""
        query_parts = []
        if name:
            query_parts.append(name)
        if sublocality:
            query_parts.append(sublocality)
        query_parts.append(city_suffix)
        address = ", ".join(query_parts)

        # HTTP request session for Google Maps API
        import aiohttp
        async with aiohttp.ClientSession() as google_session:
            while True:
                g_lat, g_lon = await geocode_address(google_session, address)
                if g_lat == "OVER_LIMIT":
                    await asyncio.sleep(2)
                    continue
                lat, lon = g_lat, g_lon
                if lat is not None:
                    stats["google_success"] += 1
                else:
                    stats["failed"] += 1
                break

    card["latitude"] = lat
    card["longitude"] = lon
    return card


def classify_type(name, desc):
    name = (name or "").lower()
    desc = (desc or "").lower()
    if any(k in name or k in desc for k in ["villa", "row house", "rowhouse", "independent house", "residential house", "bungalow", "sanctuary"]):
        return "Villa/House"
    if any(k in name or k in desc for k in ["builder floor", "independent floor"]):
        return "Builder Floor"
    if any(k in name or k in desc for k in ["plot", "layout", "land", "sites"]):
        return "Plot/Land"
    return "Apartment"


async def process_city(city_id):
    input_file = RAW_DIR / f"{city_id}_projects.jsonl"
    output_file = RAW_DIR / f"{city_id}_projects_enriched_and_geocoded.jsonl"

    if not input_file.exists():
        print(f"[Error] Input file {input_file} not found. Skipping.")
        return

    print(f"\n=== Processing {city_id.upper()} ===")
    cards = []
    plot_land_count = 0
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                card = json.loads(line)
                name = card.get("psmName") or card.get("devName") or ""
                desc = card.get("mhDesc") or ""
                p_type = classify_type(name, desc)
                if p_type == "Plot/Land":
                    plot_land_count += 1
                else:
                    card["project_type"] = p_type
                    cards.append(card)

    print(f"Loaded {len(cards)} projects (filtered out {plot_land_count} Plot/Land projects) from {input_file}")
    
    stats = {"html_success": 0, "google_success": 0, "failed": 0}
    session = cf_requests.Session()
    executor = ThreadPoolExecutor(max_workers=CONCURRENCY_LIMIT)
    city_suffix = CITIES_METADATA[city_id]["address_suffix"]

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def sem_process(card):
        async with semaphore:
            return await process_card(session, card, executor, city_suffix, stats)

    tasks = [sem_process(card) for card in cards]
    processed_cards = await asyncio.gather(*tasks)

    # Save to output file
    with open(output_file, "w", encoding="utf-8") as f:
        for card in processed_cards:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")

    print(f"Finished {city_id}. Stats:")
    print(f"  Coordinates from HTML: {stats['html_success']}")
    print(f"  Coordinates from Google Geocoding: {stats['google_success']}")
    print(f"  Failed (no coordinates found): {stats['failed']}")
    print(f"Saved: {output_file}")


async def main_async():
    for city_id in CITIES_METADATA.keys():
        await process_city(city_id)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
