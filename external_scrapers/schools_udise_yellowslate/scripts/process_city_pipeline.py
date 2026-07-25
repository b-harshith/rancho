import json
import os
import sys
import time
import random
import argparse
import subprocess

# Add curl_cffi for Ezyschooling scraping
try:
    from curl_cffi import requests
except ImportError:
    requests = None

EZY_DIR = "/Users/malleswararao/Desktop/School Data/data"

def scrape_ezyschooling(city_slug):
    if requests is None:
        print("Error: curl_cffi is not installed. Cannot perform live Ezyschooling scraping.")
        sys.exit(1)
        
    city_clean = city_slug.strip().capitalize()
    raw_json_path = os.path.join(EZY_DIR, f"ezyschooling_raw_{city_slug}.json")
    
    print(f"\n--- STEP 1: Scraping Ezyschooling API for {city_clean} ---")
    url = "https://api.main.ezyschooling.com/api/v1/schools/document/"
    limit = 100
    offset = 0
    total_count = 1
    raw_schools = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://ezyschooling.com",
        "Referer": "https://ezyschooling.com/"
    }
    
    while offset < total_count:
        exclude_cities = "boarding-schools,online-schools,delhi"
        params = {
            "is_active": "true",
            "is_verified": "true",
            "limit": str(limit),
            "offset": str(offset),
            "ordering": "-fees",
            "school_city": city_slug,
            "school_city__exclude": exclude_cities,
            "session": "2026-2027"
        }
        
        print(f"Fetching offset {offset} (Total count: {total_count})...")
        try:
            r = requests.get(url, params=params, headers=headers, impersonate="chrome", timeout=20)
            if r.status_code == 200:
                data = r.json()
                total_count = data.get("count", total_count)
                results = data.get("results", [])
                raw_schools.extend(results)
                print(f" -> Fetched {len(results)} schools. Total in list: {len(raw_schools)}.")
                if not results:
                    break
            else:
                print(f" [Error] API returned status {r.status_code}. Aborting API loop.")
                break
        except Exception as e:
            print(f" [Error] Request failed at offset {offset}: {e}")
            break
            
        offset += limit
        time.sleep(random.uniform(1.0, 2.0))
        
    if raw_schools:
        os.makedirs(EZY_DIR, exist_ok=True)
        with open(raw_json_path, 'w', encoding='utf-8') as f:
            json.dump(raw_schools, f, indent=2)
        print(f"Saved {len(raw_schools)} raw Ezyschooling schools to {raw_json_path}")
    else:
        print("No school data fetched from Ezyschooling.")

def run_command(cmd):
    print(f"\nRunning command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"Error: Command failed with code {result.returncode}")
        sys.exit(result.returncode)

def main():
    parser = argparse.ArgumentParser(description="Run end-to-end schools processing pipeline for a city.")
    parser.add_argument("--city", required=True, help="City slug (e.g. mumbai, hyderabad, chennai, kolkata, pune, ahmedabad)")
    args = parser.parse_args()
    
    city = args.city.lower().strip()
    
    # 1. Scrape Ezyschooling API
    scrape_ezyschooling(city)
    
    # 2. Scrape Yellowslate Browser
    ys_browser_cmd = ["python3", "scripts/scrape_yellowslate_browser.py", "--city", city]
    run_command(ys_browser_cmd)
    
    # 3. Scrape Yellowslate Locations
    ys_loc_cmd = [
        "python3", "scripts/scrape_yellowslate_locations.py",
        "--input", f"data/output/yellowslate/yellowslate_browser_fee_schools_{city}.json",
        "--output", f"data/output/yellowslate/yellowslate_schools_with_locations_{city}.json"
    ]
    run_command(ys_loc_cmd)
    
    # 4. Merge and Match to UDISE
    merge_cmd = [
        "python3", "scripts/merge_and_match_to_udise.py",
        "--ys-path", f"data/output/yellowslate/yellowslate_schools_with_locations_{city}.json",
        "--output", f"data/output/schools_merged_matched_udise_{city}.json"
    ]
    run_command(merge_cmd)
    
    # 5. Predict Enrollment and Google Geocode
    compile_cmd = [
        "python3", "scripts/predict_enrollment_and_compile.py",
        "--city", city
    ]
    run_command(compile_cmd)
    
    print(f"\n--- Pipeline completed successfully for city: {city} ---")

if __name__ == "__main__":
    main()
