#!/usr/bin/env python3
import os
import json
import math
import re
import sys

# Default paths relative to this script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATIC_PATH = os.path.join(SCRIPT_DIR, "static", "data", "schools.json")
DEFAULT_ROOT_PATH = os.path.join(os.path.dirname(SCRIPT_DIR), "schools.json")
DEFAULT_REPORT_PATH = os.path.join(SCRIPT_DIR, "unmatched_schools_report.json")

def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points on the Earth in meters."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return float('inf')
    R = 6371000.0 # Earth's radius in meters
    try:
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    except Exception:
        return float('inf')

def expand_abbreviations(name):
    """Normalize common school abbreviations and acronyms to standard terms."""
    replacements = {
        r'\bnps\b': 'national public school',
        r'\bdps\b': 'delhi public school',
        r'\bbgs\b': 'bgs',
        r'\bvssp\b': 'vss public',
        r'\bvss\b': 'vss',
        r'\bst\b': 'saint',
        r'\bintl\b': 'international',
    }
    for pattern, repl in replacements.items():
        name = re.sub(pattern, repl, name)
    return name

def normalize_name(name):
    """Clean and standardize school names for comparison."""
    if not name:
        return ""
    name = name.lower()
    
    # Remove punctuation that varies across lists (e.g. "V.S.S." vs "VSS")
    name = name.replace('.', '')
    name = name.replace('-', ' ')
    name = name.replace(',', ' ')
    name = name.replace('(', ' ')
    name = name.replace(')', ' ')
    name = name.replace('\'', '')
    name = name.replace('"', '')
    
    # Strip double/multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Apply abbreviation expansion
    name = expand_abbreviations(name)
    
    return name

def get_significant_tokens(name):
    """Extract significant keywords from a school name (ignoring common noise words)."""
    normalized = normalize_name(name)
    stopwords = {"school", "schools", "international", "academy", "academies", "public", 
                 "bengaluru", "bangalore", "residential", "junior", "college", "prep", "pre", "primary", "the", "and"}
    words = [w for w in normalized.split() if w not in stopwords]
    return set(words), normalized

def check_match(s, rs):
    """Evaluate if a static school matches a root school based on name and coordinates."""
    s_name = s.get('name', '')
    s_lat = s.get('lat')
    s_lon = s.get('lon')
    
    rs_name = rs.get('name', '')
    rs_lat = rs.get('lat')
    rs_lon = rs.get('lon')
    
    # Distance in meters
    dist = haversine(s_lat, s_lon, rs_lat, rs_lon)
    
    s_tokens, s_norm = get_significant_tokens(s_name)
    rs_tokens, rs_norm = get_significant_tokens(rs_name)
    
    # Clean Jaccard overlap on significant tokens
    overlap = s_tokens & rs_tokens
    union = s_tokens | rs_tokens
    jaccard = len(overlap) / len(union) if union else 0.0
    
    is_substring = (s_norm in rs_norm) or (rs_norm in s_norm)
    
    # Tier 1: Exact Name Match
    if s_norm == rs_norm:
        return True, "Tier 1: Exact normalized name match", dist
        
    # Tier 2: Close Proximity + Partial Name Overlap
    if dist < 300:
        if jaccard > 0.4 or is_substring or len(overlap) >= 1:
            return True, f"Tier 2: Close Proximity ({dist:.1f}m) + Name Overlap", dist
            
    # Tier 3: Ultra Proximity (< 100m)
    if dist < 100:
        # If they are physically at the same location, tiny overlap or sharing prefix matches
        if len(overlap) >= 1 or jaccard > 0.0 or (s_norm[:3] == rs_norm[:3]):
            return True, f"Tier 3: Ultra-Proximity ({dist:.1f}m) + Shared Context", dist
            
    # Tier 4: Medium Proximity + High Name Similarity
    if dist < 2000:
        if jaccard >= 0.7 or (is_substring and len(s_tokens) >= 2):
            return True, f"Tier 4: Medium Proximity ({dist:.1f}m) + High Similarity", dist
            
    return False, "", dist

def main():
    # Allow custom CLI arguments
    static_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STATIC_PATH
    root_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ROOT_PATH
    report_path = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_REPORT_PATH
    
    print("=" * 60)
    print("SCHOOLS DATA ALIGNMENT CHECKER")
    print("=" * 60)
    print(f"Static Schools (Source):     {static_path}")
    print(f"Master Schools (Target):     {root_path}")
    print(f"Output Report Path:          {report_path}")
    print("-" * 60)
    
    # Load files
    if not os.path.exists(static_path):
        print(f"Error: Static schools file not found at {static_path}")
        sys.exit(1)
    if not os.path.exists(root_path):
        print(f"Error: Master schools file not found at {root_path}")
        sys.exit(1)
        
    with open(static_path, 'r', encoding='utf-8') as f:
        static_schools = json.load(f)
    with open(root_path, 'r', encoding='utf-8') as f:
        root_schools = json.load(f)
        
    print(f"Loaded {len(static_schools)} schools from Source.")
    print(f"Loaded {len(root_schools)} schools from Target.")
    
    matched_schools = []
    unmatched_schools = []
    tier_counts = {}
    
    # Matching process
    for s in static_schools:
        matched = False
        best_rs = None
        best_reason = ""
        best_dist = float('inf')
        
        for rs in root_schools:
            is_match, reason, dist = check_match(s, rs)
            if is_match:
                if dist < best_dist:
                    best_rs = rs
                    best_reason = reason
                    best_dist = dist
                    matched = True
                    
        if matched:
            matched_schools.append({
                "static": s,
                "matched_with": best_rs,
                "reason": best_reason,
                "distance": best_dist
            })
            tier = best_reason.split(":")[0]
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        else:
            # Find the top 3 closest root schools geographically
            closest_candidates = []
            for rs in root_schools:
                dist = haversine(s.get('lat'), s.get('lon'), rs.get('lat'), rs.get('lon'))
                closest_candidates.append((dist, rs))
            closest_candidates.sort(key=lambda x: x[0])
            
            unmatched_schools.append({
                "school": s,
                "closest_candidates": closest_candidates[:3]
            })
            
    # Print Results terminal summary
    match_rate = (len(matched_schools) / len(static_schools)) * 100 if static_schools else 0
    print("\nMATCH STATISTICS:")
    print(f"  Matched:      {len(matched_schools)} ({match_rate:.2f}%)")
    print(f"  Unmatched:    {len(unmatched_schools)} ({100 - match_rate:.2f}%)")
    print("\nMatch Tiers Breakdown:")
    for tier, count in sorted(tier_counts.items()):
        print(f"  - {tier}: {count}")
        
    # Write report of unmatched schools
    unmatched_report = {
        "summary": {
            "total_source_schools": len(static_schools),
            "total_target_schools": len(root_schools),
            "matched": len(matched_schools),
            "unmatched": len(unmatched_schools),
            "match_percentage": round(match_rate, 2)
        },
        "missing_schools": []
    }
    
    for item in unmatched_schools:
        s = item["school"]
        candidates = []
        for dist, rs in item["closest_candidates"]:
            candidates.append({
                "name": rs.get("name"),
                "distance_meters": round(dist, 1),
                "lat": rs.get("lat"),
                "lon": rs.get("lon"),
                "udise_code": rs.get("udise_code"),
                "url": rs.get("url")
            })
        unmatched_report["missing_schools"].append({
            "name": s.get("name"),
            "lat": s.get("lat"),
            "lon": s.get("lon"),
            "category": s.get("category"),
            "board": s.get("board"),
            "fee": s.get("fee"),
            "url": s.get("url"),
            "closest_master_candidates": candidates
        })
        
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(unmatched_report, f, indent=2)
        
    print("-" * 60)
    print(f"Detailed report of unmatched schools saved to:\n{report_path}")
    print("=" * 60)
    
    # Print sample of unmatched schools
    if unmatched_schools:
        print("\nTOP 10 SAMPLE UNMATCHED SCHOOLS (with closest master candidates):")
        for idx, item in enumerate(unmatched_schools[:10]):
            s = item["school"]
            print(f"\n{idx+1}. '{s.get('name')}'")
            print(f"   Coordinates: ({s.get('lat')}, {s.get('lon')}) | Fee: {s.get('fee')} | Board: {s.get('board')}")
            for rank, (dist, rs) in enumerate(item["closest_candidates"]):
                print(f"   Candidate {rank+1}: '{rs.get('name')}' at {dist:.1f}m (Coords: {rs.get('lat')}, {rs.get('lon')})")

if __name__ == "__main__":
    main()
