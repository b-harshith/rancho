import json
import re
from pathlib import Path
from difflib import SequenceMatcher
import math

# Paths
BLR_ENTITIES_PATH = Path('/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/school_entities.json')
BLR_UDISE_PATH = Path('/Users/malleswararao/Desktop/school extraction/data/output/schools_analysis_bangalore_compact.json')

def similar(a, b):
    if not a or not b:
        return 0
    return SequenceMatcher(None, a, b).ratio()

def normalize_name(name):
    if not name:
        return ""
    name = name.lower().strip()
    
    # Standardize spelling variations
    name = re.sub(r'\bsaint\b', 'st', name)
    name = re.sub(r'\b(shri|sree|shree)\b', 'sri', name)
    name = re.sub(r'\bvidhya\b', 'vidya', name)
    name = re.sub(r'\bcentre\b', 'center', name)
    
    # Remove common school words
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

def haversine_m(lat1, lon1, lat2, lon2):
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
    except (TypeError, ValueError):
        return float('inf')
    R = 6371000.0  # Earth's radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

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

def main():
    print("Loading school entities...")
    with open(BLR_ENTITIES_PATH, 'r') as f:
        entities = json.load(f)
        
    print("Loading Bangalore UDISE database...")
    with open(BLR_UDISE_PATH, 'r') as f:
        udise_data = json.load(f)
    udise_schools = udise_data.get("schools", [])
    
    # Filter UDISE private/aided
    allowed_managements = {
        'Private Unaided (Recognized)',
        'Madrasa Private Unaided (Recognized)',
        'Government Aided'
    }
    udise_filtered = [u for u in udise_schools if u['metadata'].get('management', '') in allowed_managements]
    
    # Pre-process UDISE names
    for u in udise_filtered:
        u['norm_name'] = normalize_name(u['metadata']['school_name'])
        
    print(f"Loaded {len(entities)} entities, and {len(udise_filtered)} filtered UDISE schools.")
    
    matched_count = 0
    ezy_matched = 0
    
    for s in entities:
        # Check if already matched
        if s.get('udise_codes'):
            continue
            
        s_name = s.get('name')
        s_norm = normalize_name(s_name)
        s_lat = s.get('lat')
        s_lon = s.get('lon')
        s_url = s.get('url', '')
        s_pincode = str(s.get('pincode', '')).strip()
        
        if not s_norm or s_lat is None or s_lon is None:
            continue
            
        best_match = None
        best_score = 0
        best_dist = float('inf')
        
        for u in udise_filtered:
            u_norm = u['norm_name']
            if not u_norm:
                continue
                
            u_lat = u['metadata']['location'].get('lat') or u['metadata']['location'].get('latitude')
            u_lon = u['metadata']['location'].get('lng') or u['metadata']['location'].get('longitude')
            
            if u_lat is None or u_lon is None:
                continue
                
            dist = haversine_m(s_lat, s_lon, u_lat, u_lon)
            if dist > 1500:  # within 1.5 km
                continue
                
            score = similar(s_norm, u_norm)
            
            # Boost if pincodes match
            u_pincode = str(u['metadata'].get('pincode', '')).strip()
            pincode_match = False
            if s_pincode and u_pincode and s_pincode == u_pincode:
                score += 0.15
                pincode_match = True
                
            if score >= 0.80:
                if score > best_score:
                    best_score = score
                    best_match = u
                    best_dist = dist
                    
        if best_match:
            u_code = best_match['udise_code']
            tot, g2_9 = get_udise_enrollment(best_match)
            
            s['udise_codes'] = [u_code]
            s['students_total'] = tot
            s['students_grades_2_9'] = g2_9
            s['enrollment_source'] = 'udise'
            s['merge_status'] = 'auto_matched'
            
            matched_count += 1
            if 'ezyschooling.com' in s_url:
                ezy_matched += 1
                print(f"  [BLR-MATCH] '{s_name}' -> '{best_match['metadata']['school_name']}' | UDISE: {u_code} | Enrollment: {tot} (Grades 2-9: {g2_9})")
                
    print(f"\nBangalore Matching Complete:")
    print(f"  Matched {matched_count} previously unmatched schools.")
    print(f"  Matched {ezy_matched} schools specifically from Ezyschooling.")
    
    # Save back updated school_entities.json
    with open(BLR_ENTITIES_PATH, 'w') as f:
        json.dump(entities, f, indent=2, ensure_ascii=False)
    print("Saved updated school entities database.")

if __name__ == "__main__":
    main()
