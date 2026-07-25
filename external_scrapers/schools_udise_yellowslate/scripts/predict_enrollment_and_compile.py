import json
import os
import re
import asyncio
import aiohttp
import urllib.parse
import random
from collections import defaultdict, Counter
from difflib import SequenceMatcher
import numpy as np
import h3

# Constants
UDISE_PATH = "data/output/schools_analysis_delhi_ncr_compact.json"
CANDIDATES_PATH = "data/output/schools_merged_all_candidates.json"
API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
CONCURRENCY_LIMIT = 20

# Output Paths
FINAL_JSON_PATH = "data/output/schools_delhi_ncr_final.json"
STATIC_JSON_PATH = "/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/static/data/schools_delhi_ncr.json"

async def geocode_google(session, name, area, city_source):
    if not API_KEY:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY before running this scraper.")
    query_parts = []
    if name:
        query_parts.append(name)
    if area:
        query_parts.append(area)
        
    city_suffix = f"{str(city_source).capitalize()}, India"
    if city_source == "noida":
        city_suffix = "Noida, Uttar Pradesh, India"
    elif city_source in ("gurgaon", "gurugram"):
        city_suffix = "Gurugram, Haryana, India"
    elif city_source == "ghaziabad":
        city_suffix = "Ghaziabad, Uttar Pradesh, India"
    elif city_source == "faridabad":
        city_suffix = "Faridabad, Haryana, India"
    elif city_source in ("delhi", "delhi_ncr"):
        city_suffix = "Delhi, India"
        
    query_parts.append(city_suffix)
    address = ", ".join(query_parts)
    
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={API_KEY}"
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                status = data.get("status")
                if status == "OK" and data.get("results"):
                    loc = data["results"][0]["geometry"]["location"]
                    return (loc["lat"], loc["lng"]), None
                elif status == "OVER_QUERY_LIMIT":
                    return "RETRY_LIMIT", status
                elif status in ["ZERO_RESULTS", "REQUEST_DENIED", "INVALID_REQUEST", "UNKNOWN_ERROR"]:
                    return None, status
            return None, f"HTTP {response.status}"
    except Exception as e:
        return "RETRY_ERR", str(e)

async def geocode_worker(queue, session, progress):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
            
        p = item
        name = p.get("school_name")
        area = p.get("area")
        city_source = p.get("city_source", "delhi")
        
        await asyncio.sleep(random.uniform(0.05, 0.1))
        
        google_coords = None
        retries = 3
        backoff = 2.0
        
        while retries > 0:
            res_coords, err = await geocode_google(session, name, area, city_source)
            if res_coords == "RETRY_LIMIT":
                sleep_time = backoff + random.uniform(0.5, 1.5)
                await asyncio.sleep(sleep_time)
                retries -= 1
                backoff *= 2.0
                continue
            elif res_coords == "RETRY_ERR":
                retries -= 1
                await asyncio.sleep(0.5)
                continue
            else:
                google_coords = res_coords
                break
                
        # Fallback query
        if google_coords is None and area:
            retries = 3
            backoff = 2.0
            while retries > 0:
                res_coords, err = await geocode_google(session, None, area, city_source)
                if res_coords == "RETRY_LIMIT":
                    sleep_time = backoff + random.uniform(0.5, 1.5)
                    await asyncio.sleep(sleep_time)
                    retries -= 1
                    backoff *= 2.0
                    continue
                elif res_coords == "RETRY_ERR":
                    retries -= 1
                    await asyncio.sleep(0.5)
                    continue
                else:
                    google_coords = res_coords
                    break
        
        if google_coords:
            p["latitude"], p["longitude"] = google_coords
            progress["success"] += 1
        else:
            progress["failed"] += 1
            
        queue.task_done()

# Proximity-based deduplication helpers
def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6371000.0  # meters
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def is_valid_pincode(p):
    if not p:
        return False
    p_str = str(p).strip()
    return bool(re.match(r'^\d{6}$', p_str))

def normalize_name(name):
    if not name:
        return ""
    text = name.lower().strip()
    words = re.findall(r"[a-z0-9]+", text)
    return " ".join(x for x in words if x not in STOP_WORDS)

STOP_WORDS = {"school", "the", "of", "and", "public", "private", "international", "academy", "high", "senior", "secondary"}

import math

def is_duplicate(s1, s2):
    n1 = normalize_name(s1["name"])
    n2 = normalize_name(s2["name"])
    if not n1 or not n2:
        return False
    if n1 == n2 or n1 in n2 or n2 in n1:
        return True
    score = SequenceMatcher(None, n1, n2).ratio()
    if score >= 0.70:
        return True
    return False

def merge_schools(s1, s2):
    name = s1["name"] if len(s1["name"]) >= len(s2["name"]) else s2["name"]
    
    b1 = [x.strip() for x in str(s1.get("board") or "").split(",") if x.strip()]
    b2 = [x.strip() for x in str(s2.get("board") or "").split(",") if x.strip()]
    merged_boards = sorted(list(set(b1 + b2)))
    board_str = ", ".join(merged_boards) if merged_boards else "CBSE"
    
    f1 = s1.get("fee")
    f2 = s2.get("fee")
    if f1 is not None and f2 is not None:
        fee = (f1 + f2) / 2
    else:
        fee = f1 if f1 is not None else f2
        
    students = float((s1.get("students") or 0) + (s2.get("students") or 0))
    
    url = s1.get("url") or s2.get("url")
    address = s1.get("address") if len(str(s1.get("address") or "")) >= len(str(s2.get("address") or "")) else s2.get("address")
    pincode = s1.get("pincode") or s2.get("pincode")
    category = s1.get("category") or s2.get("category")
    hex_id = s1.get("hex_id") or s2.get("hex_id")
    zone = s1.get("zone") or s2.get("zone")
    
    return {
        "name": name,
        "lat": s1["lat"],
        "lon": s1["lon"],
        "board": board_str,
        "fee": fee,
        "students": students,
        "url": url,
        "address": address,
        "pincode": pincode,
        "category": category,
        "hex_id": hex_id,
        "zone": zone
    }

async def main_async(args):
    udise_path = args.udise_path
    candidates_path = args.candidates_path or f"data/output/schools_merged_all_candidates_{args.city}.json"
    final_json_path = f"data/output/schools_{args.city}_final.json"
    static_json_path = args.output or f"/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/static/data/schools_{args.city}.json"

    print("Loading UDISE compact database...")
    with open(udise_path, "r", encoding="utf-8") as f:
        udise_data = json.load(f)
    udise_schools = udise_data.get("schools", [])
    udise_map = {u["udise_code"]: u for u in udise_schools}
    
    # Filter UDISE to private/aided
    allowed_managements = {
        'Private Unaided (Recognized)',
        'Madrasa Private Unaided (Recognized)',
        'Government Aided'
    }
    udise_filtered = [u for u in udise_schools if u['metadata'].get('management', '') in allowed_managements]

    # Compute group averages from private/aided UDISE schools
    group_enrollments = defaultdict(list)
    group_grades_2_9 = defaultdict(list)
    highest_class_enrollments = defaultdict(list)
    highest_class_grades_2_9 = defaultdict(list)
    global_enrollments = []
    global_grades_2_9 = []
    
    for u in udise_filtered:
        low = u["metadata"].get("lowest_class") or 1
        high = u["metadata"].get("highest_class") or 12
        enroll = u.get("enrollment", {})
        if "all" in enroll:
            tot = enroll.get("all", {}).get("total") or 0
            g2_9 = enroll.get("grades_2_9", {}).get("total") or 0
        else:
            tot = enroll.get("total_students") or 0
            g2_9 = 0
            by_class = enroll.get("by_class", [])
            for c_level in by_class:
                cls = str(c_level.get("class_level"))
                if cls in ['2', '3', '4', '5', '6', '7', '8', '9']:
                    g2_9 += c_level.get("total") or 0
        if tot > 0:
            group_enrollments[(low, high)].append(tot)
            group_grades_2_9[(low, high)].append(g2_9)
            highest_class_enrollments[high].append(tot)
            highest_class_grades_2_9[high].append(g2_9)
            global_enrollments.append(tot)
            global_grades_2_9.append(g2_9)
            
    group_avg = {k: sum(v)/len(v) for k, v in group_enrollments.items()}
    group_g2_9_avg = {k: sum(v)/len(v) for k, v in group_grades_2_9.items()}
    high_class_avg = {k: sum(v)/len(v) for k, v in highest_class_enrollments.items()}
    high_class_g2_9_avg = {k: sum(v)/len(v) for k, v in highest_class_grades_2_9.items()}
    global_avg = sum(global_enrollments)/len(global_enrollments) if global_enrollments else 250.0
    global_g2_9_avg = sum(global_grades_2_9)/len(global_grades_2_9) if global_grades_2_9 else 150.0

    print("Loading merged unique candidates database...")
    with open(candidates_path, "r", encoding="utf-8") as f:
        candidates = json.load(f)
    print(f"Loaded {len(candidates)} unique candidates.")

    # Process all unique candidates
    all_schools = []
    for c in candidates:
        # Determine city_source
        ud_sch = udise_map.get(c.get("udise_code")) if c.get("is_matched") else None
        city_source = "delhi" if args.city == "delhi_ncr" else args.city
        if ud_sch:
            dist = str(ud_sch.get("metadata", {}).get("location", {}).get("district") or "").upper()
            if "GAUTAM BUDDHA" in dist:
                city_source = "noida"
            elif "GURUGRAM" in dist or "GURGAON" in dist:
                city_source = "gurugram"
            elif "GHAZIABAD" in dist:
                city_source = "ghaziabad"
            elif "FARIDABAD" in dist:
                city_source = "faridabad"
        else:
            url = c.get("ezyschooling_url") or c.get("yellowslate_url")
            # Fallback to URL or address checks
            if url:
                if "noida" in url.lower():
                    city_source = "noida"
                elif "gurugram" in url.lower() or "gurgaon" in url.lower():
                    city_source = "gurugram"
                elif "ghaziabad" in url.lower():
                    city_source = "ghaziabad"
                elif "faridabad" in url.lower():
                    city_source = "faridabad"
            if city_source == "delhi" and c.get("address"):
                addr = str(c["address"]).lower()
                if "noida" in addr:
                    city_source = "noida"
                elif "gurugram" in addr or "gurgaon" in addr:
                    city_source = "gurugram"
                elif "ghaziabad" in addr:
                    city_source = "ghaziabad"
                elif "faridabad" in addr:
                    city_source = "faridabad"

        # Determine student enrollment and grades 2-9
        low = c.get("lowest_class") or 1
        high = c.get("highest_class") or 12
        
        if c.get("is_matched") and c.get("student_enrollment", 0) > 0:
            students = float(c["student_enrollment"])
            student_enrollment_grades_2_9 = float(c.get("student_enrollment_grades_2_9") or 0)
        else:
            # Predict enrollment based on class ranges
            predicted = group_avg.get((low, high)) or high_class_avg.get(high) or global_avg
            students = float(round(predicted))
            
            predicted_g2_9 = group_g2_9_avg.get((low, high)) or high_class_g2_9_avg.get(high) or global_g2_9_avg
            student_enrollment_grades_2_9 = float(round(predicted_g2_9))
            
        all_schools.append({
            "school_name": c["school_name"],
            "latitude": None,
            "longitude": None,
            "area": c.get("area") or "",
            "board": ", ".join(c["boards"]) if c.get("boards") else "CBSE",
            "fee": (c["fee"]["min_fee"] + c["fee"]["max_fee"]) / 2 if c.get("fee") and c["fee"].get("min_fee") is not None else None,
            "students": students,
            "url": c.get("ezyschooling_url") or c.get("yellowslate_url"),
            "address": c.get("address") or "NA",
            "pincode": c.get("pincode") or "NA",
            "city_source": city_source,
            "lowest_class": low,
            "highest_class": high,
            "student_enrollment_grades_2_9": student_enrollment_grades_2_9,
            "enrollment_source": c.get("enrollment_source") or "Predicted",
            "udise_code": c.get("udise_code")
        })

    # Clear valid schools from any negative/null fees
    all_schools = [s for s in all_schools if s["fee"] is not None and s["fee"] > 0]
    print(f"Total positive fee schools to geocode: {len(all_schools)}")

    # Geocode all schools using Google Maps API (deleting all existing coordinates)
    print(f"Geocoding all {len(all_schools)} schools using Google Maps API...")
    queue = asyncio.Queue()
    for x in all_schools:
        await queue.put(x)
        
    progress = {"success": 0, "failed": 0}
    async with aiohttp.ClientSession() as session:
        workers = []
        for _ in range(CONCURRENCY_LIMIT):
            workers.append(asyncio.create_task(geocode_worker(queue, session, progress)))
        for _ in range(CONCURRENCY_LIMIT):
            await queue.put(None)
        await queue.join()
        await asyncio.gather(*workers)
    print(f"Geocoding complete: {progress['success']} resolved, {progress['failed']} failed.")

    # Filter geocoded results
    valid_schools = []
    for s in all_schools:
        if s["latitude"] is not None and s["longitude"] is not None:
            valid_schools.append({
                "name": s["school_name"],
                "lat": s["latitude"],
                "lon": s["longitude"],
                "board": s["board"],
                "fee": s["fee"],
                "students": s["students"],
                "url": s["url"],
                "address": s["address"],
                "pincode": s["pincode"],
                "city_source": s["city_source"],
                "lowest_class": s["lowest_class"],
                "highest_class": s["highest_class"],
                "student_enrollment_grades_2_9": s["student_enrollment_grades_2_9"],
                "enrollment_source": s["enrollment_source"],
                "udise_code": s.get("udise_code")
            })

    # Verification and Quality Filters (Edge Cases cleanup)
    filtered_schools = []
    dropped_count = 0
    
    city_bboxes = {
        "delhi_ncr": {"lat": (28.0, 29.0), "lon": (76.5, 78.0)},
        "mumbai": {"lat": (18.5, 19.5), "lon": (72.5, 73.5)},
        "hyderabad": {"lat": (17.0, 17.8), "lon": (78.0, 79.0)},
        "chennai": {"lat": (12.7, 13.3), "lon": (80.0, 80.5)},
        "kolkata": {"lat": (22.2, 23.0), "lon": (88.0, 88.6)},
        "pune": {"lat": (18.2, 18.8), "lon": (73.5, 74.2)}
    }
    
    bbox = city_bboxes.get(args.city)
    
    for s in valid_schools:
        students = s["students"]
        grades_offered = s["highest_class"] - s["lowest_class"] + 1
        lat = s["lat"]
        lon = s["lon"]
        
        # Rule 1: Total enrollment < 50 (too tiny)
        if students < 50:
            dropped_count += 1
            continue
            
        # Rule 2: Total enrollment < 100 but offers 10 or more classes (unrealistic class density/outlier)
        if students < 100 and grades_offered >= 10:
            dropped_count += 1
            continue
            
        # Rule 3: Coordinate validation (spatial bounding box check)
        if bbox:
            if not (bbox["lat"][0] <= lat <= bbox["lat"][1] and bbox["lon"][0] <= lon <= bbox["lon"][1]):
                dropped_count += 1
                continue
                
        # Rule 4: Must offer at least one grade in the 2-9 range
        if s.get("highest_class", 12) < 2 or s.get("lowest_class", 1) > 9:
            dropped_count += 1
            continue
                
        # Fix: Ensure total students is at least equal to grade 2-9 total
        if students < s["student_enrollment_grades_2_9"]:
            s["students"] = s["student_enrollment_grades_2_9"]
            
        filtered_schools.append(s)
        
    print(f"Verification Filter: Dropped {dropped_count} schools that failed quality checks (total remaining: {len(filtered_schools)}).")
    valid_schools = filtered_schools

    # Categorize schools across the entire spectrum
    for s in valid_schools:
        fee = s["fee"]
        if fee >= 165000.0:
            s["category"] = "Ultra Premium"
        elif fee >= 114996.0:
            s["category"] = "Super Premium"
        elif fee > 84996.0:
            s["category"] = "Premium"
        elif fee > 55000.0:
            s["category"] = "Mid-Premium"
        elif fee > 30000.0:
            s["category"] = "Affordable"
        else:
            s["category"] = "Budget"
            
        s["hex_id"] = h3.latlng_to_cell(s["lat"], s["lon"], 7)
        s["zone"] = str(s["city_source"]).capitalize()
        s.pop("city_source", None)

    # Save final schools database
    os.makedirs(os.path.dirname(final_json_path), exist_ok=True)
    with open(final_json_path, "w", encoding="utf-8") as f:
        json.dump(valid_schools, f, ensure_ascii=False, indent=2)
    print(f"Successfully saved final schools to {final_json_path}")

    # Also save to Vercel static data directory
    os.makedirs(os.path.dirname(static_json_path), exist_ok=True)
    with open(static_json_path, "w", encoding="utf-8") as f:
        json.dump(valid_schools, f, ensure_ascii=False, indent=2)
    print(f"Successfully deployed final schools JSON to {static_json_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="delhi_ncr")
    parser.add_argument("--udise-path", default="data/output/schools_analysis_delhi_ncr_compact.json")
    parser.add_argument("--candidates-path", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    asyncio.run(main_async(args))
