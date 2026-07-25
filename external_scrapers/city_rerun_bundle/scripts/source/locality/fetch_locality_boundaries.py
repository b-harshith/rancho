#!/usr/bin/env python3
import json
import os
import time
import urllib.parse
from pathlib import Path
import requests

# Config
BASE_DIR = Path(__file__).resolve().parent.parent
CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
CITY_NAME = os.environ.get("CITY_NAME", CITY_SLUG.replace("-", " ").title())
CITY_BOUNDARY_CONTEXT = os.environ.get(
    "CITY_BOUNDARY_CONTEXT",
    f"{CITY_NAME}, Karnataka, India",
)
INPUT_FILE = BASE_DIR / "data" / "raw" / f"99acres_{CITY_SLUG}_localities.json"
OUTPUT_DIR = BASE_DIR / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / f"99acres_{CITY_SLUG}_locality_boundaries.json"
TEMP_OUTPUT_FILE = OUTPUT_DIR / f"99acres_{CITY_SLUG}_locality_boundaries.jsonl"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {
    "User-Agent": f"{CITY_NAME}LocalityBoundaryFetcher/1.0 (contact: city-rerun-bundle@example.com)"
}

def load_localities():
    if not INPUT_FILE.exists():
        print(f"Error: Input file {INPUT_FILE} not found.")
        return []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_existing_results():
    existing = {}
    # Load from the temporary JSONL file if it exists (for resumption)
    if TEMP_OUTPUT_FILE.exists():
        with open(TEMP_OUTPUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line)
                        existing[record["id"]] = record
                    except json.JSONDecodeError:
                        continue
    # Alternatively load from the final JSON file if it exists
    elif OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                records = json.load(f)
                for record in records:
                    existing[record["id"]] = record
        except Exception:
            pass
    return existing

def fetch_boundary(locality_name):
    # Construct query: e.g., "Amruthahalli, Bangalore, Karnataka, India"
    query = f"{locality_name}, {CITY_BOUNDARY_CONTEXT}"
    params = {
        "q": query,
        "format": "json",
        "polygon_geojson": "1",
        "limit": "1"
    }
    
    try:
        response = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data:
                # Return the best match
                match = data[0]
                return {
                    "osm_id": match.get("osm_id"),
                    "osm_type": match.get("osm_type"),
                    "display_name": match.get("display_name"),
                    "class": match.get("class"),
                    "type": match.get("type"),
                    "geojson": match.get("geojson"),
                    "lat": match.get("lat"),
                    "lon": match.get("lon"),
                    "boundingbox": match.get("boundingbox")
                }
            else:
                # Retry with a broader query if first query returns nothing
                # e.g., just "Amruthahalli, Bangalore, India"
                query_broad = f"{locality_name}, {CITY_NAME}, India"
                params["q"] = query_broad
                time.sleep(1) # Extra delay before retry
                response_broad = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
                if response_broad.status_code == 200:
                    data_broad = response_broad.json()
                    if data_broad:
                        match = data_broad[0]
                        return {
                            "osm_id": match.get("osm_id"),
                            "osm_type": match.get("osm_type"),
                            "display_name": match.get("display_name"),
                            "class": match.get("class"),
                            "type": match.get("type"),
                            "geojson": match.get("geojson"),
                            "lat": match.get("lat"),
                            "lon": match.get("lon"),
                            "boundingbox": match.get("boundingbox")
                        }
        elif response.status_code == 403:
            print("Received HTTP 403 (Forbidden). Nominatim might have rate limited us.")
            return "rate_limited"
    except Exception as e:
        print(f"Network error querying {locality_name}: {e}")
        return "error"
    
    return None

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    localities = load_localities()
    if not localities:
        return

    print(f"Loaded {len(localities)} localities from 99acres dataset.")
    existing_results = load_existing_results()
    print(f"Found {len(existing_results)} already fetched boundaries.")

    # open temp file in append mode
    with open(TEMP_OUTPUT_FILE, "a", encoding="utf-8") as temp_file:
        count = 0
        for idx, loc in enumerate(localities):
            loc_id = loc.get("id")
            name = loc.get("localityName")
            
            if loc_id in existing_results:
                continue

            print(f"[{idx+1}/{len(localities)}] Querying boundary for: {name} ({loc_id})...")
            result = fetch_boundary(name)
            
            if result == "rate_limited":
                print("Stopping due to rate limiting. Please wait and resume later.")
                break
            elif result == "error":
                # Skip and continue, or sleep and retry
                time.sleep(2)
                continue

            record = {
                "id": loc_id,
                "localityName": name,
                "found": result is not None,
                "boundary": result
            }
            
            temp_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            temp_file.flush()
            
            # Respect rate limit of 1 req/sec
            time.sleep(1.2)
            count += 1
            
            if count >= 5:
                print("Test run complete (processed 5 items).")
                break
            
    # Compile temp JSONL into a single JSON file
    if TEMP_OUTPUT_FILE.exists():
        compiled = []
        with open(TEMP_OUTPUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        compiled.append(json.loads(line))
                    except Exception:
                        pass
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(compiled, f, indent=2, ensure_ascii=False)
        print(f"Successfully compiled {len(compiled)} results into {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
