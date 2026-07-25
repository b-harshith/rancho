import json
import os
import re
from collections import Counter
from difflib import SequenceMatcher

def similar(a, b):
    if not a or not b:
        return 0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

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
        r'playgroup', r'kindergarten', r'bengaluru', r'bangalore', r'hps', r'lps', r'hs', r'ups', 
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

import argparse

def main():
    parser = argparse.ArgumentParser(description="Auto-match Yellowslate schools to UDISE database.")
    parser.add_argument("--ys-path", default="data/output/yellowslate/yellowslate_schools_with_locations.json", help="Path to Yellowslate locations JSON")
    parser.add_argument("--udise-path", default="data/output/schools_analysis_bangalore_compact.json", help="Path to compact UDISE JSON")
    parser.add_argument("--manual-path", default="data/output/manual_matched_schools.json", help="Path to manual matches JSON")
    parser.add_argument("--out-matched", default="data/output/auto_matched_schools.json", help="Output path for matched schools")
    parser.add_argument("--out-unmatched", default="data/output/unmatched_yellowslate.json", help="Output path for unmatched schools")
    args = parser.parse_args()

    ys_path = args.ys_path if os.path.isabs(args.ys_path) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.ys_path)
    udise_path = args.udise_path if os.path.isabs(args.udise_path) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.udise_path)
    manual_path = args.manual_path if os.path.isabs(args.manual_path) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.manual_path)
    
    with open(ys_path, 'r', encoding='utf-8') as f:
        ys_schools = json.load(f)
        
    with open(udise_path, 'r', encoding='utf-8') as f:
        udise_data = json.load(f)
        udise_schools = udise_data.get('schools', [])
        
    # Load manual matches to exclude them
    manual_matches = []
    manual_ys_names = set()
    manual_udise_codes = set()
    if os.path.exists(manual_path):
        with open(manual_path, 'r', encoding='utf-8') as f:
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
    
    for y in ys_schools:
        y_name = y.get('school_name', '')
        
        # Skip if already manual matched
        if y_name in manual_ys_names:
            continue
            
        y_norm_name = normalize_name(y_name)
        y_pincode = str(y.get('school_location', {}).get('pincode', '')).strip()
        y_area = (y.get('area') or "").lower()
        
        if not y_norm_name:
            unmatched_ys.append(y)
            continue
            
        y_norm_name_with_area = normalize_name(y_name + " " + y_area)
        
        best_match = None
        best_score = 0
        
        for u in udise_filtered:
            if u['udise_code'] in matched_udise_ids:
                continue
                
            u_norm_name = u['norm_name']
            if not u_norm_name:
                continue
                
            # Base similarity score
            score = similar(y_norm_name, u_norm_name)
            
            # Area fallback: only allow if base name has moderate similarity or is a substring
            if y_area and len(y_area) > 3:
                is_substring = (y_norm_name in u_norm_name) or (u_norm_name in y_norm_name)
                if is_substring or score >= 0.50:
                    score_with_area = similar(y_norm_name_with_area, u_norm_name)
                    score = max(score, score_with_area)
            
            # --- NEW RULE: Enforce minimum name similarity of 0.70 before boosts ---
            if score < 0.70:
                continue
            
            # Pincode matching logic
            u_pincode = u['pincode_str']
            
            pincodes_differ = False
            if is_valid_pincode(y_pincode) and is_valid_pincode(u_pincode) and y_pincode != u_pincode:
                pincodes_differ = True
                
            # Check if name is common in UDISE
            name_is_common = udise_name_freq.get(u_norm_name, 0) > 1
            
            if pincodes_differ:
                # If pincodes differ and the name is common, reject the match
                if name_is_common:
                    continue
                # If pincodes differ and name is unique, we allow it but penalize it
                score -= 0.15
            else:
                # Boost if pincodes match exactly
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
    
    # Save the files
    out_matched = args.out_matched if os.path.isabs(args.out_matched) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.out_matched)
    out_unmatched = args.out_unmatched if os.path.isabs(args.out_unmatched) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.out_unmatched)
    
    os.makedirs(os.path.dirname(out_matched), exist_ok=True)
    with open(out_matched, 'w', encoding='utf-8') as f:
        json.dump(auto_matched, f, ensure_ascii=False, indent=2)
        
    with open(out_unmatched, 'w', encoding='utf-8') as f:
        json.dump(unmatched_ys, f, ensure_ascii=False, indent=2)
        
    print("Successfully saved matching outputs.")

if __name__ == "__main__":
    main()
