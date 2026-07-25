import json
import os
import re
import glob
import argparse
from collections import Counter
from difflib import SequenceMatcher

def get_udise_enrollment(u):
    enroll = u.get("enrollment", {})
    if not enroll:
        return 0, 0
    if "all" in enroll:
        tot = enroll.get("all", {}).get("total") or 0
        g2_9 = enroll.get("grades_2_9", {}).get("total") or 0
        return tot, g2_9
    tot = enroll.get("total_students") or 0
    g2_9 = 0
    by_class = enroll.get("by_class", [])
    for c_level in by_class:
        cls = str(c_level.get("class_level"))
        if cls in ['2', '3', '4', '5', '6', '7', '8', '9']:
            g2_9 += c_level.get("total") or 0
    return tot, g2_9

def similar(a, b):
    if not a or not b:
        return 0
    return SequenceMatcher(None, a, b).ratio()

def is_valid_pincode(p):
    if not p:
        return False
    p_str = str(p).strip()
    return bool(re.match(r'^\d{6}$', p_str))

def normalize_name(name):
    if not name:
        return ""
    name = name.lower().strip()
    
    # Standardize spelling variations
    name = re.sub(r'\bsaint\b', 'st', name)
    name = re.sub(r'\b(shri|sree|shree)\b', 'sri', name)
    name = re.sub(r'\bvidhya\b', 'vidya', name)
    name = re.sub(r'\bcentre\b', 'center', name)
    
    # Remove common school words, locations, suffixes, and structural terms
    words_to_remove = [
        r'school', r'public', r'convent', r'english', r'kannada', r'urdu', r'high', r'higher', 
        r'primary', r'nursery', r'vidya', r'kendra', r'institution', r'academy', r'international', 
        r'early', r'learning', r'center', r'pre', r'preschool', r'montessori', r'play', 
        r'playgroup', r'kindergarten', r'bengaluru', r'bangalore', r'delhi', r'noida', r'gurgaon',
        r'gurugram', r'ghaziabad', r'faridabad', r'hps', r'lps', r'hs', r'ups', 
        r'mps', r'society', r'trust', r'foundation', r'association', r'memorial', r'composite', 
        r'residential', r'day', r'boarding', r'boys', r'girls', r'co-ed', r'coed', r'coeducation',
        r'management', r'education', r'educational', r'vidyalaya', r'vidyashala', r'vidyapeeth', 
        r'vidyapeetha', r'shiksha', r'shikshana', r'vihar', r'shishuvihar', r'global', r'national',
        r'kids', r'kidz', r'childcare', r'daycare'
    ]
    pattern = r'\b(' + '|'.join(words_to_remove) + r')\b'
    name = re.sub(pattern, '', name)
    
    name = re.sub(r'[^a-z0-9]', '', name)
    return name

def extract_ezy_annual_fee(s):
    fees = s.get("avg_fees") or {}
    sessions = [v for v in fees.values() if isinstance(v, dict)]
    values = []
    
    def parse_k_val(val):
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        val_str = str(val).lower().strip()
        if 'k' in val_str:
            val_str = val_str.replace('k', '').strip()
            try:
                return float(val_str) * 1000
            except ValueError:
                pass
        try:
            return float(val_str)
        except ValueError:
            return None
            
    for session in sessions:
        for info in (session.get("class_wise") or {}).values():
            val = parse_k_val(info.get("fees_numbers"))
            if val is not None and val > 0:
                tenure = str(info.get("tenure", "monthly")).lower()
                multiplier = 12 if tenure == "monthly" else (4 if tenure == "quarterly" else 1)
                values.append(val * multiplier)
        rng = session.get("range") or {}
        tenure = str(rng.get("tenure", "monthly")).lower()
        multiplier = 12 if tenure == "monthly" else (4 if tenure == "quarterly" else 1)
        for val_key in ("lowest_fee", "highest_fee"):
            val = parse_k_val(rng.get(val_key))
            if val is not None and val > 0:
                values.append(val * multiplier)
                
    min_f, max_f = None, None
    if values:
        min_f, max_f = min(values), max(values)
    if min_f is None:
        flat_fee = s.get("fees") or s.get("lower_to_higher_fees")
        if flat_fee:
            try:
                parsed_flat = float(flat_fee)
                if parsed_flat > 0:
                    min_f = parsed_flat * 12
                    max_f = min_f
            except ValueError:
                pass
    return min_f, max_f

def main():
    parser = argparse.ArgumentParser(description="Merge Ezyschooling & Yellowslate, match to UDISE, and geocode.")
    parser.add_argument("--ys-path", default="data/output/yellowslate/yellowslate_schools_with_locations_delhi_ncr.json")
    parser.add_argument("--ezy-dir", default="/Users/malleswararao/Desktop/School Data/data")
    parser.add_argument("--udise-path", default="data/output/schools_analysis_delhi_ncr_compact.json")
    parser.add_argument("--output", default="data/output/schools_merged_matched_udise.json")
    args = parser.parse_args()

    print("Loading YellowSlate fee schools...")
    with open(args.ys_path, 'r', encoding='utf-8') as f:
        ys_raw = json.load(f)
    
    # Filter Yellowslate schools that have valid positive fee data
    ys_schools = []
    for s in ys_raw:
        fee_info = s.get('fee') or {}
        min_f = fee_info.get('min_fee')
        max_f = fee_info.get('max_fee')
        if min_f is not None and min_f > 0:
            ys_schools.append(s)
    print(f"Loaded {len(ys_schools)} YellowSlate schools with valid positive fee data.")

    print("Loading Ezyschooling schools...")
    # Extract city name from ys_path
    city_match = re.search(r'_locations_([a-z0-9_\-]+)\.json', args.ys_path)
    city_name = city_match.group(1) if city_match else "delhi_ncr"
    
    if city_name == "delhi_ncr" or city_name == "delhi":
        ezy_files = glob.glob(os.path.join(args.ezy_dir, "ezyschooling_raw_*.json"))
        ncr_cities = {'delhi', 'noida', 'gurugram', 'ghaziabad', 'faridabad', 'greater-noida', 'greater-noida-west'}
        ezy_files = [f for f in ezy_files if any(c in os.path.basename(f) for c in ncr_cities)]
    else:
        ezy_city = city_name
        if city_name == "bengaluru":
            ezy_city = "bangalore"
        target_file = os.path.join(args.ezy_dir, f"ezyschooling_raw_{ezy_city}.json")
        if os.path.exists(target_file):
            ezy_files = [target_file]
        else:
            print(f"Warning: Ezyschooling raw file not found at {target_file}")
            ezy_files = []
            
    ezy_raw = []
    for fpath in ezy_files:
        with open(fpath, 'r', encoding='utf-8') as f:
            ezy_raw.extend(json.load(f))
            
    # Deduplicate Ezyschooling schools by slug and ensure they have valid positive fee data
    ezy_seen = set()
    ezy_schools = []
    for s in ezy_raw:
        slug = s.get("slug")
        if slug and slug not in ezy_seen:
            e_min_fee, e_max_fee = extract_ezy_annual_fee(s)
            if e_min_fee is not None and e_min_fee > 0:
                ezy_seen.add(slug)
                # Cache the annual fees inside s
                s["_annual_min_fee"] = e_min_fee
                s["_annual_max_fee"] = e_max_fee
                ezy_schools.append(s)
    print(f"Loaded and deduplicated {len(ezy_schools)} Ezyschooling schools with valid positive fee data.")

    # Reconcile Ezyschooling and YellowSlate to produce a unified candidate list of fee schools
    print("Matching Ezyschooling to Yellowslate...")
    ys_normalized = []
    for s in ys_schools:
        y_name = s.get("school_name", "")
        ys_normalized.append({
            "school_name": y_name,
            "norm_name": normalize_name(y_name),
            "pincode": str((s.get("school_location") or {}).get("pincode") or "").strip(),
            "area": (s.get("area") or "").lower(),
            "raw": s,
            "matched": False
        })
        
    merged_candidates = []
    
    # Match Ezyschooling schools to Yellowslate
    for e_idx, e in enumerate(ezy_schools):
        e_name = e.get("name")
        e_norm = normalize_name(e_name)
        e_pincode = str(e.get("zipcode") or "").strip()
        e_area = (e.get("school_area") or {}).get("name", "").lower() if isinstance(e.get("school_area"), dict) else str(e.get("school_area") or "").lower()
        
        e_min_fee = e["_annual_min_fee"]
        e_max_fee = e["_annual_max_fee"]
        
        best_match = None
        best_score = 0
        
        for y_item in ys_normalized:
            if y_item["matched"]:
                continue
            score = similar(e_norm, y_item["norm_name"])
            
            pins_match = (e_pincode and y_item["pincode"] and e_pincode == y_item["pincode"])
            if pins_match:
                score += 0.15
            elif e_pincode and y_item["pincode"] and e_pincode != y_item["pincode"]:
                score -= 0.15
                
            if score > best_score:
                best_score = score
                best_match = y_item
                
        if best_match and best_score >= 0.82:
            best_match["matched"] = True
            y_raw = best_match["raw"]
            y_fee_info = y_raw.get("fee") or {}
            # Yellowslate fees are already annual
            ys_min_fee = (y_fee_info.get("min_fee") or 0)
            ys_max_fee = (y_fee_info.get("max_fee") or 0)
            
            final_min_fee = e_min_fee if e_min_fee is not None else ys_min_fee
            final_max_fee = e_max_fee if e_max_fee is not None else ys_max_fee
            
            merged_candidates.append({
                "school_name": e_name,
                "ezyschooling_url": f"https://ezyschooling.com/school/{e.get('slug')}",
                "yellowslate_url": y_raw.get("school_url"),
                "area": e_area or y_raw.get("area"),
                "pincode": e_pincode or best_match["pincode"],
                "address": e.get("street_address") or (y_raw.get("school_location") or {}).get("address"),
                "latitude": e.get("geocoords", {}).get("lat") or (y_raw.get("school_location") or {}).get("latitude"),
                "longitude": e.get("geocoords", {}).get("lon") or (y_raw.get("school_location") or {}).get("longitude"),
                "boards": sorted(list({str(x.get("name")) for x in e.get("school_boardss", []) if x.get("name")} | {y_raw.get("board_text")} - {None})),
                "fee": {
                    "min_fee": final_min_fee,
                    "max_fee": final_max_fee,
                    "fee_text": f"₹{final_min_fee:,.0f} - ₹{final_max_fee:,.0f}" if final_min_fee is not None else "N/A"
                },
                "source": "merged_ezy_yellowslate",
                "offered_classes": e.get("offered_classes")
            })
        else:
            merged_candidates.append({
                "school_name": e_name,
                "ezyschooling_url": f"https://ezyschooling.com/school/{e.get('slug')}",
                "yellowslate_url": None,
                "area": e_area,
                "pincode": e_pincode,
                "address": e.get("street_address"),
                "latitude": e.get("geocoords", {}).get("lat"),
                "longitude": e.get("geocoords", {}).get("lon"),
                "boards": sorted(list({str(x.get("name")) for x in e.get("school_boardss", []) if x.get("name")} - {None})),
                "fee": {
                    "min_fee": e_min_fee,
                    "max_fee": e_max_fee,
                    "fee_text": f"₹{e_min_fee:,.0f} - ₹{e_max_fee:,.0f}" if e_min_fee is not None else "N/A"
                },
                "source": "ezyschooling",
                "offered_classes": e.get("offered_classes")
            })
            
    # Add unmatched Yellowslate schools to candidates
    unmatched_ys_count = 0
    for y_item in ys_normalized:
        if not y_item["matched"]:
            unmatched_ys_count += 1
            y_raw = y_item["raw"]
            y_fee_info = y_raw.get("fee") or {}
            ys_min_fee = (y_fee_info.get("min_fee") or 0)
            ys_max_fee = (y_fee_info.get("max_fee") or 0)
            
            merged_candidates.append({
                "school_name": y_item["school_name"],
                "ezyschooling_url": None,
                "yellowslate_url": y_raw.get("school_url"),
                "area": y_raw.get("area"),
                "pincode": y_item["pincode"],
                "address": (y_raw.get("school_location") or {}).get("address"),
                "latitude": (y_raw.get("school_location") or {}).get("latitude"),
                "longitude": (y_raw.get("school_location") or {}).get("longitude"),
                "boards": [y_raw.get("board_text")] if y_raw.get("board_text") else [],
                "fee": {
                    "min_fee": ys_min_fee,
                    "max_fee": ys_max_fee,
                    "fee_text": f"₹{ys_min_fee:,.0f} - ₹{ys_max_fee:,.0f}" if ys_min_fee is not None else "N/A"
                },
                "source": "yellowslate",
                "offered_classes": None
            })
            
    print(f"Merged Yellowslate + Ezyschooling candidates: {len(merged_candidates)} unique schools (includes {unmatched_ys_count} unmatched Yellowslate schools).")

    # Load compact UDISE data
    print("Loading UDISE schools database...")
    with open(args.udise_path, 'r', encoding='utf-8') as f:
        udise_data = json.load(f)
    udise_schools = udise_data.get("schools", [])
    
    # Filter UDISE schools to private/aided and restrict to target city districts to avoid false cross-city matches
    allowed_managements = {
        'Private Unaided (Recognized)',
        'Madrasa Private Unaided (Recognized)',
        'Government Aided'
    }
    city_match = re.search(r'_locations_([a-z0-9_\-]+)\.json', args.ys_path)
    city_name = city_match.group(1) if city_match else "delhi_ncr"
    
    city_districts = []
    if city_name == "mumbai":
        city_districts = ["MUMBAI", "SUBURBAN", "THANE"]
    elif city_name == "hyderabad":
        city_districts = ["HYDERABAD", "RANGA REDDY", "RANGAREDDY", "MEDCHAL", "SANGAREDDY"]
    elif city_name == "chennai":
        city_districts = ["CHENNAI", "KANCHIPURAM", "THIRUVALLUR", "TIRUVALLUR"]
    elif city_name == "kolkata":
        city_districts = ["KOLKATA", "24 PARGANAS", "HOWRAH", "HOOGHLY"]
    elif city_name == "pune":
        city_districts = ["PUNE"]
    elif city_name in ("delhi", "delhi_ncr"):
        city_districts = ["DELHI", "GAUTAM BUDDHA", "GURUGRAM", "GURGAON", "GHAZIABAD", "FARIDABAD"]
        
    udise_filtered = []
    for u in udise_schools:
        if u['metadata'].get('management', '') not in allowed_managements:
            continue
        dist = str(u.get('metadata', {}).get('location', {}).get('district', '')).upper()
        if any(d in dist for d in city_districts):
            udise_filtered.append(u)
            
    print(f"Filtered UDISE database to {len(udise_filtered)} private/aided schools matching districts for {city_name}.")

    # Pre-process UDISE names
    for u in udise_filtered:
        u['norm_name'] = normalize_name(u['metadata']['school_name'])
        u['pincode_str'] = str(u['metadata'].get('pincode', '')).strip()

    # Pre-process Candidates
    for c in merged_candidates:
        c['norm_name'] = normalize_name(c['school_name'])

    udise_norms = [u['norm_name'] for u in udise_filtered if u['norm_name']]
    udise_name_freq = Counter(udise_norms)
    udise_char_sets = [set(u['norm_name']) for u in udise_filtered]

    matched_udise_ids = set()
    final_matched_list = []

    print("Matching merged fee schools against UDISE registry...")
    for c_idx, c in enumerate(merged_candidates):
        c_norm = c['norm_name']
        c_pincode = str(c.get('pincode') or '').strip()
        c_area = (c.get('area') or "").lower()
        
        if not c_norm:
            continue
            
        c_norm_with_area = normalize_name(c['school_name'] + " " + c_area)
        
        best_match = None
        best_score = 0
        
        len_c = len(c_norm)
        set_c = set(c_norm)
        
        for u_idx, u in enumerate(udise_filtered):
            if u['udise_code'] in matched_udise_ids:
                continue
                
            u_norm = u['norm_name']
            if not u_norm:
                continue
                
            len_u = len(u_norm)
            
            ratio_ok = (len_c / len_u >= 0.538) and (len_u / len_c >= 0.538)
            c_words = set(c['school_name'].lower().split())
            u_words = set(u['metadata']['school_name'].lower().split())
            stop_words = {'school', 'public', 'private', 'the', 'of', 'and', 'for', 'in', 'high', 'primary', 'secondary', 'co', 'education', 'learning', 'international', 'academy', 'institution'}
            c_clean = c_words - stop_words
            u_clean = u_words - stop_words
            
            if not ratio_ok:
                has_overlap = False
                if c_clean and u_clean:
                    intersection = c_clean.intersection(u_clean)
                    if len(intersection) >= 2 or (len(intersection) >= 1 and (intersection == c_clean or intersection == u_clean)):
                        has_overlap = True
                if not has_overlap:
                    continue
                
            set_u = udise_char_sets[u_idx]
            common_chars = len(set_c.intersection(set_u))
            if common_chars / max(len_c, len_u) < 0.35:
                continue
                
            score = similar(c_norm, u_norm)
            
            # Word subset overlap boost
            if c_clean and u_clean:
                intersection = c_clean.intersection(u_clean)
                if intersection == c_clean or intersection == u_clean:
                    score = max(score, 0.82)
            
            if c_area and len(c_area) > 3:
                is_substring = (c_norm in u_norm) or (u_norm in c_norm)
                if is_substring or score >= 0.50:
                    score_with_area = similar(c_norm_with_area, u_norm)
                    score = max(score, score_with_area)
                    
            if score < 0.70:
                continue
                
            u_pincode = u['pincode_str']
            pincodes_differ = False
            if is_valid_pincode(c_pincode) and is_valid_pincode(u_pincode) and c_pincode != u_pincode:
                pincodes_differ = True
                
            name_is_common = udise_name_freq.get(u_norm, 0) > 1
            
            if pincodes_differ:
                if name_is_common:
                    continue
                score -= 0.15
            else:
                if is_valid_pincode(c_pincode) and is_valid_pincode(u_pincode) and c_pincode == u_pincode:
                    score += 0.3
                    
            u_address = (u['metadata'].get('address') or "").lower()
            if c_area and len(c_area) > 3 and c_area in u_address:
                score += 0.15
                
            if score > best_score:
                best_score = score
                best_match = u
                
        if best_match and best_score >= 0.80:
            matched_udise_ids.add(best_match['udise_code'])
            
            ud_loc = best_match.get("metadata", {}).get("location") or {}
            final_lat = ud_loc.get("lat") or c.get("latitude")
            final_lon = ud_loc.get("lng") or c.get("longitude")
            
            c["is_matched"] = True
            c["udise_code"] = best_match["udise_code"]
            tot_students, g2_9_students = get_udise_enrollment(best_match)
            c["student_enrollment"] = tot_students
            c["student_enrollment_grades_2_9"] = g2_9_students
            c["lowest_class"] = best_match["metadata"].get("lowest_class")
            c["highest_class"] = best_match["metadata"].get("highest_class")
            c["enrollment_source"] = "UDISE"
            
            final_matched_list.append({
                "school_name": c["school_name"],
                "ezyschooling_url": c["ezyschooling_url"],
                "yellowslate_url": c["yellowslate_url"],
                "area": c["area"],
                "pincode": c["pincode"] or best_match.get("pincode_str"),
                "address": c["address"] or best_match.get("metadata", {}).get("address"),
                "latitude": final_lat,
                "longitude": final_lon,
                "boards": c["boards"],
                "fee": c["fee"],
                "udise_code": best_match["udise_code"],
                "udise_school_name": best_match["metadata"]["school_name"],
                "student_enrollment": c["student_enrollment"],
                "student_enrollment_grades_2_9": c["student_enrollment_grades_2_9"],
                "source": c["source"]
            })
        else:
            c["is_matched"] = False
            c["udise_code"] = None
            c["student_enrollment"] = 0
            c["student_enrollment_grades_2_9"] = 0
            
            # Parse classes for unmatched schools
            low, high = 1, 12
            offered = c.get("offered_classes")
            name_str = c["school_name"].lower()
            
            # Check if it's a preschool based on name
            is_preschool = False
            preschool_terms = [
                "preschool", "pre-school", "play school", "playschool", "nursery", 
                "kindergarten", "toddler", "kidzee", "eurokids", "euro kids", "hello kids", 
                "star kids", "time kids", "genius kids", "kids",
                "shanti juniors", "little einsteins", "little wing", "bachpan", 
                "footprints", "shemrock", "kangaroo kids", "playgroup"
            ]
            if any(term in name_str for term in preschool_terms):
                is_preschool = True
            
            if offered:
                offered_str = str(offered).lower()
                if any(x in offered_str for x in ["nursery", "play", "kg", "lkg", "ukg", "toddler", "pre-primary"]):
                    low = 1
                else:
                    match = re.search(r'\b(1[0-2]|[1-9])\b', offered_str)
                    if match:
                        low = int(match.group(1))
                        
                if "xii" in offered_str or "12" in offered_str:
                    high = 12
                elif "x" in offered_str or "10" in offered_str:
                    high = 10
                elif "viii" in offered_str or "8" in offered_str:
                    high = 8
                elif "v" in offered_str or "5" in offered_str:
                    high = 5
                elif any(x in offered_str for x in ["nursery", "play", "kg", "lkg", "ukg", "toddler", "pre-primary"]):
                    high = 1
            else:
                if "junior college" in name_str or "jr college" in name_str or "xii" in name_str or "12" in name_str:
                    high = 12
                elif "high school" in name_str or "secondary" in name_str or "x" in name_str or "10" in name_str:
                    high = 10
                elif "primary" in name_str or "play" in name_str or "nursery" in name_str or "preschool" in name_str or "pre-school" in name_str or is_preschool:
                    high = 1 if is_preschool else 5
            
            if is_preschool and high > 5:
                high = 1
                
            c["lowest_class"] = low
            c["highest_class"] = high
            c["enrollment_source"] = "Predicted"

    print(f"Successfully matched {len(final_matched_list)} fee schools to UDISE database.")
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(final_matched_list, f, ensure_ascii=False, indent=2)
    print(f"Saved merged schools to {args.output}")

    candidates_output = args.output.replace("schools_merged_matched_udise", "schools_merged_all_candidates")
    with open(candidates_output, "w", encoding="utf-8") as f:
        json.dump(merged_candidates, f, ensure_ascii=False, indent=2)
    print(f"Saved all {len(merged_candidates)} unique candidates to {candidates_output}")

if __name__ == "__main__":
    main()
