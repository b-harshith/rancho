import os
import json
import time
import re
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'output')

MASTER_PATH = os.path.join(DATA_DIR, 'yellowslate_schools_master.json')
CACHE_PATH = os.path.join(DATA_DIR, 'nominatim_geocode_cache.json')

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "yellowslate-school-geocoder/1.0 (contact: local-user)"

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_json(data, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def geocode_request(query):
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": "1",
        "countrycodes": "in"
    }
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            results = json.loads(resp.read().decode("utf-8"))
            if results:
                top = results[0]
                return {
                    "status": "ok",
                    "lat": float(top["lat"]),
                    "lon": float(top["lon"]),
                    "display_name": top.get("display_name")
                }
            return {"status": "not_found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def clean_name(name):
    # Strip bracket details or common additions
    name = re.sub(r'\(.*?\)', '', name)
    return name.strip()

def run_geocoding(max_requests=50):
    print("Loading master database and cache...")
    master_data = load_json(MASTER_PATH)
    if not master_data:
        print("Error: Master database is empty or not found.")
        return
        
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, 'r') as f:
            cache = json.load(f)
            
    print(f"Loaded {len(master_data)} schools. Geocoding cache contains {len(cache)} entries.")
    
    requests_made = 0
    updated_count = 0
    
    for idx, entry in enumerate(master_data):
        # Check if already geocoded in master (non-null)
        if entry.get("latitude") is not None and entry.get("longitude") is not None:
            continue
            
        school_name = clean_name(entry.get("school_name", ""))
        area = entry.get("area", "")
        pincode = entry.get("udise_pincode") or ""
        
        # Build queries in order of specificity
        queries = []
        if pincode:
            queries.append(f"{school_name}, {pincode}, Bengaluru, India")
        if area:
            queries.append(f"{school_name}, {area}, Bengaluru, India")
        queries.append(f"{school_name}, Bengaluru, India")
        if area:
            queries.append(f"{area}, Bengaluru, India")
            
        lat, lon = None, None
        
        # Try queries
        for q in queries:
            if q in cache:
                cached = cache[q]
                if cached.get("status") == "ok":
                    lat, lon = cached["lat"], cached["lon"]
                    break
                elif cached.get("status") in ("not_found", "error"):
                    # Query was tried and failed, try next fallback query
                    continue
            else:
                # Check if we can make a new request
                if requests_made < max_requests:
                    print(f"[{idx+1}/{len(master_data)}] Querying Nominatim for: {q}")
                    result = geocode_request(q)
                    cache[q] = result
                    requests_made += 1
                    
                    # Rate limit compliance: OSM requires max 1 req/sec
                    time.sleep(1.2)
                    
                    if result.get("status") == "ok":
                        lat, lon = result["lat"], result["lon"]
                        break
                else:
                    # Request limit reached, skip querying but check remaining cached fallback queries
                    continue
                
        # Update entry if coordinates found
        if lat is not None and lon is not None:
            entry["latitude"] = lat
            entry["longitude"] = lon
            updated_count += 1
            
        # Save cache and master data progressively
        if requests_made > 0 and requests_made % 10 == 0:
            save_json(cache, CACHE_PATH)
            save_json(master_data, MASTER_PATH)

            
    # Save final cache and master data
    save_json(cache, CACHE_PATH)
    save_json(master_data, MASTER_PATH)
    
    print(f"\nGeocoding run complete.")
    print(f"- Nominatim requests made: {requests_made}")
    print(f"- Schools updated with coordinates in master JSON: {updated_count}")
    print(f"- Total schools with coordinates now: {sum(1 for e in master_data if e.get('latitude') is not None)}")

if __name__ == "__main__":
    import sys
    max_req = 50
    if len(sys.argv) > 1:
        try:
            max_req = int(sys.argv[1])
        except ValueError:
            pass
    run_geocoding(max_req)
