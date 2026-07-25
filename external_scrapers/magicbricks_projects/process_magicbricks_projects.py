#!/usr/bin/env python3
import json
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_FILE = "data/raw/bangalore_projects.jsonl"
OUTPUT_FILE = "data/processed/processed_bangalore_projects.json"
ARCGIS_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
MAX_WORKERS = 10  # For concurrent geocoding

def fetch_coordinates(name, sublocality):
    # Try with project name and sublocality
    query = f"{name}, {sublocality}, Bangalore, India" if sublocality else f"{name}, Bangalore, India"
    params = {"SingleLine": query, "f": "json", "maxLocations": 1}
    try:
        resp = requests.get(ARCGIS_URL, params=params, timeout=5)
        if resp.status_code == 200:
            candidates = resp.json().get("candidates", [])
            if candidates:
                loc = candidates[0]["location"]
                return loc["y"], loc["x"]
    except:
        pass
    
    # Fallback to sublocality only
    if sublocality:
        query_sub = f"{sublocality}, Bangalore, India"
        params_sub = {"SingleLine": query_sub, "f": "json", "maxLocations": 1}
        try:
            resp = requests.get(ARCGIS_URL, params=params_sub, timeout=5)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    loc = candidates[0]["location"]
                    return loc["y"], loc["x"]
        except:
            pass
            
    return None, None

def process_card(card):
    name = card.get("psmName") or card.get("devName") or "Unknown Project"
    sublocality = card.get("lmtDName")
    
    # Resolve coordinates
    lat, lon = fetch_coordinates(name, sublocality)
    
    # Parse units
    units = card.get("totalUnits")
    if units is not None:
        try:
            units = float(units)
        except:
            units = None
            
    # Parse sqft price
    price = card.get("sqFtPrice")
    if price is not None:
        try:
            price = float(price)
        except:
            price = None
            
    # Construction Status
    possession_year = card.get("prjPossYear")
    oc = card.get("oc")
    desc = (card.get("mhDesc") or "").lower()
    
    if oc == "Y":
        status = "Ready To Move"
    elif possession_year:
        try:
            py = int(possession_year)
            status = "Ready To Move" if py <= 2026 else "Under Construction"
        except:
            status = "Under Construction"
    else:
        if "ready to move" in desc:
            status = "Ready To Move"
        else:
            status = "Under Construction"

    # Price bounds
    min_price = card.get("minPrice")
    if min_price is not None:
        try:
            min_price = float(min_price)
        except:
            min_price = None
            
    max_price = card.get("maxPrice")
    if max_price is not None:
        try:
            max_price = float(max_price)
        except:
            max_price = None
            
    # URL construction
    pdp_url = card.get("pdpUrl")
    url = f"https://www.magicbricks.com/{pdp_url}" if pdp_url else ""
    
    return {
        "name": name,
        "lat": lat,
        "lon": lon,
        "category": "",           # Left blank for now
        "tam": None,              # Left blank for now
        "units": units,
        "price": price,
        "locality": "",           # Left blank for now
        "hex_id": "",             # Left blank for now
        "zone": "",               # Left blank for now
        "url": url,
        "confidence": 1.0,
        "construction_status": status,
        "min_price": min_price,
        "max_price": max_price
    }

def main():
    print("[Processor] Starting Magicbricks project processor...")
    if not os.path.exists(INPUT_FILE):
        print(f"[Error] Input file {INPUT_FILE} does not exist.")
        return
        
    cards = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                cards.append(json.loads(line))
            except:
                pass
                
    print(f"[Processor] Loaded {len(cards)} project cards. Geocoding and mapping records...")
    
    processed_records = []
    
    # Process concurrently for fast geocoding
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_card, card): card for card in cards}
        for idx, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                processed_records.append(result)
            except Exception as e:
                print(f"Error processing record {idx}: {e}")
                
            if idx % 50 == 0 or idx == len(cards):
                print(f"Processed {idx}/{len(cards)} projects...")
                
    # Save output
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(processed_records, f, indent=2, ensure_ascii=False)
        
    print(f"[Processor] Completed! Saved {len(processed_records)} processed projects to {OUTPUT_FILE}.")

if __name__ == "__main__":
    main()
