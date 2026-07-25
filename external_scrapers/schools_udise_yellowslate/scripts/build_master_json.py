import os
import json
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'output')

# Input Paths
UDISE_PATH = os.path.join(DATA_DIR, 'schools_analysis_bangalore_compact.json')
AUTO_PATH = os.path.join(DATA_DIR, 'auto_matched_schools.json')
MANUAL_PATH = os.path.join(DATA_DIR, 'manual_matched_schools.json')
UNMATCHED_PATH = os.path.join(DATA_DIR, 'unmatched_yellowslate.json')

# Output Path
MASTER_OUTPUT_PATH = os.path.join(DATA_DIR, 'yellowslate_schools_master.json')
CACHE_PATH = os.path.join(DATA_DIR, 'nominatim_geocode_cache.json')

# Grades 2-9 enrollment to Total enrollment ratios computed from matched data
RATIOS_GRADES_2_9 = {
    "Pre-Primary": 0.0,
    "Primary / K-8": 0.8383,
    "Secondary / K-10": 0.7766,
    "Higher Secondary / K-12": 0.4817
}

def classify_school(name, board_text):
    name = name.lower()
    board_text = (board_text or "").lower()
    if any(k in name for k in ["montessori", "preschool", "pre-school", "early years", "early learning", "play school", "kindergarten", "kids", "toddlers", "nursery", "pre primary", "playgroup"]):
        return "Pre-Primary"
    if "montessori" in board_text or "early years" in board_text:
        return "Pre-Primary"
    if any(k in name for k in ["pu college", "junior college", "composite", "higher secondary", "senior secondary", "pre university", "p.u. college"]):
        return "Higher Secondary / K-12"
    if any(k in name for k in ["primary", "lps", "ups", "nursery & primary", "nursery and primary"]):
        return "Primary / K-8"
    return "Secondary / K-10"

def build_master():
    print("Loading datasets...")
    # Load UDISE
    if not os.path.exists(UDISE_PATH):
        print(f"Error: UDISE file not found at {UDISE_PATH}")
        return
    with open(UDISE_PATH, 'r') as f:
        udise_data = json.load(f)
    udise_map = {u["udise_code"]: u for u in udise_data["schools"]}

    # Load Nominatim Cache
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, 'r') as f:
            cache = json.load(f)

    def clean_name(name):
        name = re.sub(r'\(.*?\)', '', name)
        return name.strip()

    def get_cached_coords(school_name, area, pincode):
        school_name = clean_name(school_name)
        queries = []
        if pincode:
            queries.append(f"{school_name}, {pincode}, Bengaluru, India")
        if area:
            queries.append(f"{school_name}, {area}, Bengaluru, India")
        queries.append(f"{school_name}, Bengaluru, India")
        if area:
            queries.append(f"{area}, Bengaluru, India")
            
        for q in queries:
            if q in cache:
                cached = cache[q]
                if cached.get("status") == "ok":
                    return cached["lat"], cached["lon"]
        return None, None

    # Load matches
    auto_matches = []
    if os.path.exists(AUTO_PATH):
        with open(AUTO_PATH, 'r') as f:
            auto_matches = json.load(f)
            
    manual_matches = []
    if os.path.exists(MANUAL_PATH):
        with open(MANUAL_PATH, 'r') as f:
            manual_matches = json.load(f)

    # Load unmatched
    unmatched_schools = []
    if os.path.exists(UNMATCHED_PATH):
        with open(UNMATCHED_PATH, 'r') as f:
            unmatched_schools = json.load(f)

    print(f"Loaded: {len(auto_matches)} auto matches, {len(manual_matches)} manual matches, {len(unmatched_schools)} unmatched schools.")

    # 1. Compute Category + Bracket averages using matched schools
    matched_by_group = {}
    category_totals = {}

    def track_matched(ys_school, ud_school):
        name = ys_school.get("school_name", "")
        board = ys_school.get("board_text", "")
        cat = classify_school(name, board)
        
        fee_info = ys_school.get("fee") or {}
        bracket = fee_info.get("assigned_bracket_label") or "Unknown"
        
        enrollment = ud_school.get("enrollment", {}).get("all", {}).get("total") or 0
        if enrollment > 0:
            key = (bracket, cat)
            if key not in matched_by_group:
                matched_by_group[key] = []
            matched_by_group[key].append(enrollment)
            
            if cat not in category_totals:
                category_totals[cat] = []
            category_totals[cat].append(enrollment)

    for m in auto_matches:
        track_matched(m.get("yellowslate") or {}, m.get("udise") or {})
    for m in manual_matches:
        ud_sch = udise_map.get(m.get("udise_code")) or {}
        track_matched(m.get("yellowslate_data") or {}, ud_sch)

    # Calculate averages
    group_averages = {k: sum(v)/len(v) for k, v in matched_by_group.items()}
    cat_averages = {k: sum(v)/len(v) for k, v in category_totals.items()}

    # 2. Compile Master List
    master_list = []

    # Process Auto Matches
    for m in auto_matches:
        ys = m.get("yellowslate") or {}
        ud = m.get("udise") or {}
        
        name = ys.get("school_name", "")
        board = ys.get("board_text", "")
        cat = classify_school(name, board)
        fee_info = ys.get("fee") or {}
        
        # Enrollment
        total_students = ud.get("enrollment", {}).get("all", {}).get("total") or 0
        grades_2_9_students = ud.get("enrollment", {}).get("grades_2_9", {}).get("total") or 0
        
        # Try UDISE coordinates first, fallback to Nominatim Cache
        ud_loc = ud.get("metadata", {}).get("location") or {}
        lat = ud_loc.get("lat")
        lon = ud_loc.get("lng")
        if lat is None or lon is None:
            lat, lon = get_cached_coords(name, ys.get("area", ""), ud.get("metadata", {}).get("pincode", ""))
            
        master_list.append({
            "school_name": name,
            "school_url": ys.get("school_url", ""),
            "area": ys.get("area", ""),
            "board": board,
            "structural_category": cat,
            "fee_bracket": {
                "bracket_key": fee_info.get("assigned_bracket_key", ""),
                "bracket_label": fee_info.get("assigned_bracket_label", ""),
                "bracket_min": fee_info.get("search_bracket_min"),
                "bracket_max": fee_info.get("search_bracket_max"),
                "min_fee": fee_info.get("min_fee"),
                "max_fee": fee_info.get("max_fee"),
                "fee_text": fee_info.get("fee_text", "")
            },
            "match_status": "auto_matched",
            "udise_code": ud.get("udise_code"),
            "udise_school_name": ud.get("metadata", {}).get("school_name"),
            "udise_pincode": ud.get("metadata", {}).get("pincode"),
            "udise_address": ud.get("metadata", {}).get("address"),
            "student_enrollment": total_students,
            "student_enrollment_grades_2_9": grades_2_9_students,
            "enrollment_source": "udise",
            "latitude": lat,
            "longitude": lon
        })

    # Process Manual Matches
    for m in manual_matches:
        ys = m.get("yellowslate_data") or {}
        udise_code = m.get("udise_code")
        ud = udise_map.get(udise_code) or {}
        
        name = ys.get("school_name") or m.get("yellowslate_name", "")
        board = ys.get("board_text", "")
        cat = classify_school(name, board)
        fee_info = ys.get("fee") or {}
        
        # Enrollment
        total_students = ud.get("enrollment", {}).get("all", {}).get("total") or 0 if ud else 0
        grades_2_9_students = ud.get("enrollment", {}).get("grades_2_9", {}).get("total") or 0 if ud else 0
        
        # Try UDISE coordinates first, fallback to Nominatim Cache
        ud_loc = ud.get("metadata", {}).get("location") or {} if ud else {}
        lat = ud_loc.get("lat")
        lon = ud_loc.get("lng")
        if lat is None or lon is None:
            lat, lon = get_cached_coords(name, ys.get("area", ""), ud.get("metadata", {}).get("pincode", "") if ud else "")
            
        master_list.append({
            "school_name": name,
            "school_url": ys.get("school_url", ""),
            "area": ys.get("area", ""),
            "board": board,
            "structural_category": cat,
            "fee_bracket": {
                "bracket_key": fee_info.get("assigned_bracket_key", ""),
                "bracket_label": fee_info.get("assigned_bracket_label", ""),
                "bracket_min": fee_info.get("search_bracket_min"),
                "bracket_max": fee_info.get("search_bracket_max"),
                "min_fee": fee_info.get("min_fee"),
                "max_fee": fee_info.get("max_fee"),
                "fee_text": fee_info.get("fee_text", "")
            },
            "match_status": "manual_matched",
            "udise_code": udise_code,
            "udise_school_name": ud.get("metadata", {}).get("school_name") if ud else None,
            "udise_pincode": ud.get("metadata", {}).get("pincode") if ud else None,
            "udise_address": ud.get("metadata", {}).get("address") if ud else None,
            "student_enrollment": total_students,
            "student_enrollment_grades_2_9": grades_2_9_students,
            "enrollment_source": "udise",
            "latitude": lat,
            "longitude": lon
        })

    # Collect all matched names to prevent duplicates
    matched_names = set()
    for m in auto_matches:
        matched = m.get("yellowslate") or {}
        if matched.get("school_name"):
            matched_names.add(matched["school_name"])
    for m in manual_matches:
        if m.get("yellowslate_name"):
            matched_names.add(m["yellowslate_name"])

    # Process Unmatched
    for ys in unmatched_schools:
        name = ys.get("school_name", "")
        if name in matched_names:
            continue
            
        board = ys.get("board_text", "")
        cat = classify_school(name, board)
        fee_info = ys.get("fee") or {}
        bracket = fee_info.get("assigned_bracket_label") or "Unknown"
        
        # Determine estimated enrollment
        key = (bracket, cat)
        avg = group_averages.get(key)
        if avg is None:
            avg = cat_averages.get(cat, 100)
            
        estimated_students = round(avg)
        
        # Determine estimated Grades 2-9 enrollment using the category ratio
        ratio = RATIOS_GRADES_2_9.get(cat, 0.75)
        estimated_grades_2_9 = round(estimated_students * ratio)
        
        # Try to get coordinates from Nominatim Cache
        lat, lon = get_cached_coords(name, ys.get("area", ""), "")
        
        master_list.append({
            "school_name": name,
            "school_url": ys.get("school_url", ""),
            "area": ys.get("area", ""),
            "board": board,
            "structural_category": cat,
            "fee_bracket": {
                "bracket_key": fee_info.get("assigned_bracket_key", ""),
                "bracket_label": fee_info.get("assigned_bracket_label", ""),
                "bracket_min": fee_info.get("search_bracket_min"),
                "bracket_max": fee_info.get("search_bracket_max"),
                "min_fee": fee_info.get("min_fee"),
                "max_fee": fee_info.get("max_fee"),
                "fee_text": fee_info.get("fee_text", "")
            },
            "match_status": "unmatched",
            "udise_code": None,
            "udise_school_name": None,
            "udise_pincode": None,
            "udise_address": None,
            "student_enrollment": estimated_students,
            "student_enrollment_grades_2_9": estimated_grades_2_9,
            "enrollment_source": "estimate",
            "latitude": lat,
            "longitude": lon
        })

    # 3. Group by fee bracket and sort/rank within each fee bracket
    grouped_by_bracket = {}
    for entry in master_list:
        b_key = entry["fee_bracket"]["bracket_key"]
        if b_key not in grouped_by_bracket:
            grouped_by_bracket[b_key] = []
        grouped_by_bracket[b_key].append(entry)
        
    final_master_list = []
    # Loop fee brackets in descending order (highest first)
    for b_key in ["above_2l", "1l_2l", "70k_1l", "50k_70k", "30k_50k", "under_30k"]:
        bracket_entries = grouped_by_bracket.get(b_key, [])
        
        # Sort function: highest fee value, then highest student count
        def bracket_sort_func(x):
            max_fee = x["fee_bracket"].get("max_fee") or 0
            if max_fee == 0:
                # Parse from fee_text
                text = x["fee_bracket"].get("fee_text") or ""
                numbers = re.findall(r'[\d,]+', text)
                max_fee = max([int(num.replace(',', '')) for num in numbers]) if numbers else (x["fee_bracket"].get("bracket_min") or 0)
            return (-max_fee, -(x["student_enrollment"] or 0))
            
        bracket_entries.sort(key=bracket_sort_func)
        
        # Assign rank within this bracket
        for idx, entry in enumerate(bracket_entries, start=1):
            entry["rank_in_bracket"] = idx
            final_master_list.append(entry)

    print(f"Compiled and ranked total Master entries: {len(final_master_list)}")
    
    # Save Master JSON
    with open(MASTER_OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_master_list, f, ensure_ascii=False, indent=2)
    print(f"Successfully wrote final master JSON database to: {MASTER_OUTPUT_PATH}")

if __name__ == "__main__":
    build_master()
