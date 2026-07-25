import json
import os
import re
import argparse
from collections import Counter
from difflib import SequenceMatcher

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

def main():
    parser = argparse.ArgumentParser(description="Optimized auto-match for Delhi NCR schools.")
    parser.add_argument("--ys-path", default="data/output/yellowslate/yellowslate_schools_with_locations_delhi_ncr.json")
    parser.add_argument("--udise-path", default="data/output/schools_analysis_delhi_ncr_compact.json")
    parser.add_argument("--manual-path", default="data/output/manual_matched_schools_delhi_ncr.json")
    parser.add_argument("--out-matched", default="data/output/auto_matched_schools_delhi_ncr.json")
    parser.add_argument("--out-unmatched", default="data/output/unmatched_yellowslate_delhi_ncr.json")
    args = parser.parse_args()

    # Load datasets
    with open(args.ys_path, 'r', encoding='utf-8') as f:
        ys_schools = json.load(f)
        
    with open(args.udise_path, 'r', encoding='utf-8') as f:
        udise_data = json.load(f)
        udise_schools = udise_data.get('schools', [])

    manual_matches = []
    manual_ys_names = set()
    manual_udise_codes = set()
    if os.path.exists(args.manual_path):
        with open(args.manual_path, 'r', encoding='utf-8') as f:
            manual_matches = json.load(f)
            for m in manual_matches:
                manual_ys_names.add(m.get("yellowslate_name", ""))
                manual_udise_codes.add(m.get("udise_code", ""))

    print(f"Loaded {len(ys_schools)} Yellowslate schools and {len(udise_schools)} UDISE schools.")
    print(f"Preserving {len(manual_matches)} manual matches.")

    # Filter UDISE schools to only include private or aided management
    allowed_managements = {
        'Private Unaided (Recognized)',
        'Madrasa Private Unaided (Recognized)',
        'Government Aided'
    }
    
    udise_filtered = []
    for u in udise_schools:
        mgt = u['metadata'].get('management', '')
        if mgt in allowed_managements:
            udise_filtered.append(u)
            
    print(f"Filtered UDISE schools from {len(udise_schools)} to {len(udise_filtered)} based on management type.")

    # Pre-process UDISE schools
    for u in udise_filtered:
        u['norm_name'] = normalize_name(u['metadata']['school_name'])
        u['pincode_str'] = str(u['metadata'].get('pincode', '')).strip()

    # Build UDISE name frequencies
    udise_norms = [u['norm_name'] for u in udise_filtered if u['norm_name']]
    udise_name_freq = Counter(udise_norms)

    auto_matched = []
    unmatched_ys = []
    matched_udise_ids = set(manual_udise_codes)

    # Character sets for fast filtering
    udise_char_sets = [set(u['norm_name']) for u in udise_filtered]

    print("Starting optimized school matching...")
    for y_idx, y in enumerate(ys_schools):
        y_name = y.get('school_name', '')
        if y_name in manual_ys_names:
            continue
            
        y_norm_name = normalize_name(y_name)
        # Handle different structures of pincode
        y_loc = y.get('school_location') or {}
        y_pincode = str(y_loc.get('pincode') or '').strip()
        y_area = (y.get('area') or "").lower()
        
        if not y_norm_name:
            unmatched_ys.append(y)
            continue
            
        y_norm_name_with_area = normalize_name(y_name + " " + y_area)
        
        best_match = None
        best_score = 0
        
        len_y = len(y_norm_name)
        set_y = set(y_norm_name)
        
        for u_idx, u in enumerate(udise_filtered):
            if u['udise_code'] in matched_udise_ids:
                continue
                
            u_norm_name = u['norm_name']
            if not u_norm_name:
                continue
                
            len_u = len(u_norm_name)
            
            # --- FAST FILTER 1: Length Ratio ---
            # SequenceMatcher.ratio can only be >= 0.70 if length ratio >= 0.538
            if len_y / len_u < 0.538 or len_u / len_y < 0.538:
                continue
                
            # --- FAST FILTER 2: Character Set Overlap ---
            # Common characters must be at least 35% of the longer string
            set_u = udise_char_sets[u_idx]
            common_chars = len(set_y.intersection(set_u))
            if common_chars / max(len_y, len_u) < 0.35:
                continue
            
            # Base similarity score
            score = similar(y_norm_name, u_norm_name)
            
            if y_area and len(y_area) > 3:
                is_substring = (y_norm_name in u_norm_name) or (u_norm_name in y_norm_name)
                if is_substring or score >= 0.50:
                    score_with_area = similar(y_norm_name_with_area, u_norm_name)
                    score = max(score, score_with_area)
            
            # Enforce minimum name similarity of 0.70
            if score < 0.70:
                continue
            
            # Pincode matching logic
            u_pincode = u['pincode_str']
            pincodes_differ = False
            if is_valid_pincode(y_pincode) and is_valid_pincode(u_pincode) and y_pincode != u_pincode:
                pincodes_differ = True
                
            name_is_common = udise_name_freq.get(u_norm_name, 0) > 1
            
            if pincodes_differ:
                if name_is_common:
                    continue
                score -= 0.15
            else:
                if is_valid_pincode(y_pincode) and is_valid_pincode(u_pincode) and y_pincode == u_pincode:
                    score += 0.3
            
            # Boost score if area matches address
            u_address = (u['metadata'].get('address') or "").lower()
            if y_area and len(y_area) > 3 and y_area in u_address:
                score += 0.15
                
            if score > best_score:
                best_score = score
                best_match = u
                
        if best_match and best_score >= 0.85:
            matched_udise_ids.add(best_match['udise_code'])
            # Keep assigned fee bracket for build_master
            y["fee"]["assigned_bracket_key"] = y["fee"]["search_bracket_key"]
            y["fee"]["assigned_bracket_label"] = y["fee"]["search_bracket_label"]
            auto_matched.append({
                "yellowslate": y,
                "udise": best_match,
                "score": best_score,
                "match_type": "auto"
            })
        else:
            unmatched_ys.append(y)
            
    print(f"Auto-matched {len(auto_matched)} schools.")
    print(f"Remaining unmatched Yellowslate schools: {len(unmatched_ys)}")
    
    os.makedirs(os.path.dirname(args.out_matched), exist_ok=True)
    with open(args.out_matched, 'w', encoding='utf-8') as f:
        json.dump(auto_matched, f, ensure_ascii=False, indent=2)
        
    with open(args.out_unmatched, 'w', encoding='utf-8') as f:
        json.dump(unmatched_ys, f, ensure_ascii=False, indent=2)
        
    print("Successfully saved matching outputs.")

if __name__ == "__main__":
    main()
