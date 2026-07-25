import json
import math
from collections import defaultdict

def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return float('inf')
    radius = 6371  # km
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))

def main():
    print("Loading datasets...")
    # Load the predicted fees data (base)
    with open("data/output/schools_analysis_predicted_fees.json", "r") as f:
        data = json.load(f)
        
    # Load the foursquare match data
    with open("data/output/schools_analysis_with_foursquare.json", "r") as f:
        fsq_data = json.load(f)
        
    fsq_map = {}
    for s in fsq_data.get("schools", []):
        fsq_map[s["udise_code"]] = s.get("foursquare", {})
        
    # Step 1: Calculate Pincode Centroids
    pincode_lat_sum = defaultdict(float)
    pincode_lon_sum = defaultdict(float)
    pincode_count = defaultdict(int)
    
    for s in data["schools"]:
        udise = s.get("udise_code")
        meta = s.get("metadata", {})
        loc = meta.get("location", {})
        pincode = meta.get("reported_pincode") or meta.get("searched_pincode")
        
        if not pincode:
            continue
            
        fsq = fsq_map.get(udise, {})
        status = fsq.get("match_status")
        
        # Prefer Foursquare coordinates for centroid
        lat = None
        lon = None
        if status in ("confident", "probable"):
            place = fsq.get("place", {})
            lat = place.get("latitude")
            lon = place.get("longitude")
        
        # Fallback to original UDISE coordinates
        if lat is None or lon is None:
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            
        if lat is not None and lon is not None:
            pincode_lat_sum[str(pincode)] += float(lat)
            pincode_lon_sum[str(pincode)] += float(lon)
            pincode_count[str(pincode)] += 1
            
    pincode_centroids = {}
    for pin, count in pincode_count.items():
        pincode_centroids[pin] = (
            pincode_lat_sum[pin] / count,
            pincode_lon_sum[pin] / count
        )
        
    # Step 2: Coordinate Correction & Filtering
    BANGALORE_CENTER = (12.9716, 77.5946)
    DISTANCE_THRESHOLD = 40.0 # km
    
    cleaned_schools = []
    
    stats = {
        "total": len(data["schools"]),
        "foursquare_corrected": 0,
        "pincode_centroid_fallback": 0,
        "original_coords_kept": 0,
        "dropped_too_far": 0,
        "dropped_no_coords": 0,
        "kept_in_bangalore": 0
    }
    
    for s in data["schools"]:
        udise = s.get("udise_code")
        meta = s.get("metadata", {})
        if "location" not in meta:
            meta["location"] = {}
        
        pincode = str(meta.get("reported_pincode") or meta.get("searched_pincode") or "")
        fsq = fsq_map.get(udise, {})
        status = fsq.get("match_status")
        
        final_lat = None
        final_lon = None
        correction_method = "none"
        
        # 1. Try Foursquare
        if status in ("confident", "probable"):
            place = fsq.get("place", {})
            final_lat = place.get("latitude")
            final_lon = place.get("longitude")
            if final_lat is not None:
                correction_method = "foursquare"
                
        # 2. Try Pincode Centroid
        if final_lat is None and pincode in pincode_centroids:
            final_lat, final_lon = pincode_centroids[pincode]
            correction_method = "pincode_centroid"
            
        # 3. Try original
        if final_lat is None:
            final_lat = meta["location"].get("latitude")
            final_lon = meta["location"].get("longitude")
            if final_lat is not None:
                correction_method = "original"
                
        # Update metadata
        if final_lat is not None and final_lon is not None:
            meta["location"]["latitude"] = float(final_lat)
            meta["location"]["longitude"] = float(final_lon)
            meta["location"]["coordinate_source"] = correction_method
            
            # Check distance
            dist = haversine(BANGALORE_CENTER[0], BANGALORE_CENTER[1], final_lat, final_lon)
            
            if dist <= DISTANCE_THRESHOLD:
                # Add distance attribute for reference
                meta["location"]["distance_from_center_km"] = round(dist, 2)
                cleaned_schools.append(s)
                stats["kept_in_bangalore"] += 1
                
                if correction_method == "foursquare": stats["foursquare_corrected"] += 1
                elif correction_method == "pincode_centroid": stats["pincode_centroid_fallback"] += 1
                elif correction_method == "original": stats["original_coords_kept"] += 1
            else:
                stats["dropped_too_far"] += 1
        else:
            stats["dropped_no_coords"] += 1
            
    # Output the result
    print("--- Cleaning Stats ---")
    for k, v in stats.items():
        print(f"{k}: {v}")
        
    data["schools"] = cleaned_schools
    data["cleaning_stats"] = stats
    
    output_path = "data/output/schools_analysis_bangalore_cleaned.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
        
    print(f"\nSaved cleaned dataset to: {output_path}")

if __name__ == "__main__":
    main()
