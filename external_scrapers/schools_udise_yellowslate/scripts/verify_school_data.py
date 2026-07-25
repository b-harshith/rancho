import json
import os
import re
import math
from pathlib import Path

DATA_DIR = Path("/Users/malleswararao/Desktop/school extraction/data/output")

# Bounding boxes for each city (approximate to catch major coordinate placement errors)
CITY_BOUNDS = {
    "hyderabad": {"min_lat": 17.15, "max_lat": 17.65, "min_lon": 78.15, "max_lon": 78.70, "pin_prefixes": ["500", "501", "502"]},
    "bengaluru": {"min_lat": 12.75, "max_lat": 13.25, "min_lon": 77.35, "max_lon": 77.85, "pin_prefixes": ["560", "561", "562"]},
    "chennai": {"min_lat": 12.80, "max_lat": 13.30, "min_lon": 80.10, "max_lon": 80.35, "pin_prefixes": ["600", "601", "602", "603"]},
    "delhi_ncr": {"min_lat": 28.20, "max_lat": 28.95, "min_lon": 76.75, "max_lon": 77.65, "pin_prefixes": ["110", "121", "122", "201", "203"]},
    "kolkata": {"min_lat": 22.35, "max_lat": 22.80, "min_lon": 88.15, "max_lon": 88.60, "pin_prefixes": ["700", "711", "712", "743"]},
    "mumbai": {"min_lat": 18.85, "max_lat": 19.45, "min_lon": 72.70, "max_lon": 73.15, "pin_prefixes": ["400", "401", "410", "421"]},
    "pune": {"min_lat": 18.35, "max_lat": 18.75, "min_lon": 73.65, "max_lon": 74.05, "pin_prefixes": ["411", "412"]},
    "ahmedabad": {"min_lat": 22.85, "max_lat": 23.20, "min_lon": 72.40, "max_lon": 72.75, "pin_prefixes": ["380", "382"]}
}

def haversine_distance(lat1, lon1, lat2, lon2):
    # Returns distance in meters
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
    except (TypeError, ValueError):
        return float('inf')
    R = 6371000  # radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def extract_pincode_from_text(text):
    if not text:
        return None
    match = re.search(r"\b[1-9][0-9]{5}\b", str(text))
    return match.group(0) if match else None

def get_correct_city_by_coords(lat, lon):
    if not lat or not lon:
        return None
    try:
        lat, lon = float(lat), float(lon)
    except ValueError:
        return None
    for city, bounds in CITY_BOUNDS.items():
        if bounds["min_lat"] <= lat <= bounds["max_lat"] and bounds["min_lon"] <= lon <= bounds["max_lon"]:
            return city
    return None

def verify_file(file_path, city_name):
    print(f"\nVerifying {file_path.name} (assigned city: {city_name})...")
    with open(file_path, "r", encoding="utf-8") as f:
        schools = json.load(f)
        
    cleaned_schools = []
    pincode_mismatches = 0
    wrong_city_assignments = 0
    pincodes_fixed = 0
    duplicate_count = 0
    
    # Store references for deduplication checks
    seen_urls = {}
    seen_coords = []
    
    # Helper to find nearest valid pincode in this file's schools
    valid_pincodes_with_coords = []
    for s in schools:
        lat, lon = s.get("lat"), s.get("lon")
        pin = s.get("pincode")
        if lat and lon and pin and pin != "NA" and re.match(r"^\d{6}$", str(pin)):
            valid_pincodes_with_coords.append((float(lat), float(lon), str(pin)))
            
    def find_closest_pincode(lat, lon):
        if not lat or not lon or not valid_pincodes_with_coords:
            return "NA"
        closest_pin = "NA"
        min_dist = float('inf')
        for v_lat, v_lon, v_pin in valid_pincodes_with_coords:
            dist = haversine_distance(lat, lon, v_lat, v_lon)
            if dist < min_dist:
                min_dist = dist
                closest_pin = v_pin
        return closest_pin

    for idx, s in enumerate(schools):
        # 1. Deduplicate by URL
        url = s.get("url")
        if url and url != "NA":
            if url in seen_urls:
                duplicate_count += 1
                # Skip duplicate
                continue
            seen_urls[url] = idx

        lat, lon = s.get("lat"), s.get("lon")
        
        # 2. Deduplicate by exact/very close coordinates
        if lat and lon:
            is_dup_coord = False
            for prev_lat, prev_lon, prev_name in seen_coords:
                if haversine_distance(lat, lon, prev_lat, prev_lon) < 15:  # within 15 meters
                    # Check if names are similar
                    if s.get("name").lower()[:10] == prev_name.lower()[:10]:
                        duplicate_count += 1
                        is_dup_coord = True
                        break
            if is_dup_coord:
                continue
            seen_coords.append((lat, lon, s.get("name")))

        # 3. Check for correct pincode format / extraction from address
        pincode = str(s.get("pincode") or "").strip()
        if not re.match(r"^\d{6}$", pincode):
            extracted = extract_pincode_from_text(s.get("address"))
            if extracted:
                s["pincode"] = extracted
                pincode = extracted
                pincodes_fixed += 1
            else:
                # Try to find closest pincode based on coords
                if lat and lon:
                    closest = find_closest_pincode(lat, lon)
                    if closest != "NA":
                        s["pincode"] = closest
                        pincode = closest
                        pincodes_fixed += 1

        # 4. Check for cross-city pincode anomalies using prefixes and coordinates
        correct_city = get_correct_city_by_coords(lat, lon)
        if correct_city and correct_city != city_name:
            print(f"  [WRONG CITY] School '{s.get('name')}' is in {correct_city.upper()} based on coords ({lat}, {lon}), but in {city_name.upper()} file.")
            wrong_city_assignments += 1
            s["zone"] = correct_city.capitalize()
            
        # Check if pincode prefix belongs to this city
        if pincode != "NA" and correct_city:
            bounds = CITY_BOUNDS.get(correct_city)
            if bounds:
                prefix_match = any(pincode.startswith(pref) for pref in bounds["pin_prefixes"])
                if not prefix_match:
                    pincode_mismatches += 1
                    # Swap with the closest valid pincode for this location
                    new_pin = find_closest_pincode(lat, lon)
                    if new_pin != "NA":
                        print(f"  [PINCORRECTED] '{s.get('name')}': {pincode} -> {new_pin}")
                        s["pincode"] = new_pin
                        pincodes_fixed += 1

        cleaned_schools.append(s)
        
    print(f"  Total Schools Analyzed: {len(schools)}")
    print(f"  Duplicates Removed: {duplicate_count}")
    print(f"  Wrong City Assignments Identified: {wrong_city_assignments}")
    print(f"  Pincode Discrepancies Corrected: {pincodes_fixed}")
    print(f"  Remaining Schools: {len(cleaned_schools)}")
    
    # Save back verified file
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_schools, f, ensure_ascii=False, indent=2)
        
    return {
        "analyzed": len(schools),
        "duplicates": duplicate_count,
        "wrong_city": wrong_city_assignments,
        "pincodes_fixed": pincodes_fixed,
        "remaining": len(cleaned_schools)
    }

def main():
    report = {}
    for f in DATA_DIR.glob("schools_*_final.json"):
        match = re.search(r"schools_([a-z0-9_\-]+)_final\.json", f.name)
        if match:
            city = match.group(1)
            report[city] = verify_file(f, city)
            
    print("\n================ VERIFICATION SUMMARY ================")
    for city, stats in report.items():
        print(f"City: {city.upper()}")
        print(f"  Processed: {stats['analyzed']}")
        print(f"  Duplicates Removed: {stats['duplicates']}")
        print(f"  City Corrections: {stats['wrong_city']}")
        print(f"  Pincode Corrections: {stats['pincodes_fixed']}")
        print(f"  Final Valid: {stats['remaining']}")
        print("-" * 30)

if __name__ == "__main__":
    main()
