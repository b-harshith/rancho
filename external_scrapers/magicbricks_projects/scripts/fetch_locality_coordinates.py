#!/usr/bin/env python3
import json
import time
import urllib.parse
from pathlib import Path
import requests

# Config
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "data" / "raw" / "99acres_bangalore_localities.json"
OUTPUT_DIR = BASE_DIR / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / "99acres_locality_coordinates.json"
TEMP_FILE = OUTPUT_DIR / "99acres_locality_coordinates.jsonl"

ARCGIS_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
TEST_LIMIT = None  # Set to an integer to limit run size during testing

def load_localities():
    if not INPUT_FILE.exists():
        print(f"Error: Input file {INPUT_FILE} not found.")
        return []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_existing():
    existing = {}
    if TEMP_FILE.exists():
        with open(TEMP_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line)
                        existing[record["id"]] = record
                    except json.JSONDecodeError:
                        continue
    elif OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                records = json.load(f)
                for record in records:
                    existing[record["id"]] = record
        except Exception:
            pass
    return existing

def fetch_coordinates(name):
    query = f"{name}, Bangalore, India"
    params = {
        "SingleLine": query,
        "f": "json",
        "maxLocations": 1
    }
    try:
        resp = requests.get(ARCGIS_URL, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                loc = candidates[0]["location"]
                return {
                    "lon": loc["x"],
                    "lat": loc["y"],
                    "display_name": candidates[0].get("address"),
                }
            else:
                # Retry with a broader query
                query_broad = f"{name}, Bangalore"
                resp_broad = requests.get(ARCGIS_URL, params={"SingleLine": query_broad, "f": "json", "maxLocations": 1}, timeout=10)
                if resp_broad.status_code == 200:
                    data_broad = resp_broad.json()
                    candidates_broad = data_broad.get("candidates", [])
                    if candidates_broad:
                        loc = candidates_broad[0]["location"]
                        return {
                            "lon": loc["x"],
                            "lat": loc["y"],
                            "display_name": candidates_broad[0].get("address"),
                        }
        else:
            print(f"Non-200 response from ArcGIS for {name}: HTTP {resp.status_code}")
    except Exception as e:
        print(f"Network error querying {name}: {e}")
    return None

def compile_final_json():
    if TEMP_FILE.exists():
        compiled = []
        with open(TEMP_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        compiled.append(json.loads(line))
                    except Exception:
                        pass
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(compiled, f, indent=2, ensure_ascii=False)
        print(f"Compiled {len(compiled)} results to {OUTPUT_FILE}")

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    localities = load_localities()
    if not localities:
        return

    print(f"Loaded {len(localities)} localities.")
    existing = load_existing()
    print(f"Found {len(existing)} already fetched coordinates.")

    run_limit = TEST_LIMIT
    count = 0

    with open(TEMP_FILE, "a", encoding="utf-8") as temp:
        for idx, loc in enumerate(localities):
            loc_id = loc.get("id")
            name = loc.get("localityName")
            
            if loc_id in existing:
                continue

            print(f"[{idx+1}/{len(localities)}] Fetching coordinates for: {name}...")
            res = fetch_coordinates(name)
            
            record = {
                "id": loc_id,
                "localityName": name,
                "found": res is not None,
                "lat": res["lat"] if res else None,
                "lon": res["lon"] if res else None,
                "details": res
            }
            
            temp.write(json.dumps(record, ensure_ascii=False) + "\n")
            temp.flush()
            
            time.sleep(0.4)  # respect fair-use limits
            count += 1
            
            if run_limit and count >= run_limit:
                print(f"Reached test limit of {run_limit} items.")
                break

    compile_final_json()

if __name__ == "__main__":
    main()
