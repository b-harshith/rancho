import json
import math
import re
import os
from difflib import SequenceMatcher

STOP_WORDS = {"school", "the", "of", "and", "public", "private", "international", "academy", "high", "senior", "secondary"}

def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6371000.0  # meters
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def normalize_name(name):
    if not name:
        return ""
    text = name.lower().strip()
    words = re.findall(r"[a-z0-9]+", text)
    return " ".join(x for x in words if x not in STOP_WORDS)

def is_duplicate(s1, s2):
    n1 = normalize_name(s1["name"])
    n2 = normalize_name(s2["name"])
    if not n1 or not n2:
        return False
    # Exact or substring match of normalized names
    if n1 == n2 or n1 in n2 or n2 in n1:
        return True
    # Fuzzy match of normalized names
    score = SequenceMatcher(None, n1, n2).ratio()
    if score >= 0.70:
        return True
    return False

def merge_schools(s1, s2):
    # Choose name (prefer cleaner/longer name, avoiding trailing descriptors)
    name = s1["name"] if len(s1["name"]) >= len(s2["name"]) else s2["name"]
    
    # Merge boards
    b1 = [x.strip() for x in str(s1.get("board") or "").split(",") if x.strip()]
    b2 = [x.strip() for x in str(s2.get("board") or "").split(",") if x.strip()]
    merged_boards = sorted(list(set(b1 + b2)))
    board_str = ", ".join(merged_boards) if merged_boards else "CBSE"
    
    # Average fee
    f1 = s1.get("fee")
    f2 = s2.get("fee")
    if f1 is not None and f2 is not None:
        fee = (f1 + f2) / 2
    else:
        fee = f1 if f1 is not None else f2
        
    # Sum students (aggregating values for same building/sub-schools)
    students = float((s1.get("students") or 0) + (s2.get("students") or 0))
    
    # Choose other fields
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

def main():
    path = "/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/static/data/schools_delhi_ncr.json"
    with open(path, "r", encoding="utf-8") as f:
        schools = json.load(f)
        
    print(f"Initial schools count: {len(schools)}")
    
    # Group schools by proximity & similarity
    merged = []
    skipped = set()
    
    for i in range(len(schools)):
        if i in skipped:
            continue
            
        current = schools[i]
        for j in range(i + 1, len(schools)):
            if j in skipped:
                continue
                
            other = schools[j]
            dist = haversine_m(current["lat"], current["lon"], other["lat"], other["lon"])
            
            if dist <= 50.0 and is_duplicate(current, other):
                print(f"\nMerging Close/Duplicate Schools (Distance: {dist:.1f}m):")
                print(f"  - {current['name']} (Fee: {current['fee']}, Students: {current['students']})")
                print(f"  - {other['name']} (Fee: {other['fee']}, Students: {other['students']})")
                current = merge_schools(current, other)
                print(f"  => Combined: {current['name']} (Fee: {current['fee']:.0f}, Students: {current['students']:.0f})")
                skipped.add(j)
                
        merged.append(current)
        
    print(f"\nDeduplicated schools count: {len(merged)}")
    
    # Write back
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"Saved to {path}")
    
    final_output_path = "data/output/schools_delhi_ncr_final.json"
    os.makedirs(os.path.dirname(final_output_path), exist_ok=True)
    with open(final_output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"Saved to {final_output_path}")

if __name__ == "__main__":
    main()
