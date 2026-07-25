import os
import json
import re
from difflib import SequenceMatcher

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'output')

# Paths
YS_UNMATCHED_PATH = os.path.join(DATA_DIR, 'unmatched_yellowslate.json')
UDISE_COMPACT_PATH = os.path.join(DATA_DIR, 'schools_analysis_bangalore_compact.json')
AUTO_MATCHED_PATH = os.path.join(DATA_DIR, 'auto_matched_schools.json')
MANUAL_MATCHED_PATH = os.path.join(DATA_DIR, 'manual_matched_schools.json')

def similar(a, b):
    if not a or not b:
        return 0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def normalize_name(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'\b(school|public|convent|english|kannada|urdu|high|higher|primary|nursery|vidya|kendra|institution|academy|international|early|learning|centre|center|pre|preschool|montessori|play|playgroup|kindergarten|bengaluru|bangalore)\b', '', name)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name

def check_mismatches():
    print("Loading databases...")
    # Load UDISE
    if not os.path.exists(UDISE_COMPACT_PATH):
        print(f"Error: UDISE compact database not found at {UDISE_COMPACT_PATH}")
        return
    with open(UDISE_COMPACT_PATH, 'r') as f:
        udise_data = json.load(f)
        udise_schools = udise_data.get('schools', [])
        for u in udise_schools:
            u['norm_name'] = normalize_name(u['metadata']['school_name'])
            u['pincode_str'] = str(u['metadata'].get('pincode', '')).strip()

    # Load manual matches
    manual_matches = []
    if os.path.exists(MANUAL_MATCHED_PATH):
        with open(MANUAL_MATCHED_PATH, 'r') as f:
            manual_matches = json.load(f)
    print(f"Loaded {len(manual_matches)} manual matches.")

    # Load auto matches
    auto_matches = []
    if os.path.exists(AUTO_MATCHED_PATH):
        with open(AUTO_MATCHED_PATH, 'r') as f:
            auto_matches = json.load(f)
    print(f"Loaded {len(auto_matches)} auto matches.")

    suspicious = []

    # Process manual matches
    for i, m in enumerate(manual_matches):
        ys_name = m.get('yellowslate_name')
        udise_code = m.get('udise_code')
        ys_data = m.get('yellowslate_data') or {}
        
        # Find UDISE school
        udise_sch = next((u for u in udise_schools if u['udise_code'] == udise_code), None)
        if not udise_sch:
            print(f"Warning: Manual match index {i} links to non-existent UDISE code {udise_code}")
            continue

        u_name = udise_sch['metadata']['school_name']
        score = similar(ys_name, u_name)
        ys_norm = normalize_name(ys_name)
        u_norm = udise_sch['norm_name']
        norm_score = similar(ys_norm, u_norm)
        
        ys_pincode = str(ys_data.get('school_location', {}).get('pincode', '')).strip()
        u_pincode = udise_sch['pincode_str']
        
        pincodes_match = (ys_pincode == u_pincode) if (ys_pincode and u_pincode) else True
        
        is_suspicious = False
        reason = ""
        # Aggressive flagging for manual matches since they were done by hand
        if norm_score < 0.65:
            is_suspicious = True
            reason = f"Low normalized name similarity (Norm Score: {norm_score:.2f})"
        elif not pincodes_match and norm_score < 0.8:
            is_suspicious = True
            reason = f"Moderate normalized name similarity ({norm_score:.2f}) and mismatched pincode (YS: {ys_pincode} vs UDISE: {u_pincode})"
            
        if is_suspicious:
            suspicious.append({
                "type": "manual",
                "index": i,
                "yellowslate_name": ys_name,
                "udise_code": udise_code,
                "udise_name": u_name,
                "ys_pincode": ys_pincode,
                "u_pincode": u_pincode,
                "reason": reason,
                "score": score
            })

    # Process auto matches
    for i, m in enumerate(auto_matches):
        ys_school = m.get('yellowslate', {})
        ys_name = ys_school.get('school_name')
        udise_sch_info = m.get('udise', {})
        udise_code = udise_sch_info.get('udise_code')
        u_name = udise_sch_info.get('metadata', {}).get('school_name', '')
        
        udise_sch = next((u for u in udise_schools if u['udise_code'] == udise_code), None)
        if not udise_sch:
            continue
            
        score = similar(ys_name, u_name)
        norm_score = similar(normalize_name(ys_name), udise_sch['norm_name'])
        ys_pincode = str(ys_school.get('school_location', {}).get('pincode', '')).strip()
        u_pincode = udise_sch['pincode_str']
        pincodes_match = (ys_pincode == u_pincode) if (ys_pincode and u_pincode) else True
        
        is_suspicious = False
        reason = ""
        if score < 0.45 and norm_score < 0.45:
            is_suspicious = True
            reason = f"Low name similarity (Score: {score:.2f}, Norm: {norm_score:.2f})"
        elif score < 0.60 and not pincodes_match:
            is_suspicious = True
            reason = f"Moderate name similarity ({score:.2f}) and mismatched pincode (YS: {ys_pincode} vs UDISE: {u_pincode})"
            
        if is_suspicious:
            suspicious.append({
                "type": "auto",
                "index": i,
                "yellowslate_name": ys_name,
                "udise_code": udise_code,
                "udise_name": u_name,
                "ys_pincode": ys_pincode,
                "u_pincode": u_pincode,
                "reason": reason,
                "score": score
            })

    print(f"\nFound {len(suspicious)} suspicious matches:")
    for item in suspicious:
        print(f"\n[{item['type'].upper()} MATCH] {item['reason']}")
        print(f"  Yellowslate: {item['yellowslate_name']} (Pincode: {item['ys_pincode']})")
        print(f"  UDISE:       {item['udise_name']} (Code: {item['udise_code']}, Pincode: {item['u_pincode']})")
        
        # Look for better matches
        y_norm = normalize_name(item['yellowslate_name'])
        better_candidates = []
        for u in udise_schools:
            u_score = similar(y_norm, u['norm_name'])
            # Bonus for same pincode
            if item['ys_pincode'] and u['pincode_str'] and item['ys_pincode'] == u['pincode_str']:
                u_score += 0.2
            if u_score > 0.6:
                better_candidates.append((u_score, u))
                
        better_candidates.sort(key=lambda x: x[0], reverse=True)
        if better_candidates:
            print("  Suggested UDISE Candidates:")
            for s_score, u in better_candidates[:3]:
                print(f"    - {u['metadata']['school_name']} (Code: {u['udise_code']}, Pincode: {u['pincode_str']}, Sim Score: {s_score:.2f})")

    # Ask the user if they want to unmatch the manual ones
    suspicious_manual = [s for s in suspicious if s['type'] == 'manual']
    if suspicious_manual:
        ans = input(f"\nWould you like to automatically UNMATCH the {len(suspicious_manual)} suspicious manual matches? (y/n): ").strip().lower()
        if ans == 'y':
            codes_to_remove = set(s['udise_code'] for s in suspicious_manual)
            new_manual = [m for m in manual_matches if m.get('udise_code') not in codes_to_remove]
            with open(MANUAL_MATCHED_PATH, 'w') as f:
                json.dump(new_manual, f, indent=2)
            print(f"Successfully unmatched and removed {len(suspicious_manual)} manual matches!")

if __name__ == "__main__":
    check_mismatches()
