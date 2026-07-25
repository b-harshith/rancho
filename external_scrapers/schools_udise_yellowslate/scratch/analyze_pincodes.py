import json
import os
import sqlite3
import re
from pathlib import Path

# Paths
YELLOWSLATE_DIR = Path("/Users/malleswararao/Desktop/school extraction/data/output/yellowslate")
EZYSCHOOLING_DIR = Path("/Users/malleswararao/Desktop/School Data/data")
UDISE_DB = Path("/Users/malleswararao/Desktop/school extraction/data/runtime/udise_data.sqlite3")

def clean_pincode(pin):
    if not pin:
        return None
    pin_str = str(pin).strip()
    match = re.search(r"\b[1-9][0-9]{5}\b", pin_str)
    return match.group(0) if match else None

def get_yellowslate_pincodes():
    # Maps file suffix/name to canonical city
    # Files are: yellowslate_schools_with_locations_{city}.json
    ys_pincodes = {} # city -> set of pins
    
    # Let's inspect the files in yellowslate directory
    for f in YELLOWSLATE_DIR.glob("yellowslate_schools_with_locations_*.json"):
        # extract city name
        match = re.search(r"yellowslate_schools_with_locations_([a-z0-9_\-]+)\.json", f.name)
        if match:
            city = match.group(1)
            # normalize city name if needed
            if city == "delhi_ncr":
                canonical_city = "delhi_ncr"
            else:
                canonical_city = city
            
            with open(f, "r", encoding="utf-8") as file:
                try:
                    data = json.load(file)
                except Exception as e:
                    print(f"Error loading {f.name}: {e}")
                    continue
                
                pins = set()
                for school in data:
                    pin = (school.get("school_location") or {}).get("pincode") or school.get("pincode")
                    cleaned = clean_pincode(pin)
                    if cleaned:
                        pins.add(cleaned)
                
                ys_pincodes.setdefault(canonical_city, set()).update(pins)
                
    # Check the base file yellowslate_schools_with_locations.json (might be Bengaluru/Bangalore)
    base_file = YELLOWSLATE_DIR / "yellowslate_schools_with_locations.json"
    if base_file.exists():
        with open(base_file, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
                pins = set()
                for school in data:
                    # Let's check if this is bangalore
                    # We can look at the school_url or location
                    pin = (school.get("school_location") or {}).get("pincode") or school.get("pincode")
                    cleaned = clean_pincode(pin)
                    if cleaned:
                        pins.add(cleaned)
                # It's likely bangalore/bengaluru
                ys_pincodes.setdefault("bengaluru", set()).update(pins)
            except Exception as e:
                print(f"Error loading base yellowslate file: {e}")
                
    return ys_pincodes

def get_ezyschooling_pincodes():
    ezy_pincodes = {} # city -> set of pins
    
    # Files are: ezyschooling_raw_{city}.json
    for f in EZYSCHOOLING_DIR.glob("ezyschooling_raw_*.json"):
        match = re.search(r"ezyschooling_raw_([a-z0-9_\-]+)\.json", f.name)
        if match:
            city = match.group(1)
            
            # Map Ezyschooling city names to our canonical cities
            if city in ["delhi", "faridabad", "ghaziabad", "greater-noida", "greater-noida-west", "gurugram", "noida"]:
                canonical_city = "delhi_ncr"
            elif city == "bangalore":
                canonical_city = "bengaluru"
            else:
                canonical_city = city
                
            with open(f, "r", encoding="utf-8") as file:
                try:
                    data = json.load(file)
                except Exception as e:
                    print(f"Error loading {f.name}: {e}")
                    continue
                
                pins = set()
                for school in data:
                    pin = school.get("zipcode") or (school.get("school_location") or {}).get("pincode")
                    cleaned = clean_pincode(pin)
                    if cleaned:
                        pins.add(cleaned)
                
                ezy_pincodes.setdefault(canonical_city, set()).update(pins)
                
    return ezy_pincodes

def get_udise_completed_pincodes():
    conn = sqlite3.connect(UDISE_DB)
    cursor = conn.cursor()
    
    # Get completed pincodes
    cursor.execute("SELECT DISTINCT pincode FROM pin_tasks WHERE status = 'completed'")
    completed_pins = {r[0] for r in cursor.fetchall() if r[0]}
    
    # Let's also check all pincodes that are present in the schools table, just in case
    cursor.execute("SELECT DISTINCT pincode FROM schools WHERE pincode IS NOT NULL")
    school_pins = {r[0] for r in cursor.fetchall() if r[0]}
    
    conn.close()
    
    # Return union of both to be safe and thorough
    return completed_pins.union(school_pins)

def main():
    ys_pins = get_yellowslate_pincodes()
    ezy_pins = get_ezyschooling_pincodes()
    udise_pins = get_udise_completed_pincodes()
    
    print(f"UDISE database has {len(udise_pins)} unique completed/scraped pincodes.")
    
    # Combine YellowSlate and Ezyschooling pincodes
    all_cities = set(ys_pins.keys()).union(set(ezy_pins.keys()))
    
    results = {}
    total_missing = 0
    missing_by_city = {}
    
    for city in sorted(all_cities):
        ys_set = ys_pins.get(city, set())
        ezy_set = ezy_pins.get(city, set())
        combined_set = ys_set.union(ezy_set)
        
        missing = sorted(combined_set - udise_pins)
        results[city] = {
            "yellowslate_pincodes_count": len(ys_set),
            "ezyschooling_pincodes_count": len(ezy_set),
            "combined_unique_pincodes_count": len(combined_set),
            "missing_pincodes_count": len(missing),
            "missing_pincodes": missing
        }
        total_missing += len(missing)
        if missing:
            missing_by_city[city] = missing
            
    print("\n--- Summary by City ---")
    for city, stats in results.items():
        print(f"City: {city}")
        print(f"  YellowSlate Pincodes: {stats['yellowslate_pincodes_count']}")
        print(f"  Ezyschooling Pincodes: {stats['ezyschooling_pincodes_count']}")
        print(f"  Combined Unique: {stats['combined_unique_pincodes_count']}")
        print(f"  Missing from UDISE: {stats['missing_pincodes_count']}")
        if stats['missing_pincodes_count'] > 0:
            print(f"  Missing List: {stats['missing_pincodes']}")
        print("-" * 30)
        
    print(f"\nTotal unique missing pincodes across all cities: {total_missing}")
    
    # Also dump to a JSON file for the user
    output_path = Path("/Users/malleswararao/Desktop/school extraction/scratch/missing_pincodes_report.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total_missing_pincodes": total_missing,
                "cities_with_missing_pincodes": list(missing_by_city.keys())
            },
            "cities": results
        }, f, indent=2)
    print(f"Report saved to {output_path}")

if __name__ == "__main__":
    main()
