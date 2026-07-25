#!/usr/bin/env python3
import json
import math
import re
from collections import Counter

# File paths
foursquare_file = "bangalore_residential_listings.json"
app_societies_file = "../BangaloreRancho/web_platform_vercel_exact_latest/src/static/data/societies.json"
master_societies_file = "../BangaloreRancho/web_platform_vercel_exact_latest/99acres_bangalore_societies.json"

output_unmatched_app = "unmatched_in_app_societies.json"
output_unmatched_master = "unmatched_in_master_societies.json"

def haversine_distance(lat1, lon1, lat2, lon2):
    # Radius of the Earth in meters
    R = 6371000.0
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    
    return R * c

def normalize_name(name):
    if not name:
        return ""
    name = name.lower()
    # Replace punctuation and special characters with space
    name = re.sub(r'[^\w\s]', ' ', name)
    # Remove common filler words
    fillers = {
        "apartment", "apartments", "apts", "apt", "residency", "residencies", "villa", "villas", 
        "enclave", "enclaves", "society", "societies", "layout", "layouts", "township", "townships", 
        "the", "and", "homes", "home", "building", "buildings", "project", "projects", "block", "blocks",
        "tower", "towers", "private", "ltd", "limited", "pvt"
    }
    words = [w for w in name.split() if w not in fillers]
    return "".join(sorted(words))

def get_name_tokens(name):
    if not name:
        return set()
    name = name.lower()
    name = re.sub(r'[^\w\s]', ' ', name)
    fillers = {
        "apartment", "apartments", "apts", "apt", "residency", "residencies", "villa", "villas", 
        "enclave", "enclaves", "society", "societies", "layout", "layouts", "township", "townships", 
        "the", "and", "homes", "home", "building", "buildings", "project", "projects", "block", "blocks",
        "tower", "towers", "private", "ltd", "limited", "pvt"
    }
    return set(w for w in name.split() if w not in fillers and len(w) > 1)

def find_match(fsq_item, reference_list, lat_key="lat", lon_key="lon"):
    fsq_lat = fsq_item.get("latitude")
    fsq_lon = fsq_item.get("longitude")
    fsq_name = fsq_item.get("name", "")
    fsq_norm = normalize_name(fsq_name)
    fsq_tokens = get_name_tokens(fsq_name)
    
    if fsq_lat is None or fsq_lon is None:
        return None
        
    best_match = None
    best_match_score = 0 # Higher is better
    best_distance = float('inf')
    
    for ref_item in reference_list:
        ref_lat = ref_item.get(lat_key)
        ref_lon = ref_item.get(lon_key)
        ref_name = ref_item.get("name", "")
        ref_norm = normalize_name(ref_name)
        ref_tokens = get_name_tokens(ref_name)
        
        if ref_lat is None or ref_lon is None:
            continue
            
        distance = haversine_distance(fsq_lat, fsq_lon, ref_lat, ref_lon)
        
        # 1. Exact Name + Distance check (up to 1500m geocoding error)
        if fsq_norm and ref_norm and fsq_norm == ref_norm and distance < 1500:
            score = 100
        # 2. Strong overlap + Close distance (under 200m)
        elif distance < 200:
            if fsq_norm and ref_norm and (fsq_norm in ref_norm or ref_norm in fsq_norm):
                score = 90
            elif fsq_tokens and ref_tokens and len(fsq_tokens & ref_tokens) >= 1:
                score = 80
            else:
                score = 50 # Location match but names are different (e.g. different phase or building name)
        # 3. Identical location (under 30m)
        elif distance < 30:
            score = 70
        else:
            score = 0
            
        if score > best_match_score:
            best_match_score = score
            best_match = ref_item
            best_distance = distance
        elif score == best_match_score and score > 0:
            # Tie breaker: choose the closer one
            if distance < best_distance:
                best_match = ref_item
                best_distance = distance
                
    if best_match_score >= 50:
        return {
            "ref_name": best_match.get("name"),
            "ref_lat": best_match.get(lat_key),
            "ref_lon": best_match.get(lon_key),
            "distance_m": best_distance,
            "match_type": "Exact Name" if best_match_score == 100 else ("Name & Location" if best_match_score >= 80 else "Location Only")
        }
        
    return None

def main():
    # Load Foursquare extracted dataset
    print(f"Loading Foursquare listings from '{foursquare_file}'...")
    with open(foursquare_file, "r") as f:
        fsq_data = json.load(f)
    print(f"Loaded {len(fsq_data)} Foursquare listings.")
    
    # Load App Societies
    print(f"Loading App Societies from '{app_societies_file}'...")
    with open(app_societies_file, "r") as f:
        app_data = json.load(f)
    print(f"Loaded {len(app_data)} App Societies.")
    
    # Load Master Societies
    print(f"Loading Master Societies from '{master_societies_file}'...")
    with open(master_societies_file, "r") as f:
        master_raw = json.load(f)
        # Map location coordinates
        master_data = []
        for x in master_raw:
            loc = x.get("location", {})
            master_data.append({
                "name": x.get("name"),
                "lat": loc.get("latitude"),
                "lon": loc.get("longitude")
            })
    print(f"Loaded {len(master_data)} Master Societies.")
    
    # Matching against App Societies
    print("\nMatching against App Societies...")
    unmatched_in_app = []
    matched_app_count = 0
    
    for fsq_item in fsq_data:
        match = find_match(fsq_item, app_data, "lat", "lon")
        if match:
            matched_app_count += 1
        else:
            unmatched_in_app.append(fsq_item)
            
    print(f"Matched in App: {matched_app_count} ({matched_app_count / len(fsq_data) * 100:.2f}%)")
    print(f"Unmatched in App: {len(unmatched_in_app)} ({len(unmatched_in_app) / len(fsq_data) * 100:.2f}%)")
    
    # Matching against Master Societies
    print("\nMatching against Master 99acres Societies...")
    unmatched_in_master = []
    matched_master_count = 0
    
    for fsq_item in fsq_data:
        match = find_match(fsq_item, master_data, "lat", "lon")
        if match:
            matched_master_count += 1
        else:
            unmatched_in_master.append(fsq_item)
            
    print(f"Matched in Master: {matched_master_count} ({matched_master_count / len(fsq_data) * 100:.2f}%)")
    print(f"Unmatched in Master: {len(unmatched_in_master)} ({len(unmatched_in_master) / len(fsq_data) * 100:.2f}%)")
    
    # Save unmatched listings
    with open(output_unmatched_app, "w") as f:
        json.dump(unmatched_in_app, f, indent=4)
    with open(output_unmatched_master, "w") as f:
        json.dump(unmatched_in_master, f, indent=4)
        
    print(f"\nSaved unmatched app societies to '{output_unmatched_app}'")
    print(f"Saved unmatched master societies to '{output_unmatched_master}'")
    
    # Display 15 interesting new unmatched listings (which are not in the App list)
    # Highlight those that match major developers or have high quality names
    print("\n--- SAMPLE NEW RESIDENTIAL SOCIETIES NOT IN APP DATABASE (First 15) ---")
    count = 0
    for item in unmatched_in_app:
        name = item.get("name")
        matched_by = item.get("extraction_matched_by", "")
        # Filter for high-quality developer names or explicit apartments
        if any(term in name.lower() for term in ["prestige", "sobha", "brigade", "purva", "mantri", "salarpuria", "apartment", "residency"]):
            count += 1
            print(f"{count}. {name} | Location: {item.get('locality')} | Category: {item.get('fsq_category_labels')} | Extract Rule: {matched_by}")
            if count >= 15:
                break
                
    # Display 15 interesting new unmatched listings (not in Master list either!)
    print("\n--- SAMPLE NEW RESIDENTIAL SOCIETIES NOT IN MASTER 99ACRES LIST (First 15) ---")
    count = 0
    for item in unmatched_in_master:
        name = item.get("name")
        matched_by = item.get("extraction_matched_by", "")
        if any(term in name.lower() for term in ["prestige", "sobha", "brigade", "purva", "mantri", "salarpuria", "apartment", "residency"]):
            count += 1
            print(f"{count}. {name} | Location: {item.get('locality')} | Category: {item.get('fsq_category_labels')} | Extract Rule: {matched_by}")
            if count >= 15:
                break

if __name__ == "__main__":
    main()
